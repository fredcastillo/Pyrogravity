from functools import lru_cache
from pathlib import Path
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = True
    pyrogravity_database_url: SecretStr | None = None
    scientific_data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    ai_model: str = "demo"
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 60
    max_experiments: int = 5
    max_points: int = 1000
    contract_version: str = "1.0"

    @model_validator(mode="after")
    def require_creds_when_real(self):
        if not self.demo_mode and not self.pyrogravity_database_url:
            raise ValueError("PYROGRAVITY_DATABASE_URL del lector es obligatorio si DEMO_MODE=false")
        return self
