"""Simple machine-learning utilities for the gold strategy pipeline."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:  # pragma: no cover - exercised in lightweight environments
    RandomForestClassifier = None

from backend.ai.feature_engineering import GOLD_FEATURE_COLUMNS, GoldFeatureEngineer


class GoldRandomForestModel:
    """A lightweight Random Forest classifier for price-move prediction.

    The implementation is deliberately simple and persistent-friendly so it can
    serve as a Phase 2 baseline before moving to richer feature engineering and
    a larger model pipeline.
    """

    def __init__(self, random_state: int = 42, model_path: str | None = None) -> None:
        self.random_state = random_state
        self.model_path = Path(model_path) if model_path else None
        self.feature_engineer = GoldFeatureEngineer()
        self.feature_columns = GOLD_FEATURE_COLUMNS.copy()
        if RandomForestClassifier is not None:
            self.model = RandomForestClassifier(
                n_estimators=200,
                max_depth=4,
                random_state=random_state,
                class_weight="balanced_subsample",
            )
        else:
            self.model = {"fallback": True, "random_state": random_state}

    def prepare_training_data(self, data: pd.DataFrame, horizon: int = 1) -> Tuple[pd.DataFrame, np.ndarray]:
        """Build X/y pairs from price data.

        The target is the direction of the next candle close movement over the
        chosen horizon; the model then learns to classify a future up/down/hold.
        """
        result = self.feature_engineer.engineer(
            data,
            include_target=True,
            target_horizon=horizon,
            target_threshold=0.0,
            dropna=True,
        )
        engineered = result.data
        self.feature_columns = result.feature_columns

        if len(engineered) < horizon + 2:
            raise ValueError("Not enough data points to build a training target")

        target_column = result.target_column or "target"
        available_columns = [column for column in self.feature_columns if column in engineered.columns]
        if not available_columns:
            raise ValueError("No feature columns were produced by the feature engineer")

        features = engineered[available_columns].copy()
        labels = engineered[target_column].to_numpy(dtype=int)
        return features, labels

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "GoldRandomForestModel":
        """Train the model on the provided feature matrix."""
        if RandomForestClassifier is not None:
            self.model.fit(X, y)
        else:
            self.model["fit_samples"] = len(X)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict a signal series from a feature matrix."""
        if RandomForestClassifier is not None:
            return self.model.predict(X)

        ema_gap = X["ema_gap"].to_numpy() if "ema_gap" in X.columns else np.zeros(len(X))
        signal = np.where(ema_gap > 0, 1, np.where(ema_gap < 0, -1, 0))
        return signal.astype(int)

    def save(self, path: str) -> None:
        """Persist the trained model to disk."""
        with open(path, "wb") as handle:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_columns": self.feature_columns,
                    "random_state": self.random_state,
                },
                handle,
            )

    def load(self, path: str) -> "GoldRandomForestModel":
        """Load a persisted model from disk."""
        with open(path, "rb") as handle:
            payload = pickle.load(handle)

        if isinstance(payload, dict) and "model" in payload:
            self.model = payload["model"]
            self.feature_columns = payload.get("feature_columns", self.feature_columns)
            self.random_state = payload.get("random_state", self.random_state)
        else:
            self.model = payload

        self.model_path = Path(path)
        return self
