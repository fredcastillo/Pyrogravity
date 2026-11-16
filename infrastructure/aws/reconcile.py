"""Reintenta CI cuando main no está publicado; nunca publica código sin probar."""

import json
import os
import re
import subprocess
from urllib.error import URLError
from urllib.request import Request, urlopen

SITE = "https://d1spxqlrdcakje.cloudfront.net"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    head = json.loads(gh("api", f"repos/{repo}/git/ref/heads/main"))["object"]["sha"]
    try:
        with urlopen(Request(SITE + "/", headers={"Cache-Control": "no-cache"}), timeout=20) as response:
            published = set(re.findall(r'/assets/releases/([a-f0-9]{40})/', response.read().decode()))
        if published == {head}:
            with urlopen(Request(SITE + "/api/v1/health", headers={"Cache-Control": "no-cache"}), timeout=20) as response:
                api_current = (
                    response.headers.get("X-Pyrogravity-Release") == head
                    and json.load(response) == {"status": "ok", "mode": "demo"}
                )
            if api_current:
                print(f"La página y la API ya publican {head}. No hay que recompilar.")
                return
    except (URLError, TimeoutError, ValueError) as error:
        print(f"No se pudo verificar la publicación ({type(error).__name__}).")
    runs = json.loads(gh("api", f"repos/{repo}/actions/workflows/ci.yml/runs?branch=main&per_page=30"))["workflow_runs"]
    eligible = [r for r in runs if r["head_sha"] == head and r["event"] in ("push", "workflow_dispatch")]
    if any(r["status"] != "completed" for r in eligible):
        print("CI/CD de este commit ya está en curso.")
        return
    # Avoid unbounded retries of a broken build. A new commit gets its own budget.
    attempts = sum(r.get("run_attempt", 1) for r in eligible)
    if attempts >= 3:
        raise SystemExit("Publicación pendiente tras tres intentos. Revisar CI; un nuevo commit reinicia los intentos.")
    gh("workflow", "run", "ci.yml", "--repo", repo, "--ref", "main")
    print(f"CI solicitado para verificar y publicar {head}.")


if __name__ == "__main__":
    main()
