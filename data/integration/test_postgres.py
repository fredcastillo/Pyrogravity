"""Use only a disposable PostgreSQL database; never point this suite at production."""
import os
import secrets
import shutil
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from data.src.analysis.scientific_catalog import list_analyses, run_analysis
from data.src.database.nasa_loader import load_datasets, prepare_load
from data.src.etl.nasa_etl import DATA_DIR, run_etl

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    admin = os.environ.get("PYRO_TEST_DATABASE_URL")
    if not admin:
        pytest.skip("PYRO_TEST_DATABASE_URL is required for disposable PostgreSQL integration tests")
    with psycopg.connect(admin, autocommit=True) as conn:
        if conn.execute("SELECT to_regnamespace('scientific')").fetchone()[0] is not None:
            pytest.fail("Refusing to migrate an existing scientific schema; use an empty disposable database")
        for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        passwords = {role: secrets.token_hex(24) for role in ("pyrogravity_nasa_loader", "pyrogravity_api_reader")}
        for role, password in passwords.items():
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
        conn.execute("CREATE ROLE integration_untrusted NOLOGIN NOSUPERUSER NOBYPASSRLS")
        conn.execute("GRANT USAGE ON SCHEMA scientific TO integration_untrusted")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA scientific TO integration_untrusted")
    directory = tmp_path_factory.mktemp("nasa-postgres")
    shutil.copytree(DATA_DIR / "raw", directory / "raw")
    run_etl(data_dir=directory)
    datasets = prepare_load(directory)
    loader = make_conninfo(admin, user="pyrogravity_nasa_loader", password=passwords["pyrogravity_nasa_loader"])
    reader = make_conninfo(admin, user="pyrogravity_api_reader", password=passwords["pyrogravity_api_reader"])
    assert load_datasets(datasets, loader) == len(datasets)
    return admin, loader, reader, directory, datasets


def test_complete_inventory_and_idempotence(database):
    _, loader, reader, _, datasets = database
    assert load_datasets(datasets, loader) == 0
    with psycopg.connect(reader) as conn:
        assert conn.execute("SELECT count(*) FROM scientific.datasets").fetchone()[0] == len(datasets)
        assert conn.execute("SELECT count(*) FROM scientific.records").fetchone()[0] == sum(len(d.records) for d in datasets)
        assert conn.execute("SELECT count(*) FROM scientific.measurements").fetchone()[0] == sum(len(d.measurements) for d in datasets)
        actual = conn.execute("SELECT relative_path,sha256 FROM scientific.datasets ORDER BY relative_path").fetchall()
        assert actual == sorted((d.relative_path, d.sha256) for d in datasets)


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in ("dataset_id", "source")}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


@pytest.mark.parametrize("analysis_id", [item["analysis_id"] for item in list_analyses()])
def test_postgres_matches_parquet(database, analysis_id):
    _, _, reader, directory, _ = database
    expected = run_analysis(analysis_id, data_dir=directory)
    with psycopg.connect(reader) as conn:
        conn.read_only = True
        actual = run_analysis(analysis_id, source="postgres", connection=conn, data_dir=directory)
    assert normalize(actual) == normalize(expected)


def test_rls_blocks_untrusted_reader(database):
    admin, _, _, _, _ = database
    with psycopg.connect(admin) as conn:
        conn.execute("SET LOCAL ROLE integration_untrusted")
        for table in ("investigations", "datasets", "dataset_columns", "records", "measurements"):
            assert conn.execute(sql.SQL("SELECT count(*) FROM scientific.{}").format(sql.Identifier(table))).fetchone()[0] == 0


@pytest.mark.parametrize("role_index", [1, 2])
@pytest.mark.parametrize("statement", ["DELETE FROM scientific.datasets", "UPDATE scientific.datasets SET sha256=sha256", "TRUNCATE scientific.records"])
def test_application_roles_cannot_destroy_data(database, role_index, statement):
    with psycopg.connect(database[role_index]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_api_reader_cannot_insert(database):
    with psycopg.connect(database[2]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO scientific.investigations VALUES ('PSI-99999','forbidden','https://example.org')")

@pytest.mark.parametrize("analysis_id", [item["analysis_id"] for item in list_analyses()])
def test_backend_api_uses_read_only_postgres(database, analysis_id):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.settings import Settings, get_settings
    from pydantic import SecretStr
    _, _, reader, directory, _ = database
    app.dependency_overrides[get_settings] = lambda: Settings(
        demo_mode=False, scientific_data_dir=directory, pyrogravity_database_url=SecretStr(reader))
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analyses/" + analysis_id)
            assert response.status_code == 200
            assert response.json()["source"] == "postgres"
            with psycopg.connect(reader) as conn:
                expected = run_analysis(analysis_id, source="postgres", connection=conn, data_dir=directory)
            assert response.json() == expected
            assert client.get("/health").json()["scientific_database"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_compatibility_cli_writes_idempotently(database, monkeypatch):
    from scripts.load_to_supabase import main
    monkeypatch.setenv("PYROGRAVITY_DATABASE_URL", database[1])
    assert main(["--data-dir", str(database[3])]) == 0


def test_backend_dataset_reader_uses_current_schema(database):
    from app.infrastructure.supabase_repos import PostgresDatasetReader
    with psycopg.connect(database[2]) as conn:
        reader = PostgresDatasetReader(conn)
        datasets = reader.list()
        assert len(datasets) == len(database[4])
        assert reader.get(datasets[0]["id"])["sha256"] == datasets[0]["sha256"]
        assert reader.get("not-an-id") is None
