#!/usr/bin/env python3
"""
nTrade AI Trading System - Main Entry Point.

This is the main entry point for the synthetic-indices trading system.
It initializes the MT5-backed runner and the synthetic execution workflow.

Current focus: synthetic index scanning, deep-analysis gating, and adaptive decision making.

Usage:
    python main.py --help           # Show help
    python main.py --test           # Run system tests
    python main.py --backtest       # Run a strategy backtest
    python main.py                  # Start the trading system entry point
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
        test_database,
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
        symbol=settings.synthetic_index_20_symbol,
        timeframe=5,
        years=1,
        strategy="ma_crossover",
        use_mt5=True,
    )


def main():
    """Main entry point."""
    parser = ArgumentParser(description="nTrade AI Trading System")
    parser.add_argument("--test", action="store_true", help="Run system tests")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument(
        "--strategy", default="ma_crossover", help="Backtest strategy name"
    )
    parser.add_argument(
        "--model-path", default=None, help="Path to a trained model file"
    )
    parser.add_argument(
        "--symbol", default=settings.synthetic_index_20_symbol, help="Synthetic symbol"
    )
    parser.add_argument(
        "--timeframe", type=int, default=5, help="Historical data timeframe in minutes"
    )
    parser.add_argument(
        "--years", type=int, default=1, help="Default lookback window in years"
    )
    parser.add_argument(
        "--mode",
        choices=["default", "fxvol40_fast_profit"],
        default="default",
        help="Run the default trading system or the dedicated FX Vol 40 trend-fast-profit mode",
    )
    parser.add_argument(
        "--fx-vol-40-fast-profit",
        action="store_true",
        help="Shortcut to launch the dedicated FX Vol 40 fast-profit mode",
    )
    parser.add_argument("--version", action="version", version="nTrade AI v1.0.0")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("nTrade AI Trading System")
    logger.info("=" * 60)

    try:
        if args.fx_vol_40_fast_profit or args.mode == "fxvol40_fast_profit":
            logger.info("\nLaunching FX Vol 40 fast-profit mode...")
            from scripts.fx_vol_40_fast_profit import main as run_fx_vol_40_fast_profit

            sys.exit(run_fx_vol_40_fast_profit(["--live"]))

        elif args.test:
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
