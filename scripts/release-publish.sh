#!/usr/bin/env bash
# Publishes the release that make build left in $RELEASE_DIR. Refuses unless that build is of
# the current origin/main. Drafts the release, uploads the files and pushes the image. Last, it
# pushes the tags of the older merges and publishes, which creates the release's tag on GitHub.
# A re-run finishes the draft. Then it updates the sbt2-server service on this machine, if there
# is one, and removes the build.
# Needs GH_TOKEN or a gh login, and GHCR_TOKEN (classic, write:packages).
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

# Prints the id of the draft for tag $1 and commit $2, or nothing. Refuses a draft for another commit.
find_draft() {
    local tag=$1 commit=$2 draft id target
    draft=$(github_api "$GITHUB_API/repos/$REPO/releases?per_page=100" |
        jq -r --arg tag "$tag" '[.[] | select(.draft and .tag_name == $tag)][0] // empty | "\(.id) \(.target_commitish)"')
    [ -n "$draft" ] || return 0
    read -r id target <<<"$draft"
    [ "$target" = "$commit" ] || die "the draft of $tag targets $target, not $commit; delete it first"
    echo "$id"
}

create_draft() {
    local tag=$1 commit=$2
    jq -n --arg tag "$tag" --arg commit "$commit" --rawfile body "$RELEASE_DIR/notes.md" \
        '{tag_name: $tag, target_commitish: $commit, name: $tag, body: $body, draft: true}' |
        github_api -X POST -d @- "$GITHUB_API/repos/$REPO/releases" | jq -r .id
}

# Makes the draft for tag $1 and commit $2, or finds the one an earlier run left. Prints its id.
draft_release() {
    local tag=$1 commit=$2 id
    id=$(find_draft "$tag" "$commit")
    if [ -z "$id" ]; then
        id=$(create_draft "$tag" "$commit")
    else
        jq -n --rawfile body "$RELEASE_DIR/notes.md" '{body: $body}' | edit_release "$id" "$tag" "$commit"
    fi
    echo "$id"
}

upload_files() {
    local id=$1 file
    for file in "$RELEASE_DIR"/files/*; do
        upload_asset "$id" "$file"
    done
}

# Pushes the planned tags of the merges older than the release, all or none
push_older_tags() {
    local refspecs
    mapfile -t refspecs < <(head -n -1 "$RELEASE_DIR/tags" | awk '{ print $1 ":refs/tags/" $2 }')
    [ "${#refspecs[@]}" -eq 0 ] || git push --quiet --atomic origin "${refspecs[@]}"
}

[ -n "${GHCR_TOKEN:-}" ] || die "set GHCR_TOKEN to a classic token with write:packages"
use_github_token
check_build
make_work

read -r commit tag < <(tail -n 1 "$RELEASE_DIR/tags")
version=${tag#v}
id=$(draft_release "$tag" "$commit")
upload_files "$id"
digest=$(push_image "$version")
name_image_in_notes "$id" "$IMAGE_REPOSITORY:$version@$digest"
push_older_tags
publish "$id" "$tag" "$commit"
deploy
older=$(head -n -1 "$RELEASE_DIR/tags" | wc -l)
rm -rf "$RELEASE_DIR"
git fetch --quiet --tags origin
echo "release-publish: published $tag, and tagged $older older merges"
