#!/usr/bin/env bash
# Opens a pull request that moves the nautilus-trader pin to the newest nightly
# on Nautech's index. Does nothing when the pin is already there or a pull
# request for that nightly exists.
set -euo pipefail

manifest=sbt2-backend/packages/sbt2-core/pyproject.toml

current=$(sed -nE 's/.*"nautilus-trader\[[a-z]+\]==([^"]+)".*/\1/p' "$manifest")

# Develop builds carry a "+run" local version and are deleted by the next
# merged commit, so only nightlies count.
newest=$(
    uv run --no-project --quiet --with packaging python3 - <<'EOF'
import re
import urllib.request

from packaging.version import Version

INDEX = "https://packages.nautechsystems.io/simple/nautilus-trader/"
WHEEL = re.compile(r"nautilus_trader-([^-+]+)-cp314-cp314-manylinux_[0-9_]+_x86_64\.whl")

# Cloudflare in front of the index refuses Python's default user agent
request = urllib.request.Request(INDEX, headers={"User-Agent": "sbt2-bump-nautilus"})
with urllib.request.urlopen(request) as page:
    versions = set(WHEEL.findall(page.read().decode()))
print(max(versions, key=Version))
EOF
)

if [ "$newest" = "$current" ]; then
    echo "bump-nautilus: $current is the newest nightly"
    exit 0
fi

branch="build/nautilus-$newest"
if git ls-remote --exit-code --heads origin "$branch" >/dev/null; then
    echo "bump-nautilus: $branch is already open"
    exit 0
fi

sed -i -E "s/(\"nautilus-trader\[[a-z]+\]==)[^\"]+\"/\1$newest\"/" "$manifest"
uv lock --project sbt2-backend --upgrade-package nautilus-trader

# `==` also matches today's tagged build of the nightly while it is still on the index
if ! scripts/check-nautilus-lock.sh; then
    git checkout -- "$manifest" sbt2-backend/uv.lock
    exit 1
fi

git switch --quiet -c "$branch"
git commit --quiet -am "build(deps): bump nautilus-trader to $newest"
git push --quiet origin "$branch"
gh pr create --head "$branch" --title "build(deps): bump nautilus-trader to $newest" --body "$(
    cat <<EOF
Moves the nautilus-trader pin from \`$current\` to the nightly \`$newest\`.

CI runs the characterization and golden-run tests, which name any nautilus behaviour the upgrade changed. Once merged, update the pin on the wiki's Quality and Deferred pages.

Opened by the \`nautilus-bump\` step of the live pipeline.
EOF
)"
echo "bump-nautilus: opened $branch"
