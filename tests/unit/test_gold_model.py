import pandas as pd

from backend.ai.models import GoldRandomForestModel


def build_training_frame() -> pd.DataFrame:
    rows = []
    for i in range(60):
        close = 100 + (i * 0.6 if i < 30 else (30 * 0.6) - ((i - 30) * 0.8))
        rows.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.to_timedelta(i, unit="D"),
                "open": close - 0.2,
                "high": close + 0.6,
                "low": close - 0.6,
                "close": close,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_gold_model_can_fit_and_predict():
    data = build_training_frame()
    model = GoldRandomForestModel(random_state=42)

    X, y = model.prepare_training_data(data)
    model.fit(X, y)
    predictions = model.predict(X)

    assert len(predictions) == len(y)
    assert set(predictions).issubset({-1, 0, 1})


def test_gold_model_can_save_and_load(tmp_path):
    data = build_training_frame()
    model = GoldRandomForestModel(random_state=42)

    X, y = model.prepare_training_data(data)
    model.fit(X, y)

    model_path = tmp_path / "gold_model.pkl"
    model.save(str(model_path))

    restored = GoldRandomForestModel().load(str(model_path))
    restored_predictions = restored.predict(X)

    assert model_path.exists()
    assert len(restored_predictions) == len(y)
    assert set(restored_predictions).issubset({-1, 0, 1})
