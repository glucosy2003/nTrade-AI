#!/usr/bin/env python3
"""
Backtest Runner - Full Pipeline Test.

Tests the complete trading system pipeline:
1. Load/generate historical data
2. Calculate indicators
3. Generate trading signals
4. Simulate trade execution
5. Calculate performance metrics

Usage:
    python scripts/backtest_runner.py --strategy ma_crossover --symbol XAUUSD --tf 60 --years 2

This validates the full pipeline end-to-end before moving into
feature engineering and AI model development.
"""

import sys
from pathlib import Path
from argparse import ArgumentParser
from datetime import datetime, timedelta
import logging

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.execution.backtester import Backtester
from backend.strategies.simple_ma_crossover import SimpleMAcrossover
from backend.market_data.data_collector import mt5_collector
from backend.market_data.data_storage import market_data_storage
from backend.market_data.data_processor import prepare_price_data
from backend.ai.feature_engineering import engineer_price_features
from backend.risk.position_sizer import PositionSizer
from backend.risk.risk_manager import RiskManager
from database.database_manager import db_manager

logger = setup_logger(__name__)


def generate_synthetic_data(
    symbol: str, timeframe: int, num_candles: int = 1000, start_price: float = 2000.0
) -> pd.DataFrame:
    """
    Generate synthetic price data for testing.

    Args:
        symbol: Symbol name
        timeframe: Timeframe in minutes
        num_candles: Number of candles to generate
        start_price: Starting price

    Returns:
        DataFrame with OHLCV data
    """
    logger.info(f"Generating {num_candles} synthetic candles for {symbol}...")

    # Generate random walk
    returns = np.random.normal(0.0001, 0.005, num_candles)
    prices = start_price * np.exp(np.cumsum(returns))

    data = []
    current_time = datetime.now() - timedelta(minutes=timeframe * num_candles)

    for i, close in enumerate(prices):
        # Add noise for OHLC
        o = close * (1 + np.random.uniform(-0.001, 0.001))
        h = max(o, close) * (1 + np.random.uniform(0, 0.002))
        l = min(o, close) * (1 - np.random.uniform(0, 0.002))
        v = np.random.uniform(100, 10000)

        data.append(
            {
                "time": current_time,
                "open": o,
                "high": h,
                "low": l,
                "close": close,
                "volume": v,
                "symbol": symbol,
                "timeframe": timeframe,
            }
        )

        current_time += timedelta(minutes=timeframe)

    df = pd.DataFrame(data)
    logger.info(
        f"✓ Generated synthetic data: {df['close'].min():.2f} to {df['close'].max():.2f}"
    )
    return df


def load_or_generate_data(
    symbol: str, timeframe: int, years: int = 1, use_mt5: bool = True
) -> pd.DataFrame:
    """
    Load historical data from MT5 or generate synthetic data.

    Args:
        symbol: Trading symbol
        timeframe: Timeframe in minutes
        years: Years of historical data
        use_mt5: Try MT5 first, fallback to synthetic

    Returns:
        DataFrame with OHLCV data
    """
    # Try to get from MT5 if enabled
    if use_mt5:
        try:
            logger.info(f"Attempting to load {symbol} data from MT5...")
            if mt5_collector.connect():
                end_date = datetime.now()
                start_date = end_date - timedelta(days=years * 365)

                df = mt5_collector.get_historical_data(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date,
                )

                if df is not None and len(df) > 0:
                    logger.info(f"✓ Loaded {len(df)} candles from MT5")
                    return df
        except Exception as e:
            logger.warning(f"Could not load from MT5: {str(e)}")

    # Fallback to synthetic data
    logger.info("Falling back to synthetic data generation...")
    num_candles = years * 252 * 24 * 60 // timeframe  # Approximate trading candles
    return generate_synthetic_data(
        symbol, timeframe, num_candles=min(num_candles, 1000)
    )


def run_backtest(
    symbol: str,
    timeframe: int,
    years: int = 1,
    strategy: str = "ma_crossover",
    use_mt5: bool = True,
    model_path: str | None = None,
) -> None:
    """
    Run backtest with specified parameters.

    Args:
        symbol: Trading symbol
        timeframe: Timeframe in minutes
        years: Years of historical data
        strategy: Strategy name
        use_mt5: Use real MT5 data if available
    """
    import numpy as np

    logger.info("=" * 60)
    logger.info("PHASE 1 BACKTEST - FULL PIPELINE TEST")
    logger.info("=" * 60)

    try:
        # 1. Load data
        logger.info(f"\n1. LOADING DATA")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Timeframe: {timeframe} min")
        logger.info(f"   Years: {years}")

        df = load_or_generate_data(symbol, timeframe, years, use_mt5)
        logger.info(f"✓ Loaded {len(df)} candles")

        # 2. Preprocess data
        logger.info(f"\n2. PREPROCESSING DATA")
        df = prepare_price_data(df)
        df = engineer_price_features(df)
        logger.info("✓ Added return and volatility features for downstream analysis")

        position_sizer = PositionSizer(risk_per_trade_pct=settings.max_risk_per_trade)
        risk_manager = RiskManager(risk_per_trade_pct=settings.max_risk_per_trade)
        last_close = float(df["close"].iloc[-1])
        risk_plan = risk_manager.build_trade_plan(
            account_balance=10000.0,
            entry_price=last_close,
            stop_loss_price=last_close * 0.99,
        )
        risk_based_position_size = risk_plan["position_size"]
        logger.info(
            f"   Risk-based position size: {risk_based_position_size:.2f} units"
        )
        logger.info(
            f"   Target reward/risk ratio: {risk_plan['risk_reward_ratio']:.2f}"
        )

        # 3. Initialize strategy
        logger.info(f"\n3. INITIALIZING STRATEGY")
        logger.info(f"   Strategy: {strategy}")

        if strategy == "ma_crossover":
            strat = SimpleMAcrossover(fast_period=10, slow_period=20)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        logger.info("✓ Strategy initialized")

        # 4. Run backtest
        logger.info(f"\n4. RUNNING BACKTEST")
        backtester = Backtester(initial_balance=10000.0)
        result = backtester.run(
            data=df,
            strategy_func=strat,
            position_size=risk_based_position_size,
            max_risk_per_trade=settings.max_risk_per_trade,
        )
        logger.info("✓ Backtest completed")

        # 5. Print results
        logger.info(f"\n5. RESULTS")
        result.print_summary()
        stats = result.get_stats()
        logger.info("Backtest performance:")
        logger.info("  Trades: %s", stats["total_trades"])
        logger.info("  Win rate: %.2f%%", stats["win_rate"])
        logger.info("  Total P&L: %.2f", stats["total_profit_loss"])
        logger.info("  Profit factor: %.2f", stats["profit_factor"])
        logger.info("  Max drawdown: %.2f%%", stats["max_drawdown"])
        if stats["sharpe_ratio"] is not None:
            logger.info("  Sharpe ratio: %.2f", stats["sharpe_ratio"])
        if stats["total_trades"] == 0:
            logger.warning("  No trades were generated by the selected strategy")

        # 6. Save to database (optional)
        logger.info(f"\n6. SAVING TO DATABASE")
        try:
            storage_result = market_data_storage.store_price_frame(
                df, symbol=symbol, timeframe=timeframe
            )
            logger.info(
                "✓ Stored %s price candles to database (%s skipped)",
                storage_result.inserted_rows,
                storage_result.skipped_rows,
            )

            # Get database stats
            stats = db_manager.get_database_stats()
            logger.info("Database Statistics:")
            for key, value in stats.items():
                logger.info(f"  {key}: {value}")

        except Exception as e:
            logger.warning(f"Could not save to database: {str(e)}")
        finally:
            db_manager.close()

        logger.info("\n" + "=" * 60)
        logger.info("✓ PHASE 1 VALIDATION COMPLETE")
        logger.info("=" * 60)
        logger.info("\nNext Steps:")
        logger.info("1. Refine strategy parameters based on results")
        logger.info("2. Add more indicators for the synthetic specialist strategy")
        logger.info(
            "3. Move to live synthetic index data with tighter feedback controls"
        )

    except Exception as e:
        logger.error(f"✗ Backtest failed: {str(e)}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    parser = ArgumentParser(description="Backtest Runner")
    parser.add_argument(
        "--symbol", default=settings.synthetic_index_20_symbol, help="Trading symbol"
    )
    parser.add_argument("--tf", type=int, default=60, help="Timeframe in minutes")
    parser.add_argument("--years", type=int, default=1, help="Years of historical data")
    parser.add_argument("--strategy", default="ma_crossover", help="Strategy name")
    parser.add_argument(
        "--model-path", default=None, help="Path to a trained model file"
    )
    parser.add_argument("--no-mt5", action="store_true", help="Use synthetic data only")

    args = parser.parse_args()

    run_backtest(
        symbol=args.symbol,
        timeframe=args.tf,
        years=args.years,
        strategy=args.strategy,
        use_mt5=not args.no_mt5,
        model_path=args.model_path,
    )


if __name__ == "__main__":
    main()
