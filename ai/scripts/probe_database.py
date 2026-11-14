"""Inspect Supabase schema/pgvector readiness without changing data."""

from __future__ import annotations

from pyrogravity_ai.database.connection import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseSettings,
    probe_database,
)


def main() -> int:
    try:
        result = probe_database(DatabaseSettings.from_environment())
    except (DatabaseConfigurationError, DatabaseConnectionError) as exc:
        print(exc)
        return 1

    for name in ("scientific", "ai", "app"):
        access = result.schemas.get(name)
        if access is None:
            print(f"{name}: missing")
        else:
            print(f"{name}: exists, USAGE={access.can_use}, CREATE={access.can_create}")
    print(f"pgvector: {'enabled in ' + result.vector_schema if result.vector_schema else 'missing'}")

    ai_access = result.schemas.get("ai")
    return 0 if ai_access and ai_access.can_use and ai_access.can_create and result.vector_schema else 1


if __name__ == "__main__":
    raise SystemExit(main())
