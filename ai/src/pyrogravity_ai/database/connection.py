"""Read-only connectivity and capability check for the shared Supabase database."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psycopg
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, ValidationError
from psycopg.conninfo import conninfo_to_dict


class DatabaseConfigurationError(ValueError):
    """Database configuration is absent or invalid, without echoing credentials."""


class DatabaseConnectionError(RuntimeError):
    """The read-only database probe could not complete."""


class DatabaseSettings(BaseModel):
    url: SecretStr
    connect_timeout_seconds: int = Field(default=10, ge=1, le=30)

    @classmethod
    def from_environment(
        cls,
        *,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> DatabaseSettings:
        path = env_file if env_file is not None else Path(__file__).resolve().parents[3] / ".env"
        values = {key: value for key, value in dotenv_values(path).items() if value is not None}
        values.update(os.environ if environ is None else environ)
        url = values.get("AI_DATABASE_URL", "").strip()
        if not url:
            raise DatabaseConfigurationError("AI_DATABASE_URL is required")
        if not url.startswith(("postgresql://", "postgres://")):
            raise DatabaseConfigurationError("AI_DATABASE_URL must be a PostgreSQL URL")
        try:
            conninfo_to_dict(url)
            return cls(
                url=SecretStr(url),
                connect_timeout_seconds=values.get("AI_DB_CONNECT_TIMEOUT_SECONDS", "10"),
            )
        except (psycopg.Error, ValidationError, ValueError):
            raise DatabaseConfigurationError("Invalid AI_DATABASE_URL or AI_DB_CONNECT_TIMEOUT_SECONDS") from None


@dataclass(frozen=True)
class SchemaAccess:
    can_use: bool
    can_create: bool


@dataclass(frozen=True)
class DatabaseProbe:
    schemas: dict[str, SchemaAccess]
    vector_schema: str | None


def probe_database(
    settings: DatabaseSettings,
    *,
    connect: Callable[..., Any] = psycopg.connect,
) -> DatabaseProbe:
    """Inspect namespace permissions and pgvector in a read-only session."""
    url = settings.url.get_secret_value()
    try:
        parameters = conninfo_to_dict(url)
        sslmode = parameters.get("sslmode", "")
        if sslmode not in {"verify-ca", "verify-full"}:
            sslmode = "require"
        with connect(
            url,
            connect_timeout=settings.connect_timeout_seconds,
            sslmode=sslmode,
            options="-c default_transaction_read_only=on",
            prepare_threshold=None,
        ) as connection:
            rows = connection.execute(
                """SELECT nspname,
                          has_schema_privilege(current_user, oid, 'USAGE'),
                          has_schema_privilege(current_user, oid, 'CREATE')
                   FROM pg_namespace
                   WHERE nspname IN ('scientific', 'ai', 'app')"""
            ).fetchall()
            vector = connection.execute(
                "SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except psycopg.Error:
        raise DatabaseConnectionError("Supabase database probe failed") from None

    schemas = {name: SchemaAccess(bool(can_use), bool(can_create)) for name, can_use, can_create in rows}
    return DatabaseProbe(schemas=schemas, vector_schema=vector[0] if vector else None)
