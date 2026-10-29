"""Broker-side wrapper for a local MT5 bridge service."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from backend.broker.broker_client import BrokerClient


class MT5Bridge:
    """Concrete bridge adapter for a Windows-hosted MT5 connector service."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.client = BrokerClient(base_url=base_url, timeout=timeout)

    def is_available(self) -> bool:
        """Return True when the bridge service is reachable."""
        return self.client.ping()

    def get_historical_data(
        self,
        symbol: str,
        timeframe: int,
        start: datetime,
        end: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch candles from the bridge HTTP endpoint and normalize them."""
        payload = self.client.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )
        if payload is None or not payload.get("ok"):
            return None

        candles = payload.get("data") or []
        if not candles:
            return None

        df = pd.DataFrame(candles)
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Fetch the latest price through the bridge service."""
        payload = self.client.get_latest_price(symbol=symbol)
        if payload is None or not payload.get("ok"):
            return None
        return payload.get("price")
