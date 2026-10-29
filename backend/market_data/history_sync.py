"""Incremental historical-data synchronization for gold market data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from backend.core.settings import settings
from backend.market_data.data_storage import MarketDataStorage, market_data_storage
from backend.market_data.mt5_service import MT5Service, mt5_service


logger = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    """High-level result for a history sync run."""

    symbol: str
    timeframe: int
    start: datetime
    end: datetime
    source_rows: int = 0
    inserted_rows: int = 0
    stored_rows: int = 0
    skipped_rows: int = 0
    status: str = "pending"
    message: str = ""


class GoldHistorySyncService:
    """Download, validate, and store gold history incrementally."""

    def __init__(
        self,
        mt5: Optional[MT5Service] = None,
        storage: Optional[MarketDataStorage] = None,
        symbol: Optional[str] = None,
        timeframe: int = 60,
        default_lookback_years: int = 5,
    ) -> None:
        self.mt5 = mt5 or mt5_service
        self.storage = storage or market_data_storage
        self.symbol = symbol or settings.gold_history_symbol
        self.timeframe = timeframe
        self.default_lookback_years = default_lookback_years

    def sync(self, force_full: bool = False, lookback_years: Optional[int] = None) -> SyncSummary:
        """Sync historical candles into PostgreSQL."""
        end = datetime.utcnow()
        lookback_years = lookback_years or self.default_lookback_years
        latest_timestamp = None if force_full else self.storage.get_latest_timestamp(self.symbol, self.timeframe)

        if latest_timestamp is None:
            start = end - timedelta(days=max(lookback_years, 1) * 365)
            mode = "full"
        else:
            start = latest_timestamp + timedelta(minutes=self.timeframe)
            mode = "incremental"

        summary = SyncSummary(symbol=self.symbol, timeframe=self.timeframe, start=start, end=end)

        if not self.mt5.connect():
            summary.status = "failed"
            summary.message = "MT5 connection failed"
            return summary

        logger.info(
            "Syncing %s history (%s mode) from %s to %s",
            self.symbol,
            mode,
            start,
            end,
        )

        data = self.mt5.get_historical_data(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start=start,
            end=end,
            limit=100000,
        )

        if data is None or data.empty:
            summary.status = "empty"
            summary.message = "No historical data returned"
            return summary

        summary.source_rows = len(data)

        storage_result = self.storage.store_price_frame(data, symbol=self.symbol, timeframe=self.timeframe)
        summary.inserted_rows = storage_result.inserted_rows
        summary.stored_rows = storage_result.stored_rows
        summary.skipped_rows = storage_result.skipped_rows

        if storage_result.validation.warnings:
            summary.message = "; ".join(storage_result.validation.warnings)

        summary.status = "success"
        return summary


gold_history_sync = GoldHistorySyncService()
