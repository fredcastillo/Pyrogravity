from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.conninfo import conninfo_to_dict


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = True
    pyrogravity_database_url: SecretStr | None = None
    scientific_data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    ai_model: str = "demo"
    ai_provider_enabled: bool = False
    ai_internal_url: AnyHttpUrl | None = None
    ai_internal_token: SecretStr | None = None
    ai_citation_view_database_url: SecretStr | None = None
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 60
    max_experiments: int = 5
    max_points: int = 1000

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins or "*" in origins:
            raise ValueError("CORS_ORIGINS debe listar orígenes explícitos; no se permite '*'.")
        return ",".join(origins)

    @model_validator(mode="after")
    def require_creds_when_real(self):
        if not self.demo_mode and not self.pyrogravity_database_url:
            raise ValueError("PYROGRAVITY_DATABASE_URL del lector es obligatorio si DEMO_MODE=false")
        if self.ai_provider_enabled:
            if not self.pyrogravity_database_url:
                raise ValueError("AI_PROVIDER_ENABLED requiere PYROGRAVITY_DATABASE_URL del lector científico")
            if not self.ai_internal_url or not self.ai_internal_token or not self.ai_citation_view_database_url:
                raise ValueError("AI_PROVIDER_ENABLED requiere URL/token internos y DSN del lector de citation_passages")
            if self.ai_internal_url.scheme != "https":
                raise ValueError("AI_INTERNAL_URL debe usar HTTPS")
            if len(self.ai_internal_token.get_secret_value()) < 32:
                raise ValueError("AI_INTERNAL_TOKEN debe tener al menos 32 caracteres")
            citation_dsn = self.ai_citation_view_database_url.get_secret_value()
            if not citation_dsn:
                raise ValueError("AI_CITATION_VIEW_DATABASE_URL no puede estar vacío")
            try:
                reader_user = conninfo_to_dict(citation_dsn).get("user", "")
            except Exception as error:
                raise ValueError("AI_CITATION_VIEW_DATABASE_URL no es un DSN válido") from error
            if reader_user.lower() in {"anon", "authenticated", "service_role", "postgres"}:
                raise ValueError("AI_CITATION_VIEW_DATABASE_URL debe usar un rol lector dedicado")
        return self
