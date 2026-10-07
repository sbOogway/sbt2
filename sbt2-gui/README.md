# sbt2-gui

The sbt2 GUI, written in Rust with [iced](https://iced.rs). Linux x86_64 only.

It reads the messages of [sbt2-protocol/](../sbt2-protocol) and connects to a
separately deployed [sbt2-backend/](../sbt2-backend) server over its
WebSocket. It never imports the backend, and it builds without Python or
Nautilus.

A Cargo workspace of two crates:

- `sbt2-client`: the protocol client, with no UI. Its `build.rs` compiles the
  `.proto` files with `protox`; no `protoc` is needed and nothing generated is
  committed.
- `sbt2-gui`: the iced app. It uses only `sbt2-client`'s public API.

`rust-toolchain.toml` pins the toolchain.

## Build, run, test

```sh
cargo build --locked
cargo run --locked -p sbt2-gui
cargo test --locked                  # unit and integration tests
cargo test --locked -- --ignored     # e2e tests; they start the real server with uv
```

From the repository root, `make test-gui` runs `cargo fmt --check`,
`cargo clippy -D warnings` and the tests.

The e2e test starts `sbt2-server` from `../sbt2-backend` with a temporary data
folder holding one stored run. `SBT2_E2E_UV` names the `uv` command, and
`SBT2_E2E_PORT` the port; a free port is the default.

## Release binary

The release tarball has a native build from Fedora 44, so its binary needs a
glibc as new as that machine's, glibc 2.43. On an older system, build the GUI
from source as above.

## Connection

The token is kept in the OS keyring (Secret Service). Without a keyring it goes
to a `0600` file in `$XDG_CONFIG_HOME/sbt2-gui/`, and the GUI shows a warning.
The last server URL is remembered in `settings.toml` in the same folder.

## License

LGPL-3.0-or-later, see [COPYING.LESSER](../COPYING.LESSER) and [COPYING](../COPYING).
