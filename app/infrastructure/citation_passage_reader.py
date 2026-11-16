"""Read-only adapter for the approved ai.citation_passages private view."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


class CitationPassageReader:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def get(self, passage_id: str) -> dict[str, Any] | None:
        query = """
            SELECT passage_id::text, document_id::text, document_sha256, page_number,
                   passage_sha256, passage_text, source_id, source_title, source_url
            FROM ai.citation_passages
            WHERE passage_id = %s
        """
        try:
            with psycopg.connect(
                self.dsn,
                connect_timeout=5,
                options="-c default_transaction_read_only=on -c statement_timeout=8000",
                row_factory=dict_row,
            ) as connection:
                return connection.execute(query, (passage_id,)).fetchone()
        except psycopg.Error:
            raise RuntimeError("citation passage view unavailable") from None
