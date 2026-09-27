# AGENTS.md

Rules for AI coding agents working on sbt2. Short and imperative on purpose: the reasons live in the
[wiki](https://github.com/sbOogway/sbt2/wiki), which is the design record. If this file and the wiki
disagree, stop and ask; don't pick one.

## Status

**Design phase. No code yet.** Don't create modules, scaffolding or packaging until the user
explicitly says planning is done. A request that *describes* modules is planning input, not an
instruction to build them.

## Documentation

- Architecture and design docs go in the **GitHub wiki** (`sbOogway/sbt2.wiki.git`), never in this
  repo: no `docs/`, `ARCHITECTURE.md` or ADR files. Docstrings and comments are fine.
- When a design decision changes, update the affected wiki pages in the same piece of work,
  including [Decisions](https://github.com/sbOogway/sbt2/wiki/Decisions) and the
  [C4 model](https://github.com/sbOogway/sbt2/wiki/C4-model) diagrams.
- Don't re-propose decisions the wiki records as rejected or removed (e.g. the test lockbox and
  OOS access log, results staging, a pre-flight memory estimate).

## Nautilus

- **Use nautilus wherever it already does the job**; write code only for real gaps. Before writing
  anything, check whether nautilus v2 has it (funding settlement, equity snapshots, bar
  aggregation, catalog writers, fill/fee/margin models, `RiskEngine`, reports, tearsheets).
- nautilus_trader is **pinned exactly** to `2.0.0rc6.dev20260927+18861`, from Nautech's index (see
  the wiki's [Quality](https://github.com/sbOogway/sbt2/wiki/Quality) page). Never loosen the pin.
  Upgrade only on request, and only when the golden-run and funding round-trip tests pass.
- **Never build nautilus from source** on the local machine; it runs out of memory. Use the
  prebuilt wheels.
- Verify nautilus APIs against the installed version (its `.pyi` stubs or a quick probe), not
  against docs or memory. Release candidates rename methods and change arguments between versions.
- No private nautilus internals. The one exception is the hand-written `FundingRateUpdate` catalog
  file, whose schema comes from `get_arrow_schema_bytes`.

## Architecture rules

- Six modules, one per thing owned: `data`, `spec`, `strategy`, `run`, `results`, `cli`. The CLI
  holds no logic. No class does more than one step.
- Dependencies point one way (see [Architecture](https://github.com/sbOogway/sbt2/wiki/Architecture)).
  No shared-types module; each type lives with its owner.
- The core never names a specific exchange or asset class. Exchange-specific code goes in
  `sources/*`, asset-class code in `assets/*`.
- `ingest` is the only catalog writer; everything else reads through `data`. `download` and
  `ingest` never import each other.
- `run.execute` runs one backtest in-process and knows nothing about processes, the CLI or storage.
  It writes only through the output sink interface.
- Keep the `ResultStore` and output sink interfaces, even with a single backend.

## Strategies

- A strategy is a **plain Python object**: `decide(state) → intents`, optionally `on_fill`. It never
  subclasses nautilus `Strategy`.
- Strategies may import nautilus **data types** (`OrderBook`, `Bar`, indicators) but **never** the
  engine, the clock or the order API. The adapter is the only nautilus `Strategy` subclass and holds
  no trading logic.
- Strategies never keep their own position state; positions and equity come from nautilus.
- Bounded state only: fixed-size buffers or nautilus indicators, never lists that grow for a run.
- Strategies live in `strategies/` and are referenced by import path. No registry.

## Correctness rules

- Costs belong in PnL: fees, slippage (never folded into fees) and carry (funding).
- Instruments are real specs, never guessed. Fail loudly when data doesn't fit the spec.
- Never fall back silently: no substitute instrument, no skipped data, no default when something
  is missing. Raise a typed error.
- No look-ahead. Bar strategies fill on the trades after the bar closes.
- Splits are explicit UTC half-open dates; metrics cover the segment only, never warm-up.
- Annualization comes from the asset class's calendar (365 days for crypto), never a hard-coded 252.
- L2 data is always streamed, never loaded whole.
- A failed run crashes the program with its error. No retries, no silent cleanup.

## Code

- Python, lint with `ruff` and type-check; both must pass before committing.
- Logging only: no `print` in library code.
- Tests use the synthetic dataset and run without network or downloaded data. Golden-run tests
  must keep producing the same numbers; update them only when a change is meant to alter results,
  and say so.
- CI is Woodpecker (self-hosted), not GitHub Actions. Don't add `.github/workflows`.

## Quant terms

The user wants quant jargon explained the first time it's used (e.g. embargo, beta, carry). The
wiki's [Glossary](https://github.com/sbOogway/sbt2/wiki/Glossary) has the definitions.
