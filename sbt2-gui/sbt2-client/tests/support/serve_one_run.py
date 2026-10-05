"""Stores one tiny run in DATA, writes its id to RUN_ID_FILE and serves DATA on PORT.

Usage, from the backend's environment: serve_one_run.py DATA CONFIG PORT RUN_ID_FILE
The server stops when its stdin closes, so it never outlives the test that started it.
The token comes from SBT2_SERVER_TOKEN. It reuses the server tests' kit to store the run.
"""

import os
import sys
import threading
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4] / "sbt2-backend"


def _test_folders() -> list[str]:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    folders = config["tool"]["pytest"]["ini_options"]["pythonpath"]
    return [str(BACKEND / folder) for folder in folders]


def _exit_when_stdin_closes() -> None:
    def watch() -> None:
        sys.stdin.read()
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def main(data: str, config: str, port: str, run_id_file: str) -> None:
    sys.path[:0] = _test_folders()
    # imported late: the test folders are on the path only now
    from results_kit import stored

    from sbt2.server.cli import app

    Path(config).mkdir(parents=True, exist_ok=True)
    run = stored(Path(data))
    Path(run_id_file).write_text(run.run_id)
    sys.argv = ["sbt2-server", "--data", data, "--config", config, "--port", port]
    _exit_when_stdin_closes()
    app()


if __name__ == "__main__":
    main(*sys.argv[1:5])
