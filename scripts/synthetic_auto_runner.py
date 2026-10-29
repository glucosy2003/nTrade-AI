#!/usr/bin/env python3
"""Run the synthetic indices trader continuously."""

from __future__ import annotations

import json
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
from backend.core.settings import settings
from scripts.synthetic_demo_trade import (
    DEFAULT_MIN_ANALYSIS_SCORE,
    SyntheticTradeOptions,
    _resolve_account_id,
    run_trade_cycle,
)

logger = setup_logger(__name__)
DEFAULT_SCAN_INTERVAL_MINUTES = 5.0
_STOP_REQUESTED = False
_STATE_PATH = (
    Path(__file__).resolve().parent.parent / "logs" / "synthetic_runner_state.json"
)


def _request_stop(signum, frame) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    logger.info("Stop requested; runner will exit after the current cycle")


def _sleep_with_stop(interval_seconds: int) -> None:
    deadline = time.time() + interval_seconds
    while not _STOP_REQUESTED and time.time() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.time())))


def _state_path() -> Path:
    return _STATE_PATH


def _load_state(state_path: Path | None = None) -> dict[str, object]:
    path = state_path or _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(last_scan_time: datetime, state_path: Path | None = None) -> None:
    path = state_path or _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_scan_time": last_scan_time.isoformat()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _next_wait_seconds(
    state_path: Path | None = None,
    interval_seconds: int = 86400,
    now: datetime | None = None,
) -> int:
    state = _load_state(state_path)
    last_scan_time_raw = state.get("last_scan_time")
    if not last_scan_time_raw:
        return 0
    try:
        last_scan_time = datetime.fromisoformat(str(last_scan_time_raw))
    except ValueError:
        return 0

    current_time = now or datetime.now()
    elapsed = (current_time - last_scan_time).total_seconds()
    if elapsed <= 0:
        return 0
    return max(0, int(interval_seconds - elapsed))


def _wait_before_next_scan(
    *,
    cycle: int,
    state_path: Path | None = None,
    interval_seconds: int = 86400,
    now: datetime | None = None,
) -> int:
    if cycle == 0:
        return 0
    return _next_wait_seconds(state_path, interval_seconds, now)


def main() -> int:
    parser = ArgumentParser(
        description="Continuously monitor and trade synthetic FX indices"
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=DEFAULT_SCAN_INTERVAL_MINUTES,
        help="Minutes between market scans (default 5 for active monitoring)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Stop after N cycles, useful for testing",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Trade only one resolved symbol, or bucket: 20, 40, 80",
    )
    parser.add_argument(
        "--focus-symbol",
        default=None,
        help="Restrict trading to one specific broker symbol and use the focused-symbol feedback profile",
    )
    parser.add_argument(
        "--account-id", default=None, help="Local account identifier for DB isolation"
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
        "--min-analysis-score",
        type=float,
        default=DEFAULT_MIN_ANALYSIS_SCORE,
        help="Minimum deep-analysis score required before trading",
    )
    parser.add_argument(
        "--analysis-delay-seconds",
        type=float,
        default=35.0,
        help="Seconds to pause after deep analysis before submitting an order",
    )
    parser.add_argument(
        "--disable-deep-analysis",
        action="store_true",
        help="Disable the built-in deep-analysis gate",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Run the first scan immediately instead of waiting for the configured interval",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only preview trades without sending orders",
    )
    args = parser.parse_args()

    if args.interval_minutes <= 0:
        logger.error("--interval-minutes must be greater than zero")
        return 1

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    args.account_id = _resolve_account_id(args.account_id)
    interval_seconds = int(args.interval_minutes * 60)
    state_path = _state_path()
    cycle = 0
    analysis_mode = "disabled" if args.disable_deep_analysis else "enabled"
    logger.info(
        "Synthetic auto runner started | account=%s | mt5_account=%s | interval=%.2f minutes | timeframe=%s | signal_lookback=%s | deep_analysis=%s | min_analysis=%.2f | analysis_delay=%.1f | dry_run=%s | symbol=%s",
        args.account_id,
        settings.synthetic_mt5_account_number or "unknown",
        args.interval_minutes,
        args.timeframe,
        args.signal_lookback_candles,
        analysis_mode,
        args.min_analysis_score,
        args.analysis_delay_seconds,
        args.dry_run,
        args.focus_symbol or args.symbol or "all",
    )

    while not _STOP_REQUESTED:
        wait_seconds = _wait_before_next_scan(
            cycle=cycle,
            state_path=state_path,
            interval_seconds=interval_seconds,
            now=datetime.now(),
        )
        if args.skip_wait and cycle == 0:
            wait_seconds = 0

        if wait_seconds > 0:
            logger.info(
                "Waiting %s seconds before the next synthetic scan",
                wait_seconds,
            )
            _sleep_with_stop(wait_seconds)
            if _STOP_REQUESTED:
                break

        cycle += 1
        logger.info(
            "Starting synthetic scan cycle %s at %s | deep_analysis=%s | min_analysis=%.2f | analysis_delay=%.1f | dry_run=%s",
            cycle,
            datetime.now().isoformat(timespec="seconds"),
            "enabled" if not args.disable_deep_analysis else "disabled",
            args.min_analysis_score,
            args.analysis_delay_seconds,
            args.dry_run,
        )

        options = SyntheticTradeOptions(
            symbol=args.symbol,
            focus_symbol=args.focus_symbol,
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
            analysis_delay_seconds=args.analysis_delay_seconds,
            dry_run=args.dry_run,
        )

        try:
            result = run_trade_cycle(options)
            logger.info(
                "Finished synthetic scan cycle %s with exit code %s | deep_analysis=%s | min_analysis=%.2f",
                cycle,
                result,
                "enabled" if not args.disable_deep_analysis else "disabled",
                args.min_analysis_score,
            )
        except Exception as exc:
            logger.error(
                "Synthetic scan cycle %s failed: %s", cycle, exc, exc_info=True
            )

        if args.max_cycles is not None and cycle >= args.max_cycles:
            logger.info("Reached --max-cycles=%s; stopping runner", args.max_cycles)
            break

        if args.skip_wait and cycle >= 1:
            logger.info(
                "Completed first synthetic scan; stopping because --skip-wait was requested"
            )
            break

        _save_state(datetime.now(), state_path=state_path)

    logger.info("Synthetic auto runner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
