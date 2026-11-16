"""Prove idempotent AI writes with RLS in a disposable local PostgreSQL 17 database."""

import hashlib
import json
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from pyrogravity_ai.database.ingestion_repository import (
    IngestionPersistenceError,
    persist_ingestion,
)
from pyrogravity_ai.ingestion.loader import LoadedDocument, PageText
from pyrogravity_ai.ingestion.plan import prepare_ingestion
from pyrogravity_ai.retrieval.evaluation import (
    EvaluationCase,
    EvaluationSet,
    evaluate_active_kb,
)
from pyrogravity_ai.retrieval.postgres import RetrievalError, search_hybrid, search_text, search_vector
from pyrogravity_ai.schemas.source import SourceRecord


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "20261115120000_ai_initial.sql"
KB_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "20261115123000_ai_kb_generations.sql"
CITATION_VIEW = Path(__file__).resolve().parents[1] / "migrations" / "20261115124500_ai_citation_passages.sql"


class FakeEmbedder:
    model_name = "embed-v5.0-fast"

    def embed_documents(self, texts):
        return [[float(index == 0), float(index == 1)] + [0.0] * 1022
                for index, _ in enumerate(texts)]

    def embed_query(self, text):
        return (1.0, 0.0) + (0.0,) * 1022


def _local_test_url() -> str:
    url = os.getenv("AI_SCHEMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AI_SCHEMA_TEST_DATABASE_URL no está configurada")
    parts = conninfo_to_dict(url)
    if (parts.get("host") not in {"localhost", "127.0.0.1", "::1"}
            or parts.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
            or parts.get("dbname") != "pyrogravity_ai_test"):
        pytest.fail("La prueba solo acepta la base local pyrogravity_ai_test")
    return url


def _plan(extraction_version: str = "pypdf-7.0.0-header-v1"):
    text = "Methanol combustion in microgravity"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    document = LoadedDocument(
        sha256=digest,
        pages=(PageText(1, text), PageText(2, "NASA droplet result")),
        size_bytes=len(text),
        extraction_version=extraction_version,
    )
    manifest = Path(__file__).resolve().parents[1] / "sources" / "ntrs_20130014061.json"
    values = json.loads(manifest.read_text(encoding="utf-8"))
    values["expected_document_sha256"] = digest
    source = SourceRecord.model_validate(values)
    return prepare_ingestion(source, document, FakeEmbedder())


def test_private_repository_is_idempotent_and_rejects_reextraction() -> None:
    url = _local_test_url()
    with psycopg.connect(url, prepare_threshold=None) as db:
        try:
            assert db.execute("SELECT to_regnamespace('ai')").fetchone()[0] is None
            db.execute("CREATE SCHEMA ai")
            db.execute("CREATE SCHEMA extensions")
            db.execute("CREATE EXTENSION vector WITH SCHEMA extensions")
            for role in ("anon", "authenticated", "service_role"):
                db.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            db.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)
            db.execute(KB_MIGRATION.read_text(encoding="utf-8"), prepare=False)
            db.execute(CITATION_VIEW.read_text(encoding="utf-8"), prepare=False)
            db.execute("CREATE ROLE ai_test_ingestor NOLOGIN NOSUPERUSER NOBYPASSRLS")
            db.execute("GRANT USAGE ON SCHEMA ai, extensions TO ai_test_ingestor")
            for table in (
                "sources", "documents", "document_chunks", "chunk_embeddings", "ingestion_jobs",
            ):
                db.execute(sql.SQL(
                    "GRANT SELECT, INSERT ON ai.{} TO ai_test_ingestor"
                ).format(sql.Identifier(table)))
            for table in ("kb_generations", "kb_generation_documents"):
                db.execute(sql.SQL(
                    "GRANT SELECT ON ai.{} TO ai_test_ingestor"
                ).format(sql.Identifier(table)))
            for table in (
                "sources", "documents", "document_chunks", "chunk_embeddings", "ingestion_jobs",
                "kb_generations", "kb_generation_documents", "kb_active",
            ):
                db.execute(sql.SQL(
                    "CREATE POLICY ingest_select ON ai.{} FOR SELECT TO ai_test_ingestor USING (true)"
                ).format(sql.Identifier(table)))
                db.execute(sql.SQL(
                    "CREATE POLICY ingest_insert ON ai.{} FOR INSERT TO ai_test_ingestor WITH CHECK (true)"
                ).format(sql.Identifier(table)))

            plan = _plan()
            with pytest.raises(IngestionPersistenceError, match="dedicated"):
                persist_ingestion(plan, db)

            db.execute("SET LOCAL ROLE ai_test_ingestor")
            first = persist_ingestion(plan, db)
            second = persist_ingestion(plan, db)
            assert first.source_id == second.source_id
            assert first.document_id == second.document_id
            assert (first.chunks_created, first.embeddings_created) == (2, 2)
            assert (second.chunks_created, second.embeddings_created) == (0, 0)
            assert db.execute("SELECT count(*) FROM ai.sources").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM ai.documents").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM ai.document_chunks").fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM ai.chunk_embeddings").fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM ai.ingestion_jobs").fetchone()[0] == 2
            assert db.execute("SELECT review_status FROM ai.documents").fetchone()[0] == "extracted"

            newer_plan = _plan("different-extractor-v2")
            newer = persist_ingestion(newer_plan, db)
            assert newer.document_id != first.document_id
            assert db.execute("SELECT count(*) FROM ai.ingestion_jobs").fetchone()[0] == 3

            db.execute("RESET ROLE")
            old_generation = db.execute(
                """INSERT INTO ai.kb_generations (version_label, config_hash)
                   VALUES ('baseline', %s) RETURNING id""", (plan.config_hash,)
            ).fetchone()[0]
            db.execute(
                """INSERT INTO ai.kb_generation_documents
                   (generation_id, source_id, document_id) VALUES (%s, %s, %s)""",
                (old_generation, first.source_id, first.document_id),
            )
            sealed_target_chunk = db.execute(
                "SELECT id FROM ai.document_chunks WHERE document_id = %s ORDER BY chunk_index LIMIT 1",
                (first.document_id,),
            ).fetchone()[0]
            unsealed_source_chunk = db.execute(
                "SELECT id FROM ai.document_chunks WHERE document_id = %s ORDER BY chunk_index LIMIT 1",
                (newer.document_id,),
            ).fetchone()[0]
            vector_literal = "[" + ",".join(repr(value) for value in plan.embeddings[0]) + "]"
            db.execute(
                """INSERT INTO ai.chunk_embeddings
                   (chunk_id, model_name, config_hash, dimensions, embedding)
                   VALUES (%s, %s, %s, 1024, %s::extensions.vector)""",
                (unsealed_source_chunk, plan.model_name, plan.config_hash, vector_literal),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="unreviewed"):
                with db.transaction():
                    db.execute("SELECT ai.seal_kb_generation(%s)", (old_generation,))
            db.execute(
                """UPDATE ai.documents SET review_status = 'reviewed', reviewed_at = now()
                   WHERE id = %s""", (first.document_id,)
            )
            with pytest.raises(psycopg.errors.RaiseException, match="sealed"):
                with db.transaction():
                    db.execute("INSERT INTO ai.kb_active (generation_id) VALUES (%s)",
                               (old_generation,))
            db.execute("SELECT ai.seal_kb_generation(%s)", (old_generation,))
            db.execute("SELECT ai.activate_kb_generation(%s)", (old_generation,))
            assert db.execute("SELECT count(*) FROM ai.citation_passages").fetchone()[0] == 2
            db.execute("CREATE ROLE ai_test_backend_reader NOLOGIN NOSUPERUSER NOBYPASSRLS")
            db.execute("GRANT USAGE ON SCHEMA ai TO ai_test_backend_reader")
            db.execute("GRANT SELECT ON ai.citation_passages TO ai_test_backend_reader")
            db.execute("SET LOCAL ROLE ai_test_backend_reader")
            assert db.execute(
                "SELECT count(*) FROM ai.citation_passages"
            ).fetchone()[0] == 2
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction():
                    db.execute("SELECT count(*) FROM ai.document_chunks")
            db.execute("RESET ROLE")
            with pytest.raises(psycopg.errors.RaiseException, match="Embedding in sealed"):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.chunk_embeddings
                           (chunk_id, model_name, config_hash, dimensions, embedding)
                           VALUES (%s, %s, %s, 1024, %s::extensions.vector)
                           ON CONFLICT (chunk_id, config_hash) DO UPDATE
                           SET chunk_id = %s""",
                        (unsealed_source_chunk, plan.model_name, plan.config_hash,
                         vector_literal, sealed_target_chunk),
                    )
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                with db.transaction():
                    db.execute("DELETE FROM ai.kb_generation_documents WHERE generation_id = %s",
                               (old_generation,))
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                with db.transaction():
                    db.execute("UPDATE ai.document_chunks SET content = 'altered' WHERE document_id = %s",
                               (first.document_id,))
            with pytest.raises(RetrievalError, match="dedicated"):
                search_text(db, "Methanol combustion")
            db.execute("CREATE ROLE ai_test_reader NOLOGIN NOSUPERUSER NOBYPASSRLS")
            db.execute("GRANT USAGE ON SCHEMA ai, extensions TO ai_test_reader")
            db.execute("""GRANT SELECT ON ai.sources, ai.documents,
                          ai.document_chunks, ai.chunk_embeddings,
                          ai.kb_generations, ai.kb_generation_documents,
                          ai.kb_active TO ai_test_reader""")
            for table in (
                "sources", "documents", "document_chunks", "chunk_embeddings",
                "kb_generations", "kb_generation_documents", "kb_active",
            ):
                db.execute(sql.SQL(
                    "CREATE POLICY reader_select ON ai.{} FOR SELECT TO ai_test_reader USING (true)"
                ).format(sql.Identifier(table)))
            db.execute("SET LOCAL ROLE ai_test_reader")

            text_hits = search_text(db, "Methanol combustion")
            vector_hits = search_vector(db, FakeEmbedder().embed_query("methanol"), plan.config_hash)
            hybrid_hits = search_hybrid(db, "Methanol combustion", FakeEmbedder(), plan.config_hash)
            assert text_hits[0].page_number == 1
            relaxed_text_hits = search_text(db, "Methanol droplet combustion")
            assert relaxed_text_hits[0].document_id == first.document_id
            assert vector_hits[0].page_number == 1
            assert hybrid_hits[0].page_number == 1
            assert all(hit.document_sha256 == plan.document.sha256 for hit in hybrid_hits)
            assert search_vector(db, FakeEmbedder().embed_query("methanol"), "0" * 64) == ()
            evaluation_set = EvaluationSet(
                source_id=plan.source.source_id,
                document_sha256=plan.document.sha256,
                extraction_version=plan.document.extraction_version,
                cases=[EvaluationCase(
                    case_id="methanol", question="Methanol combustion", language="en",
                    expected_passage_sha256=[plan.chunks[0].text_sha256],
                    review_status="reviewed",
                )],
            )
            comparison = evaluate_active_kb(evaluation_set, db, FakeEmbedder(), plan.config_hash)
            assert set(comparison) == {"text", "vector", "hybrid_rrf"}
            assert comparison["text"].metrics.hit_rate_at_k == 1.0
            assert comparison["vector"].cases[0].first_expected_rank == 1
            db.execute("RESET ROLE")
            db.execute(
                """UPDATE ai.documents SET review_status = 'reviewed', reviewed_at = now()
                   WHERE id = %s""", (newer.document_id,)
            )
            new_generation = db.execute(
                """INSERT INTO ai.kb_generations (version_label, config_hash)
                   VALUES ('new-extraction', %s) RETURNING id""", (newer_plan.config_hash,)
            ).fetchone()[0]
            db.execute(
                """INSERT INTO ai.kb_generation_documents
                   (generation_id, source_id, document_id) VALUES (%s, %s, %s)""",
                (new_generation, newer.source_id, newer.document_id),
            )
            db.execute("SELECT ai.seal_kb_generation(%s)", (new_generation,))
            db.execute("SELECT ai.activate_kb_generation(%s)", (new_generation,))
            assert db.execute("SELECT DISTINCT document_id FROM ai.citation_passages").fetchall() == [
                (newer.document_id,)
            ]
            db.execute("SET LOCAL ROLE ai_test_reader")
            assert search_text(db, "Methanol combustion")[0].document_id == newer.document_id
            assert search_vector(db, FakeEmbedder().embed_query("methanol"), plan.config_hash) == ()
            db.execute("RESET ROLE")
            db.execute("SELECT ai.activate_kb_generation(%s)", (old_generation,))
            assert db.execute("SELECT DISTINCT document_id FROM ai.citation_passages").fetchall() == [
                (first.document_id,)
            ]
            db.execute("SET LOCAL ROLE ai_test_reader")
            assert search_text(db, "Methanol combustion")[0].document_id == first.document_id
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction():
                    db.execute("SELECT count(*) FROM ai.ingestion_jobs")
        finally:
            db.rollback()
