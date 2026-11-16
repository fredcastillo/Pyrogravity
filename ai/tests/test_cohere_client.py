from types import SimpleNamespace

import pytest
from cohere.core import ApiError
from httpx import TimeoutException


class FakeCohereClient:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def settings():
    from pyrogravity_ai.config import Settings

    return Settings.from_environment(
        environ={"COHERE_API_KEY": "test-secret", "COHERE_MODEL": "chosen-model"}
    )


def response(text: str, finish_reason: str = "COMPLETE"):
    return SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=[SimpleNamespace(type="text", text=text)]),
    )


def test_generate_uses_configured_model_and_returns_text() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereTextClient

    fake = FakeCohereClient(response=response("A supported explanation."))
    result = CohereTextClient(settings(), client=fake).generate("Explain this observation")

    assert result == "A supported explanation."
    assert fake.calls == [
        {
            "model": "chosen-model",
            "messages": [{"role": "user", "content": "Explain this observation"}],
            "max_tokens": 512,
            "temperature": 0,
        }
    ]


def test_blank_prompt_is_rejected_before_api_call() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereTextClient

    fake = FakeCohereClient(response=response("unused"))
    with pytest.raises(ValueError, match="prompt"):
        CohereTextClient(settings(), client=fake).generate("   ")
    assert fake.calls == []


def test_json_generation_requests_provider_json_mode() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereTextClient

    fake = FakeCohereClient(response=response('{"selected_ids":[]}'))
    result = CohereTextClient(settings(), client=fake).generate_json("Return JSON evidence IDs")
    assert result == '{"selected_ids":[]}'
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_provider_error_is_sanitized_and_classified() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereServiceError, CohereTextClient

    fake = FakeCohereClient(error=ApiError(status_code=429, body="test-secret"))
    with pytest.raises(CohereServiceError) as captured:
        CohereTextClient(settings(), client=fake).generate("Hello")

    assert captured.value.kind == "rate_limit"
    assert captured.value.retryable is True
    assert "test-secret" not in str(captured.value)


def test_timeout_is_reported_as_retryable() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereServiceError, CohereTextClient

    fake = FakeCohereClient(error=TimeoutException("timed out"))
    with pytest.raises(CohereServiceError) as captured:
        CohereTextClient(settings(), client=fake).generate("Hello")
    assert captured.value.kind == "timeout"
    assert captured.value.retryable is True


def test_incomplete_generation_is_not_returned_as_complete_answer() -> None:
    from pyrogravity_ai.llm.cohere_client import CohereResponseError, CohereTextClient

    fake = FakeCohereClient(response=response("partial text", "MAX_TOKENS"))
    with pytest.raises(CohereResponseError, match="incomplete"):
        CohereTextClient(settings(), client=fake).generate("Hello")
