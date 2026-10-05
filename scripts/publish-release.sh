#!/usr/bin/env bash
# Publishes the draft release of $CI_COMMIT_SHA, which creates its tag. Does nothing when
# there is no draft. SHA256SUMS goes up first and covers every other file of the release.
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

id=$(draft_id)
if [ -z "$id" ]; then
    echo "publish-release: no draft for $CI_COMMIT_SHA"
    exit 0
fi

download_assets "$id"
(cd "$work" && sha256sum -- * >SHA256SUMS)
upload_asset "$id" "$work/SHA256SUMS"
github_api -X PATCH -d '{"draft": false}' "$GITHUB_API/repos/$CI_REPO/releases/$id" >/dev/null
echo "publish-release: published $(draft_version "$id")"
