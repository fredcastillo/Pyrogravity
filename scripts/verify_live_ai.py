"""Exercise the public API against manifest-verified scientific PostgreSQL evidence.

Requires PYROGRAVITY_DATABASE_URL with a dedicated read-only identity. Calls Cohere
through the deployed API; never loads credentials from a tracked file.
"""
import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.src.analysis.scientific_catalog import list_analyses
from data.src.analysis.scientific_result import run_scientific_result


def verify(base_url):
    outcomes = []
    with psycopg.connect(os.environ["PYROGRAVITY_DATABASE_URL"], sslmode="require",
                          options="-c default_transaction_read_only=on", prepare_threshold=None) as db:
        analyses = [run_scientific_result(a["analysis_id"], source="postgres", connection=db)
                    for a in list_analyses()]
    with httpx.Client(base_url=base_url, timeout=90) as client:
        def query(name, question, trials=(), variables=(), chart=None):
            request_id = str(uuid4())
            response = client.post("/api/v1/ai/query", json={
                "id": request_id, "question": question, "language": "es",
                "experiment_ids": list(trials), "variables": list(variables), "chart_preference": chart,
            })
            assert response.status_code == 200, f"{name}: HTTP {response.status_code}"
            body = response.json()
            assert body["id"] == request_id and body["schema_version"] == "public-1.1"
            assert body["provenance"] == "live"
            outcomes.append({"case": name, "status": body["status"], "citations": len(body["citations"]),
                             "charts": len(body["charts"])})
            return body

        for result in analyses:
            datum = next(d for d in result.data if d.kind == "measurement")
            body = query(result.analysis_id, f"¿Cuál es el valor registrado de {datum.variable_code}?",
                         [datum.trial_code], [datum.variable_code])
            measurements = [c["measurement"] for c in body["citations"] if c.get("measurement")]
            assert body["status"] in {"supported", "partially_supported"} and measurements
            assert all(Decimal(m["value"]) == Decimal(datum.value) and m["unit"] == datum.unit
                       for m in measurements), result.analysis_id

        flex = next(r for r in analyses if r.analysis_id == "flex")
        data = [d for d in flex.data if d.kind == "measurement" and d.variable_code == "burn_time"][:2]
        body = query("comparison", "Compara el valor de burn_time de los ensayos seleccionados.",
                     [d.trial_code for d in data], ["burn_time"], "bar")
        assert body["charts"] and all(s["validated"] for c in body["charts"] for s in c["series"])
        actual = {str(p["x"]): Decimal(str(p["y"])) for c in body["charts"] for s in c["series"] for p in s["points"]}
        assert actual == {d.trial_code: Decimal(d.value) for d in data}
        body = query("document", "Explica los objetivos de la investigación BASS-II.")
        assert body["status"] == "supported" and any(c["kind"] == "document" and c["page"] for c in body["citations"])
        body = query("insufficient", "Explica el resultado de los ensayos de combustión de antimateria de BASS-II.")
        assert body["status"] == "insufficient_evidence" and not body["claims"] and not body["charts"]
    return outcomes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.base_url), ensure_ascii=False, indent=2))
    except Exception as error:
        # Transport/driver exception messages may contain connection details.
        print(f"Verification failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
