import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer

from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import Capability
from sbt2.server import Address, Server, Settings
from sbt2.server.results import routes

HOST_ENV = "SBT2_SERVER_HOST"
PORT_ENV = "SBT2_SERVER_PORT"
CREDENTIAL_ENV = "SBT2_SERVER_TOKEN"
DATA_ROOT_ENV = "SBT2_DATA"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def main(
    data_root: Annotated[
        Path,
        typer.Option(
            "--data",
            envvar=DATA_ROOT_ENV,
            show_envvar=True,
            help="Serves the results in PATH/results, priced from PATH/catalog.",
        ),
    ],
    host: Annotated[
        str,
        typer.Option(envvar=HOST_ENV, show_envvar=True, help="The address to bind."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(envvar=PORT_ENV, show_envvar=True, help="The port to listen on."),
    ] = 8765,
) -> None:
    """Serve sbt2 to its GUI over WebSocket; clients must present the API token
    in SBT2_SERVER_TOKEN."""
    token = _token()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    with suppress(KeyboardInterrupt):
        asyncio.run(_server(token, Root(data_root)).serve(Address(host, port)))


def _server(token: str, root: Root) -> Server:
    return Server(Settings(token), routes(root), [Capability.CAPABILITY_RESULTS])


def _token() -> str:
    token = os.environ.get(CREDENTIAL_ENV, "")
    if not token:
        typer.echo(
            f"Error: set {CREDENTIAL_ENV} to the API token clients must present.",
            err=True,
        )
        raise typer.Exit(2)
    return token
