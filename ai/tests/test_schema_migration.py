"""Database behavior of the AI migration in an explicitly disposable local PG17 DB."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20261115120000_ai_initial.sql"
)


def _local_test_url() -> str:
    url = os.getenv("AI_SCHEMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AI_SCHEMA_TEST_DATABASE_URL no está configurada")
    parts = conninfo_to_dict(url)
    if (
        parts.get("host") not in {"localhost", "127.0.0.1", "::1"}
        or parts.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
        or parts.get("dbname") != "pyrogravity_ai_test"
    ):
        pytest.fail("La prueba solo acepta la base local pyrogravity_ai_test")
    return url


def test_migration_provenance_constraints_and_private_access() -> None:
    url = _local_test_url()
    with psycopg.connect(url, prepare_threshold=None) as db:
        try:
            version = db.execute("SHOW server_version_num").fetchone()[0]
            assert 170000 <= int(version) < 180000, "La prueba requiere PostgreSQL 17"
            assert db.execute("SELECT to_regnamespace('ai')").fetchone()[0] is None

            db.execute("CREATE SCHEMA ai")
            db.execute("CREATE SCHEMA IF NOT EXISTS extensions")
            db.execute("CREATE EXTENSION vector WITH SCHEMA extensions")
            for role in ("anon", "authenticated", "service_role"):
                if not db.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
                ).fetchone():
                    db.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
            db.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)

            tables = db.execute(
                """SELECT c.relname, c.relrowsecurity
                   FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'ai' AND c.relkind = 'r'
                   ORDER BY c.relname"""
            ).fetchall()
            assert tables == [
                ("chunk_embeddings", True),
                ("document_chunks", True),
                ("documents", True),
                ("ingestion_jobs", True),
                ("sources", True),
            ]
            assert db.execute(
                "SELECT count(*) FROM pg_policies WHERE schemaname = 'ai'"
            ).fetchone()[0] == 0
            for role in ("anon", "authenticated", "service_role"):
                assert not db.execute(
                    "SELECT has_schema_privilege(%s, 'ai', 'USAGE')", (role,)
                ).fetchone()[0]

            source_id = db.execute(
                """INSERT INTO ai.sources (
                    source_key, repository, external_id, title, source_type,
                    publisher, authors, canonical_url, catalog_status, verified_at
                ) VALUES (
                    'ntrs:20130014061', 'ntrs', '20130014061',
                    'Methanol Droplet Combustion', 'paper', 'NASA',
                    ARRAY['Vedha Nayagam'], 'https://ntrs.nasa.gov/citations/20130014061',
                    'catalog_verified', now()
                ) RETURNING id"""
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.UniqueViolation):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.sources (
                            source_key, repository, external_id, title, source_type,
                            publisher, authors, canonical_url
                        ) VALUES (
                            'ntrs:duplicate', 'ntrs', '20130014061', 'Duplicate',
                            'paper', 'NASA', ARRAY['Author'], 'https://ntrs.nasa.gov'
                        )"""
                    )

            with pytest.raises(psycopg.errors.CheckViolation):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.documents (
                            source_id, sha256, original_url, filename, page_count
                        ) VALUES (%s, %s, 'https://ntrs.nasa.gov/file.pdf', 'file.pdf', 11)""",
                        (source_id, "invalid-hash"),
                    )
            document_id = db.execute(
                """INSERT INTO ai.documents (
                    source_id, sha256, original_url, filename, page_count,
                    extraction_version, review_status, reviewed_at
                ) VALUES (
                    %s, %s, 'https://ntrs.nasa.gov/file.pdf', 'file.pdf', 11,
                    'pypdf-7.0.0-header-v1', 'reviewed', now()
                ) RETURNING id""",
                (source_id, "a" * 64),
            ).fetchone()[0]

            content = "microgravity combustion"
            chunk_id = db.execute(
                """INSERT INTO ai.document_chunks (
                    document_id, page_number, chunk_index, char_start, char_end,
                    content, content_sha256
                ) VALUES (%s, 1, 0, 0, %s, %s, %s) RETURNING id""",
                (
                    document_id,
                    len(content),
                    content,
                    hashlib.sha256(content.encode()).hexdigest(),
                ),
            ).fetchone()[0]
            assert db.execute(
                """SELECT content_tsv @@ plainto_tsquery('english', 'combustion')
                   FROM ai.document_chunks WHERE id = %s""",
                (chunk_id,),
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.document_chunks (
                            document_id, page_number, chunk_index, char_start,
                            char_end, content, content_sha256
                        ) VALUES (%s, 1, 1, 0, 2, %s, %s)""",
                        (document_id, content, "b" * 64),
                    )

            embedding = "[" + ",".join(["1"] + ["0"] * 1023) + "]"
            db.execute(
                """INSERT INTO ai.chunk_embeddings (
                    chunk_id, model_name, config_hash, embedding
                ) VALUES (%s, 'embed-v5.0-fast', %s, %s::extensions.vector)""",
                (chunk_id, "c" * 64, embedding),
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.chunk_embeddings (
                            chunk_id, model_name, config_hash, embedding
                        ) VALUES (%s, 'embed-v5.0-fast', %s, %s::extensions.vector)""",
                        (chunk_id, "d" * 64, "[" + ",".join(["0"] * 1024) + "]"),
                    )

            other_source_id = db.execute(
                """INSERT INTO ai.sources (
                    source_key, repository, external_id, title, source_type,
                    publisher, authors, canonical_url
                ) VALUES (
                    'ntrs:other', 'ntrs', 'other', 'Other paper', 'paper',
                    'NASA', ARRAY['Author'], 'https://ntrs.nasa.gov'
                ) RETURNING id"""
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with db.transaction():
                    db.execute(
                        """INSERT INTO ai.ingestion_jobs (
                            source_id, document_id, pipeline_version
                        ) VALUES (%s, %s, 'v1')""",
                        (other_source_id, document_id),
                    )
        finally:
            db.rollback()
