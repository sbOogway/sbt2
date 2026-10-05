#!/usr/bin/env bash
# Cuts a whole release from the maintainer's machine. Refuses unless HEAD is origin/main with a
# clean tree, the last nightly run on main passed and make check passes. The version comes from
# git-cliff, or from $VERSION. Builds the wheels, the GUI and the image first, then drafts the
# release for HEAD, uploads the files, pushes the image, and publishes last. Publishing creates
# the tag on GitHub. A re-run with the same version finishes the draft for HEAD.
# Needs GH_TOKEN or a gh login, GHCR_TOKEN (classic, write:packages) and WOODPECKER_TOKEN.
# SBT2_RELEASE_CHECK replaces the make check command; only the tests of this script use it.
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

CLIFF=(uvx git-cliff==2.14.2)
FINISHED_STATUSES='["success", "failure", "error", "killed", "declined"]'

# The header goes through a file descriptor, so the token stays out of the process list
woodpecker_api() {
    curl -fsS -H @<(echo "Authorization: Bearer $WOODPECKER_TOKEN") "$@"
}

check_head_is_origin_main() {
    git fetch --quiet --tags origin main || die "cannot fetch origin"
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "HEAD is not origin/main"
}

check_tree_is_clean() {
    [ -z "$(git status --porcelain)" ] || die "the working tree is not clean"
}

# The status of the last finished run of the cron nightly on main, or none
nightly_status() {
    local repo_id
    repo_id=$(woodpecker_api "$WOODPECKER_URL/api/repos/lookup/$REPO" | jq -r .id) ||
        die "cannot read $REPO from Woodpecker at $WOODPECKER_URL"
    woodpecker_api "$WOODPECKER_URL/api/repos/$repo_id/pipelines?event=cron&branch=main&perPage=100" |
        jq -r --argjson finished "$FINISHED_STATUSES" \
            '[.[] | select(.cron == "nightly" and (.status | IN($finished[])))][0].status // "none"' ||
        die "cannot read the pipelines of $REPO from Woodpecker"
}

check_nightly_passed() {
    local status
    status=$(nightly_status)
    case $status in
    success) ;;
    none) die "no finished nightly run on main exists yet; create the Woodpecker cron nightly and let it run" ;;
    *) die "the last nightly run on main ended with $status" ;;
    esac
}

check_make_check() {
    local command
    read -ra command <<<"${SBT2_RELEASE_CHECK:-make check}"
    "${command[@]}" || die "make check failed"
}

tag_exists() {
    git rev-parse --verify --quiet "refs/tags/v$1" >/dev/null
}

# The version to release, without the v: $VERSION, or the one git-cliff picks
next_version() {
    local version=${VERSION:-} next
    if [ -z "$version" ]; then
        next=$("${CLIFF[@]}" --bumped-version 2>/dev/null) || die "git-cliff cannot pick a version"
        version=${next#v}
        ! tag_exists "$version" || die "nothing to release since v$version"
    fi
    [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$version' is not an X.Y.Z version"
    ! tag_exists "$version" || die "the tag v$version exists"
    echo "$version"
}

# Builds every file of the release into $WORK/files and its notes into $WORK/notes.md
build_all() {
    local version=$1 files=$WORK/files
    mkdir -p "$files"
    "${CLIFF[@]}" --unreleased --tag "v$version" --strip all --output "$WORK/notes.md" 2>/dev/null
    # the builds run third-party build backends, which have no use for the tokens
    env -u GH_TOKEN -u GHCR_TOKEN -u WOODPECKER_TOKEN UV_DYNAMIC_VERSIONING_BYPASS="$version" \
        uv build --project "$WORK/src/sbt2-backend" --all-packages --out-dir "$files"
    env -u GH_TOKEN -u GHCR_TOKEN -u WOODPECKER_TOKEN "$here/build-gui.sh" "$version" "$WORK/src" "$files"
    env -u GH_TOKEN -u GHCR_TOKEN -u WOODPECKER_TOKEN "$here/build-image.sh" "$version" "$WORK/src"
    (cd "$files" && sha256sum -- * >"$WORK/SHA256SUMS")
    mv "$WORK/SHA256SUMS" "$files/"
}

# Prints the id of the draft for tag $1 and commit $2, or nothing. Refuses a draft for another commit.
find_draft() {
    local tag=$1 commit=$2 draft id target
    draft=$(github_api "$GITHUB_API/repos/$REPO/releases?per_page=100" |
        jq -r --arg tag "$tag" '[.[] | select(.draft and .tag_name == $tag)][0] // empty | "\(.id) \(.target_commitish)"')
    [ -n "$draft" ] || return 0
    read -r id target <<<"$draft"
    [ "$target" = "$commit" ] || die "the draft of $tag targets $target, not HEAD; delete it first"
    echo "$id"
}

create_draft() {
    local tag=$1 commit=$2
    jq -n --arg tag "$tag" --arg commit "$commit" --rawfile body "$WORK/notes.md" \
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
        jq -n --rawfile body "$WORK/notes.md" '{body: $body}' |
            github_api -X PATCH -d @- "$GITHUB_API/repos/$REPO/releases/$id" >/dev/null
    fi
    echo "$id"
}

upload_files() {
    local id=$1 file
    for file in "$WORK"/files/*; do
        upload_asset "$id" "$file"
    done
}

publish() {
    echo '{"draft": false}' | github_api -X PATCH -d @- "$GITHUB_API/repos/$REPO/releases/$1" >/dev/null
}

[ -n "${GHCR_TOKEN:-}" ] || die "set GHCR_TOKEN to a classic token with write:packages"
[ -n "${WOODPECKER_TOKEN:-}" ] || die "set WOODPECKER_TOKEN to a Woodpecker personal token"
use_github_token
check_head_is_origin_main
check_tree_is_clean
check_nightly_passed
version=$(next_version)
check_make_check

commit=$(git rev-parse HEAD)
start_work "$commit"
build_all "$version"
id=$(draft_release "v$version" "$commit")
upload_files "$id"
digest=$(push_image "$version")
name_image_in_notes "$id" "$IMAGE_REPOSITORY:$version@$digest"
publish "$id"
git fetch --quiet --tags origin
echo "release: published v$version"
