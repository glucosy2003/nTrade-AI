from contextlib import contextmanager

import pandas as pd

from backend.market_data.data_storage import MarketDataStorage
from backend.market_data.data_validator import MarketDataValidator


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rowcount)


class FakeConnection:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    def is_connected(self) -> bool:
        return True

    @contextmanager
    def session_scope(self):
        yield FakeSession(self.rowcount)


class FakeDatabaseManager:
    def __init__(self, rowcount: int) -> None:
        self.connection = FakeConnection(rowcount)

    def initialize(self) -> None:
        raise AssertionError("initialize should not be called when the connection is already ready")


def build_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": pd.Timestamp("2024-01-01"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 900},
            {"time": pd.Timestamp("2024-01-02"), "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 950},
        ]
    )


def test_store_price_frame_uses_idempotent_upsert():
    storage = MarketDataStorage(database_manager=FakeDatabaseManager(rowcount=1), validator=MarketDataValidator())

    result = storage.store_price_frame(build_price_frame(), symbol="XAUUSD", timeframe=60)

    assert result.inserted_rows == 1
    assert result.stored_rows == 2
    assert result.skipped_rows == 1
    assert result.validation.is_valid is True
    assert result.validation.cleaned_rows == 2


def test_store_price_frame_rejects_none_input():
    storage = MarketDataStorage(database_manager=FakeDatabaseManager(rowcount=0), validator=MarketDataValidator())

    result = storage.validator.validate_price_frame(None, symbol="XAUUSD", timeframe=60)

    assert result.is_valid is False
    assert result.input_rows == 0
    assert "No price data provided" in result.warnings
