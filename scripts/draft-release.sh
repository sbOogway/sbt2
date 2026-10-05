#!/usr/bin/env bash
# Creates the draft release prepared in $1 for $CI_COMMIT_SHA, with its distributions.
# A restarted pipeline keeps the draft of its commit. A draft of another commit is stale:
# the notes of this release cover its changes, so it goes.
set -euo pipefail

out=${1:-.release}
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

delete_stale_drafts() {
    local id tag target
    while read -r id tag target; do
        if [ "$target" != "$CI_COMMIT_SHA" ]; then
            echo "draft-release: deleting the stale draft $tag"
            github_api -X DELETE "$GITHUB_API/repos/$CI_REPO/releases/$id"
        fi
    done < <(list_drafts)
}

delete_stale_drafts
if [ -n "$(draft_id)" ]; then
    echo "draft-release: the draft of $CI_COMMIT_SHA exists"
    exit 0
fi

tag=$(cat "$out/tag")
gh release create "$tag" "$out"/dist/* --draft \
    --repo "$CI_REPO" --target "$CI_COMMIT_SHA" \
    --title "$tag" --notes-file "$out/notes.md"
