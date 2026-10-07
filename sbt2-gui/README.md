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
cargo test --locked run_detail       # only the tests whose path has "run_detail"
```

The integration tests of each crate build into one binary,
`tests/integration/main.rs`, as every test binary links all dependencies.

From the repository root, `make test-gui` runs `cargo fmt --check`,
`cargo clippy -D warnings` and the tests.

The e2e test starts `sbt2-server` from `../sbt2-backend` with a temporary data
folder holding one stored run. `SBT2_E2E_UV` names the `uv` command, and
`SBT2_E2E_PORT` the port; a free port is the default.

### Faster builds

Dev builds keep only line tables as debug info, so a debugger shows lines but
no variables. For full debug info in our crates, build with
`CARGO_PROFILE_DEV_DEBUG=true`.

Rust 1.90 and later link with `rust-lld` on Linux already, so `mold` gains
nothing here. The Cranelift backend compiles debug builds without LLVM, but
needs nightly Rust; the repository pins stable. To try it:

```sh
rustup component add rustc-codegen-cranelift-preview --toolchain nightly
cargo +nightly -Zcodegen-backend test \
  --config 'profile.dev.codegen-backend="cranelift"'
```

`cargo clean` removes old builds, which `target/` keeps for ever.

## Release binary

The release tarball has a native build from Fedora 44, so its binary needs a
glibc as new as that machine's, glibc 2.43. On an older system, build the GUI
from source as above.

## Connection

The GUI keeps its files in the `sbt2-gui` folder of the OS config folder:
`$XDG_CONFIG_HOME/sbt2-gui` (`~/.config/sbt2-gui`) on Linux,
`~/Library/Application Support/sbt2-gui` on macOS and `%APPDATA%\sbt2-gui` on
Windows. It creates the folder at start when it is missing, owner-only on Unix,
and a commented `settings.toml` (`0600`) that lists the keys you can set.

The token is kept in the OS keyring. Without a keyring it goes to a `0600` file
in the config folder, and the GUI shows a warning. The last server URL is
remembered in `settings.toml` in the same folder. The
same file can hold `theme = "light"` or `theme = "dark"`; the GUI opens light
without it.

To connect at start, add `server = "wss://..."` to `settings.toml`. The GUI then
connects at once, with the stored token of that server. A `token = "..."` key in
the same file wins over the stored token. The GUI never writes this key itself.
Prefer the keyring or the token file: a token in `settings.toml` is plain text.
When the file holds a token, the GUI saves it as `0600` and warns when others
can read it. Run `chmod 600` on it then.

## License

LGPL-3.0-or-later, see [COPYING.LESSER](../COPYING.LESSER) and [COPYING](../COPYING).
