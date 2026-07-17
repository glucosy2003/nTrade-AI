"""MT5 data collection wrapper for the Windows-first trading stack."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.core.settings import settings
from backend.market_data.mt5_service import MT5Service, mt5_service


logger = logging.getLogger(__name__)


class MT5DataCollector:
    """Thin compatibility wrapper around the canonical MT5 service."""

    def __init__(self, service: Optional[MT5Service] = None) -> None:
        self.service = service or mt5_service
        self.is_connected = False

    def connect(self) -> bool:
        """Connect to MetaTrader 5."""
        self.is_connected = self.service.connect()
        if self.is_connected:
            logger.info("✓ Connected to MT5 successfully")
            account_info = self.service.account_info()
            if account_info:
                login = account_info.get("login", settings.mt5_account_number or "unknown")
                server = account_info.get("server", settings.mt5_server)
                logger.info("  Account: %s", login)
                logger.info("  Server: %s", server)
        return self.is_connected

    def disconnect(self) -> None:
        """Disconnect from MetaTrader 5."""
        self.service.disconnect()
        self.is_connected = False
        logger.info("✓ Disconnected from MT5")

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Return the latest price for a symbol."""
        if not self.is_connected and not self.connect():
            return None
        return self.service.get_live_price(symbol)

    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
    ) -> Optional[pd.DataFrame]:
        """Retrieve historical OHLCV data from MT5."""
        if not self.is_connected and not self.connect():
            return None
        return self.service.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start=start_date,
            end=end_date,
            limit=limit,
        )

    def validate_symbol(self, symbol: str) -> bool:
        """Check whether a symbol is available."""
        if not self.is_connected and not self.connect():
            return False
        return self.service.validate_symbol(symbol)

    def get_account_info(self) -> Optional[dict]:
        """Return account information as a dictionary."""
        if not self.is_connected and not self.connect():
            return None
        return self.service.account_info()

    def get_positions(self) -> list[dict]:
        """Return the current open positions."""
        if not self.is_connected and not self.connect():
            return []
        return self.service.get_positions()


# Global MT5 data collector instance
mt5_collector = MT5DataCollector()
