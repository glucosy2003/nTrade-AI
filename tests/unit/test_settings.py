import importlib
import os
import tempfile

import backend.core.settings as settings_module


def test_load_dotenv_file_overrides_existing_environment_values(monkeypatch):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write("SYNTHETIC_MT5_ACCOUNT_NUMBER=43065997\n")
        dotenv_path = handle.name

    try:
        monkeypatch.setenv("ENV_FILE", dotenv_path)
        monkeypatch.setenv("SYNTHETIC_MT5_ACCOUNT_NUMBER", "43038518")

        importlib.reload(settings_module)

        assert os.environ["SYNTHETIC_MT5_ACCOUNT_NUMBER"] == "43065997"
    finally:
        os.unlink(dotenv_path)


def test_default_symbol_is_synthetic_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DEFAULT_SYMBOL", raising=False)

    config = settings_module.Settings()

    assert config.default_symbol == "FX Vol 20"
