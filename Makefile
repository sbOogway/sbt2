.DEFAULT_GOAL := help

.PHONY: help sync check test-backend test-protocol

help:
	@echo "make sync          prepare the locked backend and protocol environments"
	@echo "make check         run the hooks and both components' test suites"
	@echo "make test-backend  run the backend test suite"
	@echo "make test-protocol run the Python and Rust protocol tests"

sync:
	uv --directory sbt2-backend sync --locked
	uv --directory sbt2-protocol sync --locked

check:
	prek run --all-files --show-diff-on-failure
	$(MAKE) test-backend
	$(MAKE) test-protocol

test-backend:
	uv --directory sbt2-backend run --locked pytest

test-protocol:
	prek run protocol-tests --all-files
	cargo test --locked --manifest-path sbt2-protocol/checks/rust/Cargo.toml
