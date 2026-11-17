"""Verify the Command Center artifact and the public AI API contract."""

import argparse
import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from uuid import uuid4


def verify(base_url: str) -> None:
    with urlopen(base_url, timeout=20) as response:
        landing_page = response.read().decode()
    link = re.search(r'href="([^"]+/command-center/index\.html)"', landing_page)
    assert link or 'id="root"' in landing_page, "Falta el frontend de React."
    spa_url = urljoin(base_url, link[1]) if link else base_url
    with urlopen(spa_url, timeout=20) as response:
        html = response.read().decode()
    script = re.search(r'<script\b[^>]+src="([^"]+\.js)"', html)
    assert 'id="root"' in html and script, "El HTML debe montar la SPA compilada."
    modules = re.findall(r'<link\b(?=[^>]*\brel="modulepreload")[^>]*\bhref="([^"]+\.js)"', html)
    for path in dict.fromkeys([script[1], *modules]):
        with urlopen(urljoin(spa_url, path), timeout=20) as response:
            if b"/api/v1/ai/query" in response.read():
                break
    else:
        raise AssertionError("El frontend debe consumir el contrato de la API.")

    payload = {
        "id": str(uuid4()),
        "question": "Explica el resultado de los ensayos de combustión de antimateria de BASS-II.",
        "language": "es",
        "experiment_ids": [],
    }
    request = Request(
        urljoin(base_url, "/api/v1/ai/query"),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=25) as response:
        result = json.load(response)
        assert response.headers.get("X-Request-Id") == payload["id"]
    assert result["id"] == payload["id"]
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == [] and result["charts"] == []
    print("Command Center y contrato público de IA verificados.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    verify(parser.parse_args().base_url)
