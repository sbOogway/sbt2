#!/usr/bin/env bash
# Builds the server image, and pushes it as :VERSION and :latest once it passed its smoke
# test. Does nothing when there is no draft for $CI_COMMIT_SHA. The version is the draft's:
# the tag does not exist before publishing.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

buildah=(buildah --root="${BUILDAH_ROOT:-/cache/storage}")
local_image=localhost/sbt2-server:release

push_image() {
    local repository=$1 version=$2
    "${buildah[@]}" login --username "$CI_REPO_OWNER" --password-stdin ghcr.io <<<"$GHCR_TOKEN"
    "${buildah[@]}" push "$local_image" "docker://$repository:$version"
    "${buildah[@]}" push "$local_image" "docker://$repository:latest"
}

id=$(draft_id)
if [ -z "$id" ]; then
    echo "release-image: no draft for $CI_COMMIT_SHA"
    exit 0
fi

version=$(draft_version "$id")
# the base images stay cached; vfs keeps a full copy of every layer, so the build goes
trap '"${buildah[@]}" rmi --force "$local_image"' EXIT
# the build runs third-party build backends, which have no use for the token
env -u GH_TOKEN -u GHCR_TOKEN "$here/build-image.sh" "$version" "$CI_COMMIT_SHA" "$local_image"
push_image "$(image_repository)" "$version"
echo "release-image: pushed $(image_repository):$version"
