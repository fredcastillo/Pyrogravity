import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings


def test_ai_provider_is_off_by_default():
    settings = Settings()
    assert settings.ai_provider_enabled is False


def test_enabled_ai_requires_https_token_and_dedicated_reader_role():
    with pytest.raises(ValidationError):
        Settings(ai_provider_enabled=True)
    with pytest.raises(ValidationError, match="al menos 32"):
        Settings(
            ai_provider_enabled=True,
            ai_internal_url="https://ai.internal",
            ai_internal_token=SecretStr("short"),
            ai_citation_view_database_url=SecretStr("postgresql://ai_reader:secret@localhost/ai"),
        )
    with pytest.raises(ValidationError, match="rol lector dedicado"):
        Settings(
            ai_provider_enabled=True,
            ai_internal_url="https://ai.internal",
            ai_internal_token=SecretStr("t" * 32),
            ai_citation_view_database_url=SecretStr("postgresql://service_role:secret@localhost/ai"),
        )

    settings = Settings(
        ai_provider_enabled=True,
        ai_internal_url="https://ai.internal",
        ai_internal_token=SecretStr("t" * 32),
        ai_citation_view_database_url=SecretStr("postgresql://ai_reader:secret@localhost/ai"),
    )
    assert settings.ai_provider_enabled is True
