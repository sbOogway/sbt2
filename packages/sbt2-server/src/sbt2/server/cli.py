import asyncio
import logging
import os
from contextlib import suppress
from typing import Annotated

import typer

from sbt2.server import Address, Server, Settings

HOST_ENV = "SBT2_SERVER_HOST"
PORT_ENV = "SBT2_SERVER_PORT"
CREDENTIAL_ENV = "SBT2_SERVER_TOKEN"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def main(
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
        asyncio.run(Server(Settings(token)).serve(Address(host, port)))


def _token() -> str:
    token = os.environ.get(CREDENTIAL_ENV, "")
    if not token:
        typer.echo(
            f"Error: set {CREDENTIAL_ENV} to the API token clients must present.",
            err=True,
        )
        raise typer.Exit(2)
    return token
