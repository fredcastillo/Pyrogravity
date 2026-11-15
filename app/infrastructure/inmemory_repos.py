

class InMemoryExperimentReader:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, experiment_id):
        return self.data.get(experiment_id)

    def list(self, page_size=100):
        return list(self.data.values())[:page_size]
