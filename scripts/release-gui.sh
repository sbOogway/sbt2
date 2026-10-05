#!/usr/bin/env bash
# Builds the GUI and uploads it to the draft release of $CI_COMMIT_SHA. Does nothing when
# there is no draft. The version is the draft's: the tag does not exist before publishing.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

id=$(draft_id)
if [ -z "$id" ]; then
    echo "release-gui: no draft for $CI_COMMIT_SHA"
    exit 0
fi

version=$(draft_version "$id")
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
# the build runs third-party build scripts, which have no use for the token
env -u GH_TOKEN "$here/build-gui.sh" "$version" "$out"
upload_asset "$id" "$out/sbt2-gui-$version-x86_64-linux.tar.gz"
echo "release-gui: uploaded the GUI $version"
