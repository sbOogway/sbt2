# shellcheck shell=bash
# Sourced by the release scripts, which run on the maintainer's machine from any directory.
# The GitHub token comes from $GH_TOKEN or the gh login. No token is ever printed or written.
REPO=${SBT2_REPO:-sbOogway/sbt2}
GITHUB_API=${GITHUB_API:-https://api.github.com}
GITHUB_UPLOADS=${GITHUB_UPLOADS:-https://uploads.github.com}
IMAGE_REGISTRY=${IMAGE_REGISTRY:-ghcr.io}
IMAGE_REPOSITORY=$IMAGE_REGISTRY/${REPO%%/*}/sbt2-server
IMAGE_REPOSITORY=${IMAGE_REPOSITORY,,}
GHCR_TOKEN=${GHCR_TOKEN:-}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root" || exit 1

# Takes GH_TOKEN and GHCR_TOKEN from $1 when the environment lacks them. The file is
# parsed, never run, so nothing in it but these two KEY=value lines has any effect.
load_tokens() {
    local file=$1 line key value
    [ -f "$file" ] || return 0
    if [ -n "$(find "$file" -perm /go=r)" ]; then
        echo "${0##*/}: other users can read $file; run chmod 600 $file" >&2
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        [[ $line =~ ^[[:space:]]*(export[[:space:]]+)?(GH_TOKEN|GHCR_TOKEN)=(.*)$ ]] || continue
        key=${BASH_REMATCH[2]}
        value=${BASH_REMATCH[3]%$'\r'}
        if [[ $value =~ ^\"(.*)\"$ || $value =~ ^\'(.*)\'$ ]]; then
            value=${BASH_REMATCH[1]}
        fi
        if [ -z "${!key:-}" ]; then
            export "$key=$value"
        fi
    done <"$file"
}

load_tokens "$root/.env"

die() {
    echo "${0##*/}: $*" >&2
    exit 1
}

use_github_token() {
    if [ -z "${GH_TOKEN:-}" ]; then
        GH_TOKEN=$(gh auth token 2>/dev/null) || true
    fi
    [ -n "${GH_TOKEN:-}" ] || die "set GH_TOKEN to a token that can edit the releases of $REPO, or log in with gh"
    export GH_TOKEN
}

# The header goes through a file descriptor, so the token stays out of the process list
github_api() {
    curl -fsS -H @<(echo "Authorization: Bearer $GH_TOKEN") -H "Accept: application/vnd.github+json" "$@"
}

newest_tag() {
    git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n 1
}

# The release tag: $TAG, or the newest vX.Y.Z tag
release_tag() {
    local tag=${TAG:-}
    git fetch --quiet --tags origin
    if [ -z "$tag" ]; then
        tag=$(newest_tag)
    fi
    [[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$tag' is not a vX.Y.Z tag"
    git rev-parse --verify --quiet "refs/tags/$tag^{commit}" >/dev/null || die "the tag $tag does not exist"
    echo "$tag"
}

# The id of the release of tag $1
release_id() {
    local id
    id=$(github_api "$GITHUB_API/repos/$REPO/releases/tags/$1" | jq -r .id) || die "$REPO has no release $1"
    echo "$id"
}

release_assets() {
    github_api "$GITHUB_API/repos/$REPO/releases/$1/assets?per_page=100"
}

has_asset() {
    release_assets "$1" | jq -e --arg name "$2" 'any(.[]; .name == $name)' >/dev/null
}

# Refuses to go on when the release $1 has the artifact $2, unless FORCE=1
refuse_existing() {
    local id=$1 name=$2
    if [ "${FORCE:-}" != 1 ] && has_asset "$id" "$name"; then
        die "release already has $name; set FORCE=1 to replace it"
    fi
}

# Uploads the file $2 to the release $1, replacing an asset of the same name
upload_asset() {
    local id=$1 file=$2 name old
    name=$(basename "$file")
    old=$(release_assets "$id" | jq -r --arg name "$name" '.[] | select(.name == $name) | .id')
    if [ -n "$old" ]; then
        github_api -X DELETE "$GITHUB_API/repos/$REPO/releases/assets/$old"
    fi
    github_api -X POST -H "Content-Type: application/octet-stream" --data-binary "@$file" \
        "$GITHUB_UPLOADS/repos/$REPO/releases/$id/assets?name=$name" >/dev/null
}

# Replaces SHA256SUMS of the release $1 with the sums of all its other files
refresh_checksums() {
    local id=$1 dir asset name
    dir=$(mktemp -d)
    release_assets "$id" |
        jq -r '.[] | select(.name != "SHA256SUMS") | "\(.id) \(.name)"' |
        while read -r asset name; do
            github_api -H "Accept: application/octet-stream" -L -o "$dir/$name" \
                "$GITHUB_API/repos/$REPO/releases/assets/$asset"
        done
    (cd "$dir" && sha256sum -- * >SHA256SUMS)
    upload_asset "$id" "$dir/SHA256SUMS"
    rm -rf "$dir"
}

# Makes the scratch directory $WORK, which goes when the script ends, even on failure
make_work() {
    WORK=$(mktemp -d)
    trap finish_work EXIT
}

# Checks out the git ref $1 into a git worktree $WORK/src, so no local edit leaks into a release
check_out_source() {
    git worktree add --quiet --detach "$WORK/src" "$1"
}

start_work() {
    make_work
    check_out_source "$1"
}

finish_work() {
    git worktree remove --force "$WORK/src" 2>/dev/null || true
    git worktree prune
    rm -rf "$WORK"
}

# Succeeds when the version $1 is not older than the newest vX.Y.Z tag
is_newest_version() {
    local newest
    newest=$(newest_tag)
    [ -z "$newest" ] || [ "$(printf '%s\n' "$newest" "v$1" | sort -V | tail -n 1)" = "v$1" ]
}

NOTES_IMAGE_HEADING="## Container image"

# The GHCR token goes to podman through stdin, and into a file in $WORK, which goes when the script ends
login() {
    podman login --authfile "$WORK/auth.json" --username "${REPO%%/*}" --password-stdin "$IMAGE_REGISTRY" <<<"$GHCR_TOKEN" >&2
}

# Pushes the local image of version $1 as the tag $2 of the repository, and prints its digest
push_tag() {
    local version=$1 tag=$2
    podman push --authfile "$WORK/auth.json" --digestfile "$WORK/digest" \
        "localhost/sbt2-server:$version" "docker://$IMAGE_REPOSITORY:$tag" >&2
    cat "$WORK/digest"
}

# Pushes the image of version $1 as :$1, and as :latest when the version is the newest
push_image() {
    local version=$1 digest
    login
    digest=$(push_tag "$version" "$version")
    if is_newest_version "$version"; then
        push_tag "$version" latest >/dev/null
    fi
    echo "$digest"
}

# Applies the JSON fields on stdin to the release $1 with tag $2 at commit $3. Every edit
# names the tag, as GitHub resets the tag of a draft that an edit leaves it out of.
edit_release() {
    local id=$1 tag=$2 commit=$3
    jq --arg tag "$tag" --arg commit "$commit" '. + {tag_name: $tag, target_commitish: $commit}' |
        github_api -X PATCH -d @- "$GITHUB_API/repos/$REPO/releases/$id" >/dev/null
}

# Publishes the release $1, which creates its tag $2 at commit $3 on GitHub
publish() {
    echo '{"draft": false}' | edit_release "$@"
}

# Puts the image reference $2 in the notes of the release $1, in place of an older one
name_image_in_notes() {
    local id=$1 reference=$2 release notes
    release=$(github_api "$GITHUB_API/repos/$REPO/releases/$id")
    notes=$(jq -r '.body // ""' <<<"$release")
    notes=${notes%%$'\n\n'"$NOTES_IMAGE_HEADING"*}
    notes+=$'\n\n'"$NOTES_IMAGE_HEADING"$'\n\n'"\`$reference\`"
    jq -n --arg body "$notes" '{body: $body}' |
        edit_release "$id" "$(jq -r .tag_name <<<"$release")" "$(jq -r .target_commitish <<<"$release")"
}

SERVER_SERVICE=sbt2-server.service

# Updates the server on this machine to the new :latest. A failure only warns, as the
# release is already published.
deploy() {
    if ! systemctl --user cat "$SERVER_SERVICE" >/dev/null 2>&1; then
        echo "${0##*/}: no sbt2-server service in the user session; skipped the deploy" >&2
        return 0
    fi
    podman auto-update >&2 || echo "${0##*/}: the deploy failed; run podman auto-update again" >&2
}
