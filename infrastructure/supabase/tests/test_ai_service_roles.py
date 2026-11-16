"""Apply the real migrations and check the proposed roles in an isolated database."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from pyrogravity_ai.database.ingestion_repository import persist_ingestion
from pyrogravity_ai.ingestion.loader import LoadedDocument, PageText
from pyrogravity_ai.ingestion.plan import prepare_ingestion
from pyrogravity_ai.retrieval.postgres import search_text, search_vector
from pyrogravity_ai.schemas.source import SourceRecord


ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "supabase/migrations"
AI = ROOT / "ai"
INGEST = "pyrogravity_ai_ingest"
RUNTIME = "pyrogravity_ai_runtime"
CITATION_READER = "pyrogravity_ai_citation_reader"
API_ROLES = ("anon", "authenticated", "service_role")
PASSAGE_TEXT = "Methanol droplet combustion in microgravity."
TEST_VECTOR = (1.0,) + (0.0,) * 1023


class FixedEmbedder:
    model_name = "embed-v5.0-fast"

    def embed_documents(self, texts):
        return [TEST_VECTOR for _ in texts]


def plan(version):
    digest = hashlib.sha256(PASSAGE_TEXT.encode()).hexdigest()
    source = json.loads((AI / "sources/ntrs_20130014061.json").read_text(encoding="utf-8"))
    source["expected_document_sha256"] = digest
    document = LoadedDocument(
        sha256=digest,
        pages=(PageText(1, PASSAGE_TEXT),),
        size_bytes=len(PASSAGE_TEXT),
        extraction_version=version,
    )
    return prepare_ingestion(SourceRecord.model_validate(source), document, FixedEmbedder())


@pytest.fixture
def db():
    dsn = os.environ.get("AI_SCHEMA_TEST_DATABASE_URL")
    if not dsn:
        pytest.fail("Falta AI_SCHEMA_TEST_DATABASE_URL para las pruebas obligatorias de permisos.", pytrace=False)
    target = conninfo_to_dict(dsn)
    if (target.get("host") not in {"127.0.0.1", "localhost", "::1"}
            or target.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
            or target.get("dbname") != "pyrogravity_ai_test"):
        pytest.fail("Usa una base de prueba local con el nombre pyrogravity_ai_test.", pytrace=False)

    with psycopg.connect(dsn, prepare_threshold=None) as connection:
        try:
            assert connection.execute("SELECT to_regnamespace('ai')").fetchone() == (None,)
            connection.execute("CREATE SCHEMA extensions")
            connection.execute("CREATE EXTENSION vector WITH SCHEMA extensions")
            for role in API_ROLES:
                connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))

            initial = SHARED / "20261115120000_ai_initial.sql"
            assert initial.read_bytes() == (AI / "migrations" / initial.name).read_bytes()
            migrations = (
                SHARED / "20261114230000_initial_schemas.sql",
                initial,
                AI / "migrations/20261115123000_ai_kb_generations.sql",
                AI / "migrations/20261115124500_ai_citation_passages.sql",
                ROOT / "infrastructure/supabase/proposals/ai_service_roles.sql",
            )
            for migration in migrations:
                connection.execute(migration.read_text(encoding="utf-8"), prepare=False)
            yield connection
        finally:
            connection.rollback()


@contextmanager
def as_role(connection, role):
    with connection.transaction():
        connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        yield
        connection.execute("RESET ROLE")


def denied(connection, statement, parameters=()):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute(statement, parameters)


def test_service_roles_chain_and_approved_citations(db):
    original_plan = plan("test-extraction-v1")
    alternate_plan = plan("test-extraction-v2")
    assert db.execute("""
        SELECT rolname FROM pg_roles
        WHERE rolname = ANY(%s) AND
            (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)
        """, ([INGEST, RUNTIME, CITATION_READER],)).fetchall() == []

    with as_role(db, INGEST):
        original = persist_ingestion(original_plan, db)
        repeated = persist_ingestion(original_plan, db)
        alternate = persist_ingestion(alternate_plan, db)
        assert original.chunks_created == 1
        assert repeated.chunks_created == repeated.embeddings_created == 0
        assert original.document_id == repeated.document_id != alternate.document_id
        generation, = db.execute("""
            INSERT INTO ai.kb_generations (version_label, config_hash)
            VALUES ('test-generation', %s) RETURNING id
            """, (original_plan.config_hash,)).fetchone()
        denied(db, "SELECT ai.seal_kb_generation(%s)", (generation,))
        denied(db, "SELECT ai.activate_kb_generation(%s)", (generation,))
        denied(db, "UPDATE ai.documents SET review_status = 'reviewed'")
        denied(db, "DELETE FROM ai.document_chunks")
        denied(db, "SELECT * FROM ai.citation_passages")
        denied(db, """
            INSERT INTO ai.documents (source_id, sha256, original_url, filename, page_count,
                                      extraction_version, review_status)
            VALUES (%s, repeat('f', 64), 'https://example.invalid/doc', 'synthetic.pdf', 1,
                    'test', 'reviewed')
            """, (original.source_id,))

    def evidence_counts():
        return db.execute("SELECT count(*) FROM ai.citation_passages").fetchone()[0]

    with as_role(db, CITATION_READER):
        assert evidence_counts() == 0

    db.execute("""
        INSERT INTO ai.kb_generation_documents (generation_id, source_id, document_id)
        VALUES (%s, %s, %s)
        """, (generation, original.source_id, original.document_id))
    with pytest.raises(psycopg.errors.RaiseException, match="unreviewed"), db.transaction():
        db.execute("SELECT ai.seal_kb_generation(%s)", (generation,))
    db.execute("""
        UPDATE ai.documents SET review_status = 'reviewed', reviewed_at = now() WHERE id = %s
        """, (original.document_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="sealed"), db.transaction():
        db.execute("SELECT ai.activate_kb_generation(%s)", (generation,))
    db.execute("SELECT ai.seal_kb_generation(%s)", (generation,))
    db.execute("SELECT ai.activate_kb_generation(%s)", (generation,))

    with as_role(db, RUNTIME):
        text, = search_text(db, "methanol")
        vector, = search_vector(db, TEST_VECTOR, original_plan.config_hash)
        assert text.passage_id == vector.passage_id
        assert text.document_id == original.document_id
        assert search_vector(db, TEST_VECTOR, alternate_plan.config_hash) == ()
        assert db.execute("SELECT id FROM ai.documents").fetchall() == [(original.document_id,)]
        assert len(db.execute("SELECT embedding FROM ai.chunk_embeddings").fetchall()) == 1
        denied(db, "SELECT storage_path FROM ai.documents")
        denied(db, "SELECT id FROM ai.ingestion_jobs")
        denied(db, "INSERT INTO ai.kb_active (generation_id) VALUES (%s)", (generation,))
        denied(db, "UPDATE ai.sources SET title = 'changed'")
        denied(db, "SELECT ai.activate_kb_generation(%s)", (generation,))

    with as_role(db, CITATION_READER):
        assert db.execute("""
            SELECT passage_id, document_id, page_number, passage_sha256
            FROM ai.citation_passages
            """).fetchall() == [(text.passage_id, original.document_id, 1, text.passage_sha256)]
        denied(db, "SELECT id FROM ai.documents")
        denied(db, "SELECT content FROM ai.document_chunks")
        denied(db, "SELECT embedding FROM ai.chunk_embeddings")
        denied(db, "DELETE FROM ai.citation_passages")

    for role in API_ROLES:
        with as_role(db, role):
            denied(db, "SELECT * FROM ai.citation_passages")
            denied(db, "SELECT * FROM ai.documents")
            denied(db, "SELECT embedding FROM ai.chunk_embeddings")

    # Removing approval also removes evidence from a generation that was already active.
    db.execute("UPDATE ai.documents SET review_status = 'rejected' WHERE id = %s", (original.document_id,))
    with as_role(db, CITATION_READER):
        assert evidence_counts() == 0
    with as_role(db, RUNTIME):
        assert search_text(db, "methanol") == ()
