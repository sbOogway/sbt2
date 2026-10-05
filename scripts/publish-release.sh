#!/usr/bin/env bash
# Publishes the draft release of $CI_COMMIT_SHA, which creates its tag. Does nothing when
# there is no draft. The notes get the digest of the pushed image. SHA256SUMS goes up
# first and covers every other file of the release.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

download_assets() {
    local id=$1 asset name
    github_api "$GITHUB_API/repos/$CI_REPO/releases/$id/assets?per_page=100" |
        jq -r '.[] | select(.name != "SHA256SUMS") | "\(.id) \(.name)"' |
        while read -r asset name; do
            github_api -H "Accept: application/octet-stream" -L -o "$work/$name" \
                "$GITHUB_API/repos/$CI_REPO/releases/assets/$asset"
        done
}

add_image_to_notes() {
    local id=$1 version=$2 digest notes
    digest=$(image_digest "$version")
    if [ -z "$digest" ]; then
        echo "publish-release: $(image_repository):$version is not on GHCR" >&2
        return 1
    fi
    # a restarted pipeline replaces the section of the first run
    notes=$(github_api "$GITHUB_API/repos/$CI_REPO/releases/$id" | jq -r .body)
    notes=${notes%%$'\n\n## Container image'*}
    notes+=$'\n\n## Container image\n\n'"\`$(image_repository):$version@$digest\`"
    jq -n --arg body "$notes" '{body: $body}' |
        github_api -X PATCH -d @- "$GITHUB_API/repos/$CI_REPO/releases/$id" >/dev/null
}

id=$(draft_id)
if [ -z "$id" ]; then
    echo "publish-release: no draft for $CI_COMMIT_SHA"
    exit 0
fi

version=$(draft_version "$id")
add_image_to_notes "$id" "$version"
download_assets "$id"
(cd "$work" && sha256sum -- * >SHA256SUMS)
upload_asset "$id" "$work/SHA256SUMS"
github_api -X PATCH -d '{"draft": false}' "$GITHUB_API/repos/$CI_REPO/releases/$id" >/dev/null
echo "publish-release: published $version"
