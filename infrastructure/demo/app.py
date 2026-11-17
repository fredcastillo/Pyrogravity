import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from pydantic import BaseModel

DEMO_DIR = Path(__file__).resolve().parent
WEB_DIR = DEMO_DIR / "web"
RELEASE_FILE = DEMO_DIR / "release.txt"
RELEASE_ID = RELEASE_FILE.read_text(encoding="ascii").strip() if RELEASE_FILE.is_file() else None
DatasetName = Literal["flex", "bass_ii"]
api = FastAPI(title="Pyrogravity | Demo científica", docs_url=None, redoc_url=None, openapi_url=None)


@api.middleware("http")
async def request_trace(request: Request, call_next):
    context = request.scope.get("aws.event", {}).get("requestContext", {})
    request_id = context.get("requestId") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@lru_cache(maxsize=1)
def science_snapshot():
    return json.loads((DEMO_DIR / "analyses.json").read_text(encoding="utf-8"))


@api.get("/api/v1/analyses")
def analyses():
    # Available filters describe the scientific engine; this immutable demo exposes its default cohort.
    return [{**item, "mode": "snapshot", "filters": []} for item in science_snapshot()["catalog"]]


@api.get("/api/v1/analyses/{analysis_id}")
def analysis(analysis_id: str):
    result = science_snapshot()["results"].get(analysis_id)
    if result is None:
        raise HTTPException(404, "Análisis desconocido.")
    return result


class Measurement(BaseModel):
    trial: str
    value: str | None
    status: str
    material: str | None
    source_record: int
    flags: list[str]


class Dataset(BaseModel):
    id: DatasetName
    study: str
    label: str
    metric: str
    metric_label: str
    unit: str
    examples: list[str]
    source: str
    source_path: str
    source_sha256: str
    count: int


class Comparison(BaseModel):
    status: Literal["ok", "partial", "insufficient_evidence"]
    dataset: Dataset
    measurements: list[Measurement]
    missing_trials: list[str]


@lru_cache(maxsize=1)
def snapshot():
    datasets = json.loads((DEMO_DIR / "snapshot.json").read_text(encoding="utf-8"))
    result = {}
    for dataset_id, dataset in datasets.items():
        records = dataset.pop("records")
        metadata = Dataset(id=dataset_id, count=len(records), **dataset)
        trials = defaultdict(list)
        for row in records:
            if row["trial"]:
                trials[row["trial"].upper()].append(Measurement(**row))
        result[dataset_id] = (metadata, trials)
    return result


@api.get("/api/v1/health")
def health(response: Response) -> dict[str, str]:
    if RELEASE_ID:
        response.headers["X-Pyrogravity-Release"] = RELEASE_ID
    snapshot()
    return {"status": "ok", "mode": "demo"}


@api.get("/api/v1/datasets", response_model=list[Dataset])
def datasets():
    return [metadata for metadata, _ in snapshot().values()]


@api.get("/api/v1/compare", response_model=Comparison)
def compare(dataset: DatasetName, trials: Annotated[str, Query(min_length=1, max_length=160)]):
    requested = list(dict.fromkeys(trial.strip().upper() for trial in trials.split(",") if trial.strip()))
    if not 1 <= len(requested) <= 12:
        raise HTTPException(422, "Escribe entre 1 y 12 identificadores de ensayo.")

    metadata, records = snapshot()[dataset]
    matches = [row for trial in requested for row in records.get(trial, ())]
    missing = [trial for trial in requested if trial not in records]
    exact = sum(row.value is not None and row.status == "exact" for row in matches)
    if exact == 0:
        status = "insufficient_evidence"
    elif missing or exact < len(matches):
        status = "partial"
    else:
        status = "ok"
    return Comparison(status=status, dataset=metadata, measurements=matches, missing_trials=missing)


if WEB_DIR.is_dir():
    @api.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(WEB_DIR / "index.html")

    @api.get("/estudios/{study}", include_in_schema=False)
    def study_page(study: str):
        return dashboard()

    api.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


handler = Mangum(api, lifespan="off")
