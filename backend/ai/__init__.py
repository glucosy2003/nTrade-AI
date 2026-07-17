"""AI and model-related components for the ntrade_ai project."""

from __future__ import annotations

from typing import Any

__all__ = [
    "GOLD_FEATURE_COLUMNS",
    "FeatureEngineeringResult",
    "GoldFeatureEngineer",
    "engineer_price_features",
    "GoldModelTrainer",
    "TrainingResult",
    "GoldRandomForestModel",
]


def __getattr__(name: str) -> Any:
    if name in {"GOLD_FEATURE_COLUMNS", "FeatureEngineeringResult", "GoldFeatureEngineer", "engineer_price_features"}:
        from backend.ai.feature_engineering import (  # noqa: WPS433
            GOLD_FEATURE_COLUMNS,
            FeatureEngineeringResult,
            GoldFeatureEngineer,
            engineer_price_features,
        )

        exported = {
            "GOLD_FEATURE_COLUMNS": GOLD_FEATURE_COLUMNS,
            "FeatureEngineeringResult": FeatureEngineeringResult,
            "GoldFeatureEngineer": GoldFeatureEngineer,
            "engineer_price_features": engineer_price_features,
        }
        return exported[name]

    if name in {"GoldModelTrainer", "TrainingResult"}:
        from backend.ai.training import GoldModelTrainer, TrainingResult  # noqa: WPS433

        exported = {
            "GoldModelTrainer": GoldModelTrainer,
            "TrainingResult": TrainingResult,
        }
        return exported[name]

    if name == "GoldRandomForestModel":
        from backend.ai.models import GoldRandomForestModel  # noqa: WPS433

        return GoldRandomForestModel

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
