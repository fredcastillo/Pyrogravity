import io
import json
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.infrastructure import internal_ai_client
from infrastructure.aws import private_ai_handler


def test_private_backend_uses_signed_aws_invocation(monkeypatch):
    client = Mock()
    client.invoke.return_value = {"Payload": io.BytesIO(b'{"status":200,"response":{"claims":[]}}')}
    monkeypatch.setattr(internal_ai_client, "_lambda_client", lambda: client)
    arn = "arn:aws:lambda:us-east-1:123456789012:function:private-ai"
    response = internal_ai_client.LambdaInternalAiClient(arn).query({"question": "test"})
    assert response == {"claims": []}
    assert client.invoke.call_args.kwargs["FunctionName"] == arn
    assert json.loads(client.invoke.call_args.kwargs["Payload"]) == {
        "operation": "query", "request": {"question": "test"},
    }


@pytest.mark.parametrize("result,code", [
    ({"status": 504}, "timeout"),
    ({"status": 503}, "upstream_unavailable"),
    ({"status": 200, "response": []}, "invalid_response"),
])
def test_private_backend_maps_controlled_errors(monkeypatch, result, code):
    client = Mock()
    client.invoke.return_value = {"Payload": io.BytesIO(json.dumps(result).encode())}
    monkeypatch.setattr(internal_ai_client, "_lambda_client", lambda: client)
    with pytest.raises(internal_ai_client.AiUpstreamError, match=code):
        internal_ai_client.LambdaInternalAiClient("private-ai").query({})


def test_probe_reports_unconfigured_secret_and_uses_an_exact_pdf_key(monkeypatch):
    secret = Mock()
    secret.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "not configured"}}, "GetSecretValue",
    )
    s3 = Mock()
    monkeypatch.setattr(private_ai_handler, "aws_client", {"secretsmanager": secret, "s3": s3}.__getitem__)
    monkeypatch.setenv("RUNTIME_SECRET_ARN", "runtime-secret")
    monkeypatch.setenv("CORPUS_BUCKET", "private-corpus")
    sha = "a" * 64
    assert private_ai_handler.handler({"operation": "probe", "pdf_sha256": sha}, None) == {
        "status": 200, "transport": "iam", "credentials_configured": False, "pdf_readable": True,
    }
    s3.head_object.assert_called_once_with(Bucket="private-corpus", Key=f"pdf/{sha}.pdf")
    assert private_ai_handler.handler({"operation": "probe", "pdf_sha256": "../not-a-pdf"}, None) == {"status": 422}
