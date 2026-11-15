from app.domain.errors import RepositoryError


class SupabaseAnalysisCache:
    def __init__(self, client):
        self.client = client

    def get(self, key):
        try:
            r = self.client.table("ai_analyses").select("*").eq("id", key).execute()
            rows = r.data or []
            return rows[0] if rows else None
        except Exception as e:
            raise RepositoryError(str(e))

    def set(self, key, value):
        if value.get("status") != "ok":
            raise ValueError("solo respuestas ok validadas")
        try:
            self.client.table("ai_analyses").upsert({"id": key, **value}).execute()
        except Exception as e:
            raise RepositoryError(str(e))
