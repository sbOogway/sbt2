#!/usr/bin/env bash
set -euo pipefail

fetch_main() {
    git -C "$1" init --quiet
    git -C "$1" fetch --quiet --depth=1 https://github.com/sbOogway/sbt2.git main
}

breaking_baseline() {
    local mode kind object path
    read -r mode kind object path < <(git -C "$1" ls-tree FETCH_HEAD -- sbt2-protocol)
    case "$mode:$kind:$path" in
    040000:tree:sbt2-protocol)
        git -C "$1" restore --source=FETCH_HEAD --worktree -- sbt2-protocol
        echo "$1/sbt2-protocol"
        ;;
    160000:commit:sbt2-protocol)
        # Before the migration, main names the baseline with a submodule commit.
        echo "https://github.com/sbOogway/sbt2-protocol.git#ref=$object"
        ;;
    *)
        echo "main has no protocol baseline" >&2
        return 1
        ;;
    esac
}

baseline=$(mktemp -d)
trap 'rm -rf "$baseline"' EXIT
fetch_main "$baseline"
against=$(breaking_baseline "$baseline")
buf breaking sbt2-protocol --against "$against"
