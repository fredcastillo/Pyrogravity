"""Check the real API and React entry point through the Compose nginx proxy."""

import argparse
import json
from urllib.request import urlopen


EXPECTED_ANALYSES = {"bass-ii", "flex", "flame-design", "cfi-g", "spice"}
LOCAL_WEB = "http://127.0.0.1:8080"


def fetch(path):
    with urlopen(f"{LOCAL_WEB}{path}", timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read()


def smoke(mode):
    for path in ("/", "/explorer"):
        if b'id="root"' not in fetch(path):
            raise RuntimeError(f"{path} did not serve the React entry point")
    health = json.loads(fetch("/health"))
    expected_db_status = "ok" if mode == "real" else "demo"
    expected_source = "postgres" if mode == "real" else "parquet"
    if health["mode"] != mode or health["scientific_database"] != expected_db_status:
        raise RuntimeError(f"Unexpected health status: {health}")
    analyses = json.loads(fetch("/api/v1/analyses"))
    if not EXPECTED_ANALYSES <= {item["analysis_id"] for item in analyses}:
        raise RuntimeError("Missing one or more of the five required analyses")
    for name in sorted(EXPECTED_ANALYSES):
        analysis = json.loads(fetch(f"/api/v1/analyses/{name}"))
        if analysis["analysis_id"] != name or analysis["source"] != expected_source:
            raise RuntimeError(f"{name} did not use {expected_source}")
        print(f"{name}: {expected_source} OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("demo", "real"))
    smoke(parser.parse_args().mode)
