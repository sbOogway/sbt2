import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[3] / "scripts"
LIB = SCRIPTS / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}
SIGNING = (
    "SBT2_SIGNING_KEY",
    "SBT2_SIGNING_PASSPHRASE_FILE",
    "SBT2_SIGNING_PUBLIC_KEY",
)
# logs its call; a pull with --signature-policy keeps a copy of the policy
FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >>"$FAKE_LOG"
while [ $# -gt 0 ]; do
    [ "$1" = --signature-policy ] && cp "$2" "$FAKE_POLICY"
    shift
done
exit "${FAKE_STATUS:-0}"
"""


def make_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("podman", "curl", "git", "gh"):
        command = bin_dir / name
        command.write_text(FAKE)
        command.chmod(0o755)
    return bin_dir


def signing_files(tmp_path: Path) -> dict[str, str]:
    files = {}
    for key, name in zip(
        SIGNING, ("key.private", "passphrase", "key.pub"), strict=True
    ):
        path = tmp_path / name
        path.write_text(name)
        files[key] = str(path)
    return files


def run(
    tmp_path: Path, command: list[str], extra: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in SIGNING}
    fakes = {
        "PATH": f"{make_bin(tmp_path)}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "log"),
        "FAKE_POLICY": str(tmp_path / "policy.json"),
    }
    return subprocess.run(
        command,
        env=env | NO_TOKENS | fakes | extra,
        check=False,
        capture_output=True,
        text=True,
    )


def in_lib(
    tmp_path: Path, code: str, extra: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    work = tmp_path / "work"
    work.mkdir()
    (work / "digest").write_text("sha256:abc")
    return run(tmp_path, ["bash", "-c", f'. "{LIB}" && WORK={work} && {code}'], extra)


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "log"
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.unit
@pytest.mark.parametrize("script", ["release-publish.sh", "release-image.sh"])
@pytest.mark.parametrize("missing", SIGNING)
def test_release_refuses_to_start_without_the_signing_keys(
    tmp_path: Path, script: str, missing: str
) -> None:
    files = signing_files(tmp_path)
    files[missing] = str(tmp_path / "absent")

    done = run(tmp_path, ["bash", str(SCRIPTS / script)], files)

    assert done.returncode != 0
    assert "SBT2_SIGNING" in done.stderr or "public key" in done.stderr
    assert calls(tmp_path) == []


@pytest.mark.unit
def test_push_signs_the_image_with_the_private_key(tmp_path: Path) -> None:
    files = signing_files(tmp_path)

    done = in_lib(tmp_path, "push_tag 1.2.3 latest", files)

    assert done.returncode == 0
    assert done.stdout == "sha256:abc"
    [push] = calls(tmp_path)
    assert push.startswith("podman push ")
    assert f"--sign-by-sigstore-private-key {files['SBT2_SIGNING_KEY']} " in push
    sign_passphrase = f"--sign-passphrase-file {files['SBT2_SIGNING_PASSPHRASE_FILE']} "
    assert sign_passphrase in push
    assert "--remove-signatures" in push
    assert push.endswith(
        "localhost/sbt2-server:1.2.3 docker://ghcr.io/sboogway/sbt2-server:latest"
    )


@pytest.mark.unit
def test_verify_pulls_under_a_policy_with_the_public_key(tmp_path: Path) -> None:
    files = signing_files(tmp_path)

    done = in_lib(tmp_path, "verify_signature ghcr.io/x@sha256:abc", files)

    assert done.returncode == 0
    [pull] = calls(tmp_path)
    assert pull.startswith("podman pull ")
    assert pull.endswith(" docker://ghcr.io/x@sha256:abc")
    policy = json.loads((tmp_path / "policy.json").read_text())
    assert policy["transports"]["docker"]["ghcr.io/sboogway/sbt2-server"] == [
        {"type": "sigstoreSigned", "keyPath": files["SBT2_SIGNING_PUBLIC_KEY"]}
    ]


@pytest.mark.unit
def test_verify_fails_when_the_signature_is_rejected(tmp_path: Path) -> None:
    files = signing_files(tmp_path)

    done = in_lib(
        tmp_path, "verify_signature ghcr.io/x@sha256:abc", files | {"FAKE_STATUS": "1"}
    )

    assert done.returncode != 0
    assert "does not verify" in done.stderr
