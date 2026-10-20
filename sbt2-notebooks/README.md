# sbt2-notebooks

Jupyter notebooks that run strategies on an sbt2 server with
[sbt2-lab](../sbt2-backend/packages/sbt2-lab). The server runs the backtests;
this environment has only the lab client and JupyterLab, from the
`sbt2-backend/` of the same checkout.

## Run

From the repository root:

```sh
export SBT2_SERVER_TOKEN=<token>
export SBT2_SERVER_URL=ws://127.0.0.1:8765  # the default; localhost can resolve to IPv6, where the image does not listen
make notebooks
```

The server must have the data of the spec in its catalog. A spec names its fees
in `execution`.

## Layout

Each topic is a Python package. A notebook sits next to its strategy module.

```
sbt2-notebooks/
  trend/ema_cross.ipynb, ema_cross.py
  options/premium/iv_ranges, management, portfolio, eth_portfolio  (.ipynb and .py)
```

The environment installs this folder as an editable package, so a package path
such as `options.premium.portfolio` resolves from any kernel directory.

A new notebook goes in the package of its topic, for example `futures/` or
`vwap/` for a new topic. Give a new folder an `__init__.py` and add it to
`packages` in [pyproject.toml](pyproject.toml). The last part of a module path
is its name on the server, so keep it unique among the modules of one run.

## Write a strategy

Put each strategy in a module next to its notebook, as
[trend/ema_cross.py](trend/ema_cross.py) is for
[trend/ema_cross.ipynb](trend/ema_cross.ipynb), and give it to `lab.run` as
`"package.module:Class"`, for example `"trend.ema_cross:EmaCross"`. The lab
sends the module's source to the server and does not import it, so the module
can import only what the server has: sbt2, nautilus and the standard library.
It cannot import a sibling module.

A strategy that ships in `sbt2.strategies` needs only a module that imports it,
as [options/premium/management.py](options/premium/management.py) does for
[management.ipynb](options/premium/management.ipynb) (the management of a short
strangle, ch. 6 of *The Unlucky Investor's Guide to Options Trading*) and
[iv_ranges.py](options/premium/iv_ranges.py) for
[iv_ranges.ipynb](options/premium/iv_ranges.ipynb) (its trades by IV rank,
ch. 3). [portfolio.py](options/premium/portfolio.py) does so for
[portfolio.ipynb](options/premium/portfolio.ipynb) (a portfolio of laddered
strangles and iron condors against a single strangle, ch. 7-8). They need the
Deribit option data of 2024 and a year of DVOL before it on the server.

The pre-commit hooks lint the modules with ruff and strip the outputs of the
notebooks.
