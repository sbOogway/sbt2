#!/usr/bin/env bash
# Checks proto/ for breaking changes against main's.
set -euo pipefail

against="https://github.com/sbOogway/sbt2.git#branch=main,subdir=proto"

if ! output=$(buf breaking proto --against "$against" 2>&1); then
    # before the first protocol reached main there was nothing to break
    if [[ $output == *"had no .proto files"* ]]; then
        exit 0
    fi
    printf '%s\n' "$output" >&2
    exit 1
fi
