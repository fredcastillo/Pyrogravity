"""Read-only PostgreSQL passage retrieval for the internal AI service."""

from __future__ import annotations

import re

import psycopg
from psycopg.conninfo import conninfo_to_dict

from pyrogravity_ai.database.connection import DatabaseSettings
from pyrogravity_ai.retrieval.postgres import (
    PassageHit,
    QueryEmbedder,
    RetrievalError,
    search_hybrid,
    search_text,
)


class PostgresPassageRetriever:
    """Open one short read-only session per request with a dedicated reader role."""

    def __init__(self, settings: DatabaseSettings, *, strategy: str = "text",
                 embedder: QueryEmbedder | None = None, config_hash: str | None = None) -> None:
        if strategy not in {"text", "hybrid"}:
            raise ValueError("unsupported retrieval strategy")
        if strategy == "hybrid" and (embedder is None or config_hash is None
                                     or re.fullmatch(r"[0-9a-f]{64}", config_hash) is None):
            raise ValueError("hybrid retrieval requires embedder and config hash")
        self._settings = settings
        self._strategy = strategy
        self._embedder = embedder
        self._config_hash = config_hash

    def retrieve(self, question: str, *, limit: int) -> tuple[PassageHit, ...]:
        url = self._settings.url.get_secret_value()
        parameters = conninfo_to_dict(url)
        sslmode = parameters.get("sslmode")
        if sslmode not in {"verify-ca", "verify-full"}:
            sslmode = "require"
        try:
            with psycopg.connect(
                url,
                connect_timeout=self._settings.connect_timeout_seconds,
                sslmode=sslmode,
                options="-c default_transaction_read_only=on -c statement_timeout=8000",
                prepare_threshold=None,
            ) as connection:
                if self._strategy == "hybrid":
                    return search_hybrid(connection, question, self._embedder,
                                         self._config_hash, limit=limit)
                return search_text(connection, question, limit=limit)
        except psycopg.Error:
            raise RetrievalError("AI passage retrieval failed") from None
