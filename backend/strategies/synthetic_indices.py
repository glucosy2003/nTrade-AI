"""Strategy profiles for synthetic FX index trading."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.indicators.indicators import MomentumIndicators, MovingAverages, TrendIndicators, VolatilityIndicators
from backend.strategies.base_strategy import BaseStrategy


@dataclass(frozen=True)
class SyntheticStrategyProfile:
    """Lightweight strategy parameters for one volatility bucket."""

    name: str
    fast_period: int
    slow_period: int
    rsi_buy_level: float
    rsi_sell_level: float
    atr_period: int
    breakout_window: int
    min_atr_ratio: float


class SyntheticIndexStrategy(BaseStrategy):
    """Shared helpers for synthetic-index strategy implementations."""

    def __init__(self, profile: SyntheticStrategyProfile) -> None:
        self.profile = profile

    def _validate_frame(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return data.copy()

        required_columns = {"close", "high", "low", "volume"}
        missing = required_columns.difference(data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        frame = data.copy()
        for column in ["close", "high", "low", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame

    def _empty_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=data.index, dtype=int)


class SyntheticTrendStrategy(SyntheticIndexStrategy):
    """Conservative trend strategy for the 20% volatility index."""

    def __init__(self) -> None:
        super().__init__(
            SyntheticStrategyProfile(
                name="synthetic_trend_20",
                fast_period=8,
                slow_period=21,
                rsi_buy_level=53.0,
                rsi_sell_level=47.0,
                atr_period=14,
                breakout_window=20,
                min_atr_ratio=0.03,
            )
        )

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        frame = self._validate_frame(data)
        if frame.empty:
            return pd.Series(dtype=int)

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        fast_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.fast_period), index=frame.index)
        slow_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.slow_period), index=frame.index)
        rsi = pd.Series(MomentumIndicators.rsi(close.to_numpy(), 14), index=frame.index)
        atr = pd.Series(VolatilityIndicators.atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), self.profile.atr_period), index=frame.index)
        atr_ratio = atr / close.replace(0, np.nan)

        signals = self._empty_signals(frame)
        for idx in range(1, len(frame)):
            if pd.isna(fast_ema.iloc[idx]) or pd.isna(slow_ema.iloc[idx]) or pd.isna(rsi.iloc[idx]):
                continue
            if pd.isna(atr_ratio.iloc[idx]) or atr_ratio.iloc[idx] < self.profile.min_atr_ratio / 100:
                continue

            if fast_ema.iloc[idx] > slow_ema.iloc[idx] and rsi.iloc[idx] >= self.profile.rsi_buy_level:
                signals.iloc[idx] = 1
            elif fast_ema.iloc[idx] < slow_ema.iloc[idx] and rsi.iloc[idx] <= self.profile.rsi_sell_level:
                signals.iloc[idx] = -1

        return signals


class SyntheticBalancedMomentumStrategy(SyntheticIndexStrategy):
    """Balanced momentum and pullback strategy for the 40% volatility index."""

    def __init__(self) -> None:
        super().__init__(
            SyntheticStrategyProfile(
                name="synthetic_momentum_40",
                fast_period=10,
                slow_period=30,
                rsi_buy_level=51.0,
                rsi_sell_level=49.0,
                atr_period=14,
                breakout_window=24,
                min_atr_ratio=0.04,
            )
        )

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        frame = self._validate_frame(data)
        if frame.empty:
            return pd.Series(dtype=int)

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        fast_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.fast_period), index=frame.index)
        slow_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.slow_period), index=frame.index)
        rsi = pd.Series(MomentumIndicators.rsi(close.to_numpy(), 14), index=frame.index)
        macd_line, macd_signal, macd_hist = MomentumIndicators.macd(close.to_numpy())
        atr = pd.Series(VolatilityIndicators.atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), self.profile.atr_period), index=frame.index)
        atr_ratio = atr / close.replace(0, np.nan)
        prev_close = close.shift(1)

        signals = self._empty_signals(frame)
        for idx in range(1, len(frame)):
            if any(
                pd.isna(value)
                for value in [fast_ema.iloc[idx], slow_ema.iloc[idx], rsi.iloc[idx], macd_hist[idx], atr_ratio.iloc[idx]]
            ):
                continue
            if atr_ratio.iloc[idx] < self.profile.min_atr_ratio / 100:
                continue

            pullback_buy = close.iloc[idx] > fast_ema.iloc[idx] and prev_close.iloc[idx] <= fast_ema.iloc[idx]
            pullback_sell = close.iloc[idx] < fast_ema.iloc[idx] and prev_close.iloc[idx] >= fast_ema.iloc[idx]

            if fast_ema.iloc[idx] >= slow_ema.iloc[idx] and macd_hist[idx] >= 0 and rsi.iloc[idx] >= self.profile.rsi_buy_level:
                signals.iloc[idx] = 1
            elif fast_ema.iloc[idx] <= slow_ema.iloc[idx] and macd_hist[idx] <= 0 and rsi.iloc[idx] <= self.profile.rsi_sell_level:
                signals.iloc[idx] = -1
            elif pullback_buy and macd_hist[idx] > 0 and rsi.iloc[idx] >= 50:
                signals.iloc[idx] = 1
            elif pullback_sell and macd_hist[idx] < 0 and rsi.iloc[idx] <= 50:
                signals.iloc[idx] = -1

        return signals


class SyntheticBreakoutStrategy(SyntheticIndexStrategy):
    """Breakout strategy for the 80% volatility index."""

    def __init__(self) -> None:
        super().__init__(
            SyntheticStrategyProfile(
                name="synthetic_breakout_80",
                fast_period=5,
                slow_period=20,
                rsi_buy_level=55.0,
                rsi_sell_level=45.0,
                atr_period=14,
                breakout_window=20,
                min_atr_ratio=0.06,
            )
        )

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        frame = self._validate_frame(data)
        if frame.empty:
            return pd.Series(dtype=int)

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        volume = frame["volume"]
        fast_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.fast_period), index=frame.index)
        slow_ema = pd.Series(MovingAverages.ema(close.to_numpy(), self.profile.slow_period), index=frame.index)
        rsi = pd.Series(MomentumIndicators.rsi(close.to_numpy(), 14), index=frame.index)
        atr = pd.Series(VolatilityIndicators.atr(high.to_numpy(), low.to_numpy(), close.to_numpy(), self.profile.atr_period), index=frame.index)
        upper_band, middle_band, lower_band = VolatilityIndicators.bollinger_bands(close.to_numpy(), period=self.profile.breakout_window, std_dev=2.0)
        volume_ma = volume.rolling(window=self.profile.breakout_window, min_periods=1).mean()
        recent_high = high.rolling(window=self.profile.breakout_window, min_periods=1).max().shift(1)
        recent_low = low.rolling(window=self.profile.breakout_window, min_periods=1).min().shift(1)
        atr_ratio = atr / close.replace(0, np.nan)

        signals = self._empty_signals(frame)
        for idx in range(1, len(frame)):
            values = [
                fast_ema.iloc[idx],
                slow_ema.iloc[idx],
                rsi.iloc[idx],
                atr_ratio.iloc[idx],
                upper_band[idx],
                middle_band[idx],
                lower_band[idx],
                recent_high.iloc[idx],
                recent_low.iloc[idx],
            ]
            if any(pd.isna(value) for value in values):
                continue
            if atr_ratio.iloc[idx] < self.profile.min_atr_ratio / 100:
                continue

            volume_confirmed = volume.iloc[idx] >= volume_ma.iloc[idx]
            bullish_breakout = close.iloc[idx] > recent_high.iloc[idx] and close.iloc[idx] > upper_band[idx]
            bearish_breakout = close.iloc[idx] < recent_low.iloc[idx] and close.iloc[idx] < lower_band[idx]
            bullish_continuation = close.iloc[idx] > middle_band[idx] and fast_ema.iloc[idx] >= slow_ema.iloc[idx]
            bearish_continuation = close.iloc[idx] < middle_band[idx] and fast_ema.iloc[idx] <= slow_ema.iloc[idx]

            if bullish_breakout and fast_ema.iloc[idx] >= slow_ema.iloc[idx] and rsi.iloc[idx] >= self.profile.rsi_buy_level and volume_confirmed:
                signals.iloc[idx] = 1
            elif bearish_breakout and fast_ema.iloc[idx] <= slow_ema.iloc[idx] and rsi.iloc[idx] <= self.profile.rsi_sell_level and volume_confirmed:
                signals.iloc[idx] = -1
            elif bullish_continuation and rsi.iloc[idx] >= self.profile.rsi_buy_level and volume_confirmed:
                signals.iloc[idx] = 1
            elif bearish_continuation and rsi.iloc[idx] <= self.profile.rsi_sell_level and volume_confirmed:
                signals.iloc[idx] = -1

        return signals


SYNTHETIC_STRATEGY_REGISTRY = {
    "20": SyntheticTrendStrategy,
    "40": SyntheticBalancedMomentumStrategy,
    "80": SyntheticBreakoutStrategy,
}


def get_synthetic_strategy(volatility_bucket: str) -> BaseStrategy:
    """Return the strategy class for a volatility bucket."""
    strategy_class = SYNTHETIC_STRATEGY_REGISTRY.get(str(volatility_bucket))
    if strategy_class is None:
        raise ValueError(f"Unsupported synthetic volatility bucket: {volatility_bucket}")
    return strategy_class()
