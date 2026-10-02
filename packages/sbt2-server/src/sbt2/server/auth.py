import hmac


class BearerToken:
    """The API token a client presents as ``Authorization: Bearer <token>``."""

    def __init__(self, token: str) -> None:
        self._token = token.encode()

    def admits(self, authorization: str | None) -> bool:
        """Whether the ``Authorization`` header carries this token."""
        scheme, _, presented = (authorization or "").partition(" ")
        matches = hmac.compare_digest(presented.encode(), self._token)
        return scheme.lower() == "bearer" and matches
