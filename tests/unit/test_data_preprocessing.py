import pandas as pd
import pytest

from backend.market_data.data_processor import prepare_price_data


def test_prepare_price_data_adds_return_features_and_sorts_by_time():
    data = pd.DataFrame(
        [
            {"time": pd.Timestamp("2024-01-03"), "open": 102.0, "high": 103.0, "low": 101.0, "close": 102.0, "volume": 1000},
            {"time": pd.Timestamp("2024-01-01"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 900},
            {"time": pd.Timestamp("2024-01-02"), "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 950},
        ]
    )

    prepared = prepare_price_data(data)

    assert prepared["time"].is_monotonic_increasing
    assert {"returns", "log_returns"}.issubset(prepared.columns)
    assert prepared.loc[prepared["time"] == pd.Timestamp("2024-01-02"), "returns"].iloc[0] == pytest.approx(0.01)
