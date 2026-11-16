"""Rerank only retrieved, immutable passages; never accept generated evidence."""
from dataclasses import replace
import math

import cohere
from cohere.core import ApiError
from httpx import HTTPError

from pyrogravity_ai.llm.cohere_client import CohereServiceError
from pyrogravity_ai.retrieval.postgres import RetrievalError


class CohereReranker:
    def __init__(self, settings, model: str):
        self.model = model
        self.client = cohere.ClientV2(api_key=settings.api_key.get_secret_value(),
                                      timeout=settings.timeout_seconds, max_retries=settings.max_retries)

    def rank(self, question, hits, *, limit):
        if not hits:
            return ()
        try:
            response = self.client.rerank(model=self.model, query=question,
                documents=[f"{hit.source_title}\nPage {hit.page_number}\n{hit.passage_text}" for hit in hits],
                top_n=min(limit, len(hits)))
        except (ApiError, HTTPError):
            raise CohereServiceError("rerank_unavailable", retryable=True) from None
        ranked, seen = [], set()
        for item in response.results:
            if (type(item.index) is not int or not 0 <= item.index < len(hits)
                    or item.index in seen or not math.isfinite(item.relevance_score)):
                raise RetrievalError("Rerank returned an invalid passage index or score")
            seen.add(item.index)
            ranked.append(replace(hits[item.index], score=float(item.relevance_score)))
        if not ranked or len(ranked) > limit:
            raise RetrievalError("Rerank returned an invalid result count")
        return tuple(ranked)
