from datetime import datetime, timedelta

import pandas as pd

from backend.strategies.fx_vol_40_trend import (
    FastProfitTradeGuard,
    FxVol40TrendAnalyzer,
    FxVol40TrendStrategy,
)


def build_uptrend_frame(rows: int = 120) -> pd.DataFrame:
    data = []
    start = 100.0
    for index in range(rows):
        close = start + index * 0.8
        data.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(index, unit="min"),
                "open": close - 0.2,
                "high": close + 0.6,
                "low": close - 0.7,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    return pd.DataFrame(data)


def build_downtrend_frame(rows: int = 120) -> pd.DataFrame:
    data = []
    start = 200.0
    for index in range(rows):
        close = start - index * 0.9
        data.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(index, unit="min"),
                "open": close + 0.2,
                "high": close + 0.9,
                "low": close - 0.8,
                "close": close,
                "volume": 1000 + index * 10,
            }
        )
    return pd.DataFrame(data)


def build_flat_frame(rows: int = 80) -> pd.DataFrame:
    frame = build_uptrend_frame(rows)
    frame["close"] = 100.0
    frame["open"] = 100.0
    frame["high"] = 100.6
    frame["low"] = 99.3
    return frame


def test_fx_vol_40_trend_strategy_detects_uptrend():
    frame = build_uptrend_frame()
    strategy = FxVol40TrendStrategy()

    signal = strategy.generate_signals(frame)

    assert len(signal) == len(frame)
    assert set(signal.unique()).issubset({-1, 0, 1})
    assert signal.iloc[-1] == 1


def test_fx_vol_40_trend_strategy_detects_downtrend():
    frame = build_downtrend_frame()
    strategy = FxVol40TrendStrategy()

    signal = strategy.generate_signals(frame)

    assert signal.iloc[-1] == -1


def test_multitimeframe_trend_analyzer_requires_alignment():
    analyzer = FxVol40TrendAnalyzer()
    frames = {
        "M5": build_uptrend_frame(80),
        "M15": build_uptrend_frame(60),
        "H1": build_uptrend_frame(40),
    }

    decision = analyzer.evaluate(frames)

    assert decision.direction == "BUY"
    assert decision.score >= 0.7
    assert decision.confirmed is True


def test_multitimeframe_trend_analyzer_confirms_two_of_three_at_065():
    analyzer = FxVol40TrendAnalyzer()
    frames = {
        "M5": build_uptrend_frame(80),
        "M15": build_uptrend_frame(60),
        "H1": build_flat_frame(80),
    }

    decision = analyzer.evaluate(frames)

    assert decision.direction == "BUY"
    assert decision.score == 0.667
    assert decision.confirmed is True


def test_fast_profit_trade_guard_closes_on_profit_target_and_caps_trades():
    now = datetime.now()
    guard = FastProfitTradeGuard(max_trades_per_6h=10, profit_target_usd=2.0)

    assert guard.should_close(position_profit=2.1) is True
    assert guard.should_close(position_profit=1.5) is False
    assert guard.should_close_for_loss(position_profit=-2.0) is True
    assert guard.should_close_for_loss(position_profit=-1.99) is False

    timestamps = [now - timedelta(minutes=30 * offset) for offset in range(10)]
    assert guard.is_trade_allowed(timestamps) is False

    allowed = guard.is_trade_allowed([now - timedelta(minutes=400)])
    assert allowed is True
