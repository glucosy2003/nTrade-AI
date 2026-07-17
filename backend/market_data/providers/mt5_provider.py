"""Provider implementation for direct Windows MT5 market data access."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.market_data.mt5_service import MT5Service, mt5_service
from backend.market_data.providers.base_provider import BaseProvider


logger = logging.getLogger(__name__)


class MT5Provider(BaseProvider):
    """Adapter for local MT5 data access in the Windows-only workspace."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 5.0,
        service: Optional[MT5Service] = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.service = service or mt5_service
        self.is_connected = False

    def connect(self) -> bool:
        """Connect to the local MT5 terminal."""
        self.is_connected = self.service.connect()
        if self.is_connected:
            logger.info("MT5 provider connection established")
        else:
            logger.warning("MT5 provider could not connect to the local terminal")
        return self.is_connected

    def disconnect(self) -> None:
        """Disconnect from the local MT5 terminal."""
        self.service.disconnect()
        self.is_connected = False

    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Return historical candles from the local MT5 service."""
        if not self.is_connected and not self.connect():
            return None

        return self.service.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    def get_live_price(self, symbol: str) -> Optional[float]:
        """Return the latest available price from the local MT5 service."""
        if not self.is_connected and not self.connect():
            return None

        return self.service.get_live_price(symbol)
