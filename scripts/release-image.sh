#!/usr/bin/env bash
# Builds the server image of a release, smoke-tests it and pushes it to GHCR as :X.Y.Z, and
# as :latest when the release is the newest. The release is $TAG or the newest vX.Y.Z tag.
# Refuses when the release names an image already, unless FORCE=1.
# Needs GH_TOKEN or a gh login, and GHCR_TOKEN, a classic token with write:packages.
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

notes_name_image() {
    github_api "$GITHUB_API/repos/$REPO/releases/$1" | jq -e --arg heading "$NOTES_IMAGE_HEADING" \
        '.body // "" | contains($heading)' >/dev/null
}

[ -n "${GHCR_TOKEN:-}" ] || die "set GHCR_TOKEN to a classic token with write:packages"
use_github_token
tag=$(release_tag)
version=${tag#v}
id=$(release_id "$tag")
if [ "${FORCE:-}" != 1 ] && notes_name_image "$id"; then
    die "release already names its image; set FORCE=1 to replace it"
fi

start_work "refs/tags/$tag"
# the build runs third-party build backends, which have no use for the tokens
env -u GH_TOKEN -u GHCR_TOKEN -u WOODPECKER_TOKEN "$here/build-image.sh" "$version" "$WORK/src"
digest=$(push_image "$version")
name_image_in_notes "$id" "$IMAGE_REPOSITORY:$version@$digest"
echo "release-image: pushed $IMAGE_REPOSITORY:$version@$digest"
