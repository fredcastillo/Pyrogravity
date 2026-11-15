"""Comprueba la demo desde el mismo origen HTTP que usa el dashboard."""

import argparse
import json
import re
import urllib.error
from urllib.parse import urlencode
from urllib.request import urlopen


def verify(base_url: str, release_id: str | None = None) -> None:
    def fetch(path):
        with urlopen(base_url + path, timeout=12) as response:
            return response.read()

    def query(dataset, trials):
        return json.loads(fetch("/api/v1/compare?" + urlencode({"dataset": dataset, "trials": trials})))

    page = fetch("/").decode("utf-8")
    assert "Combusti" in page
    script = re.search(r'src="(/assets/(?:releases/[0-9a-f]{40}/)?demo\.js)"', page)
    stylesheet = re.search(r'href="(/assets/(?:releases/[0-9a-f]{40}/)?demo\.css)"', page)
    assert script and stylesheet, "El dashboard debe enlazar su JavaScript y CSS."
    if release_id:
        prefix = f"/assets/releases/{release_id}/"
        assert script[1].startswith(prefix) and stylesheet[1].startswith(prefix), "CloudFront aún sirve otra versión."
    assert b"async function compare" in fetch(script[1])
    assert b"#bars" in fetch(stylesheet[1])
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
    parser.add_argument("--release-id")
    arguments = parser.parse_args()
    verify(arguments.base_url.rstrip("/"), arguments.release_id)
