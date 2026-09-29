#!/usr/bin/env bash
# Prepares a release in $out when the commits since the last tag call for one:
# the tag name, its notes and the built distributions. Leaves $out empty otherwise.
set -euo pipefail

out=${1:-.release}
cliff=(uvx git-cliff==2.14.2)

rm -rf "$out"
mkdir -p "$out"

next=$("${cliff[@]}" --bumped-version 2>/dev/null)
if git rev-parse --quiet --verify "refs/tags/$next" >/dev/null; then
    echo "prepare-release: nothing to release since $next"
    exit 0
fi

git tag "$next"
"${cliff[@]}" --unreleased --tag "$next" --strip all --output "$out/notes.md" 2>/dev/null
uv build --out-dir "$out/dist"
echo "$next" >"$out/tag"
echo "prepare-release: prepared $next"
