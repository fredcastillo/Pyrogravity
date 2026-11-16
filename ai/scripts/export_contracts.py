"""Export deterministic JSON Schemas for consumers outside the Python package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyrogravity_ai.schemas.contracts import AiQueryRequest, AiResponse, ChartSpec, ScientificResult
from pyrogravity_ai.schemas import contracts_v11


VERSIONS = {
    "v1": (AiQueryRequest, ScientificResult, ChartSpec, AiResponse),
    "v1_1": (contracts_v11.AiQueryRequest, contracts_v11.ScientificResult,
             contracts_v11.ChartSpec, contracts_v11.AiResponse,
             contracts_v11.Citation, contracts_v11.ErrorEnvelope),
}
OUTPUT = Path(__file__).resolve().parents[1] / "contracts"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when exported schemas differ")
    args = parser.parse_args()
    stale = []
    for version, models in VERSIONS.items():
        directory = OUTPUT / version
        if not args.check:
            directory.mkdir(parents=True, exist_ok=True)
        for model in models:
            path = directory / f"{model.__name__}.schema.json"
            expected = json.dumps(model.model_json_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != expected:
                    stale.append(f"{version}/{path.name}")
            else:
                path.write_text(expected, encoding="utf-8")
    if stale:
        parser.exit(1, f"Outdated contract schemas: {', '.join(stale)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
