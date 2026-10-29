"""Validation helpers for market-data ingestion and storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


REQUIRED_PRICE_COLUMNS = {"time", "open", "high", "low", "close"}
OPTIONAL_PRICE_COLUMNS = {"volume", "symbol", "timeframe"}


@dataclass
class PriceValidationResult:
    """Summary of a market-data validation pass."""

    is_valid: bool
    input_rows: int = 0
    cleaned_rows: int = 0
    duplicate_rows: int = 0
    invalid_rows: int = 0
    missing_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MarketDataValidator:
    """Clean and validate price data before it is stored."""

    @staticmethod
    def validate_price_frame(
        data: pd.DataFrame,
        symbol: Optional[str] = None,
        timeframe: Optional[int | str] = None,
    ) -> PriceValidationResult:
        """Return a validation summary for a price DataFrame."""
        if data is None:
            return PriceValidationResult(
                is_valid=False,
                input_rows=0,
                cleaned_rows=0,
                duplicate_rows=0,
                invalid_rows=0,
                missing_columns=sorted(REQUIRED_PRICE_COLUMNS),
                warnings=["No price data provided"],
            )

        missing_columns = sorted(REQUIRED_PRICE_COLUMNS - set(data.columns))
        if missing_columns:
            return PriceValidationResult(
                is_valid=False,
                input_rows=len(data),
                cleaned_rows=0,
                duplicate_rows=0,
                invalid_rows=len(data),
                missing_columns=missing_columns,
                warnings=[f"Missing columns: {', '.join(missing_columns)}"],
            )

        cleaned = MarketDataValidator.clean_price_frame(data, symbol=symbol, timeframe=timeframe)
        invalid_rows = max(len(data) - len(cleaned), 0)
        duplicate_rows = 0

        if "time" in data.columns:
            duplicate_rows = int(data["time"].duplicated().sum())

        warnings: list[str] = []
        if missing_columns:
            warnings.append(f"Missing columns: {', '.join(missing_columns)}")
        if duplicate_rows:
            warnings.append(f"Removed {duplicate_rows} duplicate timestamps")
        if invalid_rows and not missing_columns:
            warnings.append(f"Removed {invalid_rows} invalid or incomplete rows")

        return PriceValidationResult(
            is_valid=bool(len(cleaned) > 0 and not missing_columns),
            input_rows=len(data),
            cleaned_rows=len(cleaned),
            duplicate_rows=duplicate_rows,
            invalid_rows=invalid_rows,
            missing_columns=missing_columns,
            warnings=warnings,
        )

    @staticmethod
    def clean_price_frame(
        data: pd.DataFrame,
        symbol: Optional[str] = None,
        timeframe: Optional[int | str] = None,
    ) -> pd.DataFrame:
        """Return a normalized, deduplicated candle DataFrame."""
        if data is None or data.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "symbol", "timeframe"])

        frame = data.copy()

        missing_columns = REQUIRED_PRICE_COLUMNS - set(frame.columns)
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

        frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
        if getattr(frame["time"].dt, "tz", None) is not None:
            frame["time"] = frame["time"].dt.tz_convert(None)

        numeric_columns = ["open", "high", "low", "close", "volume"]
        for column in numeric_columns:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            elif column == "volume":
                frame[column] = 0.0

        if "volume" not in frame.columns:
            frame["volume"] = 0.0

        frame = frame.dropna(subset=["time", "open", "high", "low", "close"])
        frame = frame.loc[frame["high"] >= frame["low"]]
        frame = frame.loc[frame["high"] >= frame[["open", "close"]].max(axis=1)]
        frame = frame.loc[frame["low"] <= frame[["open", "close"]].min(axis=1)]

        frame = frame.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

        if symbol is not None:
            frame["symbol"] = symbol
        elif "symbol" not in frame.columns:
            frame["symbol"] = ""

        if timeframe is not None:
            frame["timeframe"] = timeframe
        elif "timeframe" not in frame.columns:
            frame["timeframe"] = ""

        ordered_columns = ["time", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
        existing_columns = [column for column in ordered_columns if column in frame.columns]
        return frame[existing_columns].copy()
