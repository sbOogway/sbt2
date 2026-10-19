"""A local HTTP server answering with responses recorded in a JSON file."""

import json
import threading
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

type Key = tuple[str, frozenset[tuple[str, str]]]


@dataclass
class Replay:
    """The base URL of the server, and the request targets it has been asked for."""

    url: str
    requests: list[str] = field(default_factory=list)


def _key(target: str) -> Key:
    url = urlsplit(target)
    return url.path, frozenset(parse_qsl(url.query))


def _recorded(recorded: Path | Sequence[Mapping[str, Any]]) -> Mapping[Key, Any]:
    entries = (
        json.loads(recorded.read_text()) if isinstance(recorded, Path) else recorded
    )
    return {_key(each["request"]): each["response"] for each in entries}


def _handler(
    responses: Mapping[Key, Any], requests: list[str]
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            response = responses.get(_key(self.path))
            if response is None:
                self.send_error(404, f"nothing recorded for {self.path}")
                return
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


@contextmanager
def replay(recorded: Path | Sequence[Mapping[str, Any]]) -> Generator[Replay]:
    """Serve the responses recorded in ``recorded``, a JSON file or its entries,
    keyed by request target."""
    requests: list[str] = []
    handler = _handler(_recorded(recorded), requests)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield Replay(f"http://127.0.0.1:{server.server_port}", requests)
    finally:
        server.shutdown()
        server.server_close()
