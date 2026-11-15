from functools import lru_cache
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = True
    supabase_url: str | None = None
    supabase_service_key: SecretStr | None = None
    ai_model: str = "demo"
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 60
    max_experiments: int = 5
    max_points: int = 1000
    contract_version: str = "1.0"

    @model_validator(mode="after")
    def require_creds_when_real(self):
        if not self.demo_mode and (not self.supabase_url or not self.supabase_service_key):
            raise ValueError("supabase_url y supabase_service_key son obligatorios si demo_mode=false")
        return self
