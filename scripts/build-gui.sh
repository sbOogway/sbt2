#!/usr/bin/env bash
# Builds the GUI of version $1 into the tarball $2/sbt2-gui-$1-x86_64-linux.tar.gz and
# checks that the binary prints that version. Publishes nothing. The glibc of the image
# that runs it sets the oldest distribution the binary runs on.
set -euo pipefail

version=${1:?usage: build-gui.sh VERSION OUT_DIR}
out=$(realpath -m "${2:?usage: build-gui.sh VERSION OUT_DIR}")
name=sbt2-gui-$version-x86_64-linux
root=$(cd "$(dirname "$0")/.." && pwd)

# rust-toolchain.toml pins the toolchain, and it applies under sbt2-gui
(cd "$root/sbt2-gui" && SBT2_VERSION=$version cargo build --release --locked -p sbt2-gui)
target=${CARGO_TARGET_DIR:-$root/sbt2-gui/target}

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/$name"
cp "$target/release/sbt2-gui" "$stage/$name/"
cp "$root/sbt2-gui/README.md" "$root/sbt2-gui/COPYING" "$root/sbt2-gui/COPYING.LESSER" "$stage/$name/"

printed=$("$stage/$name/sbt2-gui" --version)
if [ "$printed" != "$version" ]; then
    echo "build-gui: the binary prints '$printed', not '$version'" >&2
    exit 1
fi

mkdir -p "$out"
tar -C "$stage" -czf "$out/$name.tar.gz" "$name"
echo "build-gui: built $out/$name.tar.gz"
