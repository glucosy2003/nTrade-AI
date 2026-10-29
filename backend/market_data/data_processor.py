"""Utilities for cleaning and enriching market data for analysis and backtests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_price_data(data: pd.DataFrame, price_column: str = "close") -> pd.DataFrame:
    """Return a time-sorted frame with simple return-based features.

    The preprocessing step is intentionally lightweight for Phase 1 so it can be
    used both in local backtests and in later signal-generation pipeline stages.
    """

    if data.empty:
        return data.copy()

    if price_column not in data.columns:
        raise ValueError(f"Missing required column: {price_column}")

    prepared = data.copy()

    if "time" in prepared.columns:
        prepared["time"] = pd.to_datetime(prepared["time"])
        prepared = prepared.sort_values("time").reset_index(drop=True)

    price_series = pd.to_numeric(prepared[price_column], errors="coerce")
    prepared["returns"] = price_series.pct_change()
    prepared["log_returns"] = np.log(price_series / price_series.shift(1))

    return prepared
