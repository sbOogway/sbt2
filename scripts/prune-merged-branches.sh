#!/usr/bin/env bash
set -euo pipefail

git fetch --prune --quiet

current=$(git branch --show-current)
git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads |
    awk '$2 == "[gone]" { print $1 }' |
    while read -r branch; do
        [[ "$branch" == "$current" ]] && continue
        git branch -d "$branch" 2>/dev/null || echo "prune-merged-branches: kept $branch, not fully merged" >&2
    done
