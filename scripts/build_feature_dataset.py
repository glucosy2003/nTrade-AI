#!/usr/bin/env python3
"""Build a feature dataset from stored market data."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ai.feature_engineering import GoldFeatureEngineer
from backend.core.logger import setup_logger
from backend.core.settings import settings
from database.database_manager import db_manager

logger = setup_logger(__name__)


def load_price_data(symbol: str, timeframe: int, limit: int) -> pd.DataFrame:
    """Load stored price candles from PostgreSQL."""
    db_manager.initialize()
    try:
        records = db_manager.get_price_data(
            symbol=symbol, timeframe=timeframe, limit=limit
        )
        if not records:
            return pd.DataFrame()

        rows = []
        for record in records:
            rows.append(
                {
                    "time": record.timestamp,
                    "open": record.open,
                    "high": record.high,
                    "low": record.low,
                    "close": record.close,
                    "volume": record.volume,
                    "symbol": record.symbol,
                    "timeframe": record.timeframe,
                }
            )

        return pd.DataFrame(rows)
    finally:
        db_manager.close()


def save_dataset(data: pd.DataFrame, output_path: Path) -> None:
    """Save the feature dataset to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == ".parquet":
        data.to_parquet(output_path, index=False)
    else:
        data.to_csv(output_path, index=False)


def main() -> int:
    """Build and save a feature dataset."""
    parser = ArgumentParser(description="Build a synthetic feature dataset")
    parser.add_argument(
        "--symbol",
        default=settings.synthetic_index_20_symbol,
        help="Synthetic index symbol",
    )
    parser.add_argument(
        "--timeframe", type=int, default=60, help="Timeframe in minutes"
    )
    parser.add_argument(
        "--limit", type=int, default=5000, help="Maximum number of candles to load"
    )
    parser.add_argument(
        "--horizon", type=int, default=1, help="Target horizon in candles"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.0, help="Target return threshold"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (.csv or .parquet). Defaults to datasets/features/<symbol>_<tf>.csv",
    )
    args = parser.parse_args()

    output_path = (
        Path(args.output)
        if args.output
        else Path("datasets") / "features" / f"{args.symbol}_{args.timeframe}.csv"
    )

    logger.info(
        "Loading price data for %s (%s minutes)...", args.symbol, args.timeframe
    )
    price_data = load_price_data(args.symbol, args.timeframe, args.limit)
    if price_data.empty:
        logger.error("No stored price data found for %s", args.symbol)
        return 1

    logger.info("Engineering features...")
    engineer = GoldFeatureEngineer()
    result = engineer.engineer(
        price_data,
        include_target=True,
        target_horizon=args.horizon,
        target_threshold=args.threshold,
        dropna=True,
    )

    dataset = result.data
    if dataset.empty:
        logger.error("Feature engineering produced an empty dataset")
        return 1

    save_dataset(dataset, output_path)
    logger.info("Saved %s rows to %s", len(dataset), output_path)
    logger.info("Features: %s", ", ".join(result.feature_columns))
    logger.info("Target: %s", result.target_column or "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
