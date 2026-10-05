<div align="center">

# sbt2

Backtesting framework on [nautilus_trader](https://nautilustrader.io), with a
server and a protocol for a future GUI.

[![CI](https://woodpecker.mattiapapaccioli.com/api/badges/1/status.svg)](https://woodpecker.mattiapapaccioli.com/repos/1)
[![codecov](https://codecov.io/gh/sbOogway/sbt2/graph/badge.svg)](https://codecov.io/gh/sbOogway/sbt2)
[![release](https://img.shields.io/github/v/release/sbOogway/sbt2)](https://github.com/sbOogway/sbt2/releases)
[![python](https://img.shields.io/pypi/pyversions/sbt2)](https://pypi.org/project/sbt2/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196.svg)](https://www.conventionalcommits.org)

</div>

## Components

- [sbt2-backend/](sbt2-backend): the Python distributions, the CLI and the
  server. Its [README](sbt2-backend/README.md) has the quick start.
- [sbt2-protocol/](sbt2-protocol): the protobuf messages between the server and
  its GUI. Its [README](sbt2-protocol/README.md) has the protocol rules.
- [sbt2-gui/](sbt2-gui): reserved for the GUI.

## Install

Each [release](https://github.com/sbOogway/sbt2/releases) has the Python
distributions, the Linux GUI and `SHA256SUMS`, which covers every file of the
release. The notes name the server image with its digest.

### Server

The image is for x86_64. Pull it and run it with a token that clients must
present:

```sh
podman pull ghcr.io/sboogway/sbt2-server:latest
podman run -d -p 8765:8765 -e SBT2_SERVER_TOKEN=<token> \
  -v sbt2-data:/data -v sbt2-config:/config ghcr.io/sboogway/sbt2-server:latest
```

Use `:X.Y.Z` instead of `:latest` to pin a version. With
[sbt2-backend/compose.yaml](sbt2-backend/compose.yaml), set `SBT2_VERSION=X.Y.Z`
to run that version.

### GUI

The GUI is for Linux x86_64 with glibc 2.36 or newer: Debian 12+, Ubuntu
23.04+ or Fedora 37+. Download the tarball and `SHA256SUMS` from the release,
then:

```sh
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf sbt2-gui-X.Y.Z-x86_64-linux.tar.gz
./sbt2-gui-X.Y.Z-x86_64-linux/sbt2-gui
```

## Development

```sh
make sync
make check
```

`make help` lists the other commands. Each component also keeps its own direct
commands, run from its directory.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
