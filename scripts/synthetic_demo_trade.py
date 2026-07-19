#!/usr/bin/env python3
"""Auto-trade the synthetic FX indices on a demo MT5 account."""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.indicators.indicators import MomentumIndicators, MovingAverages, VolatilityIndicators
from backend.market_data.data_collector import MT5DataCollector
from backend.market_data.mt5_service import MT5Service
from backend.strategies.synthetic_indices import (
    SyntheticBalancedMomentumStrategy,
    SyntheticBreakoutStrategy,
    SyntheticTrendStrategy,
)
from database.database_manager import db_manager
from scripts.live_trade_signal import build_trade_setup

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - dependency is installed on Windows
    mt5 = None


logger = setup_logger(__name__)


@dataclass(frozen=True)
class SyntheticTradeOptions:
    symbol: str | None = None
    account_id: str = "synthetic"
    timeframe: int = 5
    lookback_days: int = 90
    account_balance: float | None = None
    risk_per_trade: float = 1.0
    reward_to_risk: float = 2.0
    max_spread_points: float = 50.0
    signal_lookback_candles: int = 3
    min_analysis_score: float = 0.65
    deep_analysis: bool = True
    list_symbols: bool = False
    symbol_filter: str = "fx,vol,index,sfx"
    dry_run: bool = False

    @classmethod
    def from_namespace(cls, args: Namespace) -> "SyntheticTradeOptions":
        return cls(
            symbol=args.symbol,
            account_id=args.account_id,
            timeframe=args.timeframe,
            lookback_days=args.lookback_days,
            account_balance=args.account_balance,
            risk_per_trade=args.risk_per_trade,
            reward_to_risk=args.reward_to_risk,
            max_spread_points=args.max_spread_points,
            signal_lookback_candles=args.signal_lookback_candles,
            min_analysis_score=args.min_analysis_score,
            deep_analysis=not args.disable_deep_analysis,
            list_symbols=args.list_symbols,
            symbol_filter=args.symbol_filter,
            dry_run=args.dry_run,
        )


SYNTHETIC_MT5_PROFILE = settings.mt5_account_profile("synthetic")
synthetic_mt5_service = MT5Service(
    account_number=SYNTHETIC_MT5_PROFILE["account_number"],
    password=SYNTHETIC_MT5_PROFILE["password"],
    server=SYNTHETIC_MT5_PROFILE["server"],
    terminal_path=SYNTHETIC_MT5_PROFILE.get("terminal_path"),
    profile_name="synthetic",
)
mt5_collector = MT5DataCollector(service=synthetic_mt5_service)


SYNTHETIC_PROFILES = {
    "20": {
        "configured_symbol": settings.synthetic_index_20_symbol,
        "search_terms": settings.synthetic_index_20_search_terms,
        "strategy": SyntheticTrendStrategy,
    },
    "40": {
        "configured_symbol": settings.synthetic_index_40_symbol,
        "search_terms": settings.synthetic_index_40_search_terms,
        "strategy": SyntheticBalancedMomentumStrategy,
    },
    "80": {
        "configured_symbol": settings.synthetic_index_80_symbol,
        "search_terms": settings.synthetic_index_80_search_terms,
        "strategy": SyntheticBreakoutStrategy,
    },
}


def _normalize_retcodes(result: dict[str, object] | None) -> int | None:
    if not result:
        return None
    retcode = result.get("retcode")
    return int(retcode) if retcode is not None else None


def _successful_retcodes() -> set[int]:
    if mt5 is None:
        return {0}
    return {
        0,
        int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
        int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
        int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
    }


def _unsupported_filling_retcodes() -> set[int]:
    if mt5 is None:
        return {10030}
    return {10030, int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030))}


def _retcode_succeeded(retcode: int | None) -> bool:
    return retcode is None or retcode in _successful_retcodes()


def _retcode_is_unsupported_filling(retcode: int | None) -> bool:
    return retcode in _unsupported_filling_retcodes()


def _synthetic_model_version(bucket: str, strategy_name: str) -> str:
    """Return a schema-safe strategy identifier for the signals table."""
    aliases = {
        "SyntheticTrendStrategy": "trend",
        "SyntheticBalancedMomentumStrategy": "momentum",
        "SyntheticBreakoutStrategy": "breakout",
    }
    strategy_alias = aliases.get(strategy_name, strategy_name.replace("Synthetic", "").replace("Strategy", "").lower())
    return f"syn_{bucket}_{strategy_alias}"[:20]


def _synthetic_magic(account_id: str, bucket: str) -> int:
    """Create a stable MT5 magic number per account and volatility bucket."""
    seed = f"{account_id}:{bucket}:synthetic"
    return 700000 + (sum((index + 1) * ord(character) for index, character in enumerate(seed)) % 200000)


def _trading_disabled_warnings(terminal_info: dict, account_info: dict) -> list[str]:
    warnings: list[str] = []
    if terminal_info.get("trade_allowed") is False:
        warnings.append("Terminal trading is disabled")
    if account_info.get("trade_allowed") is False:
        warnings.append("Account trading is disabled")
    return warnings


def _normalized_symbol_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _resolve_symbol(configured_symbol: str, search_terms: list[str], broker_symbols: list[str]) -> str | None:
    """Resolve the best broker symbol using exact config first, then search terms."""
    if configured_symbol:
        configured_key = _normalized_symbol_text(configured_symbol)
        for symbol in broker_symbols:
            if _normalized_symbol_text(symbol) == configured_key:
                return symbol

    normalized_terms = [_normalized_symbol_text(term) for term in search_terms if term.strip()]
    candidates: list[tuple[int, str]] = []
    for symbol in broker_symbols:
        symbol_key = _normalized_symbol_text(symbol)
        if not all(term in symbol_key for term in normalized_terms):
            continue

        score = sum(len(term) for term in normalized_terms)
        if configured_symbol and _normalized_symbol_text(configured_symbol) in symbol_key:
            score += 100
        candidates.append((score, symbol))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return candidates[0][1]


def _resolve_trade_targets(requested_symbol: str | None) -> list[tuple[str, str, type]]:
    """Resolve configured volatility buckets to broker symbols."""
    broker_symbols = mt5_collector.service.symbols()
    targets: list[tuple[str, str, type]] = []

    if requested_symbol in SYNTHETIC_PROFILES:
        profile = SYNTHETIC_PROFILES[requested_symbol]
        symbol = _resolve_symbol(
            str(profile["configured_symbol"]),
            list(profile["search_terms"]),
            broker_symbols,
        )
        if symbol:
            targets.append((requested_symbol, symbol, profile["strategy"]))
        return targets

    for bucket, profile in SYNTHETIC_PROFILES.items():
        symbol = _resolve_symbol(
            str(profile["configured_symbol"]),
            list(profile["search_terms"]),
            broker_symbols,
        )
        if not symbol:
            logger.warning("Could not resolve synthetic %s%% symbol from broker list", bucket)
            continue

        if requested_symbol and _normalized_symbol_text(requested_symbol) != _normalized_symbol_text(symbol):
            continue

        targets.append((bucket, symbol, profile["strategy"]))

    if requested_symbol and not targets:
        logger.warning("Requested symbol was not resolved as a configured synthetic index: %s", requested_symbol)

    return targets


def _list_broker_symbols(filter_text: str | None = None) -> list[str]:
    """List broker symbols from the synthetic MT5 account, optionally filtered."""
    symbols = mt5_collector.service.symbols()
    if not filter_text:
        return symbols

    filters = [_normalized_symbol_text(item) for item in filter_text.split(",") if item.strip()]
    return [
        symbol
        for symbol in symbols
        if any(filter_value in _normalized_symbol_text(symbol) for filter_value in filters)
    ]


def _load_synthetic_live_data(symbol: str, timeframe: int, lookback: int):
    """Load candles through the synthetic MT5 account profile."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback)
    data = mt5_collector.get_historical_data(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        limit=max(lookback * 2, 200),
    )
    if data is None or data.empty:
        raise RuntimeError(f"No live candles returned for {symbol}")
    return data


def _select_recent_signal(signal_series, lookback_candles: int) -> tuple[int, int | None, object | None, int, int]:
    """Return the newest actionable signal from the latest candles.

    The auto runner can scan faster than the candle timeframe. Looking back a few
    fresh candles prevents a valid setup from being missed just because the most
    recent in-progress candle temporarily reads as HOLD.
    """
    if signal_series.empty:
        return 0, None, None, 0, 0

    inspected_candles = max(1, int(lookback_candles))
    start_position = max(0, len(signal_series) - inspected_candles)
    recent_nonzero_count = 0
    selected: tuple[int, int | None, object | None] = (0, None, None)

    for position in range(len(signal_series) - 1, start_position - 1, -1):
        signal = int(signal_series.iloc[position])
        if signal == 0:
            continue

        recent_nonzero_count += 1
        if selected[0] == 0:
            selected = (signal, len(signal_series) - 1 - position, signal_series.index[position])

    return selected[0], selected[1], selected[2], recent_nonzero_count, len(signal_series) - start_position


def _deep_market_analysis(signal: int, data, minimum_score: float) -> tuple[bool, float, list[str]]:
    """Score a strategy signal with extra trend, momentum, RSI, and volatility checks."""
    if signal == 0:
        return False, 0.0, ["no primary signal"]
    if data is None or data.empty or len(data) < 35:
        return False, 0.0, ["insufficient candles for deep analysis"]

    frame = data.copy()
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    direction = 1 if signal > 0 else -1

    fast_ema = MovingAverages.ema(close.to_numpy(), 8)
    slow_ema = MovingAverages.ema(close.to_numpy(), 21)
    rsi = MomentumIndicators.rsi(close.to_numpy(), 14)
    atr = VolatilityIndicators.atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), 14)

    latest_close = float(close.iloc[-1])
    latest_fast = float(fast_ema[-1])
    latest_slow = float(slow_ema[-1])
    latest_rsi = float(rsi[-1])
    latest_atr = float(atr[-1])
    momentum = latest_close - float(close.iloc[-7])
    atr_ratio = latest_atr / latest_close if latest_close else 0.0

    score = 0.35
    reasons = ["primary strategy signal"]

    trend_aligned = (latest_fast > latest_slow and direction > 0) or (latest_fast < latest_slow and direction < 0)
    if trend_aligned:
        score += 0.20
        reasons.append("EMA trend aligned")
    else:
        reasons.append("EMA trend disagrees")

    momentum_aligned = (momentum > 0 and direction > 0) or (momentum < 0 and direction < 0)
    if momentum_aligned:
        score += 0.15
        reasons.append("short momentum aligned")
    else:
        reasons.append("short momentum disagrees")

    rsi_aligned = (50 <= latest_rsi <= 78 and direction > 0) or (22 <= latest_rsi <= 50 and direction < 0)
    if rsi_aligned:
        score += 0.15
        reasons.append(f"RSI aligned ({latest_rsi:.1f})")
    else:
        reasons.append(f"RSI not ideal ({latest_rsi:.1f})")

    if atr_ratio >= 0.0002:
        score += 0.10
        reasons.append(f"ATR active ({atr_ratio:.4%})")
    else:
        reasons.append(f"ATR too quiet ({atr_ratio:.4%})")

    if atr_ratio <= 0.02:
        score += 0.05
        reasons.append("volatility not extreme")
    else:
        reasons.append("volatility extreme")

    score = min(score, 1.0)
    return score >= minimum_score, score, reasons


def _trade_allowed(
    account_id: str,
    symbol: str,
    now: datetime,
    max_total: int,
    max_per_symbol: int,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    since = now - timedelta(hours=24)
    total_trades = db_manager.count_trades_since(since, account_id=account_id)
    symbol_trades = db_manager.count_trades_since(since, symbol=symbol, account_id=account_id)

    if total_trades >= max_total:
        warnings.append(f"Daily trade cap reached ({total_trades}/{max_total})")
    if symbol_trades >= max_per_symbol:
        warnings.append(f"Daily symbol cap reached ({symbol_trades}/{max_per_symbol})")

    return not warnings, warnings


def _has_open_position(account_id: str, symbol: str) -> bool:
    """Return True when MT5 or the local trade log already has an open position."""
    broker_positions = mt5_collector.get_positions()
    if any(position.get("symbol") == symbol for position in broker_positions):
        return True

    return bool(db_manager.get_open_trades(symbol=symbol, account_id=account_id))


def _build_order_request(symbol: str, trade_setup: dict[str, object]) -> dict[str, object]:
    """Build an MT5 market order request."""
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed")

    order_type = mt5.ORDER_TYPE_BUY if trade_setup["signal_type"] == "BUY" else mt5.ORDER_TYPE_SELL
    filling_mode = mt5_collector.service.preferred_filling_mode(symbol)
    type_filling = filling_mode if filling_mode is not None else getattr(mt5, "ORDER_FILLING_RETURN", 0)

    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(trade_setup["lot_size"]),
        "type": order_type,
        "price": float(trade_setup["entry_price"]),
        "sl": float(trade_setup["stop_loss"]),
        "tp": float(trade_setup["take_profit"]),
        "deviation": int(trade_setup["deviation_points"]),
        "magic": int(trade_setup.get("magic", 0)),
        "comment": str(trade_setup.get("comment", "synthetic_demo_trade")),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }


def _filling_mode_candidates(symbol: str, current_mode: object | None) -> list[int]:
    """Return filling modes to try for a broker order request."""
    candidates: list[int] = []

    def add_candidate(value: object | None) -> None:
        if value is None:
            return
        candidate = int(value)
        if candidate not in candidates:
            candidates.append(candidate)

    add_candidate(current_mode)

    supported_modes = getattr(mt5_collector.service, "supported_filling_modes", lambda _symbol: [])(symbol) or []
    for mode in supported_modes:
        add_candidate(mode)

    if mt5 is not None:
        for name in ["ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"]:
            add_candidate(getattr(mt5, name, None))

    return candidates


def _order_check_with_filling_retry(symbol: str, order_request: dict[str, object]) -> dict[str, object] | None:
    """Run order_check and retry alternate filling modes when MT5 rejects one."""
    last_result: dict[str, object] | None = None
    for filling_mode in _filling_mode_candidates(symbol, order_request.get("type_filling")):
        order_request["type_filling"] = filling_mode
        check_result = mt5_collector.service.order_check(order_request)
        if not check_result:
            return check_result

        last_result = check_result
        check_retcode = _normalize_retcodes(check_result)
        logger.info("%s order check retcode=%s type_filling=%s", symbol, check_retcode, filling_mode)
        if _retcode_succeeded(check_retcode):
            return check_result
        if _retcode_is_unsupported_filling(check_retcode):
            logger.warning("%s rejected filling mode %s; trying another supported mode", symbol, filling_mode)
            continue

        return check_result

    return last_result


def _store_trade(
    *,
    account_id: str,
    symbol: str,
    strategy_name: str,
    signal_record_id: int | None,
    order_result: dict[str, object],
    trade_setup: dict[str, object],
) -> None:
    """Persist the executed trade and keep history for later analysis."""
    trade_id = order_result.get("order") or order_result.get("deal") or 0
    execution_price = float(order_result.get("price") or trade_setup["entry_price"])
    now = datetime.now()

    db_manager.insert_trade(
        {
            "signal_id": signal_record_id,
            "account_id": account_id,
            "symbol": symbol,
            "trade_type": trade_setup["signal_type"],
            "entry_time": now,
            "entry_price": execution_price,
            "position_size": float(trade_setup["lot_size"]),
            "stop_loss": float(trade_setup["stop_loss"]),
            "take_profit": float(trade_setup["take_profit"]),
            "status": "OPEN",
            "notes": f"trade_id={trade_id}; strategy={strategy_name}; source=synthetic_demo",
        }
    )


def _sync_broker_open_positions(account_id: str, symbols: set[str]) -> None:
    """Backfill open broker positions that are missing from the local trade log."""
    for position in mt5_collector.get_positions():
        symbol = str(position.get("symbol") or "")
        if symbol not in symbols:
            continue
        if db_manager.get_open_trades(symbol=symbol, account_id=account_id):
            continue

        ticket = position.get("ticket") or 0
        open_time = position.get("open_time")
        try:
            entry_time = datetime.fromtimestamp(float(open_time)) if open_time else datetime.now()
        except (TypeError, ValueError, OSError):
            entry_time = datetime.now()

        entry_price = float(position.get("open_price") or position.get("current_price") or 0.0)
        stop_loss = float(position.get("stop_loss") or 0.0)
        take_profit = float(position.get("take_profit") or 0.0)
        if entry_price <= 0:
            logger.warning("Cannot sync broker position %s for %s because entry price is missing", ticket, symbol)
            continue

        db_manager.insert_trade(
            {
                "signal_id": None,
                "account_id": account_id,
                "symbol": symbol,
                "trade_type": str(position.get("type") or "UNKNOWN"),
                "entry_time": entry_time,
                "entry_price": entry_price,
                "position_size": float(position.get("volume") or 0.0),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": "OPEN",
                "notes": f"trade_id={ticket}; strategy=broker_sync; source=mt5_open_position",
            }
        )
        logger.info("Synced open broker position for %s into local trade log | ticket=%s", symbol, ticket)


def build_parser() -> ArgumentParser:
    """Build CLI parser for synthetic demo trading."""
    parser = ArgumentParser(description="Trade synthetic FX indices on a demo MT5 account")
    parser.add_argument("--symbol", default=None, help="Trade only one resolved symbol, or bucket: 20, 40, 80")
    parser.add_argument("--account-id", default=str(SYNTHETIC_MT5_PROFILE.get("account_id") or "synthetic"), help="Local account identifier for DB isolation")
    parser.add_argument("--timeframe", type=int, default=5, help="MT5 candle timeframe in minutes")
    parser.add_argument("--lookback-days", type=int, default=90, help="History window for signal generation")
    parser.add_argument("--account-balance", type=float, default=None, help="Fallback demo balance for sizing")
    parser.add_argument("--risk-per-trade", type=float, default=1.0, help="Risk per trade percent")
    parser.add_argument("--reward-to-risk", type=float, default=2.0, help="Reward-to-risk ratio")
    parser.add_argument("--max-spread-points", type=float, default=50.0, help="Maximum acceptable spread in points")
    parser.add_argument("--signal-lookback-candles", type=int, default=3, help="Recent candles to inspect for a fresh non-HOLD signal")
    parser.add_argument("--min-analysis-score", type=float, default=0.65, help="Minimum deep-analysis score required before trading")
    parser.add_argument("--disable-deep-analysis", action="store_true", help="Trade on primary strategy signals without extra analysis scoring")
    parser.add_argument("--list-symbols", action="store_true", help="List synthetic-account broker symbols")
    parser.add_argument("--symbol-filter", default="fx,vol,index,sfx", help="Comma-separated filter for --list-symbols")
    parser.add_argument("--dry-run", action="store_true", help="Only preview trades without sending orders")
    return parser


def run_trade_cycle(options: SyntheticTradeOptions) -> int:
    """Execute one synthetic FX-index trade scan."""
    account_id = options.account_id

    if settings.synthetic_demo_only and not SYNTHETIC_MT5_PROFILE["demo_mode"]:
        logger.error("Synthetic trading is configured for demo mode only")
        return 1

    if not all(
        [
            SYNTHETIC_MT5_PROFILE["account_number"],
            SYNTHETIC_MT5_PROFILE["password"],
            SYNTHETIC_MT5_PROFILE["server"],
        ]
    ):
        logger.error(
            "Synthetic MT5 account profile is incomplete. Set SYNTHETIC_MT5_ACCOUNT_NUMBER, "
            "SYNTHETIC_MT5_PASSWORD, and SYNTHETIC_MT5_SERVER."
        )
        return 1

    if not mt5_collector.connect():
        logger.error("Could not connect to MT5")
        return 1

    terminal_info = mt5_collector.service.terminal_info() or {}
    account_info = mt5_collector.get_account_info() or {}
    trading_warnings = _trading_disabled_warnings(terminal_info, account_info)
    if trading_warnings:
        message = "; ".join(trading_warnings)
        if options.dry_run:
            logger.warning("%s; continuing because --dry-run will not submit orders", message)
        else:
            logger.error("%s", message)
            return 1

    if options.list_symbols:
        symbols = _list_broker_symbols(options.symbol_filter)
        logger.info("Synthetic account symbols matching '%s': %s", options.symbol_filter, len(symbols))
        for symbol in symbols:
            logger.info("  %s", symbol)
        return 0

    targets = _resolve_trade_targets(options.symbol)
    if not targets:
        logger.error("No synthetic symbols resolved from broker symbol list")
        return 1

    account_balance = float(options.account_balance or account_info.get("balance") or 10000.0)
    now = datetime.now()
    max_total = settings.synthetic_max_trades_per_day
    max_per_symbol = settings.synthetic_max_trades_per_symbol_per_day

    db_manager.initialize()
    try:
        if not options.dry_run:
            _sync_broker_open_positions(account_id, {symbol for _, symbol, _ in targets})
        for bucket, symbol, strategy_class in targets:
            allowed, cap_warnings = _trade_allowed(account_id, symbol, now, max_total, max_per_symbol)
            if not allowed:
                logger.warning("%s", "; ".join(cap_warnings))
                continue

            if _has_open_position(account_id, symbol):
                logger.info("Skipping %s on %s because an open position already exists", symbol, account_id)
                continue

            if not mt5_collector.validate_symbol(symbol):
                logger.warning("Symbol not tradable: %s", symbol)
                continue

            live_data = _load_synthetic_live_data(symbol, timeframe=options.timeframe, lookback=options.lookback_days)
            if live_data.empty:
                logger.warning("No candle history available for %s", symbol)
                continue

            strategy = strategy_class()
            signal_series = strategy.generate_signals(live_data)
            if signal_series.empty:
                logger.info("No signal generated for %s", symbol)
                continue

            latest_signal, signal_age, signal_index, recent_signals, inspected_candles = _select_recent_signal(
                signal_series,
                options.signal_lookback_candles,
            )
            if latest_signal == 0:
                latest_row = live_data.iloc[-1]
                latest_time = latest_row.get("time", "unknown") if hasattr(latest_row, "get") else "unknown"
                logger.info(
                    "Hold signal for %s | inspected_candles=%s | recent_nonzero=%s | latest_time=%s | latest_close=%.5f",
                    symbol,
                    inspected_candles,
                    recent_signals,
                    latest_time,
                    float(latest_row["close"]),
                )
                continue
            if signal_age:
                logger.info(
                    "Using recent %s signal for %s from %s candle(s) ago at %s",
                    "BUY" if latest_signal > 0 else "SELL",
                    symbol,
                    signal_age,
                    signal_index,
                )

            analysis_score = 1.0
            analysis_reasons = ["deep analysis disabled"]
            if options.deep_analysis:
                analysis_passed, analysis_score, analysis_reasons = _deep_market_analysis(
                    latest_signal,
                    live_data,
                    options.min_analysis_score,
                )
                if not analysis_passed:
                    logger.info(
                        "Deep analysis blocked %s %s on %s | score=%.2f minimum=%.2f | %s",
                        symbol,
                        "BUY" if latest_signal > 0 else "SELL",
                        account_id,
                        analysis_score,
                        options.min_analysis_score,
                        "; ".join(analysis_reasons),
                    )
                    continue
                logger.info(
                    "Deep analysis approved %s %s on %s | score=%.2f | %s",
                    symbol,
                    "BUY" if latest_signal > 0 else "SELL",
                    account_id,
                    analysis_score,
                    "; ".join(analysis_reasons),
                )

            trade_context = mt5_collector.service.symbol_trade_context(symbol) or {}
            trade_setup = build_trade_setup(
                symbol=symbol,
                signal=latest_signal,
                entry_price=float(live_data.iloc[-1]["close"]),
                account_balance=account_balance,
                risk_per_trade_pct=options.risk_per_trade,
                reward_to_risk_ratio=options.reward_to_risk,
                trade_context=trade_context,
                max_spread_points=options.max_spread_points,
            )
            trade_setup["magic"] = _synthetic_magic(account_id, bucket)
            trade_setup["comment"] = f"syn_{account_id}_{bucket}"[:31]

            if trade_setup["warnings"]:
                logger.warning("%s: %s", symbol, "; ".join(trade_setup["warnings"]))
                blocked_keywords = {
                    "terminal trading is disabled",
                    "account trading is disabled",
                    "symbol is not visible",
                    "spread exceeds configured maximum",
                    "free margin is below estimated required margin",
                }
                if any(any(keyword in warning.lower() for keyword in blocked_keywords) for warning in trade_setup["warnings"]):
                    continue

            order_request = _build_order_request(symbol, trade_setup)
            if not options.dry_run:
                check_result = _order_check_with_filling_retry(symbol, order_request)
                if check_result:
                    check_retcode = _normalize_retcodes(check_result)
                    if not _retcode_succeeded(check_retcode):
                        logger.warning("%s order check rejected request: %s", symbol, check_result)
                        continue

            if options.dry_run:
                logger.info(
                    "DRY RUN %s %s lot=%.2f entry=%.5f sl=%.5f tp=%.5f",
                    symbol,
                    trade_setup["signal_type"],
                    trade_setup["lot_size"],
                    trade_setup["entry_price"],
                    trade_setup["stop_loss"],
                    trade_setup["take_profit"],
                )
                continue

            order_result = mt5_collector.service.order_send(order_request)
            if not order_result:
                logger.error("Order send failed for %s", symbol)
                continue

            retcode = _normalize_retcodes(order_result)
            logger.info(
                "Order result %s retcode=%s order=%s deal=%s price=%s",
                symbol,
                retcode,
                order_result.get("order"),
                order_result.get("deal"),
                order_result.get("price"),
            )
            if not _retcode_succeeded(retcode):
                logger.warning("%s order was not accepted by MT5: %s", symbol, order_result)
                continue

            strategy_name = strategy.__class__.__name__
            signal_record_id = None
            try:
                signal_record = db_manager.insert_signal(
                    {
                        "symbol": symbol,
                        "account_id": account_id,
                        "signal_type": trade_setup["signal_type"],
                        "timestamp": datetime.now(),
                        "entry_price": trade_setup["entry_price"],
                        "stop_loss": trade_setup["stop_loss"],
                        "take_profit": trade_setup["take_profit"],
                        "position_size": trade_setup["lot_size"],
                        "risk_amount": trade_setup["risk_amount"],
                        "reward_amount": abs(trade_setup["take_profit"] - trade_setup["entry_price"]) * trade_setup["lot_size"],
                        "risk_reward_ratio": trade_setup["risk_reward_ratio"],
                        "confidence_score": analysis_score,
                        "model_version": _synthetic_model_version(bucket, strategy_name),
                        "reasoning": f"synthetic {bucket}% demo trade via {strategy_name}",
                        "is_active": True,
                        "is_manual": False,
                    }
                )
                signal_record_id = signal_record.id
            except Exception as exc:
                logger.error(
                    "Broker order accepted for %s but signal logging failed; storing trade without signal link: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )

            try:
                _store_trade(
                    account_id=account_id,
                    symbol=symbol,
                    strategy_name=strategy_name,
                    signal_record_id=signal_record_id,
                    order_result=order_result,
                    trade_setup=trade_setup,
                )
            except Exception as exc:
                logger.error("Broker order accepted for %s but trade logging failed: %s", symbol, exc, exc_info=True)
                continue
            logger.info(
                "Stored synthetic demo trade for %s | symbol cap %s/%s | total cap %s/%s",
                symbol,
                db_manager.count_trades_since(now - timedelta(hours=24), symbol=symbol, account_id=account_id),
                max_per_symbol,
                db_manager.count_trades_since(now - timedelta(hours=24), account_id=account_id),
                max_total,
            )
    finally:
        db_manager.close()

    return 0


def main() -> int:
    """Execute synthetic FX-index demo trades."""
    parser = build_parser()
    options = SyntheticTradeOptions.from_namespace(parser.parse_args())
    return run_trade_cycle(options)


if __name__ == "__main__":
    sys.exit(main())
