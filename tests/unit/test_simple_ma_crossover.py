import pandas as pd

from backend.strategies.simple_ma_crossover import SimpleMAcrossover


def build_sample_frame() -> pd.DataFrame:
    prices = [100 + i * 0.5 for i in range(40)]
    rows = []
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


def test_strategy_returns_one_signal_per_candle():
    strategy = SimpleMAcrossover(fast_period=3, slow_period=5)
    data = build_sample_frame()

    signals = strategy(data)

    assert len(signals) == len(data)
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_strategy_generates_non_zero_signals_in_crossing_data():
    strategy = SimpleMAcrossover(fast_period=3, slow_period=5)

    rows = []
    prices = [100, 100, 100, 102, 106, 110, 115, 120]
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
    data = pd.DataFrame(rows)

    signals = strategy(data)

    assert any(signal != 0 for signal in signals)
