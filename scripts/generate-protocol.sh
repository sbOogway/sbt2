#!/usr/bin/env bash
# Regenerates sbt2-server's protocol modules from proto/ with the locked protoc
# and mypy-protobuf, removing the modules of deleted .proto files. Generates
# aside first, so a failure keeps the old ones.
set -euo pipefail

generated=packages/sbt2-server/src/sbt2/protocol
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

mapfile -t sources < <(cd proto && find sbt2 -name '*.proto' | sort)
uv run --locked python -m grpc_tools.protoc --proto_path=proto \
    --python_out="$staging" --mypy_out="$staging" "${sources[@]}" >/dev/null
rm -rf "$generated"
mkdir -p "$(dirname "$generated")"
cp -r "$staging/sbt2/protocol" "$generated"
