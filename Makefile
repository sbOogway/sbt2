.DEFAULT_GOAL := help

.PHONY: help sync check test-backend test-protocol

help:
	@echo "make sync          prepare the locked backend and protocol environments"
	@echo "make check         run the hooks and both components' test suites"
	@echo "make test-backend  run the backend test suite"
	@echo "make test-protocol run the Python and Rust protocol tests"

sync:
	cd sbt2-backend && uv sync --locked
	cd sbt2-protocol && uv sync --locked

check:
	prek run --all-files --show-diff-on-failure
	$(MAKE) test-backend
	$(MAKE) test-protocol

test-backend:
	cd sbt2-backend && uv run --locked pytest

test-protocol:
	cd sbt2-protocol && uv run --locked pytest
	cd sbt2-protocol && cargo test --locked --manifest-path checks/rust/Cargo.toml
