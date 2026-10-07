#!/usr/bin/env bash
# Rebases every open local branch onto origin/main, fetched first, and force-pushes
# the ones that track a remote branch. Runs from any branch, by hand or as the
# post-merge hook. Leaves a branch alone when it is checked out in a worktree, when
# its remote has commits it lacks, or when the rebase conflicts.
set -euo pipefail

# git exports these to hooks; they would point every git call below at this checkout
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

base=main
remote=origin
target=$remote/$base

say() {
    echo "rebase-open-branches: $*" >&2
}

checked_out() {
    git worktree list --porcelain | sed -n 's|^branch refs/heads/||p'
}

open_branches() {
    git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads |
        awk -v base="$base" '$1 != base && $2 != "[gone]" { print $1 }'
}

behind_its_remote() {
    local upstream
    upstream=$(git rev-parse --abbrev-ref --symbolic-full-name "$1@{upstream}" 2>/dev/null) || return 1
    ! git merge-base --is-ancestor "$upstream" "$1"
}

fetch_base() {
    git fetch --quiet "$remote" "$base" || say "cannot fetch $remote; using the last fetched $target"
}

rebase_in_worktree() {
    local branch=$1 tmp status=0
    tmp=$(mktemp -d)
    git worktree add --quiet "$tmp" "$branch"
    if ! git -C "$tmp" rebase --quiet "$target" >/dev/null 2>&1; then
        git -C "$tmp" rebase --abort
        status=1
    fi
    git worktree remove --force "$tmp"
    return "$status"
}

push() {
    local branch=$1 remote lease
    remote=$(git for-each-ref --format='%(upstream:remotename)' "refs/heads/$branch")
    [[ -n "$remote" ]] || return 0
    lease=$(git rev-parse "$branch@{upstream}")
    git push --quiet --force-with-lease="$branch:$lease" "$remote" "$branch"
}

rebase() {
    local branch=$1
    if git merge-base --is-ancestor "$target" "$branch"; then
        return
    fi
    if behind_its_remote "$branch"; then
        say "skipped $branch, its remote has commits it lacks"
        return
    fi
    if ! rebase_in_worktree "$branch"; then
        say "skipped $branch, it conflicts with $base"
        return
    fi
    if push "$branch"; then
        say "rebased $branch onto $base"
    else
        say "rebased $branch, but the push failed"
    fi
}

fetch_base
busy=$(checked_out)
open_branches | while read -r branch; do
    if grep -qxF "$branch" <<<"$busy"; then
        say "skipped $branch, it is checked out in a worktree"
        continue
    fi
    rebase "$branch"
done
