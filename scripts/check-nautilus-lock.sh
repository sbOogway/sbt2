#!/usr/bin/env bash
# Fails when uv.lock pins a nautilus-trader build with a "+run" local version.
# Nautech deletes such a wheel once it republishes the nightly without the tag,
# and `==` on the plain nightly still matches the tagged build.
set -euo pipefail

lock=sbt2-backend/uv.lock

locked=$(sed -nE '/^name = "nautilus-trader"$/{n;s/^version = "(.*)"$/\1/p}' "$lock")

if [[ $locked == *+* ]]; then
    echo "check-nautilus-lock: $lock pins $locked; relock once the index serves ${locked%%+*}" >&2
    exit 1
fi
