#!/usr/bin/env bash
# Regenerates sbt2-server's protocol modules from proto/, removing the modules
# of deleted .proto files. Generates aside first, so a failure keeps the old ones.
set -euo pipefail

generated=packages/sbt2-server/src/sbt2
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

buf generate --output "$staging"
rm -rf "$generated"/v[0-9]*
cp -r "$staging/$generated"/v[0-9]* "$generated"/
