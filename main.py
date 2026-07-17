#!/usr/bin/env python3
"""
nTrade AI Trading System - Main Entry Point.

This is the main entry point for the nTrade AI system.
It initializes all components and starts the trading engine.

Current focus: Windows migration, MT5 core connection, and data pipeline groundwork
Next focus: Gold data pipeline and backtesting framework

Usage:
    python main.py --help           # Show help
    python main.py --test           # Run system tests
    python main.py --backtest       # Run backtest
    python main.py --backtest --strategy gold_model --model-path <path>
    python main.py --sync-history   # Sync gold history to PostgreSQL
    python main.py --build-features # Build model features from stored candles
    python main.py --train-model    # Train and save the baseline gold model
    python main.py                  # Start trading system
"""

import sys
import logging
from argparse import ArgumentParser
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backend.core.application import TradingApplication
from backend.core.logger import setup_logger
from backend.market_data.history_sync import GoldHistorySyncService
from backend.ai.feature_engineering import GoldFeatureEngineer
from backend.ai.training import GoldModelTrainer
from backend.core.settings import settings
from database.database_manager import db_manager


# Setup logging
logger = setup_logger(__name__)


def run_tests() -> bool:
    """Run system validation tests."""
    logger.info("Running system validation tests...")
    logger.info("=" * 60)
    
    # Import test modules
    from scripts.mt5_connector_test import (
        test_mt5_connection,
        test_price_data,
        test_database
    )
    
    success = True
    
    # Run each test
    if not test_mt5_connection():
        success = False
    
    if not test_price_data():
        logger.warning("⚠ Price data test failed")
    
    if not test_database():
        success = False
    
    logger.info("=" * 60)
    return success


def run_backtest() -> None:
    """Run backtest validation."""
    logger.info("Starting backtest...")
    
    from scripts.backtest_runner import run_backtest
    
    run_backtest(
        symbol="XAUUSD",
        timeframe=60,
        years=1,
        strategy="ma_crossover",
        use_mt5=True,
    )


def run_history_sync(symbol: str, timeframe: int, years: int, force_full: bool) -> None:
    """Sync historical gold candles into PostgreSQL."""
    logger.info("Starting historical data sync...")
    history_sync = GoldHistorySyncService(symbol=symbol, timeframe=timeframe)
    summary = history_sync.sync(
        force_full=force_full,
        lookback_years=years,
    )

    logger.info("Sync status: %s", summary.status)
    logger.info("Symbol: %s | Timeframe: %s", summary.symbol, summary.timeframe)
    logger.info("Window: %s to %s", summary.start, summary.end)
    logger.info(
        "Rows: source=%s stored=%s inserted=%s skipped=%s",
        summary.source_rows,
        summary.stored_rows,
        summary.inserted_rows,
        summary.skipped_rows,
    )

    if summary.message:
        logger.info("Notes: %s", summary.message)

    if summary.status != "success":
        raise RuntimeError(f"History sync failed: {summary.message or summary.status}")


def run_feature_build(symbol: str, timeframe: int, limit: int, horizon: int, threshold: float) -> None:
    """Build a training-ready feature dataset from stored candles."""
    logger.info("Loading stored price data...")
    db_manager.initialize()
    try:
        records = db_manager.get_price_data(symbol=symbol, timeframe=timeframe, limit=limit)
    finally:
        db_manager.close()

    if not records:
        raise RuntimeError(f"No stored price data found for {symbol} at timeframe {timeframe}")

    import pandas as pd

    price_data = pd.DataFrame(
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

    logger.info("Engineering features...")
    engineer = GoldFeatureEngineer()
    result = engineer.engineer(
        price_data,
        include_target=True,
        target_horizon=horizon,
        target_threshold=threshold,
        dropna=True,
    )

    output_dir = Path("datasets") / "features"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{symbol}_{timeframe}.csv"
    result.data.to_csv(output_path, index=False)

    logger.info("Saved feature dataset to %s", output_path)
    logger.info("Rows: %s", len(result.data))
    logger.info("Features: %s", ", ".join(result.feature_columns))
    if result.target_column:
        logger.info("Target: %s", result.target_column)


def run_model_training(symbol: str, timeframe: int, limit: int, horizon: int, test_ratio: float) -> None:
    """Train and persist the baseline gold model from stored candles."""
    logger.info("Loading stored price data...")
    db_manager.initialize()
    try:
        records = db_manager.get_price_data(symbol=symbol, timeframe=timeframe, limit=limit)
    finally:
        db_manager.close()

    if not records:
        raise RuntimeError(f"No stored price data found for {symbol} at timeframe {timeframe}")

    import pandas as pd

    price_data = pd.DataFrame(
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

    trainer = GoldModelTrainer()
    model_name = f"gold_random_forest_{symbol}_{timeframe}.pkl"
    logger.info("Training gold model...")
    result = trainer.train_from_dataframe(
        price_data,
        horizon=horizon,
        test_ratio=test_ratio,
        model_name=model_name,
    )

    logger.info("Model saved to %s", result.model_path)
    logger.info("Metrics saved to %s", result.metrics_path)
    logger.info("Train rows: %s | Test rows: %s", result.train_rows, result.test_rows)
    for key, value in result.metrics.items():
        if key == "classification_report":
            continue
        logger.info("%s: %s", key, value)


def main():
    """Main entry point."""
    parser = ArgumentParser(description="nTrade AI Trading System")
    parser.add_argument("--test", action="store_true", help="Run system tests")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--sync-history", action="store_true", help="Sync gold history to PostgreSQL")
    parser.add_argument("--build-features", action="store_true", help="Build feature dataset from stored candles")
    parser.add_argument("--train-model", action="store_true", help="Train the gold baseline model")
    parser.add_argument("--strategy", default="ma_crossover", help="Backtest strategy name")
    parser.add_argument("--model-path", default=None, help="Path to a trained model file")
    parser.add_argument("--symbol", default=settings.gold_history_symbol, help="Gold history symbol")
    parser.add_argument("--timeframe", type=int, default=60, help="Historical data timeframe in minutes")
    parser.add_argument("--years", type=int, default=5, help="Default lookback window in years")
    parser.add_argument("--force-sync", action="store_true", help="Force a full historical sync")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum candles for feature building")
    parser.add_argument("--horizon", type=int, default=1, help="Feature target horizon in candles")
    parser.add_argument("--threshold", type=float, default=0.0, help="Feature target return threshold")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Training holdout ratio")
    parser.add_argument("--version", action="version", version="nTrade AI v1.0.0")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("nTrade AI Trading System")
    logger.info("=" * 60)
    
    try:
        if args.test:
            # Run tests
            logger.info("\nRunning system validation tests...")
            success = run_tests()
            sys.exit(0 if success else 1)
        
        elif args.backtest:
            # Run backtest
            logger.info("\nStarting backtest pipeline...")
            from scripts.backtest_runner import run_backtest as run_strat_backtest

            run_strat_backtest(
                symbol=args.symbol,
                timeframe=args.timeframe,
                years=args.years,
                strategy=args.strategy,
                use_mt5=True,
                model_path=args.model_path,
            )
            sys.exit(0)

        elif args.sync_history:
            logger.info("\nStarting historical data sync pipeline...")
            run_history_sync(
                symbol=args.symbol,
                timeframe=args.timeframe,
                years=args.years,
                force_full=args.force_sync,
            )
            sys.exit(0)

        elif args.build_features:
            logger.info("\nStarting feature engineering pipeline...")
            run_feature_build(
                symbol=args.symbol,
                timeframe=args.timeframe,
                limit=args.limit,
                horizon=args.horizon,
                threshold=args.threshold,
            )
            sys.exit(0)

        elif args.train_model:
            logger.info("\nStarting model training pipeline...")
            run_model_training(
                symbol=args.symbol,
                timeframe=args.timeframe,
                limit=args.limit,
                horizon=args.horizon,
                test_ratio=args.test_ratio,
            )
            sys.exit(0)
        
        else:
            # Start trading system
            logger.info("\nInitializing trading application...")
            trading_app = TradingApplication()
            trading_app.initialize()
            trading_app.start()
        
    except KeyboardInterrupt:
        logger.info("\nSystem interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
