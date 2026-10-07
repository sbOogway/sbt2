#!/usr/bin/env bash
# Builds a release on the maintainer's machine into $RELEASE_DIR for make publish. Refuses unless
# HEAD is origin/main with a clean tree and make check passes. Each merge on main since the newest
# tag gets a planned tag with the version git-cliff picks for it; a merge that git-cliff gives no
# new version gets none. The newest of these merges is the release; $VERSION makes HEAD the
# release with that version. Builds its wheels, GUI and image, and writes its notes. No tag
# leaves this machine.
# Needs GH_TOKEN or a gh login, to find the last release for the notes.
# SBT2_RELEASE_CHECK replaces the make check command; only the tests of this script use it.
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

CLIFF=(uvx git-cliff==2.14.2)

check_head_is_origin_main() {
    git fetch --quiet --tags origin main || die "cannot fetch origin"
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "HEAD is not origin/main"
}

check_tree_is_clean() {
    [ -z "$(git status --porcelain)" ] || die "the working tree is not clean"
}

check_make_check() {
    local command
    read -ra command <<<"${SBT2_RELEASE_CHECK:-make check}"
    "${command[@]}" || die "make check failed"
}

tag_exists() {
    git rev-parse --verify --quiet "refs/tags/$1" >/dev/null
}

# Runs git-cliff on the clone $WORK/plan, which holds the tags planned so far
plan_cliff() {
    "${CLIFF[@]}" --workdir "$WORK/plan" "$@" 2>/dev/null
}

plan_tag() {
    git -C "$WORK/plan" tag "$1" "$2"
    echo "$2 $1"
}

# Tags in $WORK/plan each merge since the newest tag that git-cliff gives a new version, oldest
# first, and prints "<commit> <tag>" for each. No tag reaches this repository.
plan_merge_tags() {
    local base commit tag
    git clone --quiet --shared "$root" "$WORK/plan"
    base=$(newest_tag)
    for commit in $(git rev-list --first-parent --reverse "$base..HEAD"); do
        tag=$(plan_cliff --bumped-version "$base..$commit") || die "git-cliff cannot pick a version"
        [ "$tag" != "$base" ] || continue
        plan_tag "$tag" "$commit"
        base=$tag
    done
}

is_newer() {
    [ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n 1)" = "$1" ] && [ "$1" != "$2" ]
}

# Replaces the planned tag of HEAD, if any, with v$VERSION
plan_version_override() {
    local plan=$1 head planned older
    [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$VERSION' is not an X.Y.Z version"
    ! tag_exists "v$VERSION" || die "the tag v$VERSION exists"
    head=$(git rev-parse HEAD)
    planned=$(grep "^$head " "$plan" | cut -d ' ' -f 2) || true
    if [ -n "$planned" ]; then
        git -C "$WORK/plan" tag -d "$planned" >/dev/null
        head -n -1 "$plan" >"$plan.older"
        mv "$plan.older" "$plan"
    fi
    older=$(tail -n 1 "$plan" | cut -d ' ' -f 2)
    older=${older:-$(newest_tag)}
    is_newer "v$VERSION" "$older" || die "v$VERSION is not newer than $older"
    plan_tag "v$VERSION" "$head" >>"$plan"
}

# Writes the planned "<commit> <tag>" lines to $WORK/tags. The last one is the release.
plan_tags() {
    plan_merge_tags >"$WORK/tags"
    if [ -n "${VERSION:-}" ]; then
        plan_version_override "$WORK/tags"
    fi
    [ -s "$WORK/tags" ] || die "nothing to release since $(newest_tag)"
}

# The tag of the newest published release, or nothing when there is none
latest_release_tag() {
    github_api "$GITHUB_API/repos/$REPO/releases/latest" 2>/dev/null | jq -r '.tag_name // empty' || true
}

# Writes the notes of the release at commit $1 to $WORK/notes.md: every change since the last
# release, one section for each planned tag
write_notes() {
    local commit=$1 since range=()
    since=$(latest_release_tag)
    if [ -n "$since" ]; then
        range=("$since..$commit")
    fi
    plan_cliff --strip all --output "$WORK/notes.md" "${range[@]}"
}

# Builds every file of the release into $WORK/files and its notes into $WORK/notes.md
build_all() {
    local version=$1 files=$WORK/files
    mkdir -p "$files"
    run_build env UV_DYNAMIC_VERSIONING_BYPASS="$version" \
        uv build --project "$WORK/src/sbt2-backend" --all-packages --out-dir "$files"
    run_build "$here/build-gui.sh" "$version" "$WORK/src" "$files"
    run_build "$here/build-image.sh" "$version" "$WORK/src"
    (cd "$files" && sha256sum -- * >"$WORK/SHA256SUMS")
    mv "$WORK/SHA256SUMS" "$files/"
}

# Replaces the build in $RELEASE_DIR with the one in $WORK
save_build() {
    rm -rf "$RELEASE_DIR"
    mkdir -p "$RELEASE_DIR"
    mv "$WORK/files" "$WORK/notes.md" "$WORK/tags" "$RELEASE_DIR/"
    git rev-parse HEAD >"$RELEASE_DIR/head"
}

use_github_token
check_head_is_origin_main
check_tree_is_clean
make_work
plan_tags
check_make_check

read -r commit tag < <(tail -n 1 "$WORK/tags")
version=${tag#v}
write_notes "$commit"
check_out_source "$commit"
build_all "$version"
save_build
echo "release-build: built $tag into $RELEASE_DIR; run make publish to publish it"
