"""IAM-authenticated Lambda entry point for the private v1.1 AI engine."""

import json
import logging
import os
import re
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from pyrogravity_ai.config import ConfigurationError
from pyrogravity_ai.core.engine import EvidenceError
from pyrogravity_ai.database.connection import DatabaseConfigurationError
from pyrogravity_ai.llm.cohere_client import CohereResponseError, CohereServiceError
from pyrogravity_ai.llm.cohere_embed import CohereEmbeddingResponseError
from pyrogravity_ai.retrieval.postgres import RetrievalError
from pyrogravity_ai.schemas.contracts_v11 import AiQueryRequest
from pyrogravity_ai.service.app import build_engine

LOG = logging.getLogger(__name__)
AWS_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2})


@lru_cache
def aws_client(service):
    return boto3.client(service, config=AWS_CONFIG)


def runtime_settings():
    response = aws_client("secretsmanager").get_secret_value(SecretId=os.environ["RUNTIME_SECRET_ARN"])
    value = json.loads(response["SecretString"])
    if not isinstance(value, dict) or not all(isinstance(entry, str) for entry in value.values()):
        raise ConfigurationError("Invalid secret configuration")
    return value


def probe(pdf_sha256):
    result = {"status": 200, "transport": "iam", "credentials_configured": False}
    try:
        build_engine(runtime_settings())
        result["credentials_configured"] = True
    except (BotoCoreError, ClientError, ConfigurationError, DatabaseConfigurationError, KeyError, ValueError):
        pass
    if pdf_sha256 is not None:
        if not isinstance(pdf_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", pdf_sha256):
            return {"status": 422}
        try:
            aws_client("s3").head_object(Bucket=os.environ["CORPUS_BUCKET"], Key=f"pdf/{pdf_sha256}.pdf")
            result["pdf_readable"] = True
        except (BotoCoreError, ClientError):
            result["pdf_readable"] = False
    return result


def handler(event, _context):
    if not isinstance(event, dict):
        return {"status": 422}
    if event.get("operation") == "probe":
        return probe(event.get("pdf_sha256"))
    if event.get("operation") != "query":
        return {"status": 422}
    try:
        request = AiQueryRequest.model_validate(event.get("request"))
    except ValidationError:
        return {"status": 422}
    try:
        result = build_engine(runtime_settings()).answer(request)
        return {"status": 200, "response": result.model_dump(mode="json")}
    except CohereServiceError as failure:
        return {"status": 504 if failure.kind == "timeout" else 503}
    except (CohereResponseError, CohereEmbeddingResponseError, EvidenceError):
        return {"status": 502}
    except (BotoCoreError, ClientError, ConfigurationError, DatabaseConfigurationError, RetrievalError, ValueError):
        LOG.warning("AI dependency unavailable request_id=%s", request.request_id)
        return {"status": 503}
