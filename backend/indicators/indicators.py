"""
Technical indicators framework for price analysis.

Provides a collection of indicators used in the analysis engine:
- Trend: Moving Averages, MACD
- Momentum: RSI, Stochastic  
- Volatility: ATR, Bollinger Bands
- Price Action: Support/Resistance, Trends

All indicators accept pandas Series/DataFrame and return numpy arrays.
"""

import numpy as np
import pandas as pd
from typing import Union, Tuple


IndicatorInput = Union[pd.Series, np.ndarray]


class MovingAverages:
    """Simple and Exponential Moving Averages."""

    @staticmethod
    def sma(data: IndicatorInput, period: int) -> np.ndarray:
        """
        Simple Moving Average.
        
        Args:
            data: Price data (series or array)
            period: Number of periods for calculation
            
        Returns:
            Array of SMA values
        """
        if period <= 0:
            raise ValueError("period must be positive")

        if isinstance(data, pd.Series):
            series = data.copy()
        else:
            series = pd.Series(data)

        if len(series) == 0:
            return np.array([], dtype=float)

        return series.rolling(window=period, min_periods=period).mean().to_numpy()

    @staticmethod
    def ema(data: IndicatorInput, period: int) -> np.ndarray:
        """
        Exponential Moving Average.
        
        Args:
            data: Price data
            period: Number of periods
            
        Returns:
            Array of EMA values
        """
        if period <= 0:
            raise ValueError("period must be positive")

        if isinstance(data, pd.Series):
            data = data.values

        if len(data) == 0:
            return np.array([], dtype=float)

        ema = np.zeros(len(data))
        ema[0] = data[0]
        multiplier = 2 / (period + 1)
        
        for i in range(1, len(data)):
            ema[i] = data[i] * multiplier + ema[i - 1] * (1 - multiplier)
        
        return ema

    @staticmethod
    def ma_crossover(fast_ma: np.ndarray, slow_ma: np.ndarray) -> np.ndarray:
        """
        Identify moving average crossovers.
        
        Args:
            fast_ma: Faster moving average
            slow_ma: Slower moving average
            
        Returns:
            Array: 1 = bullish cross, -1 = bearish cross, 0 = no cross
        """
        cross = np.zeros(len(fast_ma))
        
        for i in range(1, len(fast_ma)):
            # Bullish crossover (fast crosses above slow)
            if fast_ma[i - 1] <= slow_ma[i - 1] and fast_ma[i] > slow_ma[i]:
                cross[i] = 1
            # Bearish crossover (fast crosses below slow)
            elif fast_ma[i - 1] >= slow_ma[i - 1] and fast_ma[i] < slow_ma[i]:
                cross[i] = -1
        
        return cross


class MomentumIndicators:
    """Momentum oscillators."""

    @staticmethod
    def rsi(data: IndicatorInput, period: int = 14) -> np.ndarray:
        """
        Relative Strength Index.

        Args:
            data: Price data (typically close prices)
            period: Lookback period (default 14)

        Returns:
            Array of RSI values (0-100)
        """
        if isinstance(data, pd.Series):
            series = data.copy()
        else:
            series = pd.Series(data)

        if len(series) == 0:
            return np.array([], dtype=float)

        if period <= 0:
            raise ValueError("period must be positive")

        delta = series.diff()
        gains = delta.clip(lower=0)
        losses = (-delta.clip(upper=0))

        avg_gain = gains.rolling(window=period, min_periods=period).mean()
        avg_loss = losses.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)

        return rsi.to_numpy()

    @staticmethod
    def macd(
        data: IndicatorInput,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        MACD (Moving Average Convergence Divergence).
        
        Args:
            data: Price data
            fast: Fast EMA period (default 12)
            slow: Slow EMA period (default 26)
            signal: Signal line EMA period (default 9)
            
        Returns:
            Tuple of (MACD line, Signal line, Histogram)
        """
        ema_fast = MovingAverages.ema(data, fast)
        ema_slow = MovingAverages.ema(data, slow)
        
        macd_line = ema_fast - ema_slow
        signal_line = MovingAverages.ema(macd_line, signal)
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram


class VolatilityIndicators:
    """Volatility measurement indicators."""

    @staticmethod
    def atr(
        high: IndicatorInput,
        low: IndicatorInput,
        close: IndicatorInput,
        period: int = 14
    ) -> np.ndarray:
        """
        Average True Range - measures volatility.
        
        Args:
            high: High prices
            low: Low prices
            close: Close prices
            period: Lookback period (default 14)
            
        Returns:
            Array of ATR values
        """
        if period <= 0:
            raise ValueError("period must be positive")

        if isinstance(high, pd.Series):
            high = high.values
        if isinstance(low, pd.Series):
            low = low.values
        if isinstance(close, pd.Series):
            close = close.values

        if len(high) == 0:
            return np.array([], dtype=float)

        tr = np.zeros(len(high), dtype=float)
        tr[0] = high[0] - low[0]

        for i in range(1, len(high)):
            tr1 = high[i] - low[i]
            tr2 = abs(high[i] - close[i - 1])
            tr3 = abs(low[i] - close[i - 1])
            tr[i] = max(tr1, tr2, tr3)

        atr = np.zeros(len(tr), dtype=float)
        atr[0] = tr[0]

        for i in range(1, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    @staticmethod
    def bollinger_bands(
        data: IndicatorInput,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Bollinger Bands - volatility bands around SMA.
        
        Args:
            data: Price data
            period: SMA period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)
            
        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        if period <= 0:
            raise ValueError("period must be positive")

        if isinstance(data, pd.Series):
            series = data.copy()
        else:
            series = pd.Series(data)

        if len(series) == 0:
            empty = np.array([], dtype=float)
            return empty, empty, empty

        rolling = series.rolling(window=period, min_periods=period)
        middle = rolling.mean().to_numpy()
        std = rolling.std(ddof=0).to_numpy()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)

        return upper, middle, lower


class VolumeIndicators:
    """Volume-based indicators."""

    @staticmethod
    def obv(close: IndicatorInput, volume: IndicatorInput) -> np.ndarray:
        """
        On-Balance Volume - cumulative volume indicator.
        
        Args:
            close: Close prices
            volume: Volume data
            
        Returns:
            Array of OBV values
        """
        if isinstance(close, pd.Series):
            close = close.values
        if isinstance(volume, pd.Series):
            volume = volume.values
        
        obv = np.zeros(len(close))
        obv[0] = volume[0]
        
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]
        
        return obv


class TrendIndicators:
    """Trend identification indicators."""

    @staticmethod
    def trend_direction(high: IndicatorInput, low: IndicatorInput, period: int = 20) -> np.ndarray:
        """
        Simple trend direction based on recent highs/lows.
        
        Args:
            high: High prices
            low: Low prices
            period: Lookback period
            
        Returns:
            Array: 1 = uptrend, -1 = downtrend, 0 = sideways
        """
        if isinstance(high, pd.Series):
            high = high.values
        if isinstance(low, pd.Series):
            low = low.values
        
        trend = np.zeros(len(high))
        
        for i in range(period, len(high)):
            highest = np.max(high[i - period:i])
            lowest = np.min(low[i - period:i])
            
            if highest > high[i - 1]:
                trend[i] = 1  # Uptrend
            elif lowest < low[i - 1]:
                trend[i] = -1  # Downtrend
            else:
                trend[i] = 0  # Sideways
        
        return trend

    @staticmethod
    def support_resistance(data: IndicatorInput, period: int = 20) -> Tuple[float, float]:
        """
        Calculate support and resistance levels.
        
        Args:
            data: Price data (typically close or average)
            period: Lookback period
            
        Returns:
            Tuple of (support_level, resistance_level)
        """
        if isinstance(data, pd.Series):
            data = data.values
        
        recent_data = data[-period:]
        support = np.min(recent_data)
        resistance = np.max(recent_data)
        
        return support, resistance
