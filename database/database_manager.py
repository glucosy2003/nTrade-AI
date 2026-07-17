"""
Database manager for high-level database operations.

Provides methods for:
- Creating and initializing database schema
- Inserting and querying price data, signals, and trades
- Performance metrics calculation
- Database cleanup and maintenance
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.connection import db
from database.models import Base, PriceData, Signal, Trade, PerformanceMetrics


logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    High-level database operations manager.
    
    Provides domain-specific methods for trading system data management.
    Handles session management and basic error handling.
    """

    def __init__(self):
        """Initialize database manager."""
        self.connection = db

    # ==================== Initialization ====================

    def initialize(self) -> None:
        """
        Initialize database connection and create tables.
        
        Call this once at application startup.
        """
        try:
            self.connection.initialize()
            self.create_tables()
            logger.info("✓ Database manager initialized")
        except Exception as e:
            logger.error(f"✗ Database initialization failed: {str(e)}", exc_info=True)
            raise

    def create_tables(self) -> None:
        """Create all database tables from ORM models."""
        try:
            self.connection.create_all_tables()
        except Exception as e:
            logger.error(f"✗ Failed to create database tables: {str(e)}", exc_info=True)
            raise

    def close(self) -> None:
        """Close database connection."""
        try:
            self.connection.close()
            logger.info("✓ Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {str(e)}", exc_info=True)

    # ==================== Price Data Operations ====================

    def insert_price_data(self, data: Dict[str, Any]) -> PriceData:
        """
        Insert or update a price candle.
        
        Args:
            data: Dictionary with keys: symbol, timeframe, timestamp, open, high, low, close, volume
            
        Returns:
            PriceData instance
        """
        with self.connection.session_scope() as session:
            try:
                # Check if candle already exists
                existing = session.query(PriceData).filter(
                    PriceData.symbol == data['symbol'],
                    PriceData.timeframe == data['timeframe'],
                    PriceData.timestamp == data['timestamp']
                ).first()
                
                if existing:
                    # Update existing candle
                    existing.open = data['open']
                    existing.high = data['high']
                    existing.low = data['low']
                    existing.close = data['close']
                    existing.volume = data.get('volume', 0)
                    existing.is_closed = data.get('is_closed', False)
                    session.flush()
                    return existing
                else:
                    # Create new candle
                    price_data = PriceData(**data)
                    session.add(price_data)
                    session.flush()
                    return price_data
                    
            except Exception as e:
                logger.error(f"✗ Failed to insert price data: {str(e)}", exc_info=True)
                raise

    def insert_price_data_bulk(self, data_list: List[Dict[str, Any]]) -> int:
        """
        Insert multiple price candles efficiently.
        
        Args:
            data_list: List of price data dictionaries
            
        Returns:
            Number of records inserted
        """
        with self.connection.session_scope() as session:
            try:
                inserted_count = 0
                for data in data_list:
                    # Skip if already exists
                    existing = session.query(PriceData).filter(
                        PriceData.symbol == data['symbol'],
                        PriceData.timeframe == data['timeframe'],
                        PriceData.timestamp == data['timestamp']
                    ).first()
                    
                    if not existing:
                        price_data = PriceData(**data)
                        session.add(price_data)
                        inserted_count += 1
                
                logger.info(f"✓ Inserted {inserted_count} price candles")
                return inserted_count
                
            except Exception as e:
                logger.error(f"✗ Bulk insert failed: {str(e)}", exc_info=True)
                raise

    def get_price_data(
        self,
        symbol: str,
        timeframe: int,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[PriceData]:
        """
        Retrieve historical price data.
        
        Args:
            symbol: Trading symbol (e.g., 'XAUUSD')
            timeframe: Timeframe in minutes
            limit: Maximum number of records to return
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            List of PriceData instances
        """
        with self.connection.session_scope() as session:
            try:
                query = session.query(PriceData).filter(
                    PriceData.symbol == symbol,
                    PriceData.timeframe == timeframe
                )
                
                if start_date:
                    query = query.filter(PriceData.timestamp >= start_date)
                if end_date:
                    query = query.filter(PriceData.timestamp <= end_date)
                
                results = query.order_by(desc(PriceData.timestamp)).limit(limit).all()
                return sorted(results, key=lambda x: x.timestamp)  # Return in ascending order
                
            except Exception as e:
                logger.error(f"✗ Failed to retrieve price data: {str(e)}", exc_info=True)
                raise

    # ==================== Signal Operations ====================

    def insert_signal(self, signal_data: Dict[str, Any]) -> Signal:
        """
        Insert a new trading signal.
        
        Args:
            signal_data: Dictionary with signal information
            
        Returns:
            Signal instance
        """
        with self.connection.session_scope() as session:
            try:
                signal = Signal(**signal_data)
                session.add(signal)
                session.flush()
                return signal
            except Exception as e:
                logger.error(f"✗ Failed to insert signal: {str(e)}", exc_info=True)
                raise

    def get_active_signals(self, symbol: Optional[str] = None) -> List[Signal]:
        """
        Retrieve all active signals.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of active Signal instances
        """
        with self.connection.session_scope() as session:
            try:
                query = session.query(Signal).filter(Signal.is_active == True)
                
                if symbol:
                    query = query.filter(Signal.symbol == symbol)
                
                results = query.order_by(desc(Signal.timestamp)).all()
                return results
            except Exception as e:
                logger.error(f"✗ Failed to retrieve signals: {str(e)}", exc_info=True)
                raise

    # ==================== Trade Operations ====================

    def insert_trade(self, trade_data: Dict[str, Any]) -> Trade:
        """
        Insert a new trade record.
        
        Args:
            trade_data: Dictionary with trade information
            
        Returns:
            Trade instance
        """
        with self.connection.session_scope() as session:
            try:
                trade = Trade(**trade_data)
                session.add(trade)
                session.flush()
                return trade
            except Exception as e:
                logger.error(f"✗ Failed to insert trade: {str(e)}", exc_info=True)
                raise

    def update_trade(self, trade_id: int, update_data: Dict[str, Any]) -> Trade:
        """
        Update an existing trade.
        
        Args:
            trade_id: Trade ID
            update_data: Dictionary with fields to update
            
        Returns:
            Updated Trade instance
        """
        with self.connection.session_scope() as session:
            try:
                trade = session.query(Trade).filter(Trade.id == trade_id).first()
                if not trade:
                    raise ValueError(f"Trade {trade_id} not found")
                
                for key, value in update_data.items():
                    if hasattr(trade, key):
                        setattr(trade, key, value)
                
                session.flush()
                return trade
            except Exception as e:
                logger.error(f"✗ Failed to update trade: {str(e)}", exc_info=True)
                raise

    def get_open_trades(self, symbol: Optional[str] = None) -> List[Trade]:
        """
        Retrieve all open trades.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of open Trade instances
        """
        with self.connection.session_scope() as session:
            try:
                query = session.query(Trade).filter(Trade.status == "OPEN")
                
                if symbol:
                    query = query.filter(Trade.symbol == symbol)
                
                results = query.order_by(Trade.entry_time).all()
                return results
            except Exception as e:
                logger.error(f"✗ Failed to retrieve open trades: {str(e)}", exc_info=True)
                raise

    def get_closed_trades(
        self,
        symbol: Optional[str] = None,
        days: int = 30
    ) -> List[Trade]:
        """
        Retrieve closed trades from the past N days.
        
        Args:
            symbol: Optional filter by symbol
            days: Number of days to look back (default 30)
            
        Returns:
            List of closed Trade instances
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        with self.connection.session_scope() as session:
            try:
                query = session.query(Trade).filter(
                    Trade.status == "CLOSED",
                    Trade.exit_time >= cutoff_date
                )
                
                if symbol:
                    query = query.filter(Trade.symbol == symbol)
                
                results = query.order_by(desc(Trade.exit_time)).all()
                return results
            except Exception as e:
                logger.error(f"✗ Failed to retrieve closed trades: {str(e)}", exc_info=True)
                raise

    # ==================== Performance Metrics Operations ====================

    def get_or_create_daily_metrics(self, date: datetime) -> PerformanceMetrics:
        """
        Get or create daily performance metrics record.
        
        Args:
            date: Date for metrics (will use start of day)
            
        Returns:
            PerformanceMetrics instance
        """
        date_only = datetime(date.year, date.month, date.day)
        
        with self.connection.session_scope() as session:
            try:
                metrics = session.query(PerformanceMetrics).filter(
                    PerformanceMetrics.date == date_only
                ).first()
                
                if not metrics:
                    metrics = PerformanceMetrics(date=date_only)
                    session.add(metrics)
                    session.flush()
                
                return metrics
            except Exception as e:
                logger.error(f"✗ Failed to get/create metrics: {str(e)}", exc_info=True)
                raise

    # ==================== Cleanup & Maintenance ====================

    def delete_old_price_data(self, days_to_keep: int = 365) -> int:
        """
        Delete price data older than specified days.
        
        Args:
            days_to_keep: Number of days of data to keep
            
        Returns:
            Number of records deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        with self.connection.session_scope() as session:
            try:
                result = session.query(PriceData).filter(
                    PriceData.timestamp < cutoff_date
                ).delete()
                
                logger.info(f"✓ Deleted {result} old price data records")
                return result
            except Exception as e:
                logger.error(f"✗ Failed to delete old data: {str(e)}", exc_info=True)
                raise

    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get statistics about database contents.
        
        Returns:
            Dictionary with table statistics
        """
        with self.connection.session_scope() as session:
            try:
                stats = {
                    "price_data_records": session.query(PriceData).count(),
                    "signals": session.query(Signal).count(),
                    "active_signals": session.query(Signal).filter(Signal.is_active == True).count(),
                    "trades": session.query(Trade).count(),
                    "open_trades": session.query(Trade).filter(Trade.status == "OPEN").count(),
                    "closed_trades": session.query(Trade).filter(Trade.status == "CLOSED").count(),
                    "metrics_records": session.query(PerformanceMetrics).count(),
                }
                return stats
            except Exception as e:
                logger.error(f"✗ Failed to get database stats: {str(e)}", exc_info=True)
                raise


# Global database manager instance
db_manager = DatabaseManager()
