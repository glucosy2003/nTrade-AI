import pandas as pd

from backend.ai.feature_engineering import engineer_price_features


def build_sample_frame() -> pd.DataFrame:
    rows = []
    prices = [100, 101, 102, 103, 104, 106, 108, 110, 113, 116]
    for i, close in enumerate(prices):
        rows.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(i, unit="D"),
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_engineer_price_features_adds_indicator_columns():
    data = build_sample_frame()

    engineered = engineer_price_features(data)

    assert {"ema_fast_10", "ema_slow_30", "atr_14", "returns", "log_returns"}.issubset(engineered.columns)
    assert engineered["time"].is_monotonic_increasing
