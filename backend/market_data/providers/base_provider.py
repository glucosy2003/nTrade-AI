from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd


class BaseProvider(ABC):
    """Abstract provider interface for market-data retrieval.

    Providers are responsible only for data access. They must not contain
    strategy, risk, or persistence logic.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Establish a provider connection and return whether it is ready."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the provider connection cleanly."""

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Return a price DataFrame with OHLCV fields."""

    @abstractmethod
    def get_live_price(self, symbol: str) -> Optional[float]:
        """Return the current bid/last price for the symbol."""
