import json
import os

class DemoExperimentReader:
    def __init__(self, path="tests/fixtures/demo_experiments.json"):
        self.data = json.load(open(path)) if os.path.exists(path) else []

    def get(self, experiment_id):
        for e in self.data:
            if e["id"] == experiment_id:
                return e
        return None

    def list(self, page_size=100):
        return self.data[:page_size]

class DemoMeasurementReader:
    def __init__(self, path="tests/fixtures/demo_measurements.json"):
        self.data = json.load(open(path)) if os.path.exists(path) else []

    def list_by_experiment(self, experiment_id, page_size=1000):
        return [m for m in self.data if m["experiment_id"] == experiment_id][:page_size]

class DemoStatsReader:
    def __init__(self, path="tests/fixtures/demo_stats.json"):
        self.data = json.load(open(path)) if os.path.exists(path) else []

    def get_stats(self, experiment_id):
        return [s for s in self.data if s["experiment_id"] == experiment_id]

class DemoDocumentRetriever:
    def retrieve(self, question, k=5):
        return [{"passage_id": "p1", "text": "pasaje demo sintético", "document_id": "d1", "document_version": "v1", "source_id": "src1"}][:k]
