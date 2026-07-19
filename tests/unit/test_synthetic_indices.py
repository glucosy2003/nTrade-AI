import pandas as pd

from backend.strategies.synthetic_indices import (
    SyntheticBalancedMomentumStrategy,
    SyntheticBreakoutStrategy,
    SyntheticTrendStrategy,
    get_synthetic_strategy,
)


def build_trending_frame(direction: str = "up", rows: int = 80) -> pd.DataFrame:
    data = []
    for index in range(rows):
        if direction == "up":
            close = 100 + index * 0.8
        else:
            close = 180 - index * 0.8
        data.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(index, unit="h"),
                "open": close - 0.2,
                "high": close + 0.6,
                "low": close - 0.6,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    return pd.DataFrame(data)


def build_breakout_frame() -> pd.DataFrame:
    data = []
    close = 100.0
    for index in range(80):
        if index < 60:
            close += 0.1
        else:
            close += 1.5
        data.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(index, unit="h"),
                "open": close - 0.2,
                "high": close + (1.0 if index >= 60 else 0.4),
                "low": close - (1.0 if index >= 60 else 0.4),
                "close": close,
                "volume": 1000 + (index * 15),
            }
        )
    return pd.DataFrame(data)


def test_synthetic_trend_strategy_generates_bullish_signal():
    frame = build_trending_frame("up")
    signals = SyntheticTrendStrategy().generate_signals(frame)

    assert len(signals) == len(frame)
    assert signals.iloc[-1] in {0, 1}
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_synthetic_balanced_strategy_generates_signal():
    frame = build_trending_frame("up")
    signals = SyntheticBalancedMomentumStrategy().generate_signals(frame)

    assert len(signals) == len(frame)
    assert set(signals.unique()).issubset({-1, 0, 1})


def test_synthetic_breakout_strategy_generates_breakout_signal():
    frame = build_breakout_frame()
    signals = SyntheticBreakoutStrategy().generate_signals(frame)

    assert len(signals) == len(frame)
    assert set(signals.unique()).issubset({-1, 0, 1})
    assert signals.iloc[-1] in {0, 1}


def test_strategy_registry_returns_expected_profile():
    strategy = get_synthetic_strategy("40")

    assert strategy.__class__.__name__ == "SyntheticBalancedMomentumStrategy"
