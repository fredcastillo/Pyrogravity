import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app


EXAMPLES_DIR = ROOT / "docs" / "api" / "examples"
OUTPUT_PATH = ROOT / "docs" / "api" / "openapi.json"


def build_openapi() -> dict:
    schema = app.openapi()
    examples = {}
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        key = path.stem
        examples[key] = {
            "summary": key.replace("_", " "),
            "value": json.loads(path.read_text(encoding="utf-8")),
        }
    schema.setdefault("components", {})["examples"] = examples

    error_examples = {
        "404": ["404_experiment_not_found", "404_chart_not_found"],
        "422": ["422_validation_error"],
        "502": ["502_ai_ungrounded_response"],
        "503": ["503_ai_unavailable"],
    }
    for path, operations in schema.get("paths", {}).items():
        if not (path.startswith("/api/v1/ai") or path.startswith("/api/v1/charts")):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            if path == "/api/v1/ai/query" and operation.get("operationId") == "public_ai_query_v1_1":
                operation.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {})["examples"] = {
                    "public_request": {"$ref": "#/components/examples/public_ai_request"}
                }
                operation["responses"].setdefault("200", {}).setdefault("content", {}).setdefault("application/json", {})["examples"] = {
                    "supported": {"$ref": "#/components/examples/public_ai_supported"},
                    "insufficient_evidence": {"$ref": "#/components/examples/public_ai_insufficient"},
                }
                operation["responses"].setdefault("503", {}).setdefault("content", {}).setdefault("application/json", {})["examples"] = {
                    "ai_unavailable": {"$ref": "#/components/examples/public_ai_error_503"}
                }
            for response in operation["responses"].values():
                response.setdefault("headers", {})["X-Request-ID"] = {
                    "schema": {"type": "string"},
                    "description": "Identificador de trazabilidad.",
                }
                response["headers"]["X-Served-From"] = {
                    "schema": {"type": "string", "enum": ["live", "cache", "demo", "degraded"]},
                    "description": "Procedencia de la respuesta.",
                }
            for status, names in error_examples.items():
                if status not in operation["responses"]:
                    continue
                response = operation["responses"][status]
                response["content"] = {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiErrorResponse"},
                        "examples": {
                            name: {"$ref": f"#/components/examples/{name}"}
                            for name in names
                        },
                    }
                }
    return schema


def export_openapi() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUTPUT_PATH.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    export_openapi()
