from pathlib import Path

import pytest
from psycopg import OperationalError


class FakeConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query: str):
        self.queries.append(query)
        return self

    def fetchall(self):
        return [
            ("ai", True, True),
            ("scientific", True, False),
            ("app", False, False),
        ]

    def fetchone(self):
        return ("extensions",)


def test_probe_checks_isolated_schemas_and_vector_without_writes() -> None:
    from pyrogravity_ai.database.connection import DatabaseSettings, probe_database

    connection = FakeConnection()
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return connection

    settings = DatabaseSettings.from_environment(
        env_file=Path("missing"),
        environ={"AI_DATABASE_URL": "postgresql://test:secret@localhost/postgres"},
    )
    result = probe_database(settings, connect=connect)

    assert calls[0][1]["sslmode"] == "require"
    assert calls[0][1]["options"] == "-c default_transaction_read_only=on"
    assert calls[0][1]["prepare_threshold"] is None
    assert result.schemas["ai"].can_create is True
    assert result.schemas["scientific"].can_use is True
    assert result.schemas["app"].can_use is False
    assert result.vector_schema == "extensions"
    assert len(connection.queries) == 2
    assert all(query.lstrip().lower().startswith("select") for query in connection.queries)


def test_missing_url_is_sanitized(tmp_path: Path) -> None:
    from pyrogravity_ai.database.connection import DatabaseConfigurationError, DatabaseSettings

    with pytest.raises(DatabaseConfigurationError, match="AI_DATABASE_URL"):
        DatabaseSettings.from_environment(env_file=tmp_path / "missing", environ={})


def test_connection_failure_does_not_reveal_url() -> None:
    from pyrogravity_ai.database.connection import (
        DatabaseConnectionError,
        DatabaseSettings,
        probe_database,
    )

    secret = "private-password"
    settings = DatabaseSettings.from_environment(
        env_file=Path("missing"),
        environ={"AI_DATABASE_URL": f"postgresql://test:{secret}@localhost/postgres"},
    )

    def fail(*_args, **_kwargs):
        raise OperationalError(f"connection failed: {secret}")

    with pytest.raises(DatabaseConnectionError) as captured:
        probe_database(settings, connect=fail)
    assert secret not in str(captured.value)
