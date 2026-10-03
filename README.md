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

## Development

```sh
make sync
make check
```

`make help` lists the other commands. Each component also keeps its own direct
commands, run from its directory.

## CI

Woodpecker checks all files changed in a pull request, not only its last commit.
The `selection` step lists each check and explains why it runs or is omitted.
Repo-wide text, config and shell hooks run on every pull request.

- Backend changes run backend lint, package tests, characterization tests and
  the container build. They do not run protocol tests or Rust checks.
- Protocol changes run protocol hooks, Python tests and Rust checks. They do
  not run backend tests or the container build.
- Backend or protocol changes also check the generated backend protocol code.
- Shared CI and hook config, `Makefile`, `.gitignore`, and root Python config
  run all area checks. The exact path lists are in `.woodpecker/ci.yaml`.
- Docs-only changes run the repo-wide hooks. An empty changed-file list runs
  all checks for safety.

Pushes to `main`, all tags and manual runs use the full check set. Releases
from `main` still wait for CI. `make check` always runs the full local check set.
The required `ci/woodpecker/pr/ci` status does not change.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
