#!/usr/bin/env python3
"""Sync gold history from MT5 into PostgreSQL."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.market_data.history_sync import GoldHistorySyncService


logger = setup_logger(__name__)


def main() -> int:
    """Run the gold-history synchronization workflow."""
    parser = ArgumentParser(description="Sync gold history from MT5 into PostgreSQL")
    parser.add_argument("--symbol", default=settings.gold_history_symbol, help="Gold history symbol")
    parser.add_argument("--timeframe", type=int, default=60, help="Timeframe in minutes")
    parser.add_argument("--years", type=int, default=5, help="Default lookback window in years")
    parser.add_argument("--force", action="store_true", help="Force a full resync")
    args = parser.parse_args()

    sync_service = GoldHistorySyncService(symbol=args.symbol, timeframe=args.timeframe, default_lookback_years=args.years)
    summary = sync_service.sync(force_full=args.force, lookback_years=args.years)

    logger.info("=" * 60)
    logger.info("Gold History Sync")
    logger.info("=" * 60)
    logger.info("Status: %s", summary.status)
    logger.info("Symbol: %s", summary.symbol)
    logger.info("Timeframe: %s", summary.timeframe)
    logger.info("Window: %s -> %s", summary.start, summary.end)
    logger.info("Source rows: %s", summary.source_rows)
    logger.info("Stored rows: %s", summary.stored_rows)
    logger.info("Inserted rows: %s", summary.inserted_rows)
    logger.info("Skipped rows: %s", summary.skipped_rows)
    if summary.message:
        logger.info("Notes: %s", summary.message)

    return 0 if summary.status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
