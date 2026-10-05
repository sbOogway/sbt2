#!/usr/bin/env bash
# Builds the GUI of version $1 from the source tree $2 into the tarball
# $3/sbt2-gui-$1-x86_64-linux.tar.gz and checks that the binary prints that version.
# Publishes nothing. The binary needs a glibc as new as this machine's.
set -euo pipefail

version=${1:?usage: build-gui.sh VERSION SOURCE_DIR OUT_DIR}
source=$(realpath "${2:?usage: build-gui.sh VERSION SOURCE_DIR OUT_DIR}")
out=$(realpath -m "${3:?usage: build-gui.sh VERSION SOURCE_DIR OUT_DIR}")
name=sbt2-gui-$version-x86_64-linux
# the cache outlives the throwaway source tree, so only the workspace crates rebuild
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/sbt2-release/gui-target}

# rust-toolchain.toml pins the toolchain, and it applies under sbt2-gui
(cd "$source/sbt2-gui" && SBT2_VERSION=$version cargo build --release --locked -p sbt2-gui)

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/$name"
cp "$CARGO_TARGET_DIR/release/sbt2-gui" "$stage/$name/"
cp "$source/sbt2-gui/README.md" "$source/sbt2-gui/COPYING" "$source/sbt2-gui/COPYING.LESSER" "$stage/$name/"

printed=$("$stage/$name/sbt2-gui" --version)
if [ "$printed" != "$version" ]; then
    echo "build-gui: the binary prints '$printed', not '$version'" >&2
    exit 1
fi

mkdir -p "$out"
tar -C "$stage" -czf "$out/$name.tar.gz" "$name"
echo "build-gui: built $out/$name.tar.gz"
