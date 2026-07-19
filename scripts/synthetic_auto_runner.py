#!/usr/bin/env python3
"""Run the synthetic indices trader continuously."""

from __future__ import annotations

import signal
import os
import sys
import time
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from scripts.synthetic_demo_trade import SyntheticTradeOptions, run_trade_cycle


logger = setup_logger(__name__)
_STOP_REQUESTED = False


def _request_stop(signum, frame) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    logger.info("Stop requested; runner will exit after the current cycle")


def _sleep_with_stop(interval_seconds: int) -> None:
    deadline = time.time() + interval_seconds
    while not _STOP_REQUESTED and time.time() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.time())))


def main() -> int:
    parser = ArgumentParser(description="Continuously monitor and trade synthetic FX indices")
    parser.add_argument("--interval-minutes", type=float, default=5.0, help="Minutes between market scans")
    parser.add_argument("--max-cycles", type=int, default=None, help="Stop after N cycles, useful for testing")
    parser.add_argument("--symbol", default=None, help="Trade only one resolved symbol, or bucket: 20, 40, 80")
    parser.add_argument("--account-id", default=os.getenv("NTRADE_SYNTHETIC_ACCOUNT_ID", "synthetic"), help="Local account identifier for DB isolation")
    parser.add_argument("--timeframe", type=int, default=5, help="MT5 candle timeframe in minutes")
    parser.add_argument("--lookback-days", type=int, default=90, help="History window for signal generation")
    parser.add_argument("--account-balance", type=float, default=None, help="Fallback demo balance for sizing")
    parser.add_argument("--risk-per-trade", type=float, default=1.0, help="Risk per trade percent")
    parser.add_argument("--reward-to-risk", type=float, default=2.0, help="Reward-to-risk ratio")
    parser.add_argument("--max-spread-points", type=float, default=50.0, help="Maximum acceptable spread in points")
    parser.add_argument("--signal-lookback-candles", type=int, default=3, help="Recent candles to inspect for a fresh non-HOLD signal")
    parser.add_argument("--min-analysis-score", type=float, default=0.65, help="Minimum deep-analysis score required before trading")
    parser.add_argument("--disable-deep-analysis", action="store_true", help="Trade on primary strategy signals without extra analysis scoring")
    parser.add_argument("--dry-run", action="store_true", help="Only preview trades without sending orders")
    args = parser.parse_args()

    if args.interval_minutes <= 0:
        logger.error("--interval-minutes must be greater than zero")
        return 1

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    interval_seconds = int(args.interval_minutes * 60)
    cycle = 0
    logger.info(
        "Synthetic auto runner started | account=%s | interval=%.2f minutes | timeframe=%s | signal_lookback=%s | min_analysis=%.2f | dry_run=%s | symbol=%s",
        args.account_id,
        args.interval_minutes,
        args.timeframe,
        args.signal_lookback_candles,
        args.min_analysis_score,
        args.dry_run,
        args.symbol or "all",
    )

    while not _STOP_REQUESTED:
        cycle += 1
        logger.info("Starting synthetic scan cycle %s at %s", cycle, datetime.now().isoformat(timespec="seconds"))

        options = SyntheticTradeOptions(
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
            dry_run=args.dry_run,
        )

        try:
            result = run_trade_cycle(options)
            logger.info("Finished synthetic scan cycle %s with exit code %s", cycle, result)
        except Exception as exc:
            logger.error("Synthetic scan cycle %s failed: %s", cycle, exc, exc_info=True)

        if args.max_cycles is not None and cycle >= args.max_cycles:
            logger.info("Reached --max-cycles=%s; stopping runner", args.max_cycles)
            break

        _sleep_with_stop(interval_seconds)

    logger.info("Synthetic auto runner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
