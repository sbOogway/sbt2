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

The server must have the data of the spec in its catalog and the spec's venue
in its `venues.toml`.

## Write a strategy

Put each strategy in a module next to its notebook, as
[ema_cross.py](ema_cross.py) is for [ema_cross.ipynb](ema_cross.ipynb), and
give it to `lab.run` as `"module:Class"`. The lab sends the module's source to
the server and does not import it, so the module can import only what the
server has: sbt2, nautilus and the standard library.

The pre-commit hooks lint the modules with ruff and strip the outputs of the
notebooks.
