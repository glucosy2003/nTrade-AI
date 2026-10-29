#!/usr/bin/env python3
"""Generate and store a live trade suggestion from the latest market data."""

from __future__ import annotations

import math
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.market_data.data_collector import mt5_collector
from backend.risk.risk_manager import RiskManager
from backend.strategies.simple_ma_crossover import SimpleMAcrossover
from database.database_manager import db_manager

logger = setup_logger(__name__)


def load_live_data(symbol: str, timeframe: int, lookback: int) -> pd.DataFrame:
    """Load the latest candles from MT5."""
    if not mt5_collector.connect():
        raise RuntimeError("Could not connect to MT5")

    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=lookback)
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


def build_trade_setup(
    *,
    symbol: str,
    signal: int,
    entry_price: float,
    account_balance: float,
    risk_per_trade_pct: float,
    reward_to_risk_ratio: float,
    trade_context: dict[str, object] | None = None,
    max_spread_points: float | None = None,
) -> dict:
    """Create stop loss, take profit, and volume for a signal."""
    if signal == 0:
        return {
            "signal": 0,
            "signal_type": "HOLD",
            "entry_price": entry_price,
            "stop_loss": None,
            "take_profit": None,
            "position_size": 0.0,
            "lot_size": 0.0,
            "risk_amount": 0.0,
            "risk_reward_ratio": 0.0,
            "order_type": "HOLD",
            "deviation_points": 0,
            "time_in_force": "GTC",
            "filling_mode": None,
            "spread_points": None,
            "spread_price": None,
            "margin_required": None,
            "free_margin": None,
            "warnings": [],
        }

    trade_context = trade_context or {}
    signal_type = "BUY" if signal > 0 else "SELL"
    market_entry_price = float(
        trade_context.get("ask")
        if signal > 0 and trade_context.get("ask") is not None
        else (
            trade_context.get("bid")
            if signal < 0 and trade_context.get("bid") is not None
            else entry_price
        )
    )
    stop_distance = market_entry_price * 0.005
    if signal > 0:
        stop_loss = market_entry_price - stop_distance
        take_profit = market_entry_price + (stop_distance * reward_to_risk_ratio)
    else:
        stop_loss = market_entry_price + stop_distance
        take_profit = market_entry_price - (stop_distance * reward_to_risk_ratio)

    risk_manager = RiskManager(
        risk_per_trade_pct=risk_per_trade_pct,
        reward_to_risk_ratio=reward_to_risk_ratio,
    )
    trade_plan = risk_manager.build_trade_plan(
        account_balance=account_balance,
        entry_price=market_entry_price,
        stop_loss_price=stop_loss,
        take_profit_price=take_profit,
    )

    min_volume = float(trade_context.get("volume_min") or 0.01)
    raw_position_size = float(trade_plan["position_size"])
    max_volume = float(
        trade_context.get("volume_max") or max(raw_position_size, min_volume)
    )
    volume_step = float(trade_context.get("volume_step") or 0.01)
    trade_contract_size = float(trade_context.get("trade_contract_size") or 0.0)
    trade_tick_size = float(
        trade_context.get("trade_tick_size") or trade_context.get("point") or 0.0
    )
    trade_tick_value = float(trade_context.get("trade_tick_value") or 0.0)

    if trade_tick_size > 0 and trade_tick_value > 0:
        risk_per_lot = (
            abs(market_entry_price - stop_loss) / trade_tick_size * trade_tick_value
        )
    elif trade_contract_size > 0:
        risk_per_lot = abs(market_entry_price - stop_loss) * trade_contract_size
    else:
        risk_per_lot = abs(market_entry_price - stop_loss)

    raw_lot_size = (
        trade_plan["risk_amount"] / risk_per_lot
        if risk_per_lot > 0
        else raw_position_size
    )
    normalized_lot_size = _normalize_volume(
        raw_lot_size, min_volume, max_volume, volume_step
    )
    actual_risk_amount = risk_per_lot * normalized_lot_size
    spread_points = trade_context.get("spread")
    spread_price = None
    if trade_context.get("ask") is not None and trade_context.get("bid") is not None:
        spread_price = float(trade_context["ask"]) - float(trade_context["bid"])

    warnings: list[str] = []
    if normalized_lot_size <= 0:
        warnings.append("Calculated lot size is zero")
    if normalized_lot_size == min_volume and raw_lot_size < min_volume:
        warnings.append(
            "Calculated lot size is below broker minimum; rounded up to minimum"
        )
    if normalized_lot_size == max_volume and raw_lot_size > max_volume:
        warnings.append("Calculated lot size exceeded broker maximum; capped")
    if actual_risk_amount > trade_plan["risk_amount"] * 1.05:
        warnings.append("Rounded lot size risks more than planned budget")
    if (
        max_spread_points is not None
        and spread_points is not None
        and float(spread_points) > float(max_spread_points)
    ):
        warnings.append("Spread is above the configured maximum")

    return {
        "signal": signal,
        "signal_type": signal_type,
        "order_type": "MARKET",
        "entry_price": market_entry_price,
        "stop_loss": trade_plan["stop_loss_price"],
        "take_profit": trade_plan["take_profit_price"],
        "position_size": normalized_lot_size,
        "lot_size": normalized_lot_size,
        "raw_position_size": trade_plan["position_size"],
        "risk_amount": trade_plan["risk_amount"],
        "actual_risk_amount": actual_risk_amount,
        "risk_reward_ratio": trade_plan["risk_reward_ratio"],
        "volume_min": min_volume,
        "volume_max": max_volume,
        "volume_step": volume_step,
        "trade_contract_size": trade_contract_size,
        "trade_tick_size": trade_tick_size,
        "trade_tick_value": trade_tick_value,
        "spread_points": spread_points,
        "spread_price": spread_price,
        "deviation_points": 20,
        "time_in_force": "GTC",
        "filling_mode": trade_context.get("filling_mode"),
        "trade_mode": trade_context.get("trade_mode"),
        "margin_required": None,
        "free_margin": None,
        "warnings": warnings,
    }


def _normalize_volume(
    raw_volume: float, min_volume: float, max_volume: float, volume_step: float
) -> float:
    """Clamp and round a volume to broker-supported lot increments."""
    if raw_volume <= 0:
        return 0.0
    if min_volume <= 0:
        min_volume = 0.01
    if max_volume < min_volume:
        max_volume = min_volume
    if volume_step <= 0:
        volume_step = min_volume

    clamped_volume = min(max(raw_volume, min_volume), max_volume)
    steps = math.floor((clamped_volume - min_volume) / volume_step)
    normalized = min_volume + (steps * volume_step)
    normalized = max(min_volume, min(normalized, max_volume))

    precision = max(
        0,
        min(
            8,
            (
                len(str(volume_step).split(".")[-1].rstrip("0"))
                if "." in str(volume_step)
                else 0
            ),
        ),
    )
    return round(normalized, precision)


def resolve_or_train_model(model_path: str, symbol: str, timeframe: int) -> str:
    """Resolve an existing model path for the synthetic specialist workflow."""
    return model_path


def main() -> int:
    """Generate one live trade setup and optionally store it."""
    parser = ArgumentParser(description="Generate a live trade suggestion")
    parser.add_argument(
        "--symbol", default=settings.synthetic_index_20_symbol, help="Trading symbol"
    )
    parser.add_argument(
        "--timeframe", type=int, default=60, help="Timeframe in minutes"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=120, help="History window for analysis"
    )
    parser.add_argument(
        "--model-path", default=None, help="Path to a trained model file"
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum signal confidence",
    )
    parser.add_argument(
        "--account-balance",
        type=float,
        default=10000.0,
        help="Account balance for sizing",
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=settings.max_risk_per_trade,
        help="Risk per trade percent",
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
        "--store-signal",
        action="store_true",
        help="Save the generated signal to the database",
    )
    args = parser.parse_args()

    logger.info("Loading live candles for %s (%s min)...", args.symbol, args.timeframe)
    live_data = load_live_data(args.symbol, args.timeframe, args.lookback_days)
    terminal_info = mt5_collector.service.terminal_info() or {}
    account_info = mt5_collector.get_account_info() or {}
    trade_context = mt5_collector.service.symbol_trade_context(args.symbol) or {}
    raw_prediction = 0
    confidence_score = 0.0
    signal_source = "fallback"

    try:
        strategy = SimpleMAcrossover(fast_period=10, slow_period=20)
        fallback_signals = strategy.generate_signals(live_data)
        if len(fallback_signals) > 0:
            raw_prediction = int(fallback_signals.iloc[-1])
            confidence_score = 0.6
            signal_source = "simple_ma_crossover"
    except Exception as exc:
        logger.warning("Synthetic fallback strategy failed: %s", exc)

    signal = (
        raw_prediction
        if confidence_score >= args.confidence_threshold or signal_source != "fallback"
        else 0
    )

    latest_row = live_data.iloc[-1]
    entry_price = float(latest_row["close"])
    trade_setup = build_trade_setup(
        symbol=args.symbol,
        signal=signal,
        entry_price=entry_price,
        account_balance=args.account_balance,
        risk_per_trade_pct=args.risk_per_trade,
        reward_to_risk_ratio=args.reward_to_risk,
        trade_context=trade_context,
        max_spread_points=args.max_spread_points,
    )

    margin_required = mt5_collector.service.estimate_order_margin(
        args.symbol,
        trade_setup["position_size"],
        trade_setup["signal_type"],
        trade_setup["entry_price"],
    )
    trade_setup["margin_required"] = margin_required
    trade_setup["free_margin"] = account_info.get("free_margin")
    if (
        margin_required is not None
        and trade_setup["free_margin"] is not None
        and trade_setup["free_margin"] < margin_required
    ):
        trade_setup["warnings"].append("Free margin is below estimated required margin")
    if terminal_info.get("trade_allowed") is False:
        trade_setup["warnings"].append("Terminal trading is disabled")
    if account_info.get("trade_allowed") is False:
        trade_setup["warnings"].append("Account trading is disabled")
    if trade_context.get("visible") is False:
        trade_setup["warnings"].append("Symbol is not visible in Market Watch")
    if trade_context.get("trade_mode") is not None and str(
        trade_context.get("trade_mode")
    ).lower() in {"0", "disabled"}:
        trade_setup["warnings"].append("Symbol trade mode appears disabled")
    if trade_setup["spread_points"] is not None and args.max_spread_points is not None:
        if float(trade_setup["spread_points"]) > float(args.max_spread_points):
            trade_setup["warnings"].append("Spread exceeds configured maximum")

    logger.info("Latest close: %.5f", entry_price)
    logger.info("Signal source: %s", signal_source)
    logger.info("Raw model signal: %s", raw_prediction)
    logger.info("Confidence: %.2f%%", confidence_score * 100)
    logger.info("Final signal: %s", trade_setup["signal_type"])
    logger.info("Order type: %s", trade_setup["order_type"])
    logger.info("Trade mode: %s", trade_setup["trade_mode"])
    logger.info("Entry: %.5f", trade_setup["entry_price"])
    if trade_setup["stop_loss"] is not None:
        logger.info("Stop loss: %.5f", trade_setup["stop_loss"])
        logger.info("Take profit: %.5f", trade_setup["take_profit"])
        logger.info("Lot size: %.2f", trade_setup["position_size"])
        logger.info("Risk amount: %.2f", trade_setup["risk_amount"])
        logger.info("Actual risk amount: %.2f", trade_setup["actual_risk_amount"])
        logger.info("Risk/reward: %.2f", trade_setup["risk_reward_ratio"])
        logger.info(
            "Lot range: %.2f - %.2f step %.2f",
            trade_setup["volume_min"],
            trade_setup["volume_max"],
            trade_setup["volume_step"],
        )
        logger.info("Spread: %s points", trade_setup["spread_points"])
        logger.info("Deviation: %s points", trade_setup["deviation_points"])
        logger.info("Filling mode: %s", trade_setup["filling_mode"])
        logger.info("Time in force: %s", trade_setup["time_in_force"])
        logger.info("Estimated margin: %s", trade_setup["margin_required"])
        logger.info("Free margin: %s", trade_setup["free_margin"])
    if trade_setup["warnings"]:
        for warning in trade_setup["warnings"]:
            logger.warning("Trade check: %s", warning)

    if args.store_signal and signal != 0:
        try:
            db_manager.initialize()
            signal_record = db_manager.insert_signal(
                {
                    "symbol": args.symbol,
                    "signal_type": trade_setup["signal_type"],
                    "timestamp": datetime.now(),
                    "entry_price": trade_setup["entry_price"],
                    "stop_loss": trade_setup["stop_loss"],
                    "take_profit": trade_setup["take_profit"],
                    "position_size": trade_setup["position_size"],
                    "risk_amount": trade_setup["risk_amount"],
                    "reward_amount": abs(
                        trade_setup["take_profit"] - trade_setup["entry_price"]
                    )
                    * trade_setup["position_size"],
                    "risk_reward_ratio": trade_setup["risk_reward_ratio"],
                    "confidence_score": confidence_score,
                    "model_version": signal_source,
                    "reasoning": "; ".join(
                        [
                            "Live trade preview from latest MT5 candles",
                            f"spread={trade_setup['spread_points']}",
                            f"margin={trade_setup['margin_required']}",
                            f"warnings={len(trade_setup['warnings'])}",
                        ]
                    ),
                    "is_active": True,
                    "is_manual": True,
                }
            )
            logger.info("Stored signal ID: %s", signal_record.id)
        finally:
            db_manager.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
