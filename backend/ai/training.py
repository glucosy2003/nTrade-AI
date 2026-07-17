"""Training utilities for the gold model pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from sklearn.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score
except ImportError:  # pragma: no cover - exercised only in lightweight environments
    accuracy_score = None
    classification_report = None
    f1_score = None
    precision_score = None
    recall_score = None

from backend.ai.models import GoldRandomForestModel


logger = logging.getLogger(__name__)


@dataclass
class TrainingSplit:
    """Holds a deterministic train/test split."""

    X_train: pd.DataFrame
    X_test: pd.DataFrame
    y_train: np.ndarray
    y_test: np.ndarray


@dataclass
class TrainingResult:
    """Summary of a training run."""

    model_path: Path
    metrics_path: Path
    feature_columns: list[str]
    train_rows: int
    test_rows: int
    metrics: dict[str, object]


class GoldModelTrainer:
    """Train and evaluate the gold Random Forest baseline."""

    def __init__(
        self,
        model: Optional[GoldRandomForestModel] = None,
        model_output_dir: str | Path = "models",
        metrics_output_dir: str | Path = "models/metrics",
    ) -> None:
        self.model = model or GoldRandomForestModel()
        self.model_output_dir = Path(model_output_dir)
        self.metrics_output_dir = Path(metrics_output_dir)

    def train_from_dataframe(
        self,
        data: pd.DataFrame,
        *,
        horizon: int = 1,
        test_ratio: float = 0.2,
        model_name: str = "gold_random_forest.pkl",
    ) -> TrainingResult:
        """Train a model from stored or exported market data."""
        features, labels = self.model.prepare_training_data(data, horizon=horizon)
        split = self._time_based_split(features, labels, test_ratio=test_ratio)

        self._fit_model(split.X_train, split.y_train)
        train_predictions = self.model.predict(split.X_train)
        test_predictions = self.model.predict(split.X_test)

        metrics = self._calculate_metrics(split.y_train, train_predictions, split.y_test, test_predictions)
        model_path = self._save_model(model_name)
        metrics_path = self._save_metrics(model_path.stem, metrics)

        return TrainingResult(
            model_path=model_path,
            metrics_path=metrics_path,
            feature_columns=self.model.feature_columns.copy(),
            train_rows=len(split.X_train),
            test_rows=len(split.X_test),
            metrics=metrics,
        )

    def _fit_model(self, X_train: pd.DataFrame, y_train: np.ndarray) -> None:
        """Fit the underlying model."""
        if len(np.unique(y_train)) < 2:
            raise ValueError("Training data must contain at least two classes")
        self.model.fit(X_train, y_train)

    @staticmethod
    def _time_based_split(
        features: pd.DataFrame,
        labels: np.ndarray,
        test_ratio: float,
    ) -> TrainingSplit:
        """Split without shuffling to preserve temporal ordering."""
        if not 0 < test_ratio < 1:
            raise ValueError("test_ratio must be between 0 and 1")

        row_count = len(features)
        if row_count < 10:
            raise ValueError("Not enough data to train a model")

        split_index = max(int(row_count * (1 - test_ratio)), 1)
        if split_index >= row_count:
            split_index = row_count - 1

        X_train = features.iloc[:split_index].copy()
        X_test = features.iloc[split_index:].copy()
        y_train = labels[:split_index]
        y_test = labels[split_index:]

        if len(X_test) == 0:
            raise ValueError("Test split is empty")

        return TrainingSplit(X_train=X_train, X_test=X_test, y_train=y_train, y_test=y_test)

    def _calculate_metrics(
        self,
        y_train: np.ndarray,
        train_predictions: np.ndarray,
        y_test: np.ndarray,
        test_predictions: np.ndarray,
    ) -> dict[str, object]:
        """Calculate a compact, explainable metrics summary."""
        metrics: dict[str, object] = {
            "train_accuracy": float(accuracy_score(y_train, train_predictions)) if accuracy_score else None,
            "test_accuracy": float(accuracy_score(y_test, test_predictions)) if accuracy_score else None,
            "test_precision_macro": float(precision_score(y_test, test_predictions, average="macro", zero_division=0)) if precision_score else None,
            "test_recall_macro": float(recall_score(y_test, test_predictions, average="macro", zero_division=0)) if recall_score else None,
            "test_f1_macro": float(f1_score(y_test, test_predictions, average="macro", zero_division=0)) if f1_score else None,
            "train_distribution": self._class_distribution(y_train),
            "test_distribution": self._class_distribution(y_test),
        }

        if classification_report is not None:
            metrics["classification_report"] = classification_report(
                y_test,
                test_predictions,
                zero_division=0,
                output_dict=True,
            )

        return metrics

    @staticmethod
    def _class_distribution(values: np.ndarray) -> dict[str, int]:
        """Return label counts as a string-keyed dictionary."""
        unique, counts = np.unique(values, return_counts=True)
        return {str(label): int(count) for label, count in zip(unique, counts)}

    def _save_model(self, model_name: str) -> Path:
        """Persist the trained model package to disk."""
        self.model_output_dir.mkdir(parents=True, exist_ok=True)
        model_path = self.model_output_dir / model_name
        self.model.save(str(model_path))
        return model_path

    def _save_metrics(self, model_stem: str, metrics: dict[str, object]) -> Path:
        """Save training metrics as JSON."""
        self.metrics_output_dir.mkdir(parents=True, exist_ok=True)
        metrics_path = self.metrics_output_dir / f"{model_stem}_metrics.json"
        payload = {
            "created_at": datetime.utcnow().isoformat(),
            "model_name": model_stem,
            "metrics": metrics,
            "feature_columns": self.model.feature_columns,
        }
        with open(metrics_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        return metrics_path
