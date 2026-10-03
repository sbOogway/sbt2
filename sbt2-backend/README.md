<div align="center">

# sbt2-backend

The Python distributions of [sbt2](https://github.com/sbOogway/sbt2): the backtesting framework on [nautilus_trader](https://nautilustrader.io), its CLI and its server.

[![CI](https://woodpecker.mattiapapaccioli.com/api/badges/1/status.svg)](https://woodpecker.mattiapapaccioli.com/repos/1)
[![codecov](https://codecov.io/gh/sbOogway/sbt2/graph/badge.svg)](https://codecov.io/gh/sbOogway/sbt2)
[![release](https://img.shields.io/github/v/release/sbOogway/sbt2)](https://github.com/sbOogway/sbt2/releases)
[![python](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/sbOogway/sbt2/main/sbt2-backend/pyproject.toml)](pyproject.toml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196.svg)](https://www.conventionalcommits.org)

</div>

## Install

For a Git install, run these commands in an empty directory:

```sh
uv venv --python 3.14
uv pip install 'sbt2[server] @ git+https://github.com/sbOogway/sbt2.git#subdirectory=sbt2-backend'
```

Use uv for this install. It gets the workspace members from the same Git
commit. Pip alone cannot install the meta distribution until its exact member
versions are available from a package registry. The build needs neither Buf
nor protoc.

## Quick start

From this directory:

```sh
uv sync
export SBT2_DATA=~/sbt2-data SBT2_CONFIG=~/sbt2-config
uv run sbt2 download --source bybit --symbol BTCUSDT --start 2025-01-01 --end 2025-03-01
uv run sbt2 ingest   --source bybit --symbol BTCUSDT --start 2025-01-01 --end 2025-03-01
uv run sbt2 run spec.toml
```

Every command reads and writes the data root `SBT2_DATA` names, or the folder `--data` gives: raw files in `raw/`, the catalog in `catalog/`, results in `results/`, and in `known_gaps.toml` the days a source confirmed it lacks.

`sbt2 run` also reads the config folder `SBT2_CONFIG` names, or the folder `--config` gives, on every run. sbt2 ships no venue profiles: write them to `venues.toml` in that folder, for example Bybit's USDT perpetuals at its base rates:

```toml
[bybit_linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fee_model = { kind = "maker_taker", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
```

A spec describes the backtests to run:

```toml
strategy = "sbt2.strategies.ma_cross:MovingAverageCross"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2025-01-01, 2025-03-01]
split = { validation_start = 2025-02-01, test_start = 2025-02-15 }
part = "train"
venue = "bybit_linear"
capital = "10000 USDT"
bars = "candles"

[params]
fast = 10
slow = 30
bar = "1-HOUR-LAST"
quantity = "0.100"
```

`sbt2 run` ends with the headline metrics of each part. Results are stored under `$SBT2_DATA/results`; list them with `uv run sbt2 runs list`, and write a run's tearsheet with `uv run sbt2 report tearsheet <run_id>`.

## Deployment

`Containerfile`, `compose.yaml` and `.dockerignore` live in this directory, which is the image's build context. From the repository root:

```sh
podman compose -f sbt2-backend/compose.yaml up -d --build
```

From this directory, `podman compose up -d --build` does the same. The image needs neither protocol generation nor a Git submodule.

## Development

For an editable checkout:

```sh
git clone https://github.com/sbOogway/sbt2.git
cd sbt2
make sync
```

`make sync` installs the backend members from `sbt2-backend/packages/` into
`sbt2-backend/.venv` as editable packages. The direct backend command is
`uv --directory sbt2-backend sync --locked`. Do not use an old root `.venv`.

From the repository root, `make test-backend` runs this suite and `make check` runs every check of the repository.

The server's protobuf messages live in [sbt2-protocol](../sbt2-protocol), in the same repository. The `generate-protocol` hook regenerates `sbt2-server`'s Python from them, offline with the locked `protoc` and `mypy-protobuf`, and fails when the committed code is stale.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
