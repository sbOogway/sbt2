# sbt2-protocol

The protobuf messages between the [sbt2](https://github.com/sbOogway/sbt2) server and its GUI, sent one per binary WebSocket frame.

- `sbt2/protocol/v1/`: the `sbt2.protocol.v1` package. `envelope.proto` holds `ClientMessage` and `ServerMessage`, the envelope of every frame; `types.proto` the shared messages.
- sbt2 pins this repo as the `proto/` submodule and generates its Python from it; the GUI generates its Rust types with `prost`.

## Rules

- Prices, quantities and money are decimal strings, never `double`; timestamps are `google.protobuf.Timestamp`.
- A field where "unset" differs from zero or empty is proto3 `optional`.
- Removed fields are `reserved`, and their numbers never reused.
- A breaking change needs a new package (`sbt2.protocol.v2`).

## Checks

[prek](https://github.com/j178/prek) runs `buf format`, `buf lint` and `buf breaking` against this repo's `main`:

```sh
uvx prek install
uvx prek run --all-files
```

## License

LGPL-3.0-or-later, see [COPYING.LESSER](COPYING.LESSER) and [COPYING](COPYING).
