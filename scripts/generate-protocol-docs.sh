#!/usr/bin/env bash
# The release build uses the same hook environment for HTML as for the committed Markdown.
set -euo pipefail

format=${SBT2_PROTOCOL_DOCS_FORMAT:-markdown}
output=${SBT2_PROTOCOL_DOCS_DIR:-sbt2-protocol/docs}
case "$format" in
markdown) name=protocol.md ;;
html) name=index.html ;;
*)
    echo "generate-protocol-docs: unknown format '$format'" >&2
    exit 1
    ;;
esac

staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

mapfile -t sources < <(cd sbt2-protocol && find sbt2 -name '*.proto' | sort)
uv run --project sbt2-backend --locked python -m grpc_tools.protoc --proto_path=sbt2-protocol \
    --doc_out="$staging" --doc_opt="$format,$name" "${sources[@]}"
uv run --project sbt2-backend --locked python - "$staging/$name" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()).rstrip() + "\n")
PY
mkdir -p "$output"
if ! cmp -s "$staging/$name" "$output/$name"; then
    cp "$staging/$name" "$output/$name"
fi
