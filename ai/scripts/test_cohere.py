"""Manual Cohere connectivity check; uses one small API request."""

from pyrogravity_ai.config import ConfigurationError, Settings
from pyrogravity_ai.llm.cohere_client import CohereResponseError, CohereServiceError, CohereTextClient


def main() -> int:
    try:
        settings = Settings.from_environment()
        answer = CohereTextClient(settings).generate("Reply with the single word OK.")
    except (ConfigurationError, CohereServiceError, CohereResponseError) as exc:
        print(f"Cohere connectivity check failed: {exc}")
        return 1

    print(f"Cohere connectivity check passed using model {settings.model}: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
