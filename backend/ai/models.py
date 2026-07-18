"""Machine-learning utilities for the gold strategy pipeline."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

try:
    from xgboost import XGBClassifier
except ImportError:  # pragma: no cover - exercised in lightweight environments
    XGBClassifier = None

try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:  # pragma: no cover - exercised in lightweight environments
    RandomForestClassifier = None

from backend.ai.feature_engineering import GOLD_FEATURE_COLUMNS, GoldFeatureEngineer


class GoldRandomForestModel:
    """A tree-based classifier for price-move prediction.

    The class keeps the historical public name for compatibility, but the
    default implementation now prefers XGBoost and falls back to Random Forest
    or a deterministic rule-based signal if the optional libraries are missing.
    """

    def __init__(self, random_state: int = 42, model_path: str | None = None) -> None:
        self.random_state = random_state
        self.model_path = Path(model_path) if model_path else None
        self.feature_engineer = GoldFeatureEngineer()
        self.feature_columns = GOLD_FEATURE_COLUMNS.copy()
        self.class_labels: list[int] = []
        self._label_to_index: dict[int, int] = {}
        self._index_to_label: dict[int, int] = {}
        self.constant_label: int | None = None

        if XGBClassifier is not None:
            self.model = XGBClassifier(
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.0,
                reg_alpha=0.0,
                min_child_weight=1,
                objective="multi:softprob",
                eval_metric="mlogloss",
                tree_method="hist",
                random_state=random_state,
                n_jobs=1,
            )
            self.model_family = "xgboost"
        elif RandomForestClassifier is not None:
            self.model = RandomForestClassifier(
                n_estimators=200,
                max_depth=4,
                random_state=random_state,
                class_weight="balanced_subsample",
            )
            self.model_family = "random_forest"
        else:
            self.model = {"fallback": True, "random_state": random_state}
            self.model_family = "rule_based"

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
        self.class_labels = sorted(int(label) for label in np.unique(y))
        if len(self.class_labels) == 0:
            raise ValueError("Training data must contain at least one class")
        if len(self.class_labels) == 1:
            self.constant_label = self.class_labels[0]
            self._label_to_index = {self.constant_label: 0}
            self._index_to_label = {0: self.constant_label}
            self.model_family = "constant"
            return self

        self._label_to_index = {label: index for index, label in enumerate(self.class_labels)}
        self._index_to_label = {index: label for label, index in self._label_to_index.items()}
        self.constant_label = None

        encoded_y = np.array([self._label_to_index[int(label)] for label in y], dtype=int)

        if XGBClassifier is not None or RandomForestClassifier is not None:
            self.model.fit(X, encoded_y)
        else:
            self.model["fit_samples"] = len(X)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict a signal series from a feature matrix."""
        if self.constant_label is not None:
            return np.full(len(X), self.constant_label, dtype=int)

        if XGBClassifier is not None or RandomForestClassifier is not None:
            encoded_predictions = self.model.predict(X)
            return self._decode_labels(encoded_predictions)

        ema_gap = X["ema_gap_10_50"].to_numpy() if "ema_gap_10_50" in X.columns else np.zeros(len(X))
        signal = np.where(ema_gap > 0, 1, np.where(ema_gap < 0, -1, 0))
        return signal.astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray | None:
        """Return class probabilities when the underlying model supports them."""
        if self.constant_label is not None:
            probabilities = np.zeros((len(X), max(len(self.class_labels), 1)), dtype=float)
            if probabilities.size > 0:
                probabilities[:, 0] = 1.0
            return probabilities

        if XGBClassifier is not None or RandomForestClassifier is not None:
            probabilities = self.model.predict_proba(X)
            probabilities = np.asarray(probabilities)
            if probabilities.ndim == 1:
                probabilities = np.column_stack([1.0 - probabilities, probabilities])
            return probabilities
        return None

    def predict_signal(self, X: pd.DataFrame, confidence_threshold: float = 0.55) -> np.ndarray:
        """Predict signals and suppress low-confidence trades."""
        predictions = self.predict(X)
        probabilities = self.predict_proba(X)
        if probabilities is None or len(probabilities) == 0:
            return predictions.astype(int)

        best_probabilities = probabilities.max(axis=1)
        filtered = np.where(best_probabilities >= confidence_threshold, predictions, 0)
        return filtered.astype(int)

    def save(self, path: str) -> None:
        """Persist the trained model to disk."""
        with open(path, "wb") as handle:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_columns": self.feature_columns,
                    "random_state": self.random_state,
                    "class_labels": self.class_labels,
                    "model_family": self.model_family,
                    "constant_label": self.constant_label,
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
            self.class_labels = [int(label) for label in payload.get("class_labels", self.class_labels)]
            self.model_family = payload.get("model_family", getattr(self, "model_family", "unknown"))
            constant_label = payload.get("constant_label")
            self.constant_label = int(constant_label) if constant_label is not None else None
        else:
            self.model = payload

        if not self.class_labels and hasattr(self.model, "classes_"):
            self.class_labels = [int(label) for label in getattr(self.model, "classes_", [])]
        if self.constant_label is not None and not self.class_labels:
            self.class_labels = [self.constant_label]

        self._label_to_index = {label: index for index, label in enumerate(self.class_labels)}
        self._index_to_label = {index: label for label, index in self._label_to_index.items()}
        self.model_path = Path(path)
        return self

    def _decode_labels(self, encoded_labels: np.ndarray) -> np.ndarray:
        """Map encoded class indices back to signal labels."""
        if not self.class_labels:
            return np.asarray(encoded_labels, dtype=int)

        decoded = []
        for encoded_label in np.asarray(encoded_labels, dtype=int):
            decoded.append(self._index_to_label.get(int(encoded_label), int(encoded_label)))
        return np.asarray(decoded, dtype=int)


GoldXGBoostModel = GoldRandomForestModel
