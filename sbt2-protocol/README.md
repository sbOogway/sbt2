# sbt2-protocol

The protobuf messages between the [sbt2](https://github.com/sbOogway/sbt2) server and its GUI, sent one per binary WebSocket frame.

- `sbt2/protocol/v1/`: the `sbt2.protocol.v1` package. `envelope.proto` holds `ClientMessage` and `ServerMessage`, the envelope of every frame; `types.proto` the shared messages.
- [sbt2-backend](../sbt2-backend) generates its Python from these messages, offline with its locked `protoc`; the GUI generates its Rust types with `prost`.

## Rules

- Prices, quantities and money are decimal strings, never `double`; timestamps are `google.protobuf.Timestamp`.
- A field where "unset" differs from zero or empty is proto3 `optional`.
- Removed fields are `reserved`, and their numbers never reused.
- A breaking change needs a new package (`sbt2.protocol.v2`).

## Reference

The [protocol reference](docs/protocol.md) describes each request, reply, error,
chunk and push. The `.proto` comments are its source. The server advertises its
supported areas in `Welcome.capabilities`.

The local release scripts publish HTML to GitHub Pages at `/vX.Y.Z/` and
`/latest/`. The maintainer enables Pages from the root of the `gh-pages` branch.

## Golden fixtures

`golden/<area>/<case>.textproto` is an example message, starting with a `# proto-message: sbt2.protocol.v1.<Message>` header, and `<case>.binpb` its encoding. Every `ClientMessage` and `ServerMessage` body has at least one.

- Only `scripts/golden.sh` writes a `.binpb`, with `buf convert`; edit the textproto and run it.
- A fixture is never deleted or edited once committed, so messages written today keep decoding as intended.

## Checks

From the repository root, [prek](https://github.com/j178/prek) runs `buf format`, `buf lint`, `buf breaking` against `sbt2-protocol/` on this repository's `main`, and fails when a `.binpb` or the reference is stale. `make check` runs the hooks and both components' tests; `make test-protocol` runs the tests below alone.

- `tests/` (pytest, with `uv`): the rules above that buf lint does not check, over buf's descriptor set; and every fixture decodes with Python's `protobuf` to its textproto and re-encodes to the same bytes.

The re-encode is deterministic, as `buf convert` does: map entries sorted by key.

`prek run generate-protocol-docs --all-files` regenerates the reference with
protoc-gen-doc v1.5.1 and the backend's locked `protoc`. The hook installs its
pinned Go tools locally. Generation needs no remote plugin or build service.

## License

LGPL-3.0-or-later, see [COPYING.LESSER](../COPYING.LESSER) and [COPYING](../COPYING).
