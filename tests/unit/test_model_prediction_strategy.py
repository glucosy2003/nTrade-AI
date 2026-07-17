import pandas as pd

from backend.ai.models import GoldRandomForestModel
from backend.strategies.model_prediction_strategy import GoldModelPredictionStrategy


def build_training_frame() -> pd.DataFrame:
    rows = []
    for i in range(80):
        if i < 25:
            close = 100 + i * 0.5
        elif i < 50:
            close = 112.5 - (i - 25) * 0.6
        else:
            close = 97.5 + (i - 50) * 0.7

        rows.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(i, unit="D"),
                "open": close - 0.3,
                "high": close + 0.6,
                "low": close - 0.6,
                "close": close,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_model_prediction_strategy_generates_signals(tmp_path):
    data = build_training_frame()
    model = GoldRandomForestModel(random_state=42)
    features, labels = model.prepare_training_data(data)
    model.fit(features, labels)

    model_path = tmp_path / "gold_model.pkl"
    model.save(str(model_path))

    strategy = GoldModelPredictionStrategy(model_path=str(model_path), confidence_threshold=0.6)
    signals = strategy.generate_signals(data)

    assert len(signals) == len(data)
    assert set(signals.unique()).issubset({-1, 0, 1})
