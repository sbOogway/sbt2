import pytest

from sbt2.server import BearerToken

TOKEN = "s3cret-token"


@pytest.mark.unit
def test_the_configured_token_is_accepted() -> None:
    assert BearerToken(TOKEN).admits(f"Bearer {TOKEN}")


@pytest.mark.unit
@pytest.mark.parametrize(
    "header",
    [f"Bearer {TOKEN}x", "Bearer ", None, f"Basic {TOKEN}", TOKEN],
    ids=["wrong token", "empty token", "no header", "basic scheme", "no scheme"],
)
def test_a_wrong_or_missing_token_is_refused(header: str | None) -> None:
    assert not BearerToken(TOKEN).admits(header)
