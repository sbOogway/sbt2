#!/usr/bin/env bash
# Fails when a lock pins a nautilus-trader build with a "+run" local version, or
# when the backend and notebook locks pin different builds. Nautech deletes a
# tagged wheel once it republishes the nightly without the tag, and `==` on the
# plain nightly still matches the tagged build.
set -euo pipefail

locks=(sbt2-backend/uv.lock sbt2-notebooks/uv.lock)

locked() {
    sed -nE '/^name = "nautilus-trader"$/{n;s/^version = "(.*)"$/\1/p}' "$1"
}

for lock in "${locks[@]}"; do
    version=$(locked "$lock")
    if [[ $version == *+* ]]; then
        echo "check-nautilus-lock: $lock pins $version; relock once the index serves ${version%%+*}" >&2
        exit 1
    fi
done

backend=$(locked "${locks[0]}")
notebooks=$(locked "${locks[1]}")
if [ "$backend" != "$notebooks" ]; then
    echo "check-nautilus-lock: ${locks[0]} pins $backend but ${locks[1]} pins $notebooks" >&2
    exit 1
fi
