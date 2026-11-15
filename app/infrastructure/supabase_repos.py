from app.domain.errors import RepositoryError


class SupabaseExperimentReader:
    def __init__(self, client):
        self.client = client

    def get(self, experiment_id):
        try:
            r = self.client.table("experiments").select("*").eq("id", experiment_id).execute()
            rows = r.data or []
            return rows[0] if rows else None
        except Exception as e:
            raise RepositoryError(str(e))

    def list(self, page_size=100):
        try:
            r = self.client.table("experiments").select("*").limit(page_size).execute()
            return r.data or []
        except Exception as e:
            raise RepositoryError(str(e))
