#!/usr/bin/env bash
# Prepares a release in $out when the commits since the last tag call for one:
# the tag name, its notes and the built distributions. Leaves $out empty otherwise.
set -euo pipefail

out=${1:-.release}
config=sbt2-backend/pyproject.toml
cliff=(uvx git-cliff==2.14.2 --config "$config")

rm -rf "$out"
mkdir -p "$out"

next=$("${cliff[@]}" --bumped-version 2>/dev/null)
if git rev-parse --quiet --verify "refs/tags/$next" >/dev/null; then
    echo "prepare-release: nothing to release since $next"
    exit 0
fi

git tag "$next"
"${cliff[@]}" --latest --strip all --output "$out/notes.md" 2>/dev/null
uv build --project sbt2-backend --all-packages --out-dir "$out/dist"
echo "$next" >"$out/tag"
echo "prepare-release: prepared $next"
