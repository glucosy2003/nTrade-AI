"""Simple moving-average crossover strategy for Phase 1 backtests."""

from __future__ import annotations

import logging

import pandas as pd

from backend.strategies.base_strategy import BaseStrategy


logger = logging.getLogger(__name__)


class SimpleMAcrossover(BaseStrategy):
    """Generate BUY/SELL/HOLD signals from a fast and slow moving-average crossover."""

    def __init__(self, fast_period: int = 10, slow_period: int = 20) -> None:
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("Periods must be positive")
        if fast_period >= slow_period:
            raise ValueError("Fast period must be smaller than the slow period")

        self.fast_period = fast_period
        self.slow_period = slow_period
        logger.info(
            "SimpleMAcrossover initialized: fast=%s, slow=%s",
            fast_period,
            slow_period,
        )

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return a signal series of -1, 0, or 1 for each candle."""
        if data.empty:
            return pd.Series(dtype=int)

        required_columns = {"close"}
        missing = required_columns.difference(data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        close = pd.to_numeric(data["close"], errors="coerce")
        fast_ma = close.rolling(window=self.fast_period, min_periods=1).mean()
        slow_ma = close.rolling(window=self.slow_period, min_periods=1).mean()

        signals = pd.Series(0, index=data.index, dtype=int)
        for idx in range(1, len(data)):
            prev_fast = fast_ma.iloc[idx - 1]
            prev_slow = slow_ma.iloc[idx - 1]
            curr_fast = fast_ma.iloc[idx]
            curr_slow = slow_ma.iloc[idx]

            if pd.notna(prev_fast) and pd.notna(prev_slow) and pd.notna(curr_fast) and pd.notna(curr_slow):
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    signals.iloc[idx] = 1
                elif prev_fast >= prev_slow and curr_fast < curr_slow:
                    signals.iloc[idx] = -1

        return signals
