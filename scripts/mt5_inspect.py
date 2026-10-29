#!/usr/bin/env python3
"""Inspect the local MT5 terminal, account, symbol, and recent market state."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.market_data.mt5_service import mt5_service


logger = setup_logger(__name__)


def _format_datetime(value: object) -> str:
    """Format MT5 timestamps for readable console output."""
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _log_mapping(title: str, mapping: dict[str, object], keys: list[str]) -> None:
    """Log a small ordered subset of mapping fields."""
    logger.info("%s", title)
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if key == "time":
            value = _format_datetime(value)
        logger.info("  %s: %s", key, value)


def main() -> int:
    """Inspect the local MT5 environment."""
    parser = ArgumentParser(description="Inspect the local MT5 terminal and account")
    parser.add_argument("--symbol", default=settings.default_symbol, help="Symbol to inspect")
    parser.add_argument("--timeframe", type=int, default=settings.default_timeframe, help="Timeframe in minutes")
    parser.add_argument("--limit", type=int, default=10, help="Recent candles to display")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MT5 Inspection")
    logger.info("=" * 60)

    if not mt5_service.connect():
        logger.error("MT5 connection failed: %s", mt5_service.last_error or "unknown error")
        return 1

    terminal = mt5_service.terminal_info() or {}
    account = mt5_service.account_info() or {}
    snapshot = mt5_service.symbol_snapshot(args.symbol)
    positions = mt5_service.get_positions()

    logger.info("Connection: ready")
    if terminal:
        _log_mapping(
            "Terminal",
            terminal,
            ["name", "company", "build", "community_account", "connected", "trade_allowed", "tradeapi_disabled"],
        )

    if account:
        _log_mapping(
            "Account",
            account,
            ["login", "name", "server", "balance", "equity", "margin", "free_margin", "margin_level", "currency"],
        )

    if snapshot:
        logger.info("Symbol")
        logger.info("  symbol: %s", snapshot.get("symbol"))
        logger.info("  available: %s", snapshot.get("available"))
        logger.info("  live_price: %s", snapshot.get("live_price"))
        logger.info("  bid: %s", snapshot.get("bid"))
        logger.info("  ask: %s", snapshot.get("ask"))
        logger.info("  last: %s", snapshot.get("last"))
        logger.info("  spread: %s", snapshot.get("spread"))
        logger.info("  time: %s", _format_datetime(snapshot.get("time")))
    else:
        logger.warning("Symbol %s is not available", args.symbol)

    logger.info("Open positions: %s", len(positions))
    for position in positions:
        logger.info(
            "  #%s %s %s volume=%s open=%s profit=%s",
            position.get("ticket"),
            position.get("symbol"),
            position.get("type"),
            position.get("volume"),
            position.get("open_price"),
            position.get("profit"),
        )

    candle_frame = mt5_service.get_historical_data(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
    )
    if candle_frame is not None and not candle_frame.empty:
        latest = candle_frame.iloc[-1]
        logger.info("Recent candles: %s", len(candle_frame))
        logger.info(
            "  latest=%s open=%s high=%s low=%s close=%s volume=%s",
            _format_datetime(latest["time"]),
            latest["open"],
            latest["high"],
            latest["low"],
            latest["close"],
            latest.get("volume", 0),
        )
    else:
        logger.warning("No recent candles returned for %s", args.symbol)

    logger.info("MT5 inspection complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
