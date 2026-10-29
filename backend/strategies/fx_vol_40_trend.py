"""FX Vol 40 trend-trading engine focused on confirmed trend entries and fast profit exits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from backend.indicators.indicators import (
    MomentumIndicators,
    MovingAverages,
    VolatilityIndicators,
)
from backend.strategies.base_strategy import BaseStrategy


@dataclass(frozen=True)
class FxVol40TrendDecision:
    """Outcome of a multi-timeframe FX Vol 40 trend assessment."""

    direction: str
    score: float
    confirmed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


class FxVol40TrendStrategy(BaseStrategy):
    """Trend-following system tuned for FX Vol 40 with a strict confirmation gate."""

    def __init__(
        self, fast_period: int = 8, slow_period: int = 21, rsi_period: int = 14
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if data.empty:
            return pd.Series(dtype=int)

        frame = data.copy()
        required_columns = {"close", "high", "low"}
        missing = required_columns.difference(frame.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        for column in ["close", "high", "low"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        close = frame["close"].replace(0, pd.NA)
        high = frame["high"]
        low = frame["low"]

        fast_ema = pd.Series(
            MovingAverages.ema(close.to_numpy(), self.fast_period), index=frame.index
        )
        slow_ema = pd.Series(
            MovingAverages.ema(close.to_numpy(), self.slow_period), index=frame.index
        )
        rsi = pd.Series(
            MomentumIndicators.rsi(close.to_numpy(), self.rsi_period), index=frame.index
        )
        atr = pd.Series(
            VolatilityIndicators.atr(
                high.to_numpy(), low.to_numpy(), close.to_numpy(), 14
            ),
            index=frame.index,
        )

        signals = pd.Series(0, index=frame.index, dtype=int)
        for idx in range(1, len(frame)):
            if any(
                pd.isna(value)
                for value in [
                    fast_ema.iloc[idx],
                    slow_ema.iloc[idx],
                    rsi.iloc[idx],
                    atr.iloc[idx],
                ]
            ):
                continue

            recent_window_start = max(0, idx - 8)
            recent_window_close = close.iloc[recent_window_start : idx + 1]
            if recent_window_close.empty:
                continue

            recent_average = float(recent_window_close.mean())
            price_change = float(close.iloc[idx] - close.iloc[idx - 1])
            trend_gap = float(fast_ema.iloc[idx] - slow_ema.iloc[idx])
            atr_floor = max(float(atr.iloc[idx]), 0.0)

            bullish = (
                fast_ema.iloc[idx] > slow_ema.iloc[idx]
                and close.iloc[idx] >= recent_average
                and price_change > 0
                and rsi.iloc[idx] >= 50
                and atr_floor > 0
            )
            bearish = (
                fast_ema.iloc[idx] < slow_ema.iloc[idx]
                and close.iloc[idx] <= recent_average
                and price_change < 0
                and rsi.iloc[idx] <= 50
                and atr_floor > 0
            )

            if bullish:
                signals.iloc[idx] = 1
            elif bearish:
                signals.iloc[idx] = -1

        return signals


class FxVol40TrendAnalyzer:
    """Evaluate FX Vol 40 trend alignment across multiple timeframes."""

    def __init__(self, min_required_confidence: float = 0.65):
        self.min_required_confidence = min_required_confidence
        self.strategy = FxVol40TrendStrategy()

    def evaluate(
        self, timeframe_frames: dict[str, pd.DataFrame]
    ) -> FxVol40TrendDecision:
        if not timeframe_frames:
            return FxVol40TrendDecision(
                "HOLD", 0.0, False, ("No timeframe data available",)
            )

        signals: dict[str, int] = {}
        reasons: list[str] = []

        for timeframe_name, frame in timeframe_frames.items():
            if frame is None or getattr(frame, "empty", False):
                continue
            signal_series = self.strategy.generate_signals(frame)
            if signal_series.empty:
                continue
            last_signal = int(signal_series.iloc[-1])
            signals[timeframe_name] = last_signal
            reasons.append(f"{timeframe_name}: {last_signal}")

        if not signals:
            return FxVol40TrendDecision(
                "HOLD", 0.0, False, ("No valid trend signals generated",)
            )

        buy_count = sum(1 for value in signals.values() if value > 0)
        sell_count = sum(1 for value in signals.values() if value < 0)
        total_count = len(signals)
        score = max(0.0, min(1.0, (max(buy_count, sell_count) / total_count) * 1.0))

        if buy_count >= 2 and buy_count > sell_count:
            direction = "BUY"
            confirmed = score >= self.min_required_confidence
            return FxVol40TrendDecision(
                direction,
                round(score, 3),
                confirmed,
                tuple(reasons),
            )

        if sell_count >= 2 and sell_count > buy_count:
            direction = "SELL"
            confirmed = score >= self.min_required_confidence
            return FxVol40TrendDecision(
                direction,
                round(score, 3),
                confirmed,
                tuple(reasons),
            )

        return FxVol40TrendDecision(
            "HOLD",
            round(score, 3),
            False,
            tuple(reasons),
        )


class FastProfitTradeGuard:
    """Controls the 6-hour rolling trade cap and fast profit exit rule."""

    def __init__(
        self,
        max_trades_per_6h: int = 10,
        profit_target_usd: float = 2.0,
        loss_limit_usd: float = 2.0,
    ):
        if max_trades_per_6h <= 0:
            raise ValueError("max_trades_per_6h must be positive")
        if profit_target_usd <= 0:
            raise ValueError("profit_target_usd must be positive")
        if loss_limit_usd <= 0:
            raise ValueError("loss_limit_usd must be positive")

        self.max_trades_per_6h = max_trades_per_6h
        self.profit_target_usd = float(profit_target_usd)
        self.loss_limit_usd = float(loss_limit_usd)

    def should_close(self, position_profit: float) -> bool:
        return float(position_profit) >= self.profit_target_usd

    def should_close_for_loss(self, position_profit: float) -> bool:
        return float(position_profit) <= -self.loss_limit_usd

    def is_trade_allowed(self, recent_trade_times: Iterable[datetime] | None) -> bool:
        if recent_trade_times is None:
            return True

        cutoff = datetime.now() - timedelta(hours=6)
        recent_trades = [
            trade_time for trade_time in recent_trade_times if trade_time >= cutoff
        ]
        return len(recent_trades) < self.max_trades_per_6h


__all__ = [
    "FxVol40TrendDecision",
    "FxVol40TrendStrategy",
    "FxVol40TrendAnalyzer",
    "FastProfitTradeGuard",
]
