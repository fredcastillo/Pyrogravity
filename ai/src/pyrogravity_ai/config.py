"""Configuration for the AI package, loaded without mutating process environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, ValidationError


class ConfigurationError(ValueError):
    """A required AI setting is missing or invalid."""


class Settings(BaseModel):
    api_key: SecretStr
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_output_tokens: int = Field(default=512, ge=1, le=4096)
    max_retries: int = Field(default=1, ge=0, le=3)
    embed_model: str = Field(default="embed-v5.0-fast", min_length=1)
    embed_batch_size: int = Field(default=96, ge=1, le=96)

    @classmethod
    def from_environment(
        cls,
        *,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        path = env_file if env_file is not None else Path(__file__).resolve().parents[2] / ".env"
        values = {key: value for key, value in dotenv_values(path).items() if value is not None}
        values.update(os.environ if environ is None else environ)

        api_key = values.get("COHERE_API_KEY", "").strip()
        model = values.get("COHERE_MODEL", "").strip()
        if not api_key:
            raise ConfigurationError("COHERE_API_KEY is required")
        if not model:
            raise ConfigurationError("COHERE_MODEL is required")

        try:
            return cls(
                api_key=SecretStr(api_key),
                model=model,
                timeout_seconds=values.get("COHERE_TIMEOUT_SECONDS", "20"),
                max_output_tokens=values.get("COHERE_MAX_OUTPUT_TOKENS", "512"),
                max_retries=values.get("COHERE_MAX_RETRIES", "1"),
                embed_model=values.get("COHERE_EMBED_MODEL", "embed-v5.0-fast"),
                embed_batch_size=values.get("COHERE_EMBED_BATCH_SIZE", "96"),
            )
        except ValidationError as exc:
            names = {
                "timeout_seconds": "COHERE_TIMEOUT_SECONDS",
                "max_output_tokens": "COHERE_MAX_OUTPUT_TOKENS",
                "max_retries": "COHERE_MAX_RETRIES",
                "embed_model": "COHERE_EMBED_MODEL",
                "embed_batch_size": "COHERE_EMBED_BATCH_SIZE",
            }
            field = str(exc.errors()[0]["loc"][0])
            raise ConfigurationError(f"Invalid {names.get(field, field)}") from None
