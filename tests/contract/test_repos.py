import pytest
from app.infrastructure.inmemory_repos import InMemoryExperimentReader
from app.infrastructure.demo_repos import DemoExperimentReader, DemoMeasurementReader

@pytest.mark.parametrize("repo", [InMemoryExperimentReader({}), DemoExperimentReader()])
def test_missing(repo):
    assert repo.get("nope") is None

def test_nulls():
    r = DemoMeasurementReader()
    # smoke
    assert isinstance(r.list_by_experiment("EXP-001"), list)
