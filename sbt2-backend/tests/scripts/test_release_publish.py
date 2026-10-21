import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
LIB = ROOT / "scripts" / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}
FAKE_GIT = """#!/bin/sh
case "$1" in
fetch) exit 0 ;;
rev-parse) echo "$FAKE_MAIN" ;;
esac
"""


def check_build(tmp_path: Path, built: str | None) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(FAKE_GIT)
    git.chmod(0o755)
    build_dir = tmp_path / "release"
    if built is not None:
        build_dir.mkdir()
        (build_dir / "head").write_text(f"{built}\n")
    fakes = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_MAIN": "abc",
        "SBT2_RELEASE_DIR": str(build_dir),
    }
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}" && check_build'],
        env=os.environ | NO_TOKENS | fakes,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_publish_refuses_without_a_build(tmp_path: Path) -> None:
    done = check_build(tmp_path, None)

    assert done.returncode != 0
    assert "run make build first" in done.stderr


@pytest.mark.unit
def test_publish_refuses_a_build_of_an_older_main(tmp_path: Path) -> None:
    done = check_build(tmp_path, "old")

    assert done.returncode != 0
    assert "origin/main moved since the build" in done.stderr


@pytest.mark.unit
def test_publish_accepts_a_build_of_the_current_main(tmp_path: Path) -> None:
    done = check_build(tmp_path, "abc")

    assert done.returncode == 0


IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
FAKE_CURL = """#!/bin/sh
body=
case " $* " in *" -d @- "*) body=$(cat) ;; esac
echo "$* $body" >>"$FAKE_LOG"
case "$body" in
*'"draft": false'*)
    if git ls-remote --exit-code --heads "$FAKE_PAGES" gh-pages >/dev/null; then
        echo PUBLISHED-AFTER-PAGES >>"$FAKE_LOG"
    else
        echo PUBLISHED-BEFORE-PAGES >>"$FAKE_LOG"
    fi
    ;;
esac
case " $* " in
*"/releases?per_page"*) echo '[]' ;;
*" -X POST "*"/releases ") echo '{"id": 7}' ;;
*"/releases/7 "*) echo "{\\"body\\": \\"\\", \\"tag_name\\": \\"v1.0.1\\", \\"target_commitish\\": \\"$FAKE_HEAD\\"}" ;;
*"/assets"*) echo '[]' ;;
*) echo '{}' ;;
esac
"""
FAKE_PODMAN = """#!/bin/sh
case "$1" in
push)
    while [ $# -gt 0 ]; do
        if [ "$1" = --digestfile ]; then echo sha256:0 >"$2"; fi
        shift
    done
    ;;
esac
"""
FAKE_QUIET = "#!/bin/sh\nexit 0\n"
FAKE_NO_SERVICE = "#!/bin/sh\nexit 1\n"
STAGED_HTML = "<h1>staged docs</h1>"


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


def make_publish_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    shutil.copytree(ROOT / "sbt2-backend" / "deploy", repo / "sbt2-backend" / "deploy")
    origin = tmp_path / "origin.git"
    git("init", "--bare", "--quiet", "--initial-branch=main", origin, cwd=tmp_path)
    git("init", "--quiet", "--initial-branch=main", cwd=repo)
    git("remote", "add", "origin", origin, cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "--quiet", "-m", "chore: start", cwd=repo)
    git("push", "--quiet", "origin", "main", cwd=repo)
    return repo, origin


def stage_build(tmp_path: Path, repo: Path) -> Path:
    release = tmp_path / "release"
    head = git("rev-parse", "HEAD", cwd=repo)
    (release / "files").mkdir(parents=True)
    (release / "files" / "sbt2-1.0.1.whl").write_text("wheel")
    (release / "docs").mkdir()
    (release / "docs" / "index.html").write_text(STAGED_HTML)
    (release / "notes.md").write_text("notes")
    (release / "tags").write_text(f"{head} v1.0.1\n")
    (release / "head").write_text(f"{head}\n")
    return release


def run_release_publish(
    tmp_path: Path, repo: Path, origin: Path
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    write_stub(bin_dir, "curl", FAKE_CURL)
    write_stub(bin_dir, "podman", FAKE_PODMAN)
    write_stub(bin_dir, "skopeo", FAKE_QUIET)
    write_stub(bin_dir, "systemctl", FAKE_NO_SERVICE)
    key = tmp_path / "key"
    key.write_text("key")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SBT2_RELEASE_DIR": str(tmp_path / "release"),
        "SBT2_PAGES_REMOTE": str(origin),
        "SBT2_SIGNING_KEY": str(key),
        "SBT2_SIGNING_PASSPHRASE_FILE": str(key),
        "GH_TOKEN": "unused",
        "GHCR_TOKEN": "unused",
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_PAGES": str(origin),
        "FAKE_HEAD": git("rev-parse", "HEAD", cwd=repo),
    }
    return subprocess.run(
        [str(repo / "scripts" / "release-publish.sh")],
        cwd=repo,
        env=os.environ | IDENTITY | env,
        check=False,
        capture_output=True,
        text=True,
    )


def calls(tmp_path: Path) -> str:
    return (tmp_path / "calls.log").read_text()


@pytest.mark.integration
def test_publish_uses_staged_html_before_publishing_the_release(
    tmp_path: Path,
) -> None:
    repo, origin = make_publish_repo(tmp_path)
    release = stage_build(tmp_path, repo)

    done = run_release_publish(tmp_path, repo, origin)

    assert done.returncode == 0, done.stderr
    assert "PUBLISHED-AFTER-PAGES" in calls(tmp_path)
    for path in ("v1.0.1/index.html", "latest/index.html"):
        shown = git("--git-dir", origin, "show", f"gh-pages:{path}", cwd=tmp_path)
        assert shown == STAGED_HTML
    assert not release.exists()


@pytest.mark.integration
def test_pages_failure_keeps_the_release_build_for_retry(tmp_path: Path) -> None:
    repo, origin = make_publish_repo(tmp_path)
    release = stage_build(tmp_path, repo)
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    failed = run_release_publish(tmp_path, repo, origin)

    assert failed.returncode != 0
    assert "PUBLISHED" not in calls(tmp_path)
    assert (release / "head").exists()
    hook.unlink()
    retried = run_release_publish(tmp_path, repo, origin)
    assert retried.returncode == 0, retried.stderr
    assert "PUBLISHED-AFTER-PAGES" in calls(tmp_path)
    assert not release.exists()
