#!/usr/bin/env python3
"""Auto-trade the synthetic FX indices on a demo MT5 account."""

from __future__ import annotations

import os
import sys
import time
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.indicators.indicators import (
    MomentumIndicators,
    MovingAverages,
    VolatilityIndicators,
)
from backend.market_data.data_collector import MT5DataCollector
from backend.market_data.mt5_service import MT5Service
from backend.strategies.synthetic_indices import (
    SyntheticBalancedMomentumStrategy,
    SyntheticBreakoutStrategy,
    SyntheticTrendStrategy,
)
from backend.risk.risk_manager import RiskManager
from database.database_manager import db_manager
from scripts.live_trade_signal import build_trade_setup, _normalize_volume
import random
from statistics import mean
from datetime import timedelta

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - dependency is installed on Windows
    mt5 = None


logger = setup_logger(__name__)

DEFAULT_MIN_ANALYSIS_SCORE = 0.45
ADAPTIVE_WINRATE_TARGET = 0.60
ADAPTIVE_ALPHA = 0.25  # smoothing factor for adaptive offset
EXPLORATION_EPSILON = 0.03  # chance to explore low-confidence trades
MIN_RISK_MULTIPLIER = 0.5
MAX_RISK_MULTIPLIER = 1.5


def _resolve_account_id(explicit_account_id: str | None = None) -> str:
    """Return the local account identifier for the currently configured MT5 profile."""
    if explicit_account_id:
        return explicit_account_id

    env_account_id = os.getenv("NTRADE_SYNTHETIC_ACCOUNT_ID")
    if env_account_id:
        return env_account_id

    profile = settings.mt5_account_profile("synthetic")
    account_number = profile.get("account_number")
    if account_number:
        return f"synthetic_{account_number}"

    return str(profile.get("account_id") or "synthetic")


@dataclass(frozen=True)
class SyntheticTradeOptions:
    symbol: str | None = None
    focus_symbol: str | None = None
    account_id: str = "synthetic"
    timeframe: int = 5
    lookback_days: int = 90
    account_balance: float | None = None
    risk_per_trade: float = 1.0
    reward_to_risk: float = 2.0
    max_spread_points: float = 50.0
    signal_lookback_candles: int = 3
    min_analysis_score: float = DEFAULT_MIN_ANALYSIS_SCORE
    deep_analysis: bool = True
    analysis_delay_seconds: float = 35.0
    list_symbols: bool = False
    symbol_filter: str = "fx,vol,index,sfx"
    dry_run: bool = False

    @classmethod
    def from_namespace(cls, args: Namespace) -> "SyntheticTradeOptions":
        return cls(
            symbol=args.symbol,
            focus_symbol=getattr(args, "focus_symbol", None),
            account_id=_resolve_account_id(args.account_id),
            timeframe=args.timeframe,
            lookback_days=args.lookback_days,
            account_balance=args.account_balance,
            risk_per_trade=args.risk_per_trade,
            reward_to_risk=args.reward_to_risk,
            max_spread_points=args.max_spread_points,
            signal_lookback_candles=args.signal_lookback_candles,
            min_analysis_score=getattr(
                args,
                "min_analysis_score",
                DEFAULT_MIN_ANALYSIS_SCORE,
            ),
            deep_analysis=not args.disable_deep_analysis,
            analysis_delay_seconds=args.analysis_delay_seconds,
            list_symbols=args.list_symbols,
            symbol_filter=args.symbol_filter,
            dry_run=args.dry_run,
        )


def _refresh_synthetic_mt5_context() -> dict[str, object]:
    global SYNTHETIC_MT5_PROFILE, synthetic_mt5_service, mt5_collector

    SYNTHETIC_MT5_PROFILE = settings.mt5_account_profile("synthetic")
    synthetic_mt5_service = MT5Service(
        account_number=SYNTHETIC_MT5_PROFILE["account_number"],
        password=SYNTHETIC_MT5_PROFILE["password"],
        server=SYNTHETIC_MT5_PROFILE["server"],
        terminal_path=SYNTHETIC_MT5_PROFILE.get("terminal_path"),
        profile_name="synthetic",
    )
    mt5_collector = MT5DataCollector(service=synthetic_mt5_service)
    return SYNTHETIC_MT5_PROFILE


SYNTHETIC_MT5_PROFILE = {}
synthetic_mt5_service = None
mt5_collector = None
_refresh_synthetic_mt5_context()


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
    fallback = {0, 10008, 10009, 10010}
    if mt5 is None:
        return fallback
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
    strategy_alias = aliases.get(
        strategy_name,
        strategy_name.replace("Synthetic", "").replace("Strategy", "").lower(),
    )
    return f"syn_{bucket}_{strategy_alias}"[:20]


def _synthetic_magic(account_id: str, bucket: str) -> int:
    """Create a stable MT5 magic number per account and volatility bucket."""
    seed = f"{account_id}:{bucket}:synthetic"
    return 700000 + (
        sum((index + 1) * ord(character) for index, character in enumerate(seed))
        % 200000
    )


def _trading_disabled_warnings(terminal_info: dict, account_info: dict) -> list[str]:
    warnings: list[str] = []
    if terminal_info.get("trade_allowed") is False:
        warnings.append("Terminal trading is disabled")
    if account_info.get("trade_allowed") is False:
        warnings.append("Account trading is disabled")
    return warnings


def _balance_aware_trade_filters(
    account_balance: float | None,
    analysis_score: float,
    spread_points: float | None,
    signal_strength: int,
    focus_profile: dict[str, float | int | str] | None = None,
) -> tuple[bool, list[str], dict[str, float | str]]:
    """Apply a stricter approval gate for small balances while preserving execution potential."""
    if account_balance is None:
        return True, [], {"tier": "standard", "min_score": 0.45, "risk_multiplier": 1.0}

    profile = {"tier": "standard", "min_score": 0.45, "risk_multiplier": 1.0}
    reasons: list[str] = []
    if account_balance < 5.0:
        profile = {"tier": "micro", "min_score": 0.70, "risk_multiplier": 0.75}
    elif account_balance < 20.0:
        profile = {"tier": "small", "min_score": 0.55, "risk_multiplier": 1.0}

    if focus_profile is not None:
        recent_trades_count = int(focus_profile.get("recent_trades_count", 0))
        target_daily_trades = int(focus_profile.get("target_daily_trades", 4))
        if recent_trades_count < target_daily_trades:
            profile["min_score"] = 0.45
            profile["risk_multiplier"] = max(float(profile["risk_multiplier"]), 1.0)

    if (
        spread_points is not None
        and spread_points > 20.0
        and profile["tier"] != "standard"
    ):
        reasons.append("spread too wide for small account")
    if signal_strength == 0:
        reasons.append("signal lacked directional strength")
    if analysis_score < float(profile["min_score"]):
        reasons.append(f"analysis below {float(profile['min_score']):.2f} threshold")

    approved = not reasons
    return approved, reasons, profile


def _normalized_symbol_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _resolve_symbol(
    configured_symbol: str, search_terms: list[str], broker_symbols: list[str]
) -> str | None:
    """Resolve the best broker symbol using exact config first, then search terms."""
    if configured_symbol:
        configured_key = _normalized_symbol_text(configured_symbol)
        for symbol in broker_symbols:
            if _normalized_symbol_text(symbol) == configured_key:
                return symbol

    normalized_terms = [
        _normalized_symbol_text(term) for term in search_terms if term.strip()
    ]
    candidates: list[tuple[int, str]] = []
    for symbol in broker_symbols:
        symbol_key = _normalized_symbol_text(symbol)
        if not all(term in symbol_key for term in normalized_terms):
            continue

        score = sum(len(term) for term in normalized_terms)
        if (
            configured_symbol
            and _normalized_symbol_text(configured_symbol) in symbol_key
        ):
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
            logger.warning(
                "Could not resolve synthetic %s%% symbol from broker list", bucket
            )
            continue

        if requested_symbol and _normalized_symbol_text(
            requested_symbol
        ) != _normalized_symbol_text(symbol):
            continue

        targets.append((bucket, symbol, profile["strategy"]))

    if requested_symbol and not targets:
        logger.warning(
            "Requested symbol was not resolved as a configured synthetic index: %s",
            requested_symbol,
        )

    return targets


def _list_broker_symbols(filter_text: str | None = None) -> list[str]:
    """List broker symbols from the synthetic MT5 account, optionally filtered."""
    symbols = mt5_collector.service.symbols()
    if not filter_text:
        return symbols

    filters = [
        _normalized_symbol_text(item) for item in filter_text.split(",") if item.strip()
    ]
    return [
        symbol
        for symbol in symbols
        if any(
            filter_value in _normalized_symbol_text(symbol) for filter_value in filters
        )
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


def _load_multitimeframe_data(symbol: str, lookback_days: int) -> dict[str, object]:
    """Load W1/D1/H4/H1/M30/M15/M5 data for confluence analysis."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=max(lookback_days, 180))
    timeframes = {
        "W1": 10080,
        "D1": 1440,
        "H4": 240,
        "H1": 60,
        "M30": 30,
        "M15": 15,
        "M5": 5,
    }

    frames: dict[str, object] = {}
    for name, timeframe in timeframes.items():
        data = mt5_collector.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            limit=400,
        )
        if data is not None and not data.empty:
            frames[name] = data

    if not frames:
        raise RuntimeError(f"No timeframe data returned for {symbol}")

    return frames


def _select_recent_signal(
    signal_series, lookback_candles: int
) -> tuple[int, int | None, object | None, int, int]:
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
            selected = (
                signal,
                len(signal_series) - 1 - position,
                signal_series.index[position],
            )

    return (
        selected[0],
        selected[1],
        selected[2],
        recent_nonzero_count,
        len(signal_series) - start_position,
    )


def _evaluate_multi_timeframe_signal(
    signal: int,
    signals_by_timeframe: dict[str, int],
    minimum_score: float,
) -> tuple[bool, float, list[str]]:
    """Score a trade signal using a confluence approach across multiple timeframes."""
    if signal == 0:
        return False, 0.0, ["no primary signal"]

    direction = 1 if signal > 0 else -1
    if not signals_by_timeframe:
        return False, 0.0, ["no timeframe signals available"]

    aligned = sum(
        1 for frame_signal in signals_by_timeframe.values() if frame_signal == direction
    )
    opposing = sum(
        1
        for frame_signal in signals_by_timeframe.values()
        if frame_signal == -direction
    )
    neutral = sum(
        1 for frame_signal in signals_by_timeframe.values() if frame_signal == 0
    )

    total_frames = len(signals_by_timeframe)
    confluence_ratio = aligned / max(total_frames, 1)
    opposition_ratio = opposing / max(total_frames, 1)
    score = 0.35 + (confluence_ratio * 0.45) - (opposition_ratio * 0.20)
    score = min(max(score, 0.0), 1.0)

    reasons = [
        f"{aligned}/{total_frames} timeframes agree with the signal; {neutral} are neutral"
    ]
    if confluence_ratio >= 0.6:
        reasons.append("higher timeframes support the move")
    else:
        reasons.append("higher timeframes are mixed")

    if opposition_ratio == 0:
        reasons.append("no strong conflict from lower timeframes")
    else:
        reasons.append("lower timeframes show conflicting pressure")

    return score >= minimum_score, score, reasons


def _deep_market_analysis(
    signal: int, data, minimum_score: float, timeframe: int = 5
) -> tuple[bool, float, list[str]]:
    """Score a strategy signal with multi-timeframe confluence and local market checks."""
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
    atr = VolatilityIndicators.atr(
        high.to_numpy(), low.to_numpy(), close.to_numpy(), 14
    )

    latest_close = float(close.iloc[-1])
    latest_fast = float(fast_ema[-1])
    latest_slow = float(slow_ema[-1])
    latest_rsi = float(rsi[-1])
    latest_atr = float(atr[-1])
    momentum = latest_close - float(close.iloc[-7])
    atr_ratio = latest_atr / latest_close if latest_close else 0.0

    score = 0.30
    reasons = ["primary strategy signal", f"entry timeframe M{timeframe}"]

    trend_aligned = (latest_fast > latest_slow and direction > 0) or (
        latest_fast < latest_slow and direction < 0
    )
    if trend_aligned:
        score += 0.20
        reasons.append("EMA trend aligned")
    else:
        reasons.append("EMA trend disagrees")

    momentum_aligned = (momentum > 0 and direction > 0) or (
        momentum < 0 and direction < 0
    )
    if momentum_aligned:
        score += 0.15
        reasons.append("short momentum aligned")
    else:
        reasons.append("short momentum disagrees")

    rsi_aligned = (50 <= latest_rsi <= 78 and direction > 0) or (
        22 <= latest_rsi <= 50 and direction < 0
    )
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


def _get_recent_closed_trade_feedback(
    symbol: str, account_id: str, now: datetime, lookback_hours: int = 24
) -> list[dict[str, object]]:
    """Return recent closed trades from local trade history first, then MT5 history."""
    feedback: list[dict[str, object]] = []

    try:
        if hasattr(db_manager, "get_closed_trades"):
            trade_days = max(1, int((lookback_hours + 23) // 24))
            trades = db_manager.get_closed_trades(
                symbol=symbol,
                account_id=account_id,
                days=trade_days,
            )
            for trade in trades:
                profit_loss = getattr(trade, "profit_loss", None)
                try:
                    profit_value = (
                        float(profit_loss) if profit_loss is not None else 0.0
                    )
                except (TypeError, ValueError):
                    profit_value = 0.0
                feedback.append(
                    {
                        "symbol": str(getattr(trade, "symbol", symbol) or symbol),
                        "profit_loss": profit_value,
                    }
                )
            if feedback:
                return feedback
    except Exception as exc:  # pragma: no cover - database/library failure
        logger.debug("Local trade feedback lookup failed for %s: %s", symbol, exc)

    since = now - timedelta(hours=lookback_hours)
    try:
        history = mt5_collector.service.get_trade_history(start=since, end=now)
    except Exception as exc:  # pragma: no cover - broker/library failure
        logger.warning("Trade feedback lookup failed: %s", exc)
        return []

    for deal in history:
        deal_symbol = str(deal.get("symbol") or "")
        deal_account = str(deal.get("account") or "")
        if not deal_symbol or deal_symbol != symbol:
            continue
        if account_id and deal_account and deal_account != account_id:
            continue
        profit_loss = deal.get("profit")
        try:
            profit_value = float(profit_loss) if profit_loss is not None else 0.0
        except (TypeError, ValueError):
            profit_value = 0.0
        feedback.append({"symbol": deal_symbol, "profit_loss": profit_value})
    return feedback


def _compute_recent_win_rate(
    account_id: str, symbol: str | None, lookback_days: int = 30
) -> float:
    """Compute simple recent win rate from closed trades in the DB."""
    try:
        trades = db_manager.get_closed_trades(
            symbol=symbol, account_id=account_id, days=lookback_days
        )
    except Exception:
        return 0.0

    if not trades:
        return 0.0

    profits = []
    for t in trades:
        try:
            pnl = float(getattr(t, "profit_loss", 0.0) or 0.0)
        except Exception:
            pnl = 0.0
        profits.append(pnl)

    wins = sum(1 for p in profits if p > 0)
    return wins / max(len(profits), 1)


def _compute_adaptive_offset(
    account_id: str, symbol: str | None, base_alpha: float = ADAPTIVE_ALPHA
) -> float:
    """Return a clamped adaptive offset for the analysis threshold based on recent win-rate.

    Positive offset lowers the required confidence (makes system looser) when win-rate is high;
    negative offset tightens requirements when win-rate is poor. Output is clamped to [-0.08, 0.08].
    """
    recent_win = _compute_recent_win_rate(account_id, symbol, lookback_days=14)
    target = ADAPTIVE_WINRATE_TARGET
    # Fractional difference
    diff = recent_win - target
    # Convert diff into an offset using smoothing alpha
    offset = base_alpha * diff
    # Clamp offset
    offset = max(min(offset, 0.08), -0.08)
    return offset


def _compute_risk_multiplier(
    analysis_score: float,
    feedback_profile: dict | None = None,
    focus_profile: dict | None = None,
) -> float:
    """Map analysis confidence to a risk multiplier in a stable manner."""
    base = max(0.0, min(1.0, float(analysis_score or 0.0)))
    # simple mapping: center confidence 0.5 -> multiplier ~1.0
    multiplier = MIN_RISK_MULTIPLIER + (
        base * (MAX_RISK_MULTIPLIER - MIN_RISK_MULTIPLIER)
    )

    # incorporate feedback and focus multipliers if present
    if feedback_profile:
        try:
            multiplier *= float(feedback_profile.get("risk_multiplier", 1.0))
        except Exception:
            pass
    if focus_profile:
        try:
            multiplier *= float(focus_profile.get("risk_multiplier", 1.0))
        except Exception:
            pass

    # clamp final multiplier
    multiplier = max(MIN_RISK_MULTIPLIER, min(MAX_RISK_MULTIPLIER, multiplier))
    return multiplier


def _build_symbol_focus_profile(
    recent_trades_count: int, target_daily_trades: int = 4
) -> dict[str, float | int | str]:
    """Build a focused-symbol profile that encourages activity until a daily target is reached."""
    target = max(1, int(target_daily_trades))
    if recent_trades_count >= target:
        return {
            "threshold_offset": 0.0,
            "risk_multiplier": 1.0,
            "confidence_bias": 0.0,
            "recent_trades_count": recent_trades_count,
            "target_daily_trades": target,
            "summary": f"focus target reached ({recent_trades_count}/{target})",
        }

    deficit = target - recent_trades_count
    if deficit >= 2:
        return {
            "threshold_offset": -0.03,
            "risk_multiplier": 1.03,
            "confidence_bias": 0.02,
            "recent_trades_count": recent_trades_count,
            "target_daily_trades": target,
            "summary": f"focus target pending ({recent_trades_count}/{target})",
        }

    return {
        "threshold_offset": -0.02,
        "risk_multiplier": 1.02,
        "confidence_bias": 0.01,
        "recent_trades_count": recent_trades_count,
        "target_daily_trades": target,
        "summary": f"focus target pending ({recent_trades_count}/{target})",
    }


def _build_profit_target_profile(
    account_balance: float | None, recent_trade_count: int = 0
) -> dict[str, float | int | str]:
    """Build a conservative profit-target profile for safer money-making."""
    balance = float(account_balance or 100.0)
    recent_count = max(0, int(recent_trade_count))

    if balance < 20.0:
        profit_floor = 2.0
        daily_target = 8.0
        daily_loss_floor = 4.0
        threshold_offset = 0.05
        risk_multiplier = 0.85
        confidence_bias = -0.03
    elif balance < 100.0:
        profit_floor = 2.5
        daily_target = 8.0
        daily_loss_floor = 4.5
        threshold_offset = 0.04 if recent_count < 2 else 0.02
        risk_multiplier = 0.90 if recent_count < 2 else 0.95
        confidence_bias = -0.02 if recent_count < 2 else 0.0
    else:
        profit_floor = 2.8
        daily_target = 10.0
        daily_loss_floor = 5.0
        threshold_offset = 0.03 if recent_count < 2 else 0.0
        risk_multiplier = 0.92 if recent_count < 2 else 0.98
        confidence_bias = -0.01 if recent_count < 2 else 0.0

    return {
        "profit_floor": round(profit_floor, 2),
        "daily_target": round(daily_target, 2),
        "daily_loss_floor": round(daily_loss_floor, 2),
        "threshold_offset": round(threshold_offset, 2),
        "risk_multiplier": round(risk_multiplier, 2),
        "confidence_bias": round(confidence_bias, 2),
        "summary": "profit-target discipline: wait for stronger setups",
    }


def _build_feedback_profile(
    recent_trades: list[dict[str, object]],
) -> dict[str, float | int | str]:
    """Convert recent trade outcomes into an adaptive profile for threshold and risk control."""
    if not recent_trades:
        return {
            "threshold_offset": 0.0,
            "risk_multiplier": 1.0,
            "confidence_bias": 0.0,
            "reviewed_trades": 0,
            "summary": "no recent closed trades available",
        }

    profits = [float(trade.get("profit_loss") or 0.0) for trade in recent_trades]
    winning = sum(1 for value in profits if value > 0)
    losing = sum(1 for value in profits if value < 0)
    win_rate = winning / max(len(profits), 1)
    average_pnl = sum(profits) / max(len(profits), 1)
    total_pnl = sum(profits)

    threshold_offset = 0.0
    risk_multiplier = 1.0
    confidence_bias = 0.0
    reasons: list[str] = []

    if win_rate >= 0.7 and total_pnl > 0:
        threshold_offset = -0.04
        risk_multiplier = 1.08
        confidence_bias = 0.04
        reasons.append(f"strong recent momentum: {win_rate:.0%} win rate")
    elif win_rate <= 0.3 or total_pnl < 0:
        threshold_offset = 0.06
        risk_multiplier = 0.85
        confidence_bias = -0.04
        reasons.append(f"recent losses: {win_rate:.0%} win rate")
    else:
        threshold_offset = 0.0
        risk_multiplier = 1.0
        confidence_bias = 0.0
        reasons.append(f"mixed feedback: {win_rate:.0%} win rate")

    if average_pnl > 0:
        threshold_offset -= 0.01
        confidence_bias += 0.01
        reasons.append("average P&L positive")
    elif average_pnl < 0:
        threshold_offset += 0.01
        confidence_bias -= 0.01
        reasons.append("average P&L negative")

    reasons.append(f"{len(profits)} closed trades reviewed")
    return {
        "threshold_offset": round(min(max(threshold_offset, -0.08), 0.08), 2),
        "risk_multiplier": round(min(max(risk_multiplier, 0.7), 1.2), 2),
        "confidence_bias": round(min(max(confidence_bias, -0.08), 0.08), 2),
        "reviewed_trades": len(profits),
        "summary": "; ".join(reasons),
    }


def _count_recent_mt5_activity(
    account_id: str, symbol: str, now: datetime
) -> tuple[int, int]:
    """Count unique recent MT5 deals for the current account and symbol."""
    since = now - timedelta(hours=24)
    seen_total: set[str] = set()
    seen_symbol: set[str] = set()

    try:
        history = mt5_collector.service.get_trade_history(start=since, end=now)
    except Exception as exc:  # pragma: no cover - broker/library failure
        logger.warning("Trade-cap history lookup failed: %s", exc)
        history = []

    for deal in history:
        deal_symbol = str(deal.get("symbol") or "")
        if not deal_symbol:
            continue
        ticket = str(deal.get("ticket") or "")
        key = (
            ticket
            or f"{deal_symbol}:{deal.get('entry_time') or ''}:{deal.get('type') or ''}"
        )
        seen_total.add(key)
        if deal_symbol == symbol:
            seen_symbol.add(key)

    return len(seen_total), len(seen_symbol)


def _trade_setup_has_blocking_warnings(warnings: list[str]) -> bool:
    """Return True when the trade setup has warnings that materially break execution policy."""
    blocked_keywords = {
        "calculated lot size exceeded broker maximum",
        "calculated lot size is zero",
    }
    lowered = [str(warning).lower() for warning in warnings or []]
    return any(
        keyword in warning for warning in lowered for keyword in blocked_keywords
    )


def _trade_setup_meets_min_reward_target(
    trade_setup: dict[str, object],
    min_reward: float = 2.0,
    profit_target_profile: dict[str, object] | None = None,
) -> bool:
    """Return True when the trade setup can reasonably reach the configured reward floor."""
    try:
        risk_amount = float(
            trade_setup.get("actual_risk_amount")
            or trade_setup.get("risk_amount")
            or 0.0
        )
    except (TypeError, ValueError):
        risk_amount = 0.0

    if risk_amount <= 0.0:
        return False

    try:
        reward_to_risk = float(trade_setup.get("risk_reward_ratio") or 0.0)
    except (TypeError, ValueError):
        reward_to_risk = 0.0

    if reward_to_risk <= 0.0:
        return False

    effective_min_reward = float(min_reward)
    if profit_target_profile is not None:
        try:
            profile_floor = float(profit_target_profile.get("profit_floor") or 0.0)
        except (TypeError, ValueError):
            profile_floor = 0.0
        if profile_floor > 0.0:
            effective_min_reward = max(effective_min_reward, profile_floor)

    projected_reward = risk_amount * reward_to_risk
    return projected_reward >= effective_min_reward


def _apply_micro_account_policy(
    trade_setup: dict[str, object], analysis_score: float, account_balance: float
) -> tuple[bool, str | None]:
    """Enforce micro-account rules: for balances <= $15 require high-confidence
    setups that project > $3 reward, then place TP strictly in $2-$3 range.

    Returns (allowed: bool, reason_or_none).
    """
    try:
        if float(account_balance) > 15.0:
            return True, None
    except Exception:
        return True, None

    # micro account policy thresholds
    MIN_CONFIDENCE = 0.75
    REQUIRED_PROJECTED_REWARD = 3.0

    try:
        projected_reward = float(trade_setup.get("actual_risk_amount", 0.0)) * float(
            trade_setup.get("risk_reward_ratio", 0.0)
        )
    except Exception:
        projected_reward = 0.0

    if float(analysis_score or 0.0) < MIN_CONFIDENCE:
        return False, f"micro-account requires confidence>={MIN_CONFIDENCE:.2f}"

    if projected_reward < REQUIRED_PROJECTED_REWARD:
        return (
            False,
            f"projected reward ${projected_reward:.2f} below required ${REQUIRED_PROJECTED_REWARD:.2f}",
        )

    # enforce conservative TP between $2 and $3 (choose min(projected,3) but >=2)
    desired_reward = max(2.0, min(3.0, projected_reward))
    try:
        entry = float(trade_setup.get("entry_price") or 0.0)
        direction = 1 if int(trade_setup.get("signal", 0)) > 0 else -1
        new_tp = entry + (direction * desired_reward)
        trade_setup["take_profit"] = new_tp
        # recompute risk_reward_ratio to reflect new TP
        try:
            risk = float(trade_setup.get("actual_risk_amount") or 0.0)
            new_rr = (
                desired_reward / risk
                if risk > 0
                else trade_setup.get("risk_reward_ratio")
            )
            trade_setup["risk_reward_ratio"] = float(new_rr)
        except Exception:
            pass
        trade_setup.setdefault("warnings", []).append(
            f"micro-account TP enforced ${desired_reward:.2f}"
        )
    except Exception:
        return False, "failed to enforce micro-account TP"

    return True, None


def _trade_allowed(
    account_id: str,
    symbol: str,
    now: datetime,
    max_total: int,
    max_per_symbol: int,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    try:
        total_trades, symbol_trades = _count_recent_mt5_activity(
            account_id, symbol, now
        )
    except Exception as exc:  # pragma: no cover - broker/library failure
        logger.warning("Falling back to DB trade counts for caps: %s", exc)
        since = now - timedelta(hours=24)
        total_trades = db_manager.count_trades_since(since, account_id=account_id)
        symbol_trades = db_manager.count_trades_since(
            since, symbol=symbol, account_id=account_id
        )

    if total_trades >= max_total:
        warnings.append(f"Daily trade cap reached ({total_trades}/{max_total})")
    if symbol_trades >= max_per_symbol:
        warnings.append(f"Daily symbol cap reached ({symbol_trades}/{max_per_symbol})")

    return not warnings, warnings


def _extract_trade_ticket_from_notes(notes: str | None) -> str | None:
    """Parse an MT5 trade ticket from local trade notes."""
    if not notes:
        return None

    for segment in str(notes).split(";"):
        if segment.strip().startswith("trade_id="):
            _, _, ticket = segment.partition("=")
            return ticket.strip() or None

    return None


def _reconcile_stale_local_open_trades(
    account_id: str,
    symbol: str,
    open_trades: list,
    active_tickets: set[str],
) -> None:
    """Close stale local open trades that have no matching active broker ticket."""
    for trade in open_trades:
        ticket = _extract_trade_ticket_from_notes(getattr(trade, "notes", None))
        if not ticket or ticket in active_tickets:
            continue

        try:
            db_manager.update_trade(
                trade.id,
                {
                    "status": "CLOSED",
                    "exit_time": datetime.now(),
                    "exit_price": float(getattr(trade, "entry_price", 0.0)),
                    "profit_loss": 0.0,
                    "profit_loss_percent": 0.0,
                    "exit_reason": "STALE_LOCAL_RECONCILE",
                    "notes": f"{getattr(trade, 'notes', '')}; reconciled_stale_open_trade",
                },
            )
            logger.info(
                "Closed stale local open trade %s for %s/%s",
                ticket,
                account_id,
                symbol,
            )
        except Exception as exc:
            logger.warning(
                "Failed to reconcile stale local open trade %s for %s/%s: %s",
                ticket,
                account_id,
                symbol,
                exc,
            )


def _has_open_position(account_id: str, symbol: str) -> bool:
    """Return True when MT5 or the local trade log indicates an open position."""
    broker_positions = mt5_collector.get_positions()
    if any(position.get("symbol") == symbol for position in broker_positions):
        return True

    open_trades = db_manager.get_open_trades(symbol=symbol, account_id=account_id)
    if not open_trades:
        return False

    if not mt5_collector.is_connected:
        # Broker state unavailable; preserve defensive local open-position protection.
        return True

    active_tickets = {
        str(position.get("ticket") or "")
        for position in broker_positions
        if position.get("symbol") == symbol
    }
    for trade in open_trades:
        ticket = _extract_trade_ticket_from_notes(getattr(trade, "notes", None))
        if ticket and ticket in active_tickets:
            return True

    _reconcile_stale_local_open_trades(account_id, symbol, open_trades, active_tickets)
    logger.info(
        "Ignoring stale local OPEN trades for %s/%s because broker has no matching active position",
        account_id,
        symbol,
    )
    return False


def _build_order_request(
    symbol: str, trade_setup: dict[str, object]
) -> dict[str, object]:
    """Build an MT5 market order request."""
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not installed")

    order_type = (
        mt5.ORDER_TYPE_BUY
        if trade_setup["signal_type"] == "BUY"
        else mt5.ORDER_TYPE_SELL
    )
    filling_mode = mt5_collector.service.preferred_filling_mode(symbol)
    type_filling = (
        filling_mode
        if filling_mode is not None
        else getattr(mt5, "ORDER_FILLING_RETURN", 0)
    )

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

    supported_modes = (
        getattr(mt5_collector.service, "supported_filling_modes", lambda _symbol: [])(
            symbol
        )
        or []
    )
    for mode in supported_modes:
        add_candidate(mode)

    if mt5 is not None:
        for name in ["ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"]:
            add_candidate(getattr(mt5, name, None))

    return candidates


def _order_check_with_filling_retry(
    symbol: str, order_request: dict[str, object]
) -> dict[str, object] | None:
    """Run order_check and retry alternate filling modes when MT5 rejects one."""
    last_result: dict[str, object] | None = None
    for filling_mode in _filling_mode_candidates(
        symbol, order_request.get("type_filling")
    ):
        order_request["type_filling"] = filling_mode
        check_result = mt5_collector.service.order_check(order_request)
        if not check_result:
            return check_result

        last_result = check_result
        check_retcode = _normalize_retcodes(check_result)
        logger.info(
            "%s order check retcode=%s type_filling=%s",
            symbol,
            check_retcode,
            filling_mode,
        )
        if _retcode_succeeded(check_retcode):
            return check_result
        if _retcode_is_unsupported_filling(check_retcode):
            logger.warning(
                "%s rejected filling mode %s; trying another supported mode",
                symbol,
                filling_mode,
            )
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


def _sync_closed_trades_from_mt5(account_id: str, symbols: set[str]) -> None:
    """Sync recent broker trade history into the local trade log so daily caps include closed trades."""
    since = datetime.now() - timedelta(hours=24)
    for deal in mt5_collector.service.get_trade_history(
        start=since, end=datetime.now()
    ):
        deal_symbol = str(deal.get("symbol") or "")
        ticket = str(deal.get("ticket") or "")
        if deal_symbol not in symbols:
            continue

        existing_trade = db_manager.get_trade_by_ticket(ticket, account_id=account_id)
        if existing_trade:
            if existing_trade.status == "OPEN":
                db_manager.update_trade(
                    existing_trade.id,
                    {
                        "status": "CLOSED",
                        "exit_time": (
                            datetime.fromtimestamp(float(deal.get("entry_time") or 0))
                            if deal.get("entry_time")
                            else datetime.now()
                        ),
                        "exit_price": float(
                            deal.get("price") or existing_trade.entry_price
                        ),
                        "profit_loss": float(
                            deal.get("profit") or existing_trade.profit_loss or 0.0
                        ),
                        "notes": f"{existing_trade.notes}; source=mt5_history",
                    },
                )
                logger.info(
                    "Updated local open trade to CLOSED for %s | ticket=%s",
                    deal_symbol,
                    ticket,
                )
            continue

        db_manager.insert_trade(
            {
                "signal_id": None,
                "account_id": account_id,
                "symbol": deal_symbol,
                "trade_type": str(deal.get("type") or "UNKNOWN"),
                "entry_time": (
                    datetime.fromtimestamp(float(deal.get("entry_time") or 0))
                    if deal.get("entry_time")
                    else datetime.now()
                ),
                "entry_price": float(deal.get("price") or 0.0),
                "position_size": float(deal.get("volume") or 0.0),
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "status": "CLOSED",
                "profit_loss": float(deal.get("profit") or 0.0),
                "notes": f"trade_id={ticket}; strategy=broker_sync; source=mt5_history",
            }
        )
        logger.info(
            "Synced closed broker trade for %s into local trade log | ticket=%s",
            deal_symbol,
            ticket,
        )


def _sync_broker_open_positions(account_id: str, symbols: set[str]) -> None:
    """Backfill open broker positions that are missing from the local trade log."""
    for position in mt5_collector.get_positions():
        symbol = str(position.get("symbol") or "")
        ticket = str(position.get("ticket") or "")
        if symbol not in symbols:
            continue
        if db_manager.get_trade_by_ticket(ticket, account_id=account_id):
            continue

        ticket = position.get("ticket") or 0
        open_time = position.get("open_time")
        try:
            entry_time = (
                datetime.fromtimestamp(float(open_time))
                if open_time
                else datetime.now()
            )
        except (TypeError, ValueError, OSError):
            entry_time = datetime.now()

        entry_price = float(
            position.get("open_price") or position.get("current_price") or 0.0
        )
        stop_loss = float(position.get("stop_loss") or 0.0)
        take_profit = float(position.get("take_profit") or 0.0)
        if entry_price <= 0:
            logger.warning(
                "Cannot sync broker position %s for %s because entry price is missing",
                ticket,
                symbol,
            )
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
        logger.info(
            "Synced open broker position for %s into local trade log | ticket=%s",
            symbol,
            ticket,
        )


def build_parser() -> ArgumentParser:
    """Build CLI parser for synthetic demo trading."""
    parser = ArgumentParser(
        description="Trade synthetic FX indices on a demo MT5 account"
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Trade only one resolved symbol, or bucket: 20, 40, 80",
    )
    parser.add_argument(
        "--focus-symbol",
        default=None,
        help="Restrict trading to one specific broker symbol and use a focused-symbol feedback profile",
    )
    parser.add_argument(
        "--account-id",
        default=str(
            settings.mt5_account_profile("synthetic").get("account_id") or "synthetic"
        ),
        help="Local account identifier for DB isolation",
    )
    parser.add_argument(
        "--timeframe", type=int, default=5, help="MT5 candle timeframe in minutes"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="History window for signal generation",
    )
    parser.add_argument(
        "--account-balance",
        type=float,
        default=None,
        help="Fallback demo balance for sizing",
    )
    parser.add_argument(
        "--risk-per-trade", type=float, default=1.0, help="Risk per trade percent"
    )
    parser.add_argument(
        "--reward-to-risk", type=float, default=2.0, help="Reward-to-risk ratio"
    )
    parser.add_argument(
        "--max-spread-points",
        type=float,
        default=50.0,
        help="Maximum acceptable spread in points",
    )
    parser.add_argument(
        "--signal-lookback-candles",
        type=int,
        default=3,
        help="Recent candles to inspect for a fresh non-HOLD signal",
    )
    parser.add_argument(
        "--disable-deep-analysis",
        action="store_true",
        help="Trade on primary strategy signals without extra analysis scoring",
    )
    parser.add_argument(
        "--analysis-delay-seconds",
        type=float,
        default=35.0,
        help="Seconds to pause after deep analysis before sending an order",
    )
    parser.add_argument(
        "--list-symbols",
        action="store_true",
        help="List synthetic-account broker symbols",
    )
    parser.add_argument(
        "--symbol-filter",
        default="fx,vol,index,sfx",
        help="Comma-separated filter for --list-symbols",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only preview trades without sending orders",
    )
    return parser


def run_trade_cycle(options: SyntheticTradeOptions) -> int:
    """Execute one synthetic FX-index trade scan."""
    account_id = options.account_id
    _refresh_synthetic_mt5_context()

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
            logger.warning(
                "%s; continuing because --dry-run will not submit orders", message
            )
        else:
            logger.warning(
                "%s; skipping this cycle because trading is disabled", message
            )
        return 0

    if options.list_symbols:
        symbols = _list_broker_symbols(options.symbol_filter)
        logger.info(
            "Synthetic account symbols matching '%s': %s",
            options.symbol_filter,
            len(symbols),
        )
        for symbol in symbols:
            logger.info("  %s", symbol)
        return 0

    requested_symbol = options.focus_symbol or options.symbol
    targets = _resolve_trade_targets(requested_symbol)
    if not targets:
        logger.error("No synthetic symbols resolved from broker symbol list")
        return 1

    account_balance = float(
        options.account_balance or account_info.get("balance") or 10000.0
    )
    now = datetime.now()
    max_total = settings.synthetic_max_trades_per_day
    max_per_symbol = settings.synthetic_max_trades_per_symbol_per_day

    db_manager.initialize()
    summary = {
        "checked": 0,
        "approved": 0,
        "rejected": 0,
        "skipped": 0,
        "details": [],
    }
    try:
        if not options.dry_run:
            symbols = {symbol for _, symbol, _ in targets}
            _sync_closed_trades_from_mt5(account_id, symbols)
            _sync_broker_open_positions(account_id, symbols)
        for bucket, symbol, strategy_class in targets:
            allowed, cap_warnings = _trade_allowed(
                account_id, symbol, now, max_total, max_per_symbol
            )
            summary["checked"] += 1
            if not allowed:
                summary["skipped"] += 1
                summary["details"].append(f"{symbol}: skipped (daily cap reached)")
                logger.warning(
                    "Cap block for %s | %s | total=%s/%s | symbol=%s/%s",
                    symbol,
                    "; ".join(cap_warnings),
                    _count_recent_mt5_activity(account_id, symbol, now)[0],
                    max_total,
                    _count_recent_mt5_activity(account_id, symbol, now)[1],
                    max_per_symbol,
                )
                continue

            if _has_open_position(account_id, symbol):
                summary["skipped"] += 1
                summary["details"].append(
                    f"{symbol}: skipped (open position already exists)"
                )
                logger.info(
                    "Skipping %s on %s because an open position already exists",
                    symbol,
                    account_id,
                )
                continue

            if not mt5_collector.validate_symbol(symbol):
                summary["skipped"] += 1
                summary["details"].append(f"{symbol}: skipped (symbol not tradable)")
                logger.warning("Symbol not tradable: %s", symbol)
                continue

            live_data = _load_synthetic_live_data(
                symbol, timeframe=options.timeframe, lookback=options.lookback_days
            )
            if live_data.empty:
                summary["skipped"] += 1
                summary["details"].append(f"{symbol}: skipped (no candle history)")
                logger.warning("No candle history available for %s", symbol)
                continue

            try:
                multi_timeframe_data = _load_multitimeframe_data(
                    symbol, lookback_days=options.lookback_days
                )
            except Exception as exc:
                logger.warning(
                    "Multitimeframe data unavailable for %s; falling back to single timeframe: %s",
                    symbol,
                    exc,
                )
                multi_timeframe_data = {"M5": live_data}

            strategy = strategy_class()
            signal_series = strategy.generate_signals(live_data)
            if signal_series.empty:
                summary["skipped"] += 1
                summary["details"].append(f"{symbol}: skipped (no signal generated)")
                logger.info("No signal generated for %s", symbol)
                continue

            (
                latest_signal,
                signal_age,
                signal_index,
                recent_signals,
                inspected_candles,
            ) = _select_recent_signal(
                signal_series,
                options.signal_lookback_candles,
            )
            if latest_signal == 0:
                latest_row = live_data.iloc[-1]
                latest_time = (
                    latest_row.get("time", "unknown")
                    if hasattr(latest_row, "get")
                    else "unknown"
                )
                summary["skipped"] += 1
                summary["details"].append(f"{symbol}: skipped (hold signal only)")
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
            analysis_approved = False
            effective_min_score = options.min_analysis_score
            feedback_profile: dict[str, float | int | str] | None = None
            focus_profile: dict[str, float | int | str] | None = None
            profit_target_profile: dict[str, float | int | str] | None = None
            feedback_reasons: list[str] = []
            if options.deep_analysis:
                feedback_trades = _get_recent_closed_trade_feedback(
                    symbol, account_id, now, lookback_hours=24
                )
                feedback_profile = _build_feedback_profile(feedback_trades)
                profit_target_profile = _build_profit_target_profile(
                    account_balance=account_balance,
                    recent_trade_count=len(feedback_trades),
                )
                feedback_reasons = [str(feedback_profile.get("summary", ""))]
                feedback_reasons.append(str(profit_target_profile.get("summary", "")))
                if options.focus_symbol or requested_symbol not in {"20", "40", "80"}:
                    focus_trade_count = len(feedback_trades)
                    focus_profile = _build_symbol_focus_profile(
                        focus_trade_count,
                        target_daily_trades=4,
                    )
                    feedback_reasons.append(str(focus_profile.get("summary", "")))

                # base effective threshold starts from configured minimum
                effective_min_score = options.min_analysis_score

                # incorporate adaptive controller based on recent win-rate
                try:
                    adaptive_offset = _compute_adaptive_offset(account_id, symbol)
                    effective_min_score = float(effective_min_score) + float(
                        adaptive_offset
                    )
                    logger.info(
                        "Adaptive offset for %s: %.3f | recent win-rate adjusted threshold",
                        symbol,
                        adaptive_offset,
                    )
                except Exception:
                    adaptive_offset = 0.0

                if feedback_profile.get("reviewed_trades", 0):
                    effective_min_score = float(effective_min_score) + float(
                        feedback_profile.get("threshold_offset", 0.0)
                    )
                    logger.info(
                        "Recent trade feedback for %s: threshold_offset %.2f risk_multiplier %.2f confidence_bias %.2f | %s",
                        symbol,
                        feedback_profile.get("threshold_offset", 0.0),
                        feedback_profile.get("risk_multiplier", 1.0),
                        feedback_profile.get("confidence_bias", 0.0),
                        feedback_profile.get("summary", ""),
                    )
                if focus_profile is not None:
                    effective_min_score = float(effective_min_score) + float(
                        focus_profile.get("threshold_offset", 0.0)
                    )
                    logger.info(
                        "Focused-symbol profile for %s: threshold_offset %.2f risk_multiplier %.2f confidence_bias %.2f | %s",
                        symbol,
                        focus_profile.get("threshold_offset", 0.0),
                        focus_profile.get("risk_multiplier", 1.0),
                        focus_profile.get("confidence_bias", 0.0),
                        focus_profile.get("summary", ""),
                    )
                effective_min_score = float(effective_min_score) + float(
                    profit_target_profile.get("threshold_offset", 0.0)
                )
                logger.info(
                    "Profit-target profile for %s: threshold_offset %.2f risk_multiplier %.2f confidence_bias %.2f | %s",
                    symbol,
                    profit_target_profile.get("threshold_offset", 0.0),
                    profit_target_profile.get("risk_multiplier", 1.0),
                    profit_target_profile.get("confidence_bias", 0.0),
                    profit_target_profile.get("summary", ""),
                )
                timeframe_signals: dict[str, int] = {}
                for name, frame_data in multi_timeframe_data.items():
                    if frame_data is None or getattr(frame_data, "empty", False):
                        continue
                    try:
                        frame_signals = strategy.generate_signals(frame_data)
                        if frame_signals.empty:
                            continue
                        timeframe_signals[name] = int(frame_signals.iloc[-1])
                    except Exception as exc:
                        logger.debug(
                            "Unable to evaluate %s on %s timeframe: %s",
                            symbol,
                            name,
                            exc,
                        )

                if timeframe_signals:
                    confluence_passed, confluence_score, confluence_reasons = (
                        _evaluate_multi_timeframe_signal(
                            latest_signal,
                            timeframe_signals,
                            effective_min_score,
                        )
                    )
                    if not confluence_passed:
                        # exploration: allow a small-probability exploratory trade with tiny size
                        if random.random() < EXPLORATION_EPSILON:
                            analysis_score = max(0.0, float(confluence_score))
                            analysis_reasons = confluence_reasons + [
                                f"exploration epsilon {EXPLORATION_EPSILON:.3f} allowed"
                            ]
                            analysis_approved = True
                            logger.info(
                                "Exploration allowed %s %s for %s: confidence %.2f. %s",
                                symbol,
                                "BUY" if latest_signal > 0 else "SELL",
                                account_id,
                                analysis_score,
                                "; ".join(analysis_reasons),
                            )
                        else:
                            summary["rejected"] += 1
                            summary["details"].append(
                                f"{symbol}: rejected (confidence {confluence_score:.2f} below {effective_min_score:.2f})"
                            )
                            logger.info(
                                "Deep analysis rejected %s %s for %s: confidence %.2f is below the required %.2f. %s",
                                symbol,
                                "BUY" if latest_signal > 0 else "SELL",
                                account_id,
                                confluence_score,
                                effective_min_score,
                                "; ".join(confluence_reasons),
                            )
                            continue
                    else:
                        analysis_score = min(
                            1.0,
                            confluence_score
                            + float(feedback_profile.get("confidence_bias", 0.0))
                            + (
                                float(focus_profile.get("confidence_bias", 0.0))
                                if focus_profile is not None
                                else 0.0
                            )
                            + (
                                float(profit_target_profile.get("confidence_bias", 0.0))
                                if profit_target_profile is not None
                                else 0.0
                            ),
                        )
                        analysis_reasons = confluence_reasons + feedback_reasons
                        analysis_approved = True
                        logger.info(
                            "Deep analysis approved %s %s for %s: confidence %.2f. %s",
                            symbol,
                            "BUY" if latest_signal > 0 else "SELL",
                            account_id,
                            analysis_score,
                            "; ".join(analysis_reasons),
                        )
                else:
                    analysis_passed, analysis_score, analysis_reasons = (
                        _deep_market_analysis(
                            latest_signal,
                            live_data,
                            effective_min_score,
                            timeframe=options.timeframe,
                        )
                    )
                    if not analysis_passed:
                        # exploration path for single-timeframe analysis
                        if random.random() < EXPLORATION_EPSILON:
                            analysis_approved = True
                            logger.info(
                                "Exploration allowed (single timeframe) %s %s for %s: confidence %.2f. %s",
                                symbol,
                                "BUY" if latest_signal > 0 else "SELL",
                                account_id,
                                analysis_score,
                                "; ".join(analysis_reasons),
                            )
                        else:
                            summary["rejected"] += 1
                            summary["details"].append(
                                f"{symbol}: rejected (confidence {analysis_score:.2f} below {effective_min_score:.2f})"
                            )
                            logger.info(
                                "Deep analysis rejected %s %s for %s: confidence %.2f is below the required %.2f. %s",
                                symbol,
                                "BUY" if latest_signal > 0 else "SELL",
                                account_id,
                                analysis_score,
                                effective_min_score,
                                "; ".join(analysis_reasons),
                            )
                            continue
                    analysis_approved = True
                    logger.info(
                        "Deep analysis approved %s %s for %s: confidence %.2f. %s",
                        symbol,
                        "BUY" if latest_signal > 0 else "SELL",
                        account_id,
                        analysis_score,
                        "; ".join(analysis_reasons),
                    )
            else:
                analysis_approved = True

            if not analysis_approved:
                summary["rejected"] += 1
                summary["details"].append(f"{symbol}: rejected (analysis not approved)")
                continue

            trade_context = mt5_collector.service.symbol_trade_context(symbol) or {}
            spread_points = float(trade_context.get("spread") or 0.0)
            balance_filters_ok, balance_reasons, balance_profile = (
                _balance_aware_trade_filters(
                    account_balance,
                    analysis_score,
                    spread_points,
                    latest_signal,
                    focus_profile=focus_profile,
                )
            )
            if not balance_filters_ok:
                summary["rejected"] += 1
                summary["details"].append(
                    f"{symbol}: rejected by micro-account filter ({'; '.join(balance_reasons)})"
                )
                logger.info(
                    "%s: rejected for account balance %.2f | %s",
                    symbol,
                    account_balance if account_balance is not None else 0.0,
                    "; ".join(balance_reasons),
                )
                continue

            summary["approved"] += 1
            summary["details"].append(
                f"{symbol}: approved (confidence {analysis_score:.2f})"
            )

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
            risk_manager = RiskManager(risk_per_trade_pct=options.risk_per_trade)
            trade_plan = risk_manager.build_trade_plan(
                account_balance=float(account_balance or 0.0),
                entry_price=float(trade_setup["entry_price"]),
                stop_loss_price=float(trade_setup["stop_loss"]),
                take_profit_price=float(trade_setup["take_profit"]),
            )
            trade_setup["risk_amount"] = float(trade_plan["risk_amount"])
            trade_setup["actual_risk_amount"] = float(trade_plan["risk_amount"])
            trade_setup["risk_profile"] = trade_plan["risk_profile"]
            trade_setup["warnings"].append(
                f"risk tier {trade_plan['risk_profile']['tier']}"
            )
            if (
                feedback_profile is not None
                or focus_profile is not None
                or profit_target_profile is not None
            ):
                # compute analysis-aware risk multiplier
                try:
                    computed_multiplier = _compute_risk_multiplier(
                        analysis_score,
                        feedback_profile=feedback_profile,
                        focus_profile=focus_profile,
                    )
                except Exception:
                    computed_multiplier = 1.0

                # preserve any existing profile multipliers as well
                try:
                    profile_mult = (
                        float(feedback_profile.get("risk_multiplier", 1.0))
                        if feedback_profile
                        else 1.0
                    )
                except Exception:
                    profile_mult = 1.0
                try:
                    focus_mult = (
                        float(focus_profile.get("risk_multiplier", 1.0))
                        if focus_profile
                        else 1.0
                    )
                except Exception:
                    focus_mult = 1.0
                try:
                    profit_mult = (
                        float(profit_target_profile.get("risk_multiplier", 1.0))
                        if profit_target_profile
                        else 1.0
                    )
                except Exception:
                    profit_mult = 1.0

                risk_multiplier = (
                    computed_multiplier * profile_mult * focus_mult * profit_mult
                )

                trade_setup["risk_amount"] = (
                    float(trade_setup["risk_amount"]) * risk_multiplier
                )
                # scale volumes and recompute normalized lot size to respect broker limits
                scaled_lot = float(trade_setup["lot_size"]) * risk_multiplier
                min_vol = float(trade_setup.get("volume_min") or 0.01)
                max_vol = float(
                    trade_setup.get("volume_max") or max(scaled_lot, min_vol)
                )
                vol_step = float(trade_setup.get("volume_step") or 0.01)
                try:
                    normalized_lot = _normalize_volume(
                        scaled_lot, min_vol, max_vol, vol_step
                    )
                except Exception:
                    normalized_lot = max(min_vol, min(scaled_lot, max_vol))

                trade_setup["lot_size"] = normalized_lot
                trade_setup["position_size"] = normalized_lot

                # recompute actual risk amount based on instrument parameters
                try:
                    market_entry = float(trade_setup.get("entry_price") or 0.0)
                    stop_price = float(trade_setup.get("stop_loss") or market_entry)
                    trade_tick_size = float(trade_setup.get("trade_tick_size") or 0.0)
                    trade_tick_value = float(trade_setup.get("trade_tick_value") or 0.0)
                    trade_contract_size = float(
                        trade_setup.get("trade_contract_size") or 0.0
                    )
                    if trade_tick_size > 0 and trade_tick_value > 0:
                        risk_per_lot = (
                            abs(market_entry - stop_price)
                            / trade_tick_size
                            * trade_tick_value
                        )
                    elif trade_contract_size > 0:
                        risk_per_lot = (
                            abs(market_entry - stop_price) * trade_contract_size
                        )
                    else:
                        risk_per_lot = abs(market_entry - stop_price)
                    actual_risk = risk_per_lot * float(trade_setup["lot_size"])
                except Exception:
                    actual_risk = (
                        float(trade_setup.get("actual_risk_amount", 0.0))
                        * risk_multiplier
                    )

                trade_setup["actual_risk_amount"] = actual_risk

                # refresh warnings: if capping no longer applies remove that warning
                refreshed_warnings: list[str] = []
                for w in trade_setup.get("warnings", []):
                    lw = str(w).lower()
                    if "calculated lot size exceeded broker maximum" in lw:
                        # if normalized lot is strictly below max, drop the capped warning
                        if float(trade_setup.get("lot_size", 0.0)) < max_vol:
                            continue
                    if "calculated lot size is zero" in lw:
                        if float(trade_setup.get("lot_size", 0.0)) > 0:
                            continue
                    refreshed_warnings.append(w)
                trade_setup["warnings"] = refreshed_warnings

                trade_setup["warnings"].append(
                    f"adaptive risk multiplier {risk_multiplier:.2f}"
                )
                # Apply micro-account policy for tiny balances
                micro_ok, micro_reason = _apply_micro_account_policy(
                    trade_setup, analysis_score, account_balance
                )
                if not micro_ok:
                    summary["rejected"] += 1
                    summary["details"].append(f"{symbol}: rejected ({micro_reason})")
                    logger.info(
                        "%s: rejected for micro-account policy (%s)",
                        symbol,
                        micro_reason,
                    )
                    continue
            if float(trade_setup["position_size"]) <= 0:
                summary["rejected"] += 1
                summary["details"].append(
                    f"{symbol}: rejected (zero or negative risk size)"
                )
                logger.warning(
                    "%s: rejected because computed position size is %.5f",
                    symbol,
                    float(trade_setup["position_size"]),
                )
                continue
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
                if any(
                    any(keyword in warning.lower() for keyword in blocked_keywords)
                    for warning in trade_setup["warnings"]
                ):
                    continue
                if _trade_setup_has_blocking_warnings(trade_setup["warnings"]):
                    summary["rejected"] += 1
                    summary["details"].append(
                        f"{symbol}: rejected (risk budget warning: {'; '.join(trade_setup['warnings'])})"
                    )
                    logger.warning(
                        "%s: rejecting trade because the setup breaks the planned risk budget: %s",
                        symbol,
                        "; ".join(trade_setup["warnings"]),
                    )
                    continue

            effective_min_reward = 2.0
            if profit_target_profile is not None:
                try:
                    effective_min_reward = max(
                        effective_min_reward,
                        float(profit_target_profile.get("profit_floor") or 2.0),
                    )
                except (TypeError, ValueError):
                    effective_min_reward = 2.0

            if not _trade_setup_meets_min_reward_target(
                trade_setup,
                min_reward=effective_min_reward,
                profit_target_profile=profit_target_profile,
            ):
                summary["rejected"] += 1
                summary["details"].append(
                    f"{symbol}: rejected (projected reward below ${effective_min_reward:.2f} minimum)"
                )
                logger.warning(
                    "%s: rejecting trade because projected reward %.2f is below the $%.2f minimum",
                    symbol,
                    float(trade_setup.get("risk_amount") or 0.0)
                    * float(trade_setup.get("risk_reward_ratio") or 0.0),
                    effective_min_reward,
                )
                continue

            if (
                options.deep_analysis
                and options.analysis_delay_seconds > 0
                and not options.dry_run
            ):
                logger.info(
                    "Pausing for %.1f seconds to complete deep analysis before %s",
                    options.analysis_delay_seconds,
                    symbol,
                )
                time.sleep(options.analysis_delay_seconds)

            order_request = _build_order_request(symbol, trade_setup)
            if not options.dry_run:
                check_result = _order_check_with_filling_retry(symbol, order_request)
                if check_result:
                    check_retcode = _normalize_retcodes(check_result)
                    if not _retcode_succeeded(check_retcode):
                        logger.warning(
                            "%s order check rejected request: %s", symbol, check_result
                        )
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
                logger.warning(
                    "%s order was not accepted by MT5: %s", symbol, order_result
                )
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
                        "reward_amount": abs(
                            trade_setup["take_profit"] - trade_setup["entry_price"]
                        )
                        * trade_setup["lot_size"],
                        "risk_reward_ratio": trade_setup["risk_reward_ratio"],
                        "confidence_score": analysis_score,
                        "model_version": _synthetic_model_version(
                            bucket, strategy_name
                        ),
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
                logger.error(
                    "Broker order accepted for %s but trade logging failed: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )
                continue
            logger.info(
                "Stored synthetic demo trade for %s | symbol cap %s/%s | total cap %s/%s",
                symbol,
                db_manager.count_trades_since(
                    now - timedelta(hours=24), symbol=symbol, account_id=account_id
                ),
                max_per_symbol,
                db_manager.count_trades_since(
                    now - timedelta(hours=24), account_id=account_id
                ),
                max_total,
            )
        logger.info(
            "Scan summary: checked=%s approved=%s rejected=%s skipped=%s",
            summary["checked"],
            summary["approved"],
            summary["rejected"],
            summary["skipped"],
        )
        for detail in summary["details"]:
            logger.info("  - %s", detail)
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
