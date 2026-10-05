#!/usr/bin/env bash
# Builds the server image of version $1 from the source tree $2 as localhost/sbt2-server:$1
# with podman, starts it and waits until /health answers. Publishes nothing. In the docker
# format, so the HEALTHCHECK stays.
set -euo pipefail

version=${1:?usage: build-image.sh VERSION SOURCE_DIR}
source=$(realpath "${2:?usage: build-image.sh VERSION SOURCE_DIR}")
image=localhost/sbt2-server:$version
port=8765
attempts=60

build() {
    local revision
    revision=$(git -C "$source" rev-parse HEAD)
    podman build --format docker --tag "$image" \
        --build-arg SBT2_VERSION="$version" \
        --label org.opencontainers.image.source=https://github.com/sbOogway/sbt2 \
        --label org.opencontainers.image.version="$version" \
        --label org.opencontainers.image.revision="$revision" \
        --file "$source/sbt2-backend/Containerfile" "$source/sbt2-backend"
}

start_container() {
    podman run --detach --env SBT2_SERVER_TOKEN=smoke-test --publish "127.0.0.1::$port" "$image"
}

wait_for_health() {
    local url=http://127.0.0.1:$1/health
    for _ in $(seq "$attempts"); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "build-image: /health did not answer in ${attempts}s" >&2
    return 1
}

smoke_test() {
    local host_port
    container=$(start_container)
    trap 'podman rm --force --time 0 "$container" >/dev/null' EXIT
    host_port=$(podman port "$container" "$port" | head -n 1 | sed 's/.*://')
    wait_for_health "$host_port"
    echo "build-image: $image answers on /health"
}

build
smoke_test
