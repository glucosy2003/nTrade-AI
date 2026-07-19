#!/usr/bin/env python3
"""Run one isolated synthetic trader worker per configured MT5 account."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings


logger = setup_logger(__name__)
_STOP_REQUESTED = False


def _request_stop(signum, frame) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    logger.info("Stop requested; stopping account workers")


def _worker_command(args) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).with_name("synthetic_auto_runner.py")),
        "--interval-minutes",
        str(args.interval_minutes),
        "--account-id",
        "",
        "--timeframe",
        str(args.timeframe),
        "--lookback-days",
        str(args.lookback_days),
        "--risk-per-trade",
        str(args.risk_per_trade),
        "--reward-to-risk",
        str(args.reward_to_risk),
        "--max-spread-points",
        str(args.max_spread_points),
        "--signal-lookback-candles",
        str(args.signal_lookback_candles),
        "--min-analysis-score",
        str(args.min_analysis_score),
    ]
    if args.symbol:
        command.extend(["--symbol", args.symbol])
    if args.max_cycles is not None:
        command.extend(["--max-cycles", str(args.max_cycles)])
    if args.dry_run:
        command.append("--dry-run")
    if args.disable_deep_analysis:
        command.append("--disable-deep-analysis")
    return command


def _worker_env(profile: dict, base_env: dict[str, str]) -> dict[str, str]:
    env = base_env.copy()
    env["NTRADE_SYNTHETIC_ACCOUNT_ID"] = str(profile["account_id"])
    env["SYNTHETIC_MT5_ACCOUNT_NUMBER"] = str(profile["account_number"])
    env["SYNTHETIC_MT5_PASSWORD"] = str(profile["password"])
    env["SYNTHETIC_MT5_SERVER"] = str(profile["server"])
    env["SYNTHETIC_MT5_DEMO_MODE"] = "true" if profile.get("demo_mode", True) else "false"
    if profile.get("terminal_path"):
        env["SYNTHETIC_MT5_TERMINAL_PATH"] = str(profile["terminal_path"])
    return env


def _complete_profile(profile: dict) -> bool:
    return bool(profile.get("account_id") and profile.get("account_number") and profile.get("password") and profile.get("server"))


def main() -> int:
    parser = ArgumentParser(description="Run synthetic traders across multiple isolated MT5 terminals")
    parser.add_argument("--interval-minutes", type=float, default=5.0, help="Minutes between market scans")
    parser.add_argument("--max-cycles", type=int, default=None, help="Stop each worker after N cycles")
    parser.add_argument("--symbol", default=None, help="Trade only one resolved symbol, or bucket: 20, 40, 80")
    parser.add_argument("--timeframe", type=int, default=5, help="MT5 candle timeframe in minutes")
    parser.add_argument("--lookback-days", type=int, default=90, help="History window for signal generation")
    parser.add_argument("--risk-per-trade", type=float, default=1.0, help="Risk per trade percent")
    parser.add_argument("--reward-to-risk", type=float, default=2.0, help="Reward-to-risk ratio")
    parser.add_argument("--max-spread-points", type=float, default=50.0, help="Maximum acceptable spread in points")
    parser.add_argument("--signal-lookback-candles", type=int, default=3, help="Recent candles to inspect for a fresh non-HOLD signal")
    parser.add_argument("--min-analysis-score", type=float, default=0.65, help="Minimum deep-analysis score required before trading")
    parser.add_argument("--disable-deep-analysis", action="store_true", help="Trade on primary strategy signals without extra analysis scoring")
    parser.add_argument("--dry-run", action="store_true", help="Only preview trades without sending orders")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    profiles = [profile for profile in settings.synthetic_account_profiles() if profile.get("enabled", True)]
    workers: list[subprocess.Popen] = []
    base_command = _worker_command(args)
    base_env = os.environ.copy()

    for profile in profiles:
        account_id = str(profile.get("account_id") or profile.get("name") or "unknown")
        if not _complete_profile(profile):
            logger.warning("Skipping incomplete synthetic account profile: %s", account_id)
            continue

        command = base_command.copy()
        account_flag_index = command.index("--account-id") + 1
        command[account_flag_index] = account_id

        logger.info("Starting synthetic worker for account=%s terminal=%s", account_id, profile.get("terminal_path") or "default")
        workers.append(
            subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=_worker_env(profile, base_env),
            )
        )

    if not workers:
        logger.error("No complete synthetic account profiles were started")
        return 1

    exit_code = 0
    try:
        while workers and not _STOP_REQUESTED:
            for worker in workers[:]:
                result = worker.poll()
                if result is None:
                    continue
                workers.remove(worker)
                if result != 0:
                    exit_code = result
                    logger.warning("Synthetic account worker exited with code %s", result)
            if workers:
                time.sleep(1.0)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()

    logger.info("Synthetic multi-account runner stopped")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
