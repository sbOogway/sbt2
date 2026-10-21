LINE_LIMIT = 8192
MARKER = "…[truncated]"


class Lines:
    """Splits a job's output into lines of at most ``LINE_LIMIT`` bytes, the rest
    of a longer line replaced by a marker; a stream without a newline is held
    to that size too."""

    def __init__(self) -> None:
        self._line = b""
        self._cut = False

    def feed(self, chunk: bytes) -> list[str]:
        """The lines ``chunk`` completes."""
        *complete, rest = chunk.split(b"\n")
        done = []
        for piece in complete:
            self._add(piece)
            done.append(self._take())
        self._add(rest)
        return done

    def flush(self) -> list[str]:
        """The line the stream ended in, if any."""
        if not self._line and not self._cut:
            return []
        return [self._take()]

    def _add(self, piece: bytes) -> None:
        room = LINE_LIMIT - len(self._line)
        self._line += piece[:room]
        self._cut = self._cut or len(piece) > room

    def _take(self) -> str:
        text = self._line.decode(errors="replace").rstrip("\r")
        text += MARKER if self._cut else ""
        self._line, self._cut = b"", False
        return text
