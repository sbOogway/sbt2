#!/usr/bin/env bash
# Encodes every golden/**/<case>.textproto into its <case>.binpb, with the message type
# its "# proto-message:" header names, and removes the .binpb files left without a textproto.
# The only writer of the .binpb files: the golden hook fails when one is stale.
set -euo pipefail

cd "$(dirname "$0")/.."

find golden -name '*.binpb' -print0 | while IFS= read -r -d '' binary; do
    [[ -e ${binary%.binpb}.textproto ]] || rm -- "$binary"
done

find golden -name '*.textproto' -print0 | sort -z | while IFS= read -r -d '' text; do
    header=$(head -n 1 -- "$text")
    type=${header#\# proto-message: }
    if [[ $header == "$type" || -z $type ]]; then
        echo "$text: the first line must be '# proto-message: <full message name>'" >&2
        exit 1
    fi
    buf convert . --type "$type" --from "$text#format=txtpb" --to "${text%.textproto}.binpb#format=binpb"
done
