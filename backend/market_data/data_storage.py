"""Persistence helpers for validated market data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import desc

from backend.market_data.data_validator import MarketDataValidator, PriceValidationResult
from database.models import PriceData
from database.database_manager import db_manager


logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Summary for a storage operation."""

    inserted_rows: int
    stored_rows: int
    skipped_rows: int
    validation: PriceValidationResult


class MarketDataStorage:
    """Store validated market data in PostgreSQL."""

    def __init__(self, database_manager=db_manager, validator: Optional[MarketDataValidator] = None) -> None:
        self.database_manager = database_manager
        self.validator = validator or MarketDataValidator()

    def ensure_ready(self) -> None:
        """Initialize the database layer if needed."""
        if not self.database_manager.connection.is_connected():
            self.database_manager.initialize()

    def get_latest_timestamp(self, symbol: str, timeframe: int) -> Optional[datetime]:
        """Return the latest stored candle timestamp for a symbol and timeframe."""
        try:
            self.ensure_ready()
            with self.database_manager.connection.session_scope() as session:
                latest_timestamp = (
                    session.query(PriceData.timestamp)
                    .filter(PriceData.symbol == symbol, PriceData.timeframe == timeframe)
                    .order_by(desc(PriceData.timestamp))
                    .limit(1)
                    .scalar()
                )
                return latest_timestamp
        except Exception as exc:
            logger.error("Failed to look up latest timestamp for %s: %s", symbol, exc, exc_info=True)
            return None

    def store_price_frame(self, data: pd.DataFrame, symbol: str, timeframe: int) -> StorageResult:
        """Validate, normalize, and store a candle DataFrame."""
        self.ensure_ready()

        validation = self.validator.validate_price_frame(data, symbol=symbol, timeframe=timeframe)
        cleaned = self.validator.clean_price_frame(data, symbol=symbol, timeframe=timeframe)

        if cleaned.empty:
            logger.warning("No valid price rows available for %s", symbol)
            return StorageResult(inserted_rows=0, stored_rows=0, skipped_rows=validation.input_rows, validation=validation)

        records = self._frame_to_records(cleaned, symbol=symbol, timeframe=timeframe)
        inserted_rows = self._upsert_price_records(records)
        stored_rows = len(records)
        skipped_rows = max(stored_rows - inserted_rows, 0)

        logger.info(
            "Stored %s price rows for %s (%s skipped)",
            inserted_rows,
            symbol,
            skipped_rows,
        )

        return StorageResult(
            inserted_rows=inserted_rows,
            stored_rows=stored_rows,
            skipped_rows=skipped_rows,
            validation=validation,
        )

    def _upsert_price_records(self, records: list[dict]) -> int:
        """Insert new candles and ignore rows that already exist."""
        if not records:
            return 0

        with self.database_manager.connection.session_scope() as session:
            try:
                statement = pg_insert(PriceData).values(records)
                statement = statement.on_conflict_do_nothing(
                    index_elements=["symbol", "timeframe", "timestamp"]
                )
                result = session.execute(statement)
                return max(int(result.rowcount or 0), 0)
            except Exception as exc:
                logger.error("Failed to upsert price records: %s", exc, exc_info=True)
                raise

    @staticmethod
    def _frame_to_records(data: pd.DataFrame, symbol: str, timeframe: int) -> list[dict]:
        """Convert a cleaned DataFrame into database-ready dictionaries."""
        records: list[dict] = []
        for row in data.itertuples(index=False):
            timestamp = getattr(row, "time")
            if isinstance(timestamp, pd.Timestamp):
                timestamp = timestamp.to_pydatetime()
            if timestamp.tzinfo is not None:
                timestamp = timestamp.replace(tzinfo=None)

            records.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": timestamp,
                    "open": float(getattr(row, "open")),
                    "high": float(getattr(row, "high")),
                    "low": float(getattr(row, "low")),
                    "close": float(getattr(row, "close")),
                    "volume": float(getattr(row, "volume", 0.0)),
                    "is_closed": True,
                    "is_synthetic": False,
                }
            )

        return records


market_data_storage = MarketDataStorage()
