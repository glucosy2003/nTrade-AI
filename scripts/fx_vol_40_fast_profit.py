#!/usr/bin/env python3
"""Dedicated FX Vol 40 trend-following entry and fast-profit exit runner."""

from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - available only on Windows/MT5 runtime
    mt5 = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.market_data.data_collector import MT5DataCollector
from backend.market_data.mt5_service import MT5Service
from backend.risk.risk_manager import RiskManager
from backend.strategies.fx_vol_40_trend import (
    FastProfitTradeGuard,
    FxVol40TrendAnalyzer,
)
from scripts.live_trade_signal import build_trade_setup

logger = setup_logger(__name__)

FIXED_RISK_USD = 2.0
FIXED_PROFIT_USD = 2.0
POSITION_POLL_INTERVAL_SECONDS = 1.0
TRADE_COMMENT = "fx_vol_40_fast_profit"


def _has_sufficient_margin(free_margin: float, required_margin: float) -> bool:
    """Keep a 10% free-margin reserve after opening the position."""
    return (
        free_margin > 0
        and required_margin > 0
        and required_margin <= free_margin * 0.90
    )


def _balance_supports_fixed_risk(balance: float) -> bool:
    return float(balance) >= FIXED_RISK_USD


def _recent_trade_times(service: MT5Service, symbol: str) -> list[datetime]:
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    history = service.get_trade_history(
        start=end - timedelta(hours=6), end=end, symbol=symbol
    )
    trade_times: list[datetime] = []
    for deal in history:
        if deal.get("comment") != TRADE_COMMENT:
            continue
        entry_time = deal.get("entry_time")
        try:
            if isinstance(entry_time, datetime):
                trade_time = entry_time.replace(tzinfo=None)
            elif entry_time is not None:
                trade_time = (
                    datetime.fromtimestamp(float(entry_time), tz=timezone.utc)
                    .astimezone()
                    .replace(tzinfo=None)
                )
            else:
                continue
        except (OverflowError, OSError, TypeError, ValueError):
            continue
        trade_times.append(trade_time)
    return trade_times


def _find_cash_price(
    service: MT5Service,
    *,
    symbol: str,
    order_type: str,
    volume: float,
    open_price: float,
    tick_size: float,
    target_amount: float,
    is_profit_target: bool,
) -> float | None:
    """Find the nearest tick whose broker-estimated P/L reaches a cash amount."""
    if volume <= 0 or open_price <= 0 or tick_size <= 0 or target_amount <= 0:
        return None

    favorable = (order_type == "BUY") == is_profit_target
    price_direction = 1.0 if favorable else -1.0

    def reaches_target(tick_count: int) -> bool | None:
        close_price = open_price + price_direction * tick_count * tick_size
        if close_price <= 0:
            return None
        estimated_profit = service.estimate_order_profit(
            symbol, volume, order_type, open_price, close_price
        )
        if estimated_profit is None:
            return None
        amount = (
            float(estimated_profit) if is_profit_target else -float(estimated_profit)
        )
        if is_profit_target:
            return amount + 1e-9 >= target_amount
        return amount > target_amount + 1e-9

    low_ticks = 0
    high_ticks = 1
    for _ in range(60):
        reached = reaches_target(high_ticks)
        if reached is None:
            return None
        if reached:
            break
        low_ticks = high_ticks
        high_ticks *= 2
    else:
        return None

    while high_ticks - low_ticks > 1:
        middle_ticks = (low_ticks + high_ticks) // 2
        reached = reaches_target(middle_ticks)
        if reached is None:
            return None
        if reached:
            high_ticks = middle_ticks
        else:
            low_ticks = middle_ticks

    selected_ticks = high_ticks if is_profit_target else low_ticks
    if selected_ticks <= 0:
        return None
    return open_price + price_direction * selected_ticks * tick_size


def _configure_fixed_dollar_setup(
    service: MT5Service,
    symbol: str,
    setup: dict,
    trade_context: dict,
) -> tuple[dict | None, str | None]:
    """Cap estimated stop loss at $2 and set a $2 gross profit target."""
    order_type = str(setup.get("signal_type") or "")
    open_price = float(setup.get("entry_price") or 0.0)
    technical_stop = float(setup.get("stop_loss") or 0.0)
    min_volume = float(trade_context.get("volume_min") or 0.0)
    max_volume = float(trade_context.get("volume_max") or 0.0)
    volume_step = float(trade_context.get("volume_step") or 0.0)
    tick_size = float(trade_context.get("trade_tick_size") or 0.0)

    if (
        order_type not in {"BUY", "SELL"}
        or open_price <= 0
        or technical_stop <= 0
        or min_volume <= 0
        or max_volume < min_volume
        or volume_step <= 0
        or tick_size <= 0
    ):
        return None, "missing valid broker volume, tick, or price information"

    min_volume_loss = service.estimate_order_profit(
        symbol, min_volume, order_type, open_price, technical_stop
    )
    if min_volume_loss is None or min_volume_loss >= 0:
        return None, "MT5 could not estimate stop-loss risk"

    stop_loss = technical_stop
    if abs(float(min_volume_loss)) > FIXED_RISK_USD:
        stop_loss = _find_cash_price(
            service,
            symbol=symbol,
            order_type=order_type,
            volume=min_volume,
            open_price=open_price,
            tick_size=tick_size,
            target_amount=FIXED_RISK_USD,
            is_profit_target=False,
        )
        if stop_loss is None:
            return None, "minimum lot cannot be kept within the $2 loss limit"
        volume = min_volume
    else:
        raw_volume = min_volume * FIXED_RISK_USD / abs(float(min_volume_loss))
        capped_volume = min(raw_volume, max_volume)
        volume_steps = math.floor((capped_volume - min_volume) / volume_step + 1e-9)
        volume = min_volume + max(volume_steps, 0) * volume_step

    estimated_loss = service.estimate_order_profit(
        symbol, volume, order_type, open_price, stop_loss
    )
    while (
        estimated_loss is not None
        and abs(float(estimated_loss)) > FIXED_RISK_USD + 1e-6
    ):
        if volume <= min_volume + 1e-9:
            return None, "minimum lot exceeds the $2 loss limit"
        volume = max(min_volume, volume - volume_step)
        estimated_loss = service.estimate_order_profit(
            symbol, volume, order_type, open_price, stop_loss
        )
    if estimated_loss is None or estimated_loss >= 0:
        return None, "MT5 could not verify estimated stop-loss risk"

    take_profit = _find_cash_price(
        service,
        symbol=symbol,
        order_type=order_type,
        volume=volume,
        open_price=open_price,
        tick_size=tick_size,
        target_amount=FIXED_PROFIT_USD,
        is_profit_target=True,
    )
    if take_profit is None:
        return None, "MT5 could not calculate a $2 profit target"

    point = float(trade_context.get("point") or tick_size)
    min_stop_distance = float(trade_context.get("trade_stops_level") or 0) * point
    if (
        min_stop_distance > 0
        and min(abs(open_price - stop_loss), abs(take_profit - open_price))
        < min_stop_distance
    ):
        return None, "$2 stop or target is inside the broker's minimum stop distance"

    setup.update(
        lot_size=volume,
        position_size=volume,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=FIXED_RISK_USD,
        actual_risk_amount=abs(float(estimated_loss)),
        profit_target_amount=FIXED_PROFIT_USD,
        risk_reward_ratio=FIXED_PROFIT_USD / abs(float(estimated_loss)),
    )
    return setup, None


def _order_was_accepted(result: dict | None) -> bool:
    if not result or result.get("retcode") is None:
        return False

    if mt5 is None:
        successful_retcodes = {10008, 10009, 10010}
    else:
        successful_retcodes = {
            int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        }
    return int(result["retcode"]) in successful_retcodes


def _build_demo_frames() -> dict[str, object]:
    """Build a simple multi-timeframe demo for local verification and tests."""
    import pandas as pd

    def make_frame(direction: str, rows: int) -> pd.DataFrame:
        data = []
        start = 100.0 if direction == "up" else 200.0
        step = 0.8 if direction == "up" else -0.7
        for index in range(rows):
            close = start + index * step
            data.append(
                {
                    "time": pd.Timestamp("2024-01-01")
                    + pd.to_timedelta(index, unit="min"),
                    "open": close - 0.2,
                    "high": close + 0.6,
                    "low": close - 0.7,
                    "close": close,
                    "volume": 1000 + index * 10,
                }
            )
        return pd.DataFrame(data)

    return {
        "M5": make_frame("up", 80),
        "M15": make_frame("up", 60),
        "H1": make_frame("up", 40),
    }


def run_demo_cycle() -> int:
    frames = _build_demo_frames()
    decision = FxVol40TrendAnalyzer().evaluate(frames)
    guard = FastProfitTradeGuard()
    print(f"Direction: {decision.direction}")
    print(f"Score: {decision.score}")
    print(f"Confirmed: {decision.confirmed}")
    print(
        f"Trade allowed in current 6h window: {guard.is_trade_allowed([datetime.now() - __import__('datetime').timedelta(minutes=30)])}"
    )
    return 0


def _load_timeframe_data(service: MT5Service, symbol: str) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    end = datetime.now()
    start = end - timedelta(days=30)
    for label, minutes in (("M5", 5), ("M15", 15), ("H1", 60)):
        frame = service.get_historical_data(
            symbol=symbol,
            timeframe=minutes,
            start=start,
            end=end,
            limit=300,
        )
        if frame is not None and not frame.empty:
            frames[label] = frame
    return frames


def _close_position(service: MT5Service, symbol: str, position: dict) -> bool:
    ticket = int(position.get("ticket") or 0)
    order_type = position.get("type", "BUY")
    close_type = "SELL" if str(order_type).upper() == "BUY" else "BUY"
    volume = float(position.get("volume") or 0.0)
    current_price = float(
        position.get("current_price") or position.get("open_price") or 0.0
    )

    if ticket <= 0 or volume <= 0 or current_price <= 0:
        logger.warning(
            "Cannot close %s position %s because ticket, volume, or price is invalid",
            symbol,
            position,
        )
        return False

    if mt5 is None:
        raise RuntimeError("MetaTrader5 is not available in this environment")

    filling_mode = service.preferred_filling_mode(symbol)
    if filling_mode is None:
        filling_mode = getattr(mt5, "ORDER_FILLING_RETURN", 2)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "position": ticket,
        "volume": volume,
        "type": mt5.ORDER_TYPE_SELL if close_type == "SELL" else mt5.ORDER_TYPE_BUY,
        "price": current_price,
        "deviation": 20,
        "magic": 940040,
        "comment": "fx_vol_40_fast_profit_close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    result = service.order_send(request)
    if _order_was_accepted(result):
        logger.info(
            "Close request accepted for %s position #%s: %s",
            symbol,
            ticket,
            result,
        )
        return True
    logger.warning(
        "MT5 rejected close for %s: retcode=%s comment=%s",
        symbol,
        result.get("retcode") if result else None,
        result.get("comment") if result else "no response",
    )
    return False


def _ensure_runtime_configured() -> tuple[MT5Service, MT5DataCollector, dict]:
    profile = settings.mt5_account_profile("synthetic")
    if (
        not profile.get("account_number")
        or not profile.get("password")
        or not profile.get("server")
    ):
        raise RuntimeError(
            "Synthetic MT5 profile is incomplete. Set SYNTHETIC_MT5_ACCOUNT_NUMBER, "
            "SYNTHETIC_MT5_PASSWORD, and SYNTHETIC_MT5_SERVER."
        )

    service = MT5Service(
        account_number=profile["account_number"],
        password=profile["password"],
        server=profile["server"],
        terminal_path=profile.get("terminal_path"),
        profile_name="synthetic_fxvol40",
    )
    collector = MT5DataCollector(service=service)
    if not collector.connect():
        raise RuntimeError("Could not connect to MT5 for FX Vol 40 fast-profit mode")

    account = collector.get_account_info() or {}
    return service, collector, account


def _run_live_cycle(
    symbol: str, *, dry_run: bool = False, interval_seconds: int = 30
) -> int:
    service, collector, account = _ensure_runtime_configured()
    guard = FastProfitTradeGuard()
    analyzer = FxVol40TrendAnalyzer()
    balance = float(account.get("balance") or 10000.0)
    free_margin = float(account.get("margin_free") or account.get("equity") or balance)

    logger.info(
        "FX Vol 40 live loop started | symbol=%s | balance=%.2f | free_margin=%.2f",
        symbol,
        balance,
        free_margin,
    )

    for attempt in range(1, 999999):
        try:
            positions = collector.get_positions()
            for position in positions:
                if str(position.get("symbol") or "").upper() != str(symbol).upper():
                    continue
                profit = float(position.get("profit") or 0.0)
                if guard.should_close(profit) or guard.should_close_for_loss(profit):
                    exit_reason = "profit target" if profit >= 0 else "loss limit"
                    logger.info(
                        "%s reached for %s: %.2f; closing immediately",
                        exit_reason,
                        symbol,
                        profit,
                    )
                    if not dry_run and not _close_position(service, symbol, position):
                        logger.warning("Failed to close %s at target profit", symbol)
                    break

            if dry_run:
                frames = _load_timeframe_data(service, symbol)
                decision = analyzer.evaluate(frames)
                logger.info(
                    "Decision for %s: direction=%s score=%.2f confirmed=%s",
                    symbol,
                    decision.direction,
                    decision.score,
                    decision.confirmed,
                )
                if attempt >= 1:
                    break
                time.sleep(interval_seconds)
                continue

            open_positions = [
                pos
                for pos in collector.get_positions()
                if str(pos.get("symbol") or "").upper() == str(symbol).upper()
            ]
            if open_positions:
                time.sleep(POSITION_POLL_INTERVAL_SECONDS)
                continue

            recent_trade_times = _recent_trade_times(service, symbol)
            frames = _load_timeframe_data(service, symbol)
            decision = analyzer.evaluate(frames)
            if not decision.confirmed:
                logger.info(
                    "FX Vol 40 setup rejected for %s: %s", symbol, decision.reasons
                )
                time.sleep(interval_seconds)
                continue

            if not guard.is_trade_allowed(recent_trade_times):
                logger.info(
                    "FX Vol 40 trade cap reached for %s; waiting for the next 6-hour window",
                    symbol,
                )
                time.sleep(interval_seconds)
                continue

            signal = (
                1
                if decision.direction == "BUY"
                else -1 if decision.direction == "SELL" else 0
            )
            if signal == 0:
                time.sleep(interval_seconds)
                continue

            latest_account = collector.get_account_info() or {}
            latest_balance = latest_account.get("balance")
            if latest_balance is not None:
                balance = float(latest_balance)
            latest_free_margin = latest_account.get("margin_free")
            if latest_free_margin is None:
                latest_free_margin = latest_account.get("equity")
            free_margin = float(latest_free_margin or 0.0)
            if not _balance_supports_fixed_risk(balance):
                logger.warning(
                    "FX Vol 40 %s trade rejected: balance %.2f is below the fixed $2 risk limit",
                    symbol,
                    balance,
                )
                time.sleep(interval_seconds)
                continue

            trade_context = service.symbol_trade_context(symbol) or {}
            setup = build_trade_setup(
                symbol=symbol,
                signal=signal,
                entry_price=float(service.get_live_price(symbol) or 0.0),
                account_balance=balance,
                risk_per_trade_pct=1.0,
                reward_to_risk_ratio=2.0,
                trade_context=trade_context,
                max_spread_points=50.0,
            )

            setup, setup_rejection = _configure_fixed_dollar_setup(
                service, symbol, setup, trade_context
            )
            if setup is None:
                logger.warning(
                    "FX Vol 40 %s trade rejected: %s", symbol, setup_rejection
                )
                time.sleep(interval_seconds)
                continue

            if float(setup.get("position_size") or 0.0) <= 0:
                logger.warning(
                    "FX Vol 40 %s trade rejected: position size invalid (%s)",
                    symbol,
                    setup,
                )
                time.sleep(interval_seconds)
                continue

            required_margin = service.estimate_order_margin(
                symbol=symbol,
                volume=float(setup["lot_size"]),
                order_type=str(setup["signal_type"]),
                price=float(setup["entry_price"]),
            )
            if required_margin is None or required_margin <= 0:
                logger.warning(
                    "FX Vol 40 %s trade rejected: MT5 could not estimate required margin",
                    symbol,
                )
                time.sleep(interval_seconds)
                continue

            if not _has_sufficient_margin(free_margin, float(required_margin)):
                logger.warning(
                    "FX Vol 40 %s trade rejected: required margin %.2f exceeds "
                    "available margin %.2f after 10%% reserve",
                    symbol,
                    float(required_margin),
                    free_margin * 0.90,
                )
                time.sleep(interval_seconds)
                continue

            if mt5 is None:
                raise RuntimeError("MetaTrader5 is not available in this environment")

            filling_mode = service.preferred_filling_mode(symbol)
            if filling_mode is None:
                filling_mode = getattr(mt5, "ORDER_FILLING_RETURN", 2)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(setup["lot_size"]),
                "type": mt5.ORDER_TYPE_BUY if signal > 0 else mt5.ORDER_TYPE_SELL,
                "price": float(setup["entry_price"]),
                "sl": float(setup["stop_loss"]),
                "tp": float(setup["take_profit"]),
                "deviation": 20,
                "magic": 940040,
                "comment": TRADE_COMMENT,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            sent = service.order_send(request)
            if _order_was_accepted(sent):
                logger.info("FX Vol 40 %s order accepted by MT5: %s", symbol, sent)
                time.sleep(POSITION_POLL_INTERVAL_SECONDS)
            else:
                logger.warning(
                    "FX Vol 40 %s order rejected by MT5: retcode=%s comment=%s",
                    symbol,
                    sent.get("retcode") if sent else None,
                    sent.get("comment") if sent else "no response",
                )
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("FX Vol 40 live loop interrupted by user")
            return 0
        except Exception as exc:
            logger.exception("FX Vol 40 live loop error: %s", exc)
            time.sleep(interval_seconds)
            continue

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FX Vol 40 fast-profit trend mode")
    parser.add_argument("--demo", action="store_true", help="Run a local demo check")
    parser.add_argument("--live", action="store_true", help="Run the live MT5 loop")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate entries without submitting orders",
    )
    parser.add_argument(
        "--symbol", default=settings.synthetic_index_40_symbol, help="FX Vol 40 symbol"
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=30,
        help="Polling interval for the live loop",
    )
    parser.add_argument(
        "--once", action="store_true", help="Execute one evaluation cycle only"
    )
    args = parser.parse_args(argv)

    if args.demo:
        return run_demo_cycle()

    if args.live or args.once or args.dry_run:
        try:
            return _run_live_cycle(
                args.symbol,
                dry_run=args.dry_run,
                interval_seconds=args.interval_seconds,
            )
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 1

    print(
        "FX Vol 40 fast-profit mode is ready. Use --demo to verify the signal engine or --live to run the MT5 loop."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
