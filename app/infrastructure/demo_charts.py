import csv
import hashlib
import io
from pathlib import Path

from app.domain.ai_contract import ChartData, ChartPoint, ChartSeriesData


CHART_ID = "psi69-flex-burn-time"
DEMO_REQUEST_ID = "demo-1"
PSI_CODE = "PSI-69"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MANIFEST_PATH = DATA_DIR / "source_manifest.csv"
SOURCE_PATH = DATA_DIR / "raw" / "PSI-69_Experimental table_FLEX.csv"


def load_psi69_chart() -> ChartData | None:
    with MANIFEST_PATH.open(encoding="utf-8", newline="") as manifest_file:
        manifest_rows = csv.DictReader(manifest_file)
        entry = next((row for row in manifest_rows if row["psi_code"] == PSI_CODE), None)
    if entry is None:
        return None

    source_bytes = SOURCE_PATH.read_bytes()
    # The tracked checkout uses LF; the manifest hash is for the original CRLF bytes.
    canonical_bytes = source_bytes.replace(bytes((13, 10)), bytes((10,))).replace(
        bytes((10,)), bytes((13, 10))
    )
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    if digest != entry["sha256"]:
        return None

    source_text = source_bytes.decode(entry["encoding"])
    source_rows = csv.DictReader(io.StringIO(source_text), delimiter=entry["delimiter"])
    points = []
    for row_number, row in enumerate(source_rows, start=1):
        if row_number not in (1, 2):
            continue
        try:
            x_value = float(row["FLEX Test #"])
            y_value = float(row["Burn time; s"])
        except (KeyError, ValueError):
            return None
        points.append(
            ChartPoint(
                x=x_value,
                y=y_value,
                trial_code=row["FLEX Identifier"],
                # TODO(PENDIENTE: Johan): agree the data_ref/evidence_id format.
                evidence_id=f"{PSI_CODE}:source_record:{row_number}",
            )
        )

    if len(points) != 2:
        return None

    return ChartData(
        chart_id=CHART_ID,
        type="bar",
        title="PSI-69 FLEX burn time by test",
        x_label="FLEX test number",
        y_label="Burn time",
        series=[
            ChartSeriesData(
                label="Burn time",
                unit="s",
                # Manifest-verified source rows have not been verified against DB.
                validated=False,
                points=points,
            )
        ],
    )
