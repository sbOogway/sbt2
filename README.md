<div align="center">

# sbt2

Backtesting framework on [nautilus_trader](https://nautilustrader.io).

[![CI](https://woodpecker.mattiapapaccioli.com/api/badges/1/status.svg)](https://woodpecker.mattiapapaccioli.com/repos/1)
[![codecov](https://codecov.io/gh/sbOogway/sbt2/graph/badge.svg)](https://codecov.io/gh/sbOogway/sbt2)
[![release](https://img.shields.io/github/v/release/sbOogway/sbt2)](https://github.com/sbOogway/sbt2/releases)
[![python](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/sbOogway/sbt2/main/pyproject.toml)](pyproject.toml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196.svg)](https://www.conventionalcommits.org)

</div>

## Quick start

```sh
uv sync
uv run sbt2 download --source bybit --symbol BTCUSDT --start 2025-01-01 --end 2025-03-01
uv run sbt2 ingest   --source bybit --symbol BTCUSDT --start 2025-01-01 --end 2025-03-01
uv run sbt2 run spec.toml
```

A spec describes the backtests to run:

```toml
strategy = "strategies.ma_cross:MovingAverageCross"
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

`sbt2 run` ends with the headline metrics of each part. Results are stored under `data/results`; list them with `uv run sbt2 runs list`, and write a run's tearsheet with `uv run sbt2 report tearsheet <run_id>`.

## License

sbt2 is licensed under the [GNU Lesser General Public License v3.0 or later](COPYING.LESSER), which builds on the [GNU General Public License v3.0](COPYING).
