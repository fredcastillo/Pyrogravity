from app.domain.ai_contract import Evidence


def test_traceability():
    ev = Evidence(experiment_id="EXP-001", variable="v", metric="mean", value=1.0, unit="m/s", dataset_id="ds1", dataset_version="v1", trial_id="t1", source_row_ref=None, source_id="src1")
    assert ev.dataset_id == "ds1" and ev.dataset_version == "v1" and ev.trial_id == "t1" and ev.source_row_ref is None
