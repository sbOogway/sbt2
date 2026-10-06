.DEFAULT_GOAL := help

.PHONY: help sync check test-backend test-protocol test-gui release release-gui release-image

help:
	@echo "make sync          prepare the locked backend and protocol environments"
	@echo "make check         run the hooks and both components' test suites"
	@echo "make test-backend  run the backend test suite"
	@echo "make test-protocol run the Python and Rust protocol tests"
	@echo "make test-gui      run the GUI's format, lint and test checks"
	@echo "make release-gui   backfill: build the Linux GUI and upload it to a release"
	@echo "make release-image backfill: build the image, test it and push it to GHCR"
	@echo "make release       tag the merges since the last tag, build and publish the newest"

sync:
	uv --directory sbt2-backend sync --locked
	uv --directory sbt2-protocol sync --locked

check:
	prek run --all-files --show-diff-on-failure
	$(MAKE) test-backend
	$(MAKE) test-protocol
	$(MAKE) test-gui

test-backend:
	uv --directory sbt2-backend run --locked pytest

test-protocol:
	prek run protocol-tests --all-files
	cargo test --locked --manifest-path sbt2-protocol/checks/rust/Cargo.toml

test-gui:
	cd sbt2-gui && cargo fmt --all --check
	cd sbt2-gui && cargo clippy --locked --all-targets -- -D warnings
	cd sbt2-gui && cargo test --locked

release-gui:
	scripts/release-gui.sh

release-image:
	scripts/release-image.sh

release:
	scripts/release.sh
