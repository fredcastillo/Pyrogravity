import json
import traceback
from decimal import Decimal
from hashlib import sha256

import psycopg
import pytest

from data.src.analysis import bass_ii_co2, cfi_g_duration, flame_design_pressure, flex_combustion, scientific_catalog, spice_flow
from data.src.database import nasa_loader as loader
from data.src.etl.nasa_etl import DATA_DIR, discover_sources
from test_nasa_loader import SimulatedCursor, etl_outputs, simulated_database


ANALYSES = {
    "bass-ii": ("PSI-25", bass_ii_co2), "flex": ("PSI-69", flex_combustion),
    "flame-design": ("PSI-10", flame_design_pressure), "cfi-g": ("PSI-159", cfi_g_duration), "spice": ("PSI-107", spice_flow),
}


@pytest.fixture(scope="module")
def dataset_dir(request):
    manifest_path = DATA_DIR / "source_manifest.csv"
    if manifest_path.is_file():
        entries = loader.read_manifest(manifest_path)
        needed = [entry["parquet_filename"] for entry in entries.values() if entry["psi_code"] in {p for p, _ in ANALYSES.values()}]
        if len(needed) == 7 and all((DATA_DIR / "processed" / filename).is_file() for filename in needed):
            return DATA_DIR
    return request.getfixturevalue("etl_outputs")


def test_catalog_metadata_is_stable_and_independent_between_calls():
    entries = scientific_catalog.list_analyses()
    assert [entry["analysis_id"] for entry in entries] == list(ANALYSES)
    for entry in entries:
        code, _ = ANALYSES[entry["analysis_id"]]
        assert entry["psi_code"] == code and entry["investigation_name"]
        assert entry["description"] and all(var["unit"] for var in entry["variables"])
        assert entry["sources"] == ["parquet", "postgres"]
        assert entry["filters"] == (["pi", "material"] if code == "PSI-25" else [])
    assert entries[0]["variables"][0] == {"name": "initial_co2", "unit": "% by vol"}
    assert json.loads(json.dumps(entries)) == entries
    entries[0]["variables"][0]["unit"] = "changed"
    entries[0]["filters"].clear()
    assert scientific_catalog.list_analyses()[0]["filters"] == ["pi", "material"]
    assert scientific_catalog.list_analyses()[0]["variables"][0]["unit"] == "% by vol"


@pytest.mark.parametrize("name", ANALYSES)
def test_parquet_wraps_full_direct_result_without_changes(dataset_dir, name):
    code, module = ANALYSES[name]
    direct = module.analyze_parquet(data_dir=dataset_dir)
    wrapped = scientific_catalog.run_analysis(name, data_dir=dataset_dir)
    assert wrapped == {
        "analysis_id": name, "analysis_name": next(e["analysis_name"] for e in scientific_catalog.list_analyses()
                                                  if e["analysis_id"] == name),
        "psi_code": code, "source": "parquet", "contract_version": "1.0", "filters": {}, "result": direct,
    }
    assert json.loads(json.dumps(wrapped, allow_nan=False)) == wrapped
    assert scientific_catalog.run_analysis(name, data_dir=dataset_dir) == wrapped
    assert wrapped["result"]["warnings"] and wrapped["result"]["plots"]


def test_bass_filters_are_forwarded_and_preserve_statistics(dataset_dir):
    filters = {"pi": " Olson ", "material": " 2 cm SIBAL "}
    before = filters.copy()
    wrapped = scientific_catalog.run_analysis("bass-ii", filters=filters, data_dir=dataset_dir)
    assert filters == before
    assert wrapped["filters"] == {"pi": "Olson", "material": "2 cm SIBAL"}
    assert wrapped["result"] == bass_ii_co2.analyze_parquet(data_dir=dataset_dir, **wrapped["filters"])
    unfiltered = scientific_catalog.run_analysis("bass-ii", filters={"pi": None}, data_dir=dataset_dir)
    assert unfiltered["filters"] == {"pi": None}
    assert unfiltered["result"]["valid_pair_count"] == 121


@pytest.mark.parametrize(("name", "options", "code", "message"), [
    ("data.src.analysis.spice_flow", {}, "unknown_analysis", "Allowed analysis IDs"),
    ([], {}, "unknown_analysis", "Allowed analysis IDs"),
    ("spice", {"source": "http"}, "unsupported_source", "parquet, postgres"),
    ("spice", {"source": []}, "unsupported_source", "parquet, postgres"),
    ("spice", {"source": "postgres"}, "missing_connection", "caller-managed"),
    ("spice", {"source": "postgres", "connection": "postgresql://secret"}, "missing_connection", "caller-managed"),
    ("spice", {"filters": {"cohort": "conservative"}}, "unsupported_filter", "none"),
    ("flex", {"filters": {"fuel": "Methanol"}}, "unsupported_filter", "none"),
    ("flame-design", {"filters": {"configuration": "normal"}}, "unsupported_filter", "none"),
    ("cfi-g", {"filters": {"termination": "SE"}}, "unsupported_filter", "none"),
    ("bass-ii", {"filters": {"unknown": "value"}}, "unsupported_filter", "pi, material"),
    ("bass-ii", {"filters": [("pi", "Olson")]}, "invalid_filter", "mapping"),
    ("bass-ii", {"filters": {"pi": " \t"}}, "invalid_filter", "non-empty string"),
    ("bass-ii", {"filters": {"material": True}}, "invalid_filter", "non-empty string"),
])
def test_invalid_parameters_fail_before_reading_data(monkeypatch, name, options, code, message):
    monkeypatch.setattr(scientific_catalog, "read_manifest", lambda _: pytest.fail("unexpected manifest read"))
    with pytest.raises(scientific_catalog.CatalogError, match=message) as error:
        scientific_catalog.run_analysis(name, **options)
    assert error.value.code == code
    assert "postgresql://secret" not in str(error.value)


def test_reports_missing_manifest_and_required_dataset(dataset_dir, tmp_path, monkeypatch):
    with pytest.raises(scientific_catalog.CatalogError, match="manifest was not found") as error:
        scientific_catalog.run_analysis("spice", data_dir=tmp_path)
    assert error.value.code == "dataset_not_found"
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    del manifest[flame_design_pressure.PATHS["inverse"]]
    monkeypatch.setattr(scientific_catalog, "read_manifest", lambda _: manifest)
    with pytest.raises(scientific_catalog.CatalogError, match="Inverse Flame") as error:
        scientific_catalog.run_analysis("flame-design", data_dir=dataset_dir)
    assert error.value.code == "dataset_not_found"


@pytest.mark.parametrize("bad_sha", ("not-a-digest", "0" * 64))
def test_rejects_invalid_or_mismatched_sha256(dataset_dir, monkeypatch, bad_sha):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    manifest[spice_flow.SOURCE.as_posix()]["sha256"] = bad_sha
    monkeypatch.setattr(scientific_catalog, "read_manifest", lambda _: manifest)
    monkeypatch.setattr(spice_flow, "read_manifest", lambda _: manifest)
    with pytest.raises(scientific_catalog.CatalogError, match="SHA-256") as error:
        scientific_catalog.run_analysis("spice", data_dir=dataset_dir)
    assert error.value.code == "invalid_dataset_version"


@pytest.mark.parametrize(("change", "code"), [
    ({"analysis_id": "other"}, "inconsistent_result"),
    ({"dataset": None}, "inconsistent_result"),
    ({"not_json": Decimal("1.01")}, "inconsistent_result"),
    ({"not_json": float("nan")}, "inconsistent_result"),
])
def test_rejects_inconsistent_module_results(dataset_dir, monkeypatch, change, code):
    direct = bass_ii_co2.analyze_parquet(data_dir=dataset_dir)
    monkeypatch.setattr(bass_ii_co2, "analyze_parquet", lambda **_: {**direct, **change})
    with pytest.raises(scientific_catalog.CatalogError) as error:
        scientific_catalog.run_analysis("bass-ii", data_dir=dataset_dir)
    assert error.value.code == code


def test_read_errors_have_safe_diagnostics(dataset_dir, monkeypatch):
    secret_dsn = "postgresql://user:test-secret@localhost/db"

    def fail(*args, **kwargs):
        raise psycopg.OperationalError(secret_dsn)

    class Connection:
        def cursor(self):
            pytest.fail("unexpected cursor")

    monkeypatch.setattr(spice_flow, "analyze_postgres", fail)
    with pytest.raises(scientific_catalog.CatalogError, match="OperationalError") as error:
        scientific_catalog.run_analysis("spice", source="postgres", connection=Connection(), data_dir=dataset_dir)
    assert error.value.code == "read_error"
    assert secret_dsn not in "".join(traceback.format_exception(error.value))


def test_parquet_calls_leave_manifest_csv_and_parquet_intact(dataset_dir):
    manifest_path = dataset_dir / "source_manifest.csv"
    source_paths = [manifest_path]
    for path, entry in loader.read_manifest(manifest_path).items():
        source_paths.extend((dataset_dir / path, dataset_dir / "processed" / entry["parquet_filename"]))
    before = {path: sha256(path.read_bytes()).hexdigest() for path in source_paths}
    for name in ANALYSES:
        scientific_catalog.run_analysis(name, data_dir=dataset_dir)
    assert {path: sha256(path.read_bytes()).hexdigest() for path in source_paths} == before


def test_postgres_delegation_is_read_only_and_keeps_caller_connection(simulated_database, dataset_dir, tmp_path, monkeypatch):
    manifest = loader.read_manifest(dataset_dir / "source_manifest.csv")
    codes = {entry[0] for entry in ANALYSES.values()}
    sources = [source for source in discover_sources(dataset_dir) if source.study in codes]
    datasets = [loader.prepare_dataset(dataset_dir, source, manifest[source.path.as_posix()]) for source in sources]
    assert loader.load_datasets(datasets, "simulated") == 7

    def no_connection(*args, **kwargs):
        pytest.fail("catalog opened or managed a connection")

    class ReadCursor(SimulatedCursor):
        def execute(self, statement, params):
            assert statement.lstrip().startswith("SELECT")
            assert statement.count("%s") == len(params)
            super().execute(statement, params)

        def fetchall(self):
            fields = [column[0] for column in self.cursor.description]
            return [dict(zip(fields, row, strict=True)) for row in super().fetchall()]

    class Connection:
        __slots__ = ()
        close = commit = rollback = __enter__ = __exit__ = no_connection

        def cursor(self, *, row_factory):
            return ReadCursor(simulated_database.cursor())

    simulated_database.execute("PRAGMA query_only = ON")
    monkeypatch.setattr(psycopg, "connect", no_connection)
    monkeypatch.setattr(scientific_catalog, "read_manifest", lambda _: manifest)
    connection = Connection()
    for name, (code, module) in ANALYSES.items():
        selected = {"pi": "Olson", "material": "2 cm SIBAL"} if name == "bass-ii" else {}
        hashes = ({label: manifest[path]["sha256"] for label, path in module.PATHS.items()}
                  if name in {"flame-design", "cfi-g"}
                  else next(dataset.sha256 for dataset in datasets if dataset.investigation[0] == code))
        wrapped = scientific_catalog.run_analysis(name, "postgres", connection, selected, data_dir=tmp_path)
        assert wrapped["filters"] == selected and wrapped["source"] == "postgres"
        assert wrapped["result"] == module.analyze_postgres(connection, hashes, **selected)
        assert json.loads(json.dumps(wrapped, allow_nan=False)) == wrapped
        if name == "cfi-g":
            assert all(type(part["dataset"]["dataset_id"]) is int for part in wrapped["result"]["configurations"].values())

    manifest[spice_flow.SOURCE.as_posix()]["sha256"] = "0" * 64
    with pytest.raises(scientific_catalog.CatalogError, match="missing or not visible") as error:
        scientific_catalog.run_analysis("spice", "postgres", connection, data_dir=tmp_path)
    assert error.value.code == "dataset_not_found"
    assert simulated_database.execute("SELECT count(*) FROM scientific.datasets").fetchone() == (7,)
