"""Resolve selected PSI-69 FLEX trials through the audited NASA ETL."""

from __future__ import annotations

import csv
import hashlib
import re
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

from data.src.analysis.scientific_catalog import CatalogError
from data.src.etl.nasa_etl import FLEX, classify_rows, inspect_nasa_csv, transform
from data.src.etl.nasa_tables import PROFILES

from app.application.public_ai_mapper import _canonical_json, _data_version, _dataset_identity


TRIAL_CODE = re.compile(r"^PSI-69:psi-69_flex:([1-9][0-9]*)$")


class ScientificSelectionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class CatalogScientificResultResolver:
    """Read all five catalog analyses from PostgreSQL using a dedicated reader."""

    def __init__(self, data_dir: Path, dsn: str):
        self.data_dir = data_dir
        self.dsn = dsn

    def resolve(self, trial_codes: list[str], variables: list[str]) -> list[dict]:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        from data.src.analysis.scientific_catalog import list_analyses
        from data.src.analysis.scientific_result import run_scientific_result
        from pyrogravity_ai.schemas.scientific_scope import scope_scientific_result

        if not trial_codes:
            return []
        if len(set(trial_codes)) != len(trial_codes):
            raise ScientificSelectionError("VALIDATION_ERROR", "La selección contiene ensayos duplicados.")
        parsed = [re.fullmatch(r"(PSI-[0-9]+):([a-zA-Z0-9_-]+):([1-9][0-9]*)", code) for code in trial_codes]
        analyses = {item["psi_code"]: item for item in list_analyses()}
        if any(match is None or match[1] not in analyses for match in parsed):
            raise ScientificSelectionError("EXPERIMENT_NOT_FOUND", "Identificador científico desconocido.")
        selected = {match[1] for match in parsed}
        allowed_variables = {v["name"] for psi in selected for v in analyses[psi]["variables"]}
        if set(variables) - allowed_variables:
            raise ScientificSelectionError("VALIDATION_ERROR", "Variable no disponible para los análisis seleccionados.")
        parameters = conninfo_to_dict(self.dsn)
        if parameters.get("user", "").lower() in {"postgres", "anon", "authenticated", "service_role", ""}:
            raise ScientificSelectionError("AI_UNAVAILABLE", "Se requiere un lector científico dedicado.")
        results = []
        try:
            sslmode = parameters.get("sslmode")
            if sslmode not in {"verify-ca", "verify-full"}:
                sslmode = "require"
            with psycopg.connect(self.dsn, sslmode=sslmode, connect_timeout=5,
                    options="-c default_transaction_read_only=on -c statement_timeout=30000",
                    prepare_threshold=None) as connection:
                for psi in sorted(selected):
                    result = run_scientific_result(analyses[psi]["analysis_id"], source="postgres",
                                                  connection=connection, data_dir=self.data_dir)
                    by_table = {dataset.table_name: dataset for dataset in result.datasets}
                    for match in parsed:
                        if match[1] != psi:
                            continue
                        dataset = by_table.get(match[2])
                        if dataset is None or not connection.execute(
                            "SELECT 1 FROM scientific.records WHERE dataset_id=%s AND source_record=%s",
                            (dataset.database_dataset_id, int(match[3])),
                        ).fetchone():
                            raise ScientificSelectionError("EXPERIMENT_NOT_FOUND", "Ensayo no encontrado en la versión científica.")
                    results.append(scope_scientific_result(result, trial_codes, variables).model_dump(mode="json"))
        except (psycopg.Error, CatalogError):
            raise ScientificSelectionError("AI_UNAVAILABLE", "No se pudo verificar el catálogo científico en PostgreSQL.") from None
        return results


class FlexScientificResultResolver:
    """Build a canonical v1.1 ScientificResult from manifest-verified Parquet rows."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def resolve(self, trial_codes: list[str], variables: list[str]) -> list[dict]:
        if not trial_codes:
            return []
        records = []
        for code in trial_codes:
            match = TRIAL_CODE.fullmatch(code)
            if match is None:
                raise ScientificSelectionError("EXPERIMENT_NOT_FOUND", "No se reconoce el identificador de ensayo.")
            records.append(int(match.group(1)))
        if len(records) != len(set(records)):
            raise ScientificSelectionError("VALIDATION_ERROR", "La selección contiene ensayos duplicados.")
        if any(variable != "burn_time" for variable in variables):
            raise ScientificSelectionError("VALIDATION_ERROR", "La variable solicitada no está disponible para PSI-69 FLEX.")

        manifest_path = self.data_dir / "source_manifest.csv"
        source_path = self.data_dir / FLEX.source
        with manifest_path.open(encoding="utf-8", newline="") as stream:
            manifest = next((row for row in csv.DictReader(stream) if row["psi_code"] == "PSI-69"), None)
        if manifest is None:
            raise ScientificSelectionError("AI_UNAVAILABLE", "No está disponible el manifiesto PSI-69.")

        source_bytes = source_path.read_bytes()
        canonical_bytes = source_bytes.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if hashlib.sha256(canonical_bytes).hexdigest() != manifest["sha256"]:
            raise ScientificSelectionError("AI_UNAVAILABLE", "El CSV PSI-69 no coincide con el manifiesto.")

        source = inspect_nasa_csv(source_path, FLEX.encoding)
        table = classify_rows(transform(FLEX, self.data_dir, source), source, PROFILES[("PSI-69", "FLEX")])
        # The internal contract identifies the scientific storage source as Parquet.
        # Use an actual temporary Parquet round-trip; do not claim DB provenance here.
        with tempfile.TemporaryDirectory(prefix="pyrogravity-flex-") as temp_dir:
            parquet_path = Path(temp_dir) / "psi-69_flex.parquet"
            pq.write_table(table, parquet_path)
            parquet = pq.read_table(parquet_path)
            by_record = {row["source_record"]: row for row in parquet.to_pylist()}
        if any(record not in by_record for record in records):
            raise ScientificSelectionError("EXPERIMENT_NOT_FOUND", "No se encontró uno de los ensayos PSI-69 seleccionados.")

        selected = [by_record[number] for number in records]
        admitted = [row for row in selected if row["quantitative_candidate"]
                    and row["burn_time_status"] == "exact" and not row["anomalies"]]
        if selected and not admitted:
            status = "insufficient_evidence"
        elif len(admitted) != len(selected):
            status = "partial"
        else:
            status = "ok"

        identity = {"psi_code": manifest["psi_code"], "relative_path": manifest["relative_path"],
                    "sha256": manifest["sha256"]}
        dataset = {
            "ref_id": _dataset_identity({**identity, "ref_id": "unused"}),
            "psi_code": manifest["psi_code"], "table_name": "psi-69_flex",
            "relative_path": manifest["relative_path"], "sha256": manifest["sha256"],
            "source_id": manifest["psi_code"], "source_title": manifest["investigation_name"],
            "source_url": manifest["nasa_psi_url"], "database_dataset_id": None,
        }
        data = []
        for row in admitted:
            number = row["source_record"]
            data.append({
                "kind": "measurement", "datum_id": f"burn_time_trial_{number}",
                "dataset_ref_id": dataset["ref_id"], "trial_code": f"PSI-69:psi-69_flex:{number}",
                "source_record": number, "column_ordinal": source.header.index("Burn time; s") + 1,
                "source_header": "Burn time; s", "variable_code": "burn_time",
                "value": str(row["burn_time"]), "raw_value": row["burn_time_raw"], "unit": "s",
                "interpretation_status": "exact", "validation_status": "validated", "anomalies": [],
            })
        result = {
            "schema_version": "1.1", "canonicalization_version": "scientific-result-c14n-v1",
            "result_id": "flex_" + hashlib.sha256("|".join(trial_codes).encode()).hexdigest()[:24],
            "data_version": "0" * 64, "analysis_id": "flex", "status": status, "source": "parquet",
            "datasets": [dataset], "data": data, "warnings": [],
            "limitations": [
                f"El manifiesto clasifica el dataset como {manifest['validation_status']}; cada fila publicada pasó los criterios cuantitativos y no tiene anomalías."
            ],
        }
        result["data_version"] = _data_version(result)
        return [result]
