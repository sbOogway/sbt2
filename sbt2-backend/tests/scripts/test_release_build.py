import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
LIB = ROOT / "scripts" / "release-lib.sh"
TOKENS = {"GH_TOKEN": "gh-secret", "GHCR_TOKEN": "ghcr-secret"}
PROBE = 'echo "$GH_TOKEN|$GHCR_TOKEN|$CARGO_BUILD_JOBS|$(nice)|$(ionice)"'


def build_sees(extra: dict[str, str]) -> list[str]:
    done = subprocess.run(
        ["bash", "-c", f". \"{LIB}\" && run_build sh -c '{PROBE}'"],
        env=os.environ | TOKENS | extra,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip().split("|")


@pytest.mark.unit
def test_a_build_runs_without_the_tokens_at_the_lowest_priority() -> None:
    gh, ghcr, _, niceness, io_class = build_sees({})

    assert (gh, ghcr) == ("", "")
    assert niceness == "19"
    assert io_class == "idle"


@pytest.mark.unit
def test_a_build_uses_half_the_cores_unless_told_otherwise() -> None:
    # nproc counts the cores this process may use, as process_cpu_count does
    half = str(((os.process_cpu_count() or 1) + 1) // 2)

    assert build_sees({})[2] == half
    assert build_sees({"SBT2_BUILD_JOBS": "3"})[2] == "3"


IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
FAKE_UVX = """#!/bin/sh
case " $* " in
*" --bumped-version "*) echo v1.0.1 ;;
*)
    while [ $# -gt 0 ]; do
        if [ "$1" = --output ]; then echo notes >"$2"; fi
        shift
    done
    ;;
esac
"""
FAKE_UV = f"""#!/bin/sh
if [ "$1" = build ]; then
    while [ $# -gt 0 ]; do
        if [ "$1" = --out-dir ]; then touch "$2/sbt2-1.0.1.whl"; fi
        shift
    done
    exit 0
fi
while [ "$1" != python ]; do shift; done
shift
exec {sys.executable} "$@"
"""
FAKE_CURL = "#!/bin/sh\necho '{}'\n"
FAKE_BUILD_IMAGE = "#!/bin/sh\n"
FAKE_GO_FAILING = "#!/bin/sh\necho 'no generator' >&2\nexit 1\n"
PROTO_DIR = "sbt2-protocol/sbt2/protocol/v1"
IGNORED_PROTO = (
    'syntax = "proto3";\npackage sbt2.protocol.v1;\nmessage IgnoredLocalMessage {}\n'
)


def git(*args: str | Path, cwd: Path) -> str:
    done = subprocess.run(
        ["git", *map(str, args)],
        cwd=cwd,
        env=os.environ | IDENTITY,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def write_stub(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / name
    stub.write_text(text)
    stub.chmod(0o755)


def make_release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    write_stub(repo / "scripts", "build-image.sh", FAKE_BUILD_IMAGE)
    shutil.copytree(ROOT / "sbt2-protocol" / "sbt2", repo / "sbt2-protocol" / "sbt2")
    shutil.copy(ROOT / ".pre-commit-config.yaml", repo)
    (repo / PROTO_DIR / "ignored_local.proto").write_text(IGNORED_PROTO)
    (repo / ".gitignore").write_text(f"{PROTO_DIR}/ignored_local.proto\n")
    origin = tmp_path / "origin.git"
    git("init", "--bare", "--quiet", "--initial-branch=main", origin, cwd=tmp_path)
    git("init", "--quiet", "--initial-branch=main", cwd=repo)
    git("remote", "add", "origin", origin, cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "--quiet", "-m", "chore: start", cwd=repo)
    git("tag", "v1.0.0", cwd=repo)
    (repo / "CHANGELOG").write_text("fix\n")
    git("add", "-A", cwd=repo)
    git("commit", "--quiet", "-m", "fix: change", cwd=repo)
    git("push", "--quiet", "origin", "main", cwd=repo)
    return repo


def run_release_build(
    tmp_path: Path, repo: Path, extra_bin: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    write_stub(bin_dir, "uvx", FAKE_UVX)
    write_stub(bin_dir, "uv", FAKE_UV)
    write_stub(bin_dir, "curl", FAKE_CURL)
    for name, text in extra_bin.items():
        write_stub(bin_dir, name, text)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SBT2_RELEASE_DIR": str(tmp_path / "release"),
        "SBT2_RELEASE_CHECK": "true",
        "GH_TOKEN": "unused",
        "GHCR_TOKEN": "unused",
    }
    return subprocess.run(
        [str(repo / "scripts" / "release-build.sh")],
        cwd=repo,
        env=os.environ | IDENTITY | env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
def test_release_build_stages_protocol_html_from_the_release_commit(
    tmp_path: Path,
) -> None:
    repo = make_release_repo(tmp_path)

    done = run_release_build(tmp_path, repo, {})

    assert done.returncode == 0, done.stderr
    html = (tmp_path / "release" / "docs" / "index.html").read_text()
    assert "SubmitRun" in html
    assert "IgnoredLocalMessage" not in html
    assert not list((tmp_path / "release" / "files").glob("*.html"))
    assert (
        "index.html" not in (tmp_path / "release" / "files" / "SHA256SUMS").read_text()
    )


@pytest.mark.integration
def test_failed_protocol_html_build_keeps_the_previous_release_build(
    tmp_path: Path,
) -> None:
    repo = make_release_repo(tmp_path)
    previous = tmp_path / "release"
    (previous / "docs").mkdir(parents=True)
    (previous / "docs" / "index.html").write_text("previous")

    done = run_release_build(tmp_path, repo, {"go": FAKE_GO_FAILING})

    assert done.returncode != 0
    assert (previous / "docs" / "index.html").read_text() == "previous"
    assert not (previous / "files").exists()


@pytest.mark.integration
def test_release_build_installs_the_generator_with_the_hook_go_version(
    tmp_path: Path,
) -> None:
    repo = make_release_repo(tmp_path)
    seen = tmp_path / "toolchain"
    spy = f'#!/bin/sh\necho "$GOTOOLCHAIN" >{seen}\nexit 1\n'

    run_release_build(tmp_path, repo, {"go": spy})

    hook = (ROOT / ".pre-commit-config.yaml").read_text()
    version = (
        hook.split("id: generate-protocol-docs")[1]
        .split("language_version: ")[1]
        .split()[0]
    )
    assert seen.read_text().strip() == f"go{version}"
