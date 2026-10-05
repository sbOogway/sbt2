# shellcheck shell=bash
# Sourced by the release scripts. Talks to the GitHub API with $GH_TOKEN for $CI_REPO.
# Drafts are reached by id, because the tag lookups of older gh versions skip them.
GITHUB_API=${GITHUB_API:-https://api.github.com}
GITHUB_UPLOADS=${GITHUB_UPLOADS:-https://uploads.github.com}

github_api() {
    curl -fsS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$@"
}

# The drafts as "id tag target" lines
list_drafts() {
    github_api "$GITHUB_API/repos/$CI_REPO/releases?per_page=100" |
        jq -r '.[] | select(.draft) | "\(.id) \(.tag_name) \(.target_commitish)"'
}

# The id of the draft of $CI_COMMIT_SHA, or nothing
draft_id() {
    list_drafts | awk -v sha="$CI_COMMIT_SHA" '$3 == sha { print $1 }'
}

# The version of the draft with id $1, without the "v"
draft_version() {
    local tag
    tag=$(github_api "$GITHUB_API/repos/$CI_REPO/releases/$1" | jq -r .tag_name)
    echo "${tag#v}"
}

# Uploads the file $2 to the draft with id $1, replacing an asset of the same name
upload_asset() {
    local id=$1 file=$2 name old
    name=$(basename "$file")
    old=$(github_api "$GITHUB_API/repos/$CI_REPO/releases/$id/assets?per_page=100" |
        jq -r --arg name "$name" '.[] | select(.name == $name) | .id')
    if [ -n "$old" ]; then
        github_api -X DELETE "$GITHUB_API/repos/$CI_REPO/releases/assets/$old"
    fi
    github_api -X POST -H "Content-Type: application/octet-stream" --data-binary "@$file" \
        "$GITHUB_UPLOADS/repos/$CI_REPO/releases/$id/assets?name=$name" >/dev/null
}

# The repository of the server image, which GHCR wants in lower case
image_repository() {
    echo "ghcr.io/${CI_REPO_OWNER,,}/sbt2-server"
}

# The digest GHCR holds for the tag $1 of the server image
image_digest() {
    local path token
    path=${CI_REPO_OWNER,,}/sbt2-server
    token=$(curl -fsS -u "$CI_REPO_OWNER:$GH_TOKEN" \
        "https://ghcr.io/token?service=ghcr.io&scope=repository:$path:pull" | jq -r .token)
    curl -fsSI -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
        "https://ghcr.io/v2/$path/manifests/$1" |
        tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" { print $2 }'
}
