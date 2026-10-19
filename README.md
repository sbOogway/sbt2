<div align="center">

# sbt2

Backtesting framework on [nautilus_trader](https://nautilustrader.io), with a
server and a protocol for a GUI. The GUI lives on the
[`gui`](https://github.com/sbOogway/sbt2/tree/gui) branch.

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
- [sbt2-notebooks/](sbt2-notebooks): Jupyter notebooks that run strategies on
  the server. Its [README](sbt2-notebooks/README.md) shows how to start them.

## Install

Each [release](https://github.com/sbOogway/sbt2/releases) has the Python
distributions and `SHA256SUMS`, which covers every file of the
release. The notes name the server image with its digest.

### Server

The image is for x86_64. Pull it and run it with a token that clients must
present:

```sh
podman pull ghcr.io/sboogway/sbt2-server:latest
podman run -d -p 127.0.0.1:8765:8765 -e SBT2_SERVER_TOKEN=<token> \
  -v sbt2-data:/data -v sbt2-config:/config ghcr.io/sboogway/sbt2-server:latest
```

Use `:X.Y.Z` instead of `:latest` to pin a version. With
[sbt2-backend/compose.yaml](sbt2-backend/compose.yaml), set `SBT2_VERSION=X.Y.Z`
to run that version.

To run it as a rootless user service that follows `:latest`, use the Quadlet
unit [sbt2-backend/sbt2-server.container](sbt2-backend/sbt2-server.container):

```sh
mkdir -p ~/.config/containers/systemd ~/.config/sbt2
cp sbt2-backend/sbt2-server.container ~/.config/containers/systemd/
echo 'SBT2_SERVER_TOKEN=<token>' >~/.config/sbt2/server.env
chmod 600 ~/.config/sbt2/server.env
systemctl --user daemon-reload
systemctl --user start sbt2-server
loginctl enable-linger "$USER"  # keeps it running after logout
```

The server listens on `127.0.0.1:8765`. `podman auto-update` pulls a new
`:latest` and restarts the service. If the new image does not become healthy,
it rolls back to the old one.

The server speaks plain `ws://`, so publish its port only on loopback. For
remote access, open an SSH tunnel and point the client at it:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@host
export SBT2_SERVER_URL=ws://127.0.0.1:8765
```

## Development

```sh
make sync
make check
```

`make help` lists the other commands. Each component also keeps its own direct
commands, run from its directory.

## Release

The maintainer cuts each release on their machine in two steps: `make build`,
then `make publish`. `make release` runs both. There is no release in CI, and
for now no CI: the tests run locally.

`make build` refuses to start unless:

- `HEAD` is `origin/main` after a fetch, and the working tree is clean;
- `make check` passes.

It then plans a tag for each merge on `main` since the last tag, with the
version that git-cliff picks from its Conventional Commits. A merge with no
`feat`, `fix`, `perf`, `refactor` or `revert` change gets no new version, so it
gets no tag. The newest tagged merge is the release; `VERSION=X.Y.Z` makes
`HEAD` the release with that version. The target refuses when there is nothing
to release. It builds the wheels and the server image of the release,
and smoke-tests the image. It writes the files, `SHA256SUMS`, the
notes and the planned tags to the git-ignored `dist/release/`; the image stays
in the local podman store. Nothing leaves the machine.

`make publish` refuses unless `dist/release/` holds a build of the current
`origin/main`. It drafts the release, uploads the files and pushes the image as
`:X.Y.Z` and `:latest`. Last, it pushes the tags of the older merges and
publishes. Publishing creates the release's tag on GitHub. The older merges get
a tag only; the notes of the release list every change since the last release,
by version. A failure before the publish leaves a draft; a re-run of
`make publish` finishes it. After the publish, it removes `dist/release/`.

After the publish, `make publish` runs `podman auto-update` when the `sbt2-server`
user service exists, so the server on the maintainer's machine runs the new
image. A failed update only gives a warning.

The tokens come from the environment or from a git-ignored `.env` at the repo
root (mode 600). A variable set in the environment wins over `.env`:

```sh
GH_TOKEN=...    # or a gh login; can edit the releases
GHCR_TOKEN=...  # classic token with write:packages
```

To add the image to an existing release, use `make release-image`. It acts on
the newest `vX.Y.Z` tag; `TAG=vX.Y.Z` picks another release. It refuses when the
release has the image already, unless `FORCE=1`. It builds the tag's commit in a
temporary worktree.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
