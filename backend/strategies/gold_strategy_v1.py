"""Gold-focused rule strategy for Phase 2 bridge work."""

from __future__ import annotations

import logging

import pandas as pd

from backend.indicators.indicators import MomentumIndicators, MovingAverages, VolatilityIndicators
from backend.strategies.base_strategy import BaseStrategy


logger = logging.getLogger(__name__)


class GoldStrategyV1(BaseStrategy):
    """A simple trend-following strategy tuned for gold-style price action.

    Signals are generated from a fast/slow EMA crossover and an RSI trend filter.
    The design intentionally stays lightweight and fully explainable so it can be
    used as a Phase 2 baseline before introducing ML components.
    """

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        rsi_period: int = 14,
        atr_period: int = 14,
    ) -> None:
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("Periods must be positive")
        if fast_period >= slow_period:
            raise ValueError("Fast period must be smaller than the slow period")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return -1, 0, or 1 signals aligned with the input candles."""
        if data.empty:
            return pd.Series(dtype=int)

        required_columns = {"close", "high", "low"}
        missing = required_columns.difference(data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        close = pd.to_numeric(data["close"], errors="coerce")
        high = pd.to_numeric(data["high"], errors="coerce")
        low = pd.to_numeric(data["low"], errors="coerce")

        fast_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.fast_period), index=data.index)
        slow_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.slow_period), index=data.index)
        rsi = pd.Series(MomentumIndicators.rsi(close.to_numpy(), self.rsi_period), index=data.index)
        atr = pd.Series(
            VolatilityIndicators.atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), self.atr_period),
            index=data.index,
        )

        signals = pd.Series(0, index=data.index, dtype=int)
        for idx in range(1, len(data)):
            prev_fast = fast_ema.iloc[idx - 1]
            prev_slow = slow_ema.iloc[idx - 1]
            curr_fast = fast_ema.iloc[idx]
            curr_slow = slow_ema.iloc[idx]
            curr_rsi = rsi.iloc[idx]
            curr_atr = atr.iloc[idx]
            prev_close = close.iloc[idx - 1]
            curr_close = close.iloc[idx]

            if pd.isna(curr_fast) or pd.isna(curr_slow) or pd.isna(curr_rsi) or pd.isna(curr_atr):
                continue

            if prev_fast <= prev_slow and curr_fast > curr_slow and curr_rsi >= 50 and curr_atr > 0:
                signals.iloc[idx] = 1
            elif prev_fast >= prev_slow and curr_fast < curr_slow and curr_rsi <= 50 and curr_atr > 0:
                signals.iloc[idx] = -1
            elif curr_fast > curr_slow and curr_close > prev_close and curr_rsi >= 50 and curr_atr > 0:
                signals.iloc[idx] = 1
            elif curr_fast < curr_slow and curr_close < prev_close and curr_rsi <= 50 and curr_atr > 0:
                signals.iloc[idx] = -1

        return signals
