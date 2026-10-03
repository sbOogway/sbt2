# sbt2-protocol

The protobuf messages between the [sbt2](https://github.com/sbOogway/sbt2) server and its GUI, sent one per binary WebSocket frame.

- `sbt2/protocol/v1/`: the `sbt2.protocol.v1` package. `envelope.proto` holds `ClientMessage` and `ServerMessage`, the envelope of every frame; `types.proto` the shared messages.
- [sbt2-backend](../sbt2-backend) generates its Python from these messages, offline with its locked `protoc`; the GUI generates its Rust types with `prost`.

## Rules

- Prices, quantities and money are decimal strings, never `double`; timestamps are `google.protobuf.Timestamp`.
- A field where "unset" differs from zero or empty is proto3 `optional`.
- Removed fields are `reserved`, and their numbers never reused.
- A breaking change needs a new package (`sbt2.protocol.v2`).

## Results

`CAPABILITY_RESULTS` advertises lists, summaries, metrics, Arrow series and HTML
tearsheets. `GetRun` has one `run_summary` response. The other results requests
have numbered responses starting at index zero, all carrying the request's ID
and no subscription ID. Exactly one chunk has `last = true`, including for an
empty result. Responses to different requests may interleave; clients must use
distinct IDs for outstanding requests. A correlated `Error` terminates the
response and invalidates its partial chunks.

Each complete serialized envelope is at most 1,048,576 bytes. List and metric
chunks contain whole records; an individual record that cannot fit returns
`RESOURCE_EXHAUSTED`. Lists preserve the store's oldest-first ordering.
Concatenate byte chunks before interpreting the Arrow IPC stream or UTF-8 HTML.
Chunk boundaries need not align with Arrow records or UTF-8 characters.

Equity is the core's settlement-currency curve on the run's time grid, including
its endpoints. Its Arrow columns are `timestamp` (UTC nanoseconds), `currency`
(string) and `equity` (float64, as calculated by core). Fills retain the stored
report's rows, columns, types and index, with Arrow's pandas metadata describing
the index. These Arrow payloads are distinct from the protobuf decimal-string
convention. Summary `params_json` and `split_json` retain the stored JSON
documents; undefined metric values are absent optional strings, not zero.

An absent benchmark selection, `UNSPECIFIED`, or `DEFAULT` uses the strategy's
benchmark, matching the CLI. Explicit choices are `NONE`, `BUY_AND_HOLD` and
`EQUAL_WEIGHT`; only buy-and-hold accepts an instrument ID. External benchmark
uploads are not part of this API. Missing default-benchmark dependencies cause
an error, without silently changing the benchmark.

## Golden fixtures

`golden/<area>/<case>.textproto` is an example message, starting with a `# proto-message: sbt2.protocol.v1.<Message>` header, and `<case>.binpb` its encoding. Every `ClientMessage` and `ServerMessage` body has at least one.

- Only `scripts/golden.sh` writes a `.binpb`, with `buf convert`; edit the textproto and run it.
- A fixture is never deleted or edited once committed, so messages written today keep decoding as intended.

## Checks

From the repository root, [prek](https://github.com/j178/prek) runs `buf format`, `buf lint`, `buf breaking` against `sbt2-protocol/` on this repository's `main`, and fails when a `.binpb` is stale. `make check` runs the hooks and both components' tests; `make test-protocol` runs the tests below alone.

- `tests/` (pytest, with `uv`): the rules above that buf lint does not check, over buf's descriptor set; and every fixture decodes with Python's `protobuf` to its textproto and re-encodes to the same bytes.
- `checks/rust/` (CI only, `cargo test --manifest-path sbt2-protocol/checks/rust/Cargo.toml`): the same round trip with `prost`.

Both re-encode deterministically, as `buf convert` does: map entries sorted by key.

## License

LGPL-3.0-or-later, see [COPYING.LESSER](COPYING.LESSER) and [COPYING](COPYING).
