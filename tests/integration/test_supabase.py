import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="requiere Supabase real o Postgres local via docker compose")
def test_integration_placeholder():
    pass
