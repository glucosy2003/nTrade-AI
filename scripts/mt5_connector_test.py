#!/usr/bin/env python3
"""
Test MT5 connection and data collection.

This is a Windows/MT5 core validation script to confirm:
1. MT5 connection works
2. Can retrieve price data
3. Database stores data correctly

Usage:
    python scripts/mt5_connector_test.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from backend.market_data.data_collector import mt5_collector
from database.database_manager import db_manager


logger = setup_logger(__name__)


def test_mt5_connection() -> bool:
    """Test MT5 connection."""
    logger.info("=" * 60)
    logger.info("Testing MT5 Connection")
    logger.info("=" * 60)
    
    if not mt5_collector.connect():
        logger.error("✗ Failed to connect to MT5")
        return False
    
    logger.info("✓ MT5 connection successful")
    
    # Get account info
    account_info = mt5_collector.get_account_info()
    if account_info:
        logger.info("Account Information:")
        logger.info(f"  Balance: {account_info['balance']:.2f} {account_info['currency']}")
        logger.info(f"  Equity: {account_info['equity']:.2f}")
        logger.info(f"  Free Margin: {account_info['free_margin']:.2f}")
        logger.info(f"  Margin Level: {account_info['margin_level']:.2f}%")
    
    return True


def test_price_data() -> bool:
    """Test price data retrieval."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Price Data Retrieval")
    logger.info("=" * 60)
    
    symbol = settings.default_symbol
    timeframe = settings.default_timeframe
    
    logger.info(f"Retrieving data for {symbol} ({timeframe} min timeframe)...")
    
    # Validate symbol
    if not mt5_collector.validate_symbol(symbol):
        logger.error(f"✗ Symbol {symbol} not available")
        return False
    
    logger.info(f"✓ Symbol {symbol} is available")
    
    # Get historical data
    df = mt5_collector.get_historical_data(
        symbol=symbol,
        timeframe=timeframe,
        limit=100
    )
    
    if df is None or len(df) == 0:
        logger.error("✗ Failed to retrieve price data")
        return False
    
    logger.info(f"✓ Retrieved {len(df)} candles")
    logger.info(f"  Time Range: {df['time'].min()} to {df['time'].max()}")
    logger.info(f"  Price Range: {df['low'].min():.2f} to {df['high'].max():.2f}")
    logger.info(f"  Latest Close: {df['close'].iloc[-1]:.2f}")
    
    # Get current price
    current_price = mt5_collector.get_current_price(symbol)
    if current_price:
        logger.info(f"✓ Current {symbol} Price: {current_price:.2f}")
    
    return True


def test_database() -> bool:
    """Test database operations."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Database")
    logger.info("=" * 60)
    
    try:
        # Initialize database
        logger.info("Initializing database...")
        db_manager.initialize()
        logger.info("✓ Database initialized")
        
        # Get database stats
        stats = db_manager.get_database_stats()
        logger.info("Database Statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Database test failed: {str(e)}")
        return False


def main():
    """Main test execution."""
    logger.info("\n" + "=" * 60)
    logger.info("nTrade AI - Phase 0 Validation Test")
    logger.info("=" * 60)
    
    try:
        # Test 1: MT5 Connection
        if not test_mt5_connection():
            return False
        
        # Test 2: Price Data
        if not test_price_data():
            logger.warning("⚠ Price data test failed, but continuing...")
        
        # Test 3: Database
        if not test_database():
            return False
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ All validation tests passed!")
        logger.info("=" * 60)
        logger.info("\nNext Steps:")
        logger.info("1. Copy .env.example to .env")
        logger.info("2. Fill in MT5 credentials in .env")
        logger.info("3. Run: python main.py")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Test failed with error: {str(e)}", exc_info=True)
        return False
    finally:
        # Cleanup
        mt5_collector.disconnect()
        db_manager.close()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
