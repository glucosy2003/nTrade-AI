import pandas as pd

from backend.strategies.gold_strategy_v1 import GoldStrategyV1


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


def test_gold_strategy_returns_signal_series_for_each_candle():
    strategy = GoldStrategyV1()
    data = build_sample_frame()

    signals = strategy(data)

    assert len(signals) == len(data)
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_gold_strategy_produces_non_zero_signal_in_trending_market():
    strategy = GoldStrategyV1()
    data = build_sample_frame()

    signals = strategy(data)

    assert any(signal != 0 for signal in signals)
