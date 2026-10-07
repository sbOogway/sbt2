#!/usr/bin/env bash
# Builds the GUI of a release and uploads it. The release is $TAG or the newest vX.Y.Z tag.
# Refuses when the release has the GUI already, unless FORCE=1. Needs GH_TOKEN or a gh login.
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=release-lib.sh
. "$here/release-lib.sh"

use_github_token
tag=$(release_tag)
version=${tag#v}
tarball=sbt2-gui-$version-x86_64-linux.tar.gz
id=$(release_id "$tag")
refuse_existing "$id" "$tarball"

start_work "refs/tags/$tag"
# the build runs third-party build scripts, which have no use for the token
run_build "$here/build-gui.sh" "$version" "$WORK/src" "$WORK/out"
upload_asset "$id" "$WORK/out/$tarball"
refresh_checksums "$id"
echo "release-gui: uploaded $tarball to $tag"
