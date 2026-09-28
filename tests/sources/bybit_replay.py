"""A local HTTP server answering with Bybit responses recorded in ``bybit_responses.json``."""

import json
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

RECORDED = Path(__file__).with_name("bybit_responses.json")

type Key = tuple[str, frozenset[tuple[str, str]]]


def _key(target: str) -> Key:
    url = urlsplit(target)
    return url.path, frozenset(parse_qsl(url.query))


def _recorded() -> Mapping[Key, Any]:
    return {
        _key(each["request"]): each["response"]
        for each in json.loads(RECORDED.read_text())
    }


def _handler(responses: Mapping[Key, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
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
def bybit_replay() -> Iterator[str]:
    """Serve the recorded responses; yields the base URL to use as Bybit's API."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(_recorded()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
