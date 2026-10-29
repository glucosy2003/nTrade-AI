import pandas as pd

from backend.execution.backtester import Backtester


def build_sample_frame() -> pd.DataFrame:
    rows = []
    prices = [100.0, 101.0, 103.0, 106.0]
    for index, close in enumerate(prices):
        rows.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(index, unit="D"),
                "open": close - 0.5,
                "high": close + 0.5,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + index,
            }
        )
    return pd.DataFrame(rows)


def test_backtester_closes_open_position_at_end_and_uses_signal_order():
    data = build_sample_frame()
    backtester = Backtester(initial_balance=10000.0)

    def strategy(frame: pd.DataFrame) -> pd.Series:
        return pd.Series([1, 0, 0, 0], index=pd.date_range("2025-01-01", periods=len(frame), freq="D"))

    result = backtester.run(data=data, strategy_func=strategy, position_size=10.0)
    stats = result.get_stats()

    assert stats["total_trades"] == 1
    assert result.trades[0]["exit_time"] == data.iloc[-1]["time"]
    assert result.trades[0]["profit_loss"] == 60.0
    assert result.equity_curve[-1] == 10060.0
