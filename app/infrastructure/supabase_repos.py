"""PostgreSQL adapter; Supabase is consumed through its PostgreSQL endpoint."""
import psycopg
from psycopg.rows import dict_row
from app.domain.errors import RepositoryError

class PostgresDatasetReader:
    def __init__(self, connection):
        self.connection = connection

    def get(self, experiment_id):
        try:
            dataset_id = int(experiment_id)
        except (ValueError, TypeError):
            return None
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT dataset_id AS id, psi_code, relative_path, sha256, data_scope FROM scientific.datasets WHERE dataset_id = %s", (dataset_id,))
                return cursor.fetchone()
        except psycopg.Error:
            raise RepositoryError("Scientific dataset read failed") from None

    def list(self, page_size=100):
        if not isinstance(page_size, int) or not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT dataset_id AS id, psi_code, relative_path, sha256, data_scope FROM scientific.datasets ORDER BY dataset_id LIMIT %s", (page_size,))
                return cursor.fetchall()
        except psycopg.Error:
            raise RepositoryError("Scientific dataset read failed") from None

# Compatibility name; callers must supply a PostgreSQL connection, not a service-role SDK client.
SupabaseExperimentReader = PostgresDatasetReader
