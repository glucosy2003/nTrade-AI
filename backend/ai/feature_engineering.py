"""Feature engineering utilities for gold and market-data analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backend.indicators.indicators import MomentumIndicators, MovingAverages, VolatilityIndicators


GOLD_FEATURE_COLUMNS = [
    "returns",
    "log_returns",
    "price_range",
    "candle_body",
    "upper_wick",
    "lower_wick",
    "body_to_range",
    "rolling_volatility_5",
    "rolling_volatility_10",
    "rolling_volatility_20",
    "volume_ma_5",
    "volume_ma_20",
    "volume_zscore_20",
    "relative_volume_20",
    "ema_5",
    "ema_10",
    "ema_20",
    "ema_50",
    "ema_gap_10_50",
    "ema_gap_5_20",
    "ema_slope_10",
    "ema_slope_50",
    "rsi_14",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "atr_14",
    "atr_percent",
    "bollinger_middle",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_bandwidth",
    "bollinger_percent_b",
    "trend_strength_10",
    "trend_strength_20",
    "volatility_ratio_20_50",
    "market_regime_score",
    "distance_from_ema_20",
    "distance_from_ema_50",
    "hour_of_day",
    "day_of_week",
]


@dataclass
class FeatureEngineeringResult:
    """Bundle of engineered features and optional targets."""

    data: pd.DataFrame
    feature_columns: list[str]
    target_column: Optional[str] = None


class GoldFeatureEngineer:
    """Build explainable features for gold price modeling."""

    def __init__(
        self,
        fast_ema: int = 5,
        medium_ema: int = 20,
        slow_ema: int = 50,
        rsi_period: int = 14,
        atr_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bollinger_period: int = 20,
    ) -> None:
        self.fast_ema = fast_ema
        self.medium_ema = medium_ema
        self.slow_ema = slow_ema
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bollinger_period = bollinger_period

    def engineer(
        self,
        data: pd.DataFrame,
        include_target: bool = False,
        target_horizon: int = 1,
        target_threshold: float = 0.0,
        dropna: bool = True,
    ) -> FeatureEngineeringResult:
        """Return a feature-rich frame ready for training or backtesting."""
        if data.empty:
            return FeatureEngineeringResult(data=data.copy(), feature_columns=[], target_column=None)

        required_columns = {"time", "open", "high", "low", "close", "volume"}
        missing = required_columns.difference(data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        engineered = data.copy()
        engineered["time"] = pd.to_datetime(engineered["time"], errors="coerce")
        if getattr(engineered["time"].dt, "tz", None) is not None:
            engineered["time"] = engineered["time"].dt.tz_convert(None)
        engineered = engineered.sort_values("time").reset_index(drop=True)

        for column in ["open", "high", "low", "close", "volume"]:
            engineered[column] = pd.to_numeric(engineered[column], errors="coerce")

        open_price = engineered["open"]
        high_price = engineered["high"]
        low_price = engineered["low"]
        close_price = engineered["close"]
        volume = engineered["volume"]

        price_range = high_price - low_price
        candle_body = close_price - open_price
        upper_wick = high_price - pd.concat([open_price, close_price], axis=1).max(axis=1)
        lower_wick = pd.concat([open_price, close_price], axis=1).min(axis=1) - low_price

        engineered["returns"] = close_price.pct_change()
        engineered["log_returns"] = np.log(close_price / close_price.shift(1))
        engineered["price_range"] = price_range
        engineered["candle_body"] = candle_body
        engineered["upper_wick"] = upper_wick
        engineered["lower_wick"] = lower_wick
        engineered["body_to_range"] = candle_body.div(price_range.replace(0, np.nan))

        engineered["rolling_volatility_5"] = engineered["returns"].rolling(window=5, min_periods=2).std()
        engineered["rolling_volatility_10"] = engineered["returns"].rolling(window=10, min_periods=2).std()
        engineered["rolling_volatility_20"] = engineered["returns"].rolling(window=20, min_periods=2).std()

        engineered["volume_ma_5"] = volume.rolling(window=5, min_periods=2).mean()
        engineered["volume_ma_20"] = volume.rolling(window=20, min_periods=2).mean()
        volume_std_20 = volume.rolling(window=20, min_periods=2).std(ddof=0)
        engineered["volume_zscore_20"] = (volume - engineered["volume_ma_20"]) / volume_std_20.replace(0, np.nan)
        engineered["relative_volume_20"] = volume / engineered["volume_ma_20"]

        engineered["ema_5"] = pd.Series(MovingAverages.ema(close_price.to_numpy(), self.fast_ema), index=engineered.index)
        engineered["ema_10"] = pd.Series(MovingAverages.ema(close_price.to_numpy(), 10), index=engineered.index)
        engineered["ema_20"] = pd.Series(MovingAverages.ema(close_price.to_numpy(), self.medium_ema), index=engineered.index)
        engineered["ema_50"] = pd.Series(MovingAverages.ema(close_price.to_numpy(), self.slow_ema), index=engineered.index)
        engineered["ema_gap_10_50"] = engineered["ema_10"] - engineered["ema_50"]
        engineered["ema_gap_5_20"] = engineered["ema_5"] - engineered["ema_20"]
        engineered["ema_slope_10"] = engineered["ema_10"].diff()
        engineered["ema_slope_50"] = engineered["ema_50"].diff()

        engineered["rsi_14"] = pd.Series(MomentumIndicators.rsi(close_price.to_numpy(), self.rsi_period), index=engineered.index)
        macd_line, macd_signal, macd_histogram = MomentumIndicators.macd(
            close_price.to_numpy(),
            fast=self.macd_fast,
            slow=self.macd_slow,
            signal=self.macd_signal,
        )
        engineered["macd_line"] = macd_line
        engineered["macd_signal"] = macd_signal
        engineered["macd_histogram"] = macd_histogram

        engineered["atr_14"] = pd.Series(
            VolatilityIndicators.atr(
                high_price.to_numpy(),
                low_price.to_numpy(),
                close_price.to_numpy(),
                self.atr_period,
            ),
            index=engineered.index,
        )
        engineered["atr_percent"] = engineered["atr_14"] / close_price.replace(0, np.nan)

        bollinger_upper, bollinger_middle, bollinger_lower = VolatilityIndicators.bollinger_bands(
            close_price.to_numpy(),
            period=self.bollinger_period,
            std_dev=2.0,
        )
        bollinger_upper_series = pd.Series(bollinger_upper, index=engineered.index)
        bollinger_middle_series = pd.Series(bollinger_middle, index=engineered.index)
        bollinger_lower_series = pd.Series(bollinger_lower, index=engineered.index)
        band_width = (bollinger_upper_series - bollinger_lower_series).replace(0, np.nan)
        engineered["bollinger_upper"] = bollinger_upper_series
        engineered["bollinger_middle"] = bollinger_middle_series
        engineered["bollinger_lower"] = bollinger_lower_series
        engineered["bollinger_bandwidth"] = band_width / bollinger_middle_series.replace(0, np.nan)
        engineered["bollinger_percent_b"] = (close_price - bollinger_lower_series) / band_width

        engineered["trend_strength_10"] = close_price.pct_change(10)
        engineered["trend_strength_20"] = close_price.pct_change(20)

        rolling_vol_20 = engineered["rolling_volatility_20"]
        rolling_vol_50 = engineered["rolling_volatility_20"].rolling(window=50, min_periods=5).mean()
        engineered["volatility_ratio_20_50"] = rolling_vol_20 / rolling_vol_50.replace(0, np.nan)
        engineered["market_regime_score"] = (
            engineered["ema_gap_10_50"].fillna(0)
            * engineered["trend_strength_20"].fillna(0)
            / engineered["volatility_ratio_20_50"].replace(0, np.nan)
        )
        engineered["distance_from_ema_20"] = (close_price - engineered["ema_20"]) / close_price.replace(0, np.nan)
        engineered["distance_from_ema_50"] = (close_price - engineered["ema_50"]) / close_price.replace(0, np.nan)

        engineered["hour_of_day"] = engineered["time"].dt.hour.astype("float64")
        engineered["day_of_week"] = engineered["time"].dt.dayofweek.astype("float64")

        target_column = None
        if include_target:
            future_close = close_price.shift(-target_horizon)
            future_return = future_close / close_price - 1.0
            target_column = "target"
            engineered[target_column] = np.where(
                future_return > target_threshold,
                1,
                np.where(future_return < -target_threshold, -1, 0),
            )

        engineered = engineered.replace([np.inf, -np.inf], np.nan)

        if dropna:
            required_features = GOLD_FEATURE_COLUMNS.copy()
            if include_target and target_column is not None:
                required_features.append(target_column)
            engineered = engineered.dropna(subset=required_features).reset_index(drop=True)

        return FeatureEngineeringResult(
            data=engineered,
            feature_columns=GOLD_FEATURE_COLUMNS.copy(),
            target_column=target_column,
        )


def engineer_price_features(data: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible entrypoint used by the backtester and model code."""
    result = GoldFeatureEngineer().engineer(data, include_target=False, dropna=False)
    return result.data
