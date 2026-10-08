#!/usr/bin/env bash
# Regenerates the Python modules of the sbt2-protocol member from sbt2-protocol/ with the
# locked protoc and mypy-protobuf, removing the modules of deleted .proto files.
# Generates aside first, so a failure keeps the old ones.
set -euo pipefail

generated=sbt2-backend/packages/sbt2-protocol/src/sbt2/protocol
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

mapfile -t sources < <(cd sbt2-protocol && find sbt2 -name '*.proto' | sort)
uv run --project sbt2-backend --locked python -m grpc_tools.protoc --proto_path=sbt2-protocol \
    --python_out="$staging" --mypy_out="$staging" "${sources[@]}" >/dev/null
# CI's test steps import the modules while this runs beside them
if diff -r -x __pycache__ "$staging/sbt2/protocol" "$generated" >/dev/null 2>&1; then
    exit 0
fi
rm -rf "$generated"
mkdir -p "$(dirname "$generated")"
cp -r "$staging/sbt2/protocol" "$generated"
