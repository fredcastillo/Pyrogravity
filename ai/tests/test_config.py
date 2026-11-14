from pathlib import Path

import pytest


def test_environment_overrides_dotenv_without_exposing_secret(tmp_path: Path) -> None:
    from pyrogravity_ai.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "COHERE_API_KEY=file-secret\nCOHERE_MODEL=file-model\nCOHERE_TIMEOUT_SECONDS=4\n",
        encoding="utf-8",
    )

    settings = Settings.from_environment(
        env_file=env_file,
        environ={"COHERE_API_KEY": "process-secret", "COHERE_MODEL": "chosen-model"},
    )

    assert settings.api_key.get_secret_value() == "process-secret"
    assert settings.model == "chosen-model"
    assert settings.timeout_seconds == 4
    assert "process-secret" not in repr(settings)


def test_missing_api_key_is_rejected(tmp_path: Path) -> None:
    from pyrogravity_ai.config import ConfigurationError, Settings

    with pytest.raises(ConfigurationError, match="COHERE_API_KEY"):
        Settings.from_environment(env_file=tmp_path / "missing", environ={"COHERE_MODEL": "model"})


def test_nonpositive_timeout_is_rejected(tmp_path: Path) -> None:
    from pyrogravity_ai.config import ConfigurationError, Settings

    with pytest.raises(ConfigurationError, match="COHERE_TIMEOUT_SECONDS"):
        Settings.from_environment(
            env_file=tmp_path / "missing",
            environ={
                "COHERE_API_KEY": "test-secret",
                "COHERE_MODEL": "model",
                "COHERE_TIMEOUT_SECONDS": "0",
            },
        )
