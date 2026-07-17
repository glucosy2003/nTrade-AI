#!/usr/bin/env python3
"""Train the baseline gold model from stored market data."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ai.training import GoldModelTrainer
from backend.core.logger import setup_logger
from backend.core.settings import settings
from database.database_manager import db_manager


logger = setup_logger(__name__)


def load_price_data(symbol: str, timeframe: int, limit: int) -> pd.DataFrame:
    """Load stored price candles from PostgreSQL."""
    db_manager.initialize()
    try:
        records = db_manager.get_price_data(symbol=symbol, timeframe=timeframe, limit=limit)
        if not records:
            return pd.DataFrame()

        return pd.DataFrame(
            [
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
                for record in records
            ]
        )
    finally:
        db_manager.close()


def main() -> int:
    """Train and persist the gold model."""
    parser = ArgumentParser(description="Train the gold baseline model")
    parser.add_argument("--symbol", default=settings.gold_history_symbol, help="Gold history symbol")
    parser.add_argument("--timeframe", type=int, default=60, help="Timeframe in minutes")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum number of candles to load")
    parser.add_argument("--horizon", type=int, default=1, help="Prediction horizon in candles")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Holdout ratio for evaluation")
    args = parser.parse_args()

    logger.info("Loading price data for %s (%s minutes)...", args.symbol, args.timeframe)
    price_data = load_price_data(args.symbol, args.timeframe, args.limit)
    if price_data.empty:
        logger.error("No stored price data found for %s", args.symbol)
        return 1

    trainer = GoldModelTrainer()
    model_name = f"gold_xgboost_{args.symbol}_{args.timeframe}.pkl"

    logger.info("Training model...")
    result = trainer.train_from_dataframe(
        price_data,
        horizon=args.horizon,
        test_ratio=args.test_ratio,
        model_name=model_name,
    )

    logger.info("Training complete")
    logger.info("Model saved to: %s", result.model_path)
    logger.info("Metrics saved to: %s", result.metrics_path)
    logger.info("Train rows: %s", result.train_rows)
    logger.info("Test rows: %s", result.test_rows)
    logger.info("Features: %s", ", ".join(result.feature_columns))
    for key, value in result.metrics.items():
        if key == "classification_report":
            continue
        logger.info("%s: %s", key, value)

    return 0


if __name__ == "__main__":
    sys.exit(main())
