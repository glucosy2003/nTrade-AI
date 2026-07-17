"""Strategy wrapper that turns a trained gold model into backtest signals."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.ai.feature_engineering import GoldFeatureEngineer
from backend.ai.models import GoldRandomForestModel
from backend.strategies.base_strategy import BaseStrategy


class GoldModelPredictionStrategy(BaseStrategy):
    """Generate trading signals from a persisted gold classifier."""

    def __init__(self, model_path: str, horizon: int = 1) -> None:
        self.model_path = Path(model_path)
        self.horizon = horizon
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        self.model = GoldRandomForestModel().load(str(self.model_path))
        self.feature_engineer = GoldFeatureEngineer()

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return a signal series aligned to the input candles."""
        if data.empty:
            return pd.Series(dtype=int)

        feature_result = self.feature_engineer.engineer(data, include_target=False, dropna=True)
        feature_frame = feature_result.data
        if feature_frame.empty:
            return pd.Series(0, index=data.index, dtype=int)

        available_columns = [column for column in self.model.feature_columns if column in feature_frame.columns]
        if not available_columns:
            raise ValueError("The trained model does not share any feature columns with the input data")

        predictions = self.model.predict(feature_frame[available_columns])
        signals = pd.Series(0, index=data.index, dtype=int)
        signals.loc[feature_frame.index] = pd.Series(predictions, index=feature_frame.index).astype(int)
        return signals
