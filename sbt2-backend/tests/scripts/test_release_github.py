import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

LIB = Path(__file__).parents[3] / "scripts" / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}
RELEASE = {"body": "notes", "tag_name": "v1.2.3", "target_commitish": "abc"}
FAKE_CURL = """#!/bin/sh
case " $* " in
*" -d @- "*) cat >"$FAKE_SENT" ;;
*) printf '%s' "$FAKE_RELEASE" ;;
esac
"""


def run_lib(tmp_path: Path, call: str) -> dict[str, Any]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    sent = tmp_path / "sent.json"
    fakes = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_SENT": str(sent),
        "FAKE_RELEASE": json.dumps(RELEASE),
    }
    subprocess.run(
        ["bash", "-c", f'. "{LIB}" && {call}'],
        env=os.environ | NO_TOKENS | fakes,
        check=True,
        capture_output=True,
    )
    return json.loads(sent.read_text())


@pytest.mark.unit
def test_publish_names_the_tag_and_commit_of_the_release(tmp_path: Path) -> None:
    sent = run_lib(tmp_path, "publish 7 v1.2.3 abc")

    assert sent == {"draft": False, "tag_name": "v1.2.3", "target_commitish": "abc"}


@pytest.mark.unit
def test_naming_the_image_keeps_the_tag_and_commit_of_the_release(
    tmp_path: Path,
) -> None:
    sent = run_lib(tmp_path, "name_image_in_notes 7 ghcr.io/x/y:1.2.3@sha256:0")

    assert sent["tag_name"] == "v1.2.3"
    assert sent["target_commitish"] == "abc"
    assert sent["body"].endswith("`ghcr.io/x/y:1.2.3@sha256:0`")
