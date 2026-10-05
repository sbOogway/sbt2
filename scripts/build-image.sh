#!/usr/bin/env bash
# Builds the server image of version $1 from revision $2 as the local image $3 with buildah,
# starts it and waits until /health answers. Publishes nothing. In the docker format, so the
# HEALTHCHECK stays. The storage options come from the environment, as in the CI step.
set -euo pipefail

version=${1:?usage: build-image.sh VERSION REVISION IMAGE}
revision=${2:?usage: build-image.sh VERSION REVISION IMAGE}
image=${3:?usage: build-image.sh VERSION REVISION IMAGE}
root=$(cd "$(dirname "$0")/.." && pwd)
buildah=(buildah --root="${BUILDAH_ROOT:-/cache/storage}")
port=8765
attempts=60

build() {
    "${buildah[@]}" build --format=docker --tag="$image" \
        --build-arg SBT2_VERSION="$version" \
        --label org.opencontainers.image.source=https://github.com/sbOogway/sbt2 \
        --label org.opencontainers.image.version="$version" \
        --label org.opencontainers.image.revision="$revision" \
        --file="$root/sbt2-backend/Containerfile" "$root/sbt2-backend"
}

# buildah runs the command in a chroot on the host's network, so the server answers on localhost
in_container() {
    "${buildah[@]}" run --env SBT2_SERVER_TOKEN=smoke-test "$container" -- "$@"
}

wait_for_health() {
    local probe="import urllib.request; urllib.request.urlopen('http://127.0.0.1:$port/health', timeout=2)"
    for _ in $(seq "$attempts"); do
        if in_container python -c "$probe" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "build-image: /health did not answer in ${attempts}s" >&2
    return 1
}

smoke_test() {
    container=$("${buildah[@]}" from "$image")
    in_container sbt2-server >/dev/null 2>&1 &
    server=$!
    trap 'kill "$server" 2>/dev/null || true; "${buildah[@]}" rm "$container" >/dev/null' EXIT
    wait_for_health
    echo "build-image: $image answers on /health"
}

build
smoke_test
