from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Address:
    host: str
    port: int


@dataclass(frozen=True)
class HttpRequest:
    """What the server decides an HTTP request on, before any WebSocket upgrade."""

    method: str
    path: str
    authorization: str | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    text: str
    content_type: str = "text/plain; charset=utf-8"


class Channel(ABC):
    """One client's open WebSocket connection."""

    @abstractmethod
    def frames(self) -> AsyncIterator[bytes | str]:
        """The frames the client sends, binary as bytes and text as str, until the
        connection closes."""

    @abstractmethod
    async def send(self, frame: bytes) -> None:
        """Send ``frame`` as one binary frame; a closed channel drops it."""

    @abstractmethod
    async def close(self, code: int) -> None:
        """Close the connection with the WebSocket close ``code``."""


class Endpoint(ABC):
    """What the transport serves: it answers plain HTTP requests, picks the
    connections to upgrade and handles each one."""

    subprotocol: ClassVar[str]
    """The WebSocket subprotocol a client must ask for; any other handshake is
    refused with HTTP 400."""

    @abstractmethod
    def respond(self, request: HttpRequest) -> HttpResponse | None:
        """The response to ``request``, or None to go on with the upgrade."""

    @abstractmethod
    async def connected(self, channel: Channel) -> None:
        """Handle ``channel`` until it closes."""


class Transport(ABC):
    """Serves an endpoint over WebSocket on one address."""

    @abstractmethod
    def listening(
        self, address: Address, endpoint: Endpoint
    ) -> AbstractAsyncContextManager[Address]:
        """Serve ``endpoint`` on ``address`` while the context is open; it gives
        the address bound, whose port is a free one when ``address``'s is 0."""
