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
- [sbt2-gui/](sbt2-gui): the GUI, written in Rust with
  [iced](https://iced.rs). Its [README](sbt2-gui/README.md) has the build.

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

### GUI

The GUI is for Linux x86_64. The maintainer builds it on Fedora 44, so the
binary needs a glibc as new as that machine's, glibc 2.43. On an older system,
build it from source (see [sbt2-gui/README.md](sbt2-gui/README.md)).
Download the tarball and `SHA256SUMS` from the release, then:

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

## Release

The maintainer cuts each release on their machine with `make release`. There is
no release in CI, and for now no CI: the tests run locally. The target refuses to start unless:

- `HEAD` is `origin/main` after a fetch, and the working tree is clean;
- `make check` passes.

It then tags each merge on `main` since the last tag with the version that
git-cliff picks from its Conventional Commits. A merge with no `feat`, `fix`,
`perf`, `refactor` or `revert` change gets no new version, so it gets no tag.
The newest tagged merge is the release; `VERSION=X.Y.Z` makes `HEAD` the
release with that version. The target refuses when there is nothing to release.
It builds the wheels, the GUI and the server image of the release, and
smoke-tests the GUI and the image. Only then does it draft the release, upload
the files and `SHA256SUMS`, and push the image as `:X.Y.Z` and `:latest`. Last,
it pushes the tags of the older merges and publishes. Publishing creates the
release's tag on GitHub. The older merges get a tag only; the notes of the
release list every change since the last release, by version. A failure before
the publish leaves a draft; a re-run finishes it.

After the publish, the target runs `podman auto-update` when the `sbt2-server`
user service exists, so the server on the maintainer's machine runs the new
image. A failed update only gives a warning.

The tokens come from the environment or from a git-ignored `.env` at the repo
root (mode 600). A variable set in the environment wins over `.env`:

```sh
GH_TOKEN=...    # or a gh login; can edit the releases
GHCR_TOKEN=...  # classic token with write:packages
```

To add the GUI or the image to an existing release, use `make release-gui` or
`make release-image`. They act on the newest `vX.Y.Z` tag; `TAG=vX.Y.Z` picks
another release. A target refuses when the release has its artifact already,
unless `FORCE=1`. Each builds the tag's commit in a temporary worktree.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
