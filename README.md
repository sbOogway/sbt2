# sbt2-protocol

The protobuf messages between the [sbt2](https://github.com/sbOogway/sbt2) server and its GUI, sent one per binary WebSocket frame.

- `sbt2/protocol/v1/`: the `sbt2.protocol.v1` package. `envelope.proto` holds `ClientMessage` and `ServerMessage`, the envelope of every frame; `types.proto` the shared messages.
- sbt2 pins this repo as the `proto/` submodule and generates its Python from it; the GUI generates its Rust types with `prost`.

## Rules

- Prices, quantities and money are decimal strings, never `double`; timestamps are `google.protobuf.Timestamp`.
- A field where "unset" differs from zero or empty is proto3 `optional`.
- Removed fields are `reserved`, and their numbers never reused.
- A breaking change needs a new package (`sbt2.protocol.v2`).

## Golden fixtures

`golden/<area>/<case>.textproto` is an example message, starting with a `# proto-message: sbt2.protocol.v1.<Message>` header, and `<case>.binpb` its encoding. Every `ClientMessage` and `ServerMessage` body has at least one.

- Only `scripts/golden.sh` writes a `.binpb`, with `buf convert`; edit the textproto and run it.
- A fixture is never deleted or edited once committed, so messages written today keep decoding as intended.

## Checks

[prek](https://github.com/j178/prek) runs `buf format`, `buf lint`, `buf breaking` against this repo's `main`, fails when a `.binpb` is stale, and runs the tests:

```sh
uvx prek install
uvx prek run --all-files
```

- `tests/` (pytest, with `uv`): the rules above that buf lint does not check, over buf's descriptor set; and every fixture decodes with Python's `protobuf` to its textproto and re-encodes to the same bytes.
- `checks/rust/` (CI only, `cargo test --manifest-path checks/rust/Cargo.toml`): the same round trip with `prost`.

Both re-encode deterministically, as `buf convert` does: map entries sorted by key.

## License

LGPL-3.0-or-later, see [COPYING.LESSER](COPYING.LESSER) and [COPYING](COPYING).
