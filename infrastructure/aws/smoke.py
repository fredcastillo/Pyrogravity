"""Comprueba la demo desde el mismo origen HTTP que usa el dashboard."""

import argparse
import json
import urllib.error
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(base_url: str) -> None:
    def fetch(path):
        with urlopen(base_url + path, timeout=12) as response:
            return response.read()

    def query(dataset, trials):
        return json.loads(fetch("/api/v1/compare?" + urlencode({"dataset": dataset, "trials": trials})))

    assert b"Combusti" in fetch("/")
    assert b"async function compare" in fetch("/assets/demo.js")
    assert b"#bars" in fetch("/assets/demo.css")
    assert json.loads(fetch("/api/v1/health")) == {"status": "ok", "mode": "demo"}
    catalog = json.loads(fetch("/api/v1/datasets"))
    assert {item["study"]: item["count"] for item in catalog} == {"PSI-25": 129, "PSI-69": 274}

    flex = query("flex", "1, 2, 3")
    assert flex["status"] == "ok"
    assert flex["dataset"]["unit"] == "s"
    assert flex["dataset"]["source"] == "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"
    assert [(row["trial"], row["value"], row["source_record"]) for row in flex["measurements"]] == [
        ("1", "4.30", 1), ("2", "5.00", 2), ("3", "3.20", 3),
    ]

    bass = query("bass_ii", "B1, b2, B3")
    assert bass["status"] == "ok" and len(bass["measurements"]) == 3
    assert bass["dataset"]["unit"] == "% by vol"
    assert bass["dataset"]["source"].endswith("/PSI-25")

    partial = query("flex", "1, 223, inexistente")
    assert partial["status"] == "partial" and partial["missing_trials"] == ["INEXISTENTE"]
    insufficient = query("flex", "223, inexistente")
    assert insufficient["status"] == "insufficient_evidence"
    assert insufficient["measurements"][0]["value"] is None
    try:
        query("unknown", "1")
    except urllib.error.HTTPError as error:
        assert error.code == 422
    else:
        raise AssertionError("Un estudio desconocido debe devolver 422.")

    print(f"Verificado {base_url}: dashboard, API, ambos estudios, valores exactos y evidencia insuficiente.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    arguments = parser.parse_args()
    verify(arguments.base_url.rstrip("/"))
