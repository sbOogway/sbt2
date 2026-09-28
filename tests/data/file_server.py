"""A local HTTP server for files, with faults scripted per path."""

import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FileServer:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.requests: Counter[str] = Counter()
        self._files: dict[str, bytes] = {}
        self._faults: dict[str, list[str | int]] = {}

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def serve(self, path: str, body: bytes) -> None:
        self._files[path] = body

    def fail(self, path: str, *faults: str | int) -> None:
        """Answer the next requests for ``path`` with these faults, in order.

        A fault is an HTTP status, or ``"truncate"`` for half the body before
        the connection closes.
        """
        self._faults[path] = list(faults)

    def file(self, path: str) -> bytes | None:
        return self._files.get(path)

    def next_fault(self, path: str) -> str | int | None:
        faults = self._faults.get(path)
        return faults.pop(0) if faults else None


def _handler(server: FileServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            server.requests[self.path] += 1
            fault = server.next_fault(self.path)
            body = server.file(self.path)
            if isinstance(fault, int):
                self.send_error(fault)
            elif body is None:
                self.send_error(404)
            elif fault == "truncate":
                self._send(body, body[: len(body) // 2])
            else:
                self._send(body, body)

        def _send(self, body: bytes, sent: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(sent)
            self.close_connection = len(sent) < len(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


@contextmanager
def file_server() -> Iterator[FileServer]:
    files = FileServer("")
    http = ThreadingHTTPServer(("127.0.0.1", 0), _handler(files))
    files.base_url = f"http://127.0.0.1:{http.server_port}"
    thread = threading.Thread(target=http.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield files
    finally:
        http.shutdown()
        http.server_close()
