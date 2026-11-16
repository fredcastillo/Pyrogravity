"""Comprueba la demo desde el mismo origen HTTP que usa el dashboard."""

import argparse
import json
import re
import urllib.error
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import urlopen

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def verify(base_url: str, release_id: str | None = None, *, api_release_id: str | None = None) -> None:
    def fetch(path):
        with urlopen(base_url + path, timeout=12) as response:
            return response.read()

    def query(dataset, trials):
        return json.loads(fetch("/api/v1/compare?" + urlencode({"dataset": dataset, "trials": trials})))

    page = fetch("/").decode("utf-8")
    science_link = re.search(r'<meta name="pyrogravity-science" content="([^"]+)"', page)
    science_url = base_url + "/"
    if science_link:
        assert 'id="root"' in page, "La entrada debe montar el frontend de React."
        science_url = urljoin(base_url, science_link[1])
        with urlopen(science_url, timeout=12) as response:
            page = response.read().decode("utf-8")
    assert "Combusti" in page
    script = re.search(r'src="([^"]*demo\.js)"', page)
    stylesheet = re.search(r'href="([^"]*demo\.css)"', page)
    assert script and stylesheet, "El dashboard debe enlazar su JavaScript y CSS."
    script_path = urlsplit(urljoin(science_url, script[1])).path
    style_path = urlsplit(urljoin(science_url, stylesheet[1])).path
    if release_id:
        prefix = f"/assets/releases/{release_id}/"
        assert script_path.startswith(prefix) and style_path.startswith(prefix), "CloudFront aún sirve otra versión."
    assert b"async function compare" in fetch(script_path)
    assert b"#bars" in fetch(style_path)
    asset_directory = script_path.rsplit("/", 1)[0]
    source_catalog = json.loads(fetch(f"{asset_directory}/catalog.json"))
    csv_hashes = {
        path.relative_to(DATA_DIR).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in (DATA_DIR / "raw").iterdir()
        if path.is_file() and path.suffix.lower() == ".csv"
    }
    published_hashes = {table["source_path"]: table["source_sha256"] for table in source_catalog}
    assert csv_hashes and len(source_catalog) == len(csv_hashes)
    assert published_hashes == csv_hashes, "El catálogo publicado debe corresponder a todos los CSV del commit."
    with urlopen(base_url + "/api/v1/health", timeout=12) as response:
        expected_api_release = api_release_id or release_id
        if expected_api_release:
            assert response.headers.get("X-Pyrogravity-Release") == expected_api_release, "Lambda sirve otro commit."
        assert json.load(response) == {"status": "ok", "mode": "demo"}
    science = json.loads(fetch("/api/v1/analyses"))
    assert {item["analysis_id"] for item in science} == {"bass-ii", "flex", "flame-design", "cfi-g", "spice"}
    for item in science:
        with urlopen(base_url + "/api/v1/analyses/" + item["analysis_id"], timeout=12) as response:
            assert response.headers.get("X-Request-Id"), "La API debe devolver una referencia trazable."
            analysis = json.load(response)
        assert analysis["analysis_id"] == item["analysis_id"] and analysis["contract_version"] == "1.0"
        result = analysis["result"]
        sources = [part["dataset"] for part in result["configurations"].values()] if "configurations" in result else [result["dataset"]]
        for source in sources:
            assert source["sha256"] == csv_hashes[source["relative_path"]]
    assert "science-analysis" in page
    assert b"selectCohort" in fetch(asset_directory + "/science.js")
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

    print(f"Verificado {base_url}: {len(source_catalog)} CSV, cinco análisis trazables y comparaciones de FLEX y BASS-II.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--release-id")
    parser.add_argument("--api-release-id")
    arguments = parser.parse_args()
    verify(arguments.base_url.rstrip("/"), arguments.release_id, api_release_id=arguments.api_release_id)
