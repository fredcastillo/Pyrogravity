"""Transactional, idempotent writes to the private AI knowledge base."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg

from pyrogravity_ai.ingestion.plan import PreparedIngestion


class IngestionPersistenceError(RuntimeError):
    """The plan could not be stored without exposing database details."""


class IngestionConflictError(IngestionPersistenceError):
    """Existing evidence differs from the prepared plan; manual reindexing is required."""


@dataclass(frozen=True)
class PersistenceResult:
    source_id: UUID
    document_id: UUID
    chunks_created: int
    embeddings_created: int


def _vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(repr(value) for value in values) + "]"


def persist_ingestion(plan: PreparedIngestion, connection: psycopg.Connection) -> PersistenceResult:
    """Store all five record types in one transaction; never overwrite reviewed evidence."""
    try:
        with connection.transaction():
            role = connection.execute(
                """SELECT rolsuper, rolbypassrls FROM pg_roles
                   WHERE rolname = current_user"""
            ).fetchone()
            owner = connection.execute(
                """SELECT c.relowner = current_user::regrole
                   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'ai' AND c.relname = 'sources'"""
            ).fetchone()
            if role is None or owner is None or any(role) or owner[0]:
                raise IngestionPersistenceError("A dedicated non-owner AI ingestion role is required")

            source = plan.source
            source_id_row = connection.execute(
                """INSERT INTO ai.sources (
                    source_key, repository, external_id, title, source_type,
                    publisher, authors, published_at, canonical_url, doi,
                    catalog_status, verified_at
                ) VALUES (
                    %s, 'ntrs', %s, %s, 'paper', %s, %s, %s, %s, %s,
                    'catalog_verified', now()
                ) ON CONFLICT (source_key) DO NOTHING RETURNING id""",
                (source.source_id, source.ntrs_id, source.title, source.publisher,
                 source.authors, source.publication_date, str(source.catalog_url), source.doi),
            ).fetchone()
            if source_id_row is None:
                existing = connection.execute(
                    """SELECT id, repository, external_id, title, source_type, publisher,
                              authors, published_at, canonical_url, doi, catalog_status
                       FROM ai.sources WHERE source_key = %s""",
                    (source.source_id,),
                ).fetchone()
                expected = (
                    "ntrs", source.ntrs_id, source.title, "paper", source.publisher,
                    source.authors, source.publication_date, str(source.catalog_url),
                    source.doi, "catalog_verified",
                )
                if existing is None or existing[1:] != expected:
                    raise IngestionConflictError("Existing source metadata differs from manifest")
                source_id = existing[0]
            else:
                source_id = source_id_row[0]

            document = plan.document
            filename = f"{source.ntrs_id}.pdf"
            original_url = str(source.document_url)
            document_id_row = connection.execute(
                """INSERT INTO ai.documents (
                    source_id, sha256, original_url, filename, version_label,
                    page_count, extraction_version, review_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'extracted')
                ON CONFLICT (source_id, sha256) DO NOTHING RETURNING id""",
                (source_id, document.sha256, original_url, filename,
                 source.document_version, len(document.pages), document.extraction_version),
            ).fetchone()
            if document_id_row is None:
                existing = connection.execute(
                    """SELECT id, original_url, filename, version_label, page_count,
                              extraction_version, review_status
                       FROM ai.documents WHERE source_id = %s AND sha256 = %s""",
                    (source_id, document.sha256),
                ).fetchone()
                expected = (
                    original_url, filename, source.document_version, len(document.pages),
                    document.extraction_version,
                )
                if (existing is None or existing[1:6] != expected
                        or existing[6] not in {"extracted", "reviewed"}):
                    raise IngestionConflictError("Existing document requires explicit reindexing")
                document_id = existing[0]
            else:
                document_id = document_id_row[0]

            chunks_created = 0
            embeddings_created = 0
            for chunk, vector in zip(plan.chunks, plan.embeddings, strict=True):
                chunk_id_row = connection.execute(
                    """INSERT INTO ai.document_chunks (
                        document_id, page_number, chunk_index, char_start, char_end,
                        content, content_sha256
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_id, page_number, chunk_index)
                    DO NOTHING RETURNING id""",
                    (document_id, chunk.page_number, chunk.chunk_index,
                     chunk.char_start, chunk.char_end, chunk.text, chunk.text_sha256),
                ).fetchone()
                if chunk_id_row is None:
                    existing = connection.execute(
                        """SELECT id, char_start, char_end, content, content_sha256
                           FROM ai.document_chunks
                           WHERE document_id = %s AND page_number = %s AND chunk_index = %s""",
                        (document_id, chunk.page_number, chunk.chunk_index),
                    ).fetchone()
                    if (existing is None or existing[1:] != (
                            chunk.char_start, chunk.char_end, chunk.text, chunk.text_sha256)):
                        raise IngestionConflictError("Existing chunk differs from prepared evidence")
                    chunk_id = existing[0]
                else:
                    chunk_id = chunk_id_row[0]
                    chunks_created += 1

                embedding_id_row = connection.execute(
                    """INSERT INTO ai.chunk_embeddings (
                        chunk_id, model_name, config_hash, dimensions, embedding
                    ) VALUES (%s, %s, %s, 1024, %s::extensions.vector)
                    ON CONFLICT (chunk_id, config_hash) DO NOTHING RETURNING id""",
                    (chunk_id, plan.model_name, plan.config_hash, _vector_literal(vector)),
                ).fetchone()
                if embedding_id_row is None:
                    existing = connection.execute(
                        """SELECT model_name, dimensions FROM ai.chunk_embeddings
                           WHERE chunk_id = %s AND config_hash = %s""",
                        (chunk_id, plan.config_hash),
                    ).fetchone()
                    if existing != (plan.model_name, 1024):
                        raise IngestionConflictError("Existing embedding configuration differs")
                else:
                    embeddings_created += 1

            connection.execute(
                """INSERT INTO ai.ingestion_jobs (
                    source_id, document_id, status, pipeline_version,
                    started_at, finished_at, chunks_created
                ) VALUES (%s, %s, 'succeeded', %s, now(), now(), %s)""",
                (source_id, document_id, plan.pipeline_version, chunks_created),
            )
            return PersistenceResult(
                source_id=source_id,
                document_id=document_id,
                chunks_created=chunks_created,
                embeddings_created=embeddings_created,
            )
    except psycopg.Error:
        raise IngestionPersistenceError("AI ingestion transaction failed") from None
