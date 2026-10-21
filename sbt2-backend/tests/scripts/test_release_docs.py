import os
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).parents[3] / "scripts" / "release-lib.sh"
# set, so release-lib.sh takes nothing from the maintainer's .env
NO_TOKENS = {"GH_TOKEN": "unused", "GHCR_TOKEN": "unused"}
IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(*args: str | Path, cwd: Path | None = None) -> str:
    done = subprocess.run(
        ["git", *map(str, args)],
        cwd=cwd,
        env=os.environ | IDENTITY,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def make_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git("init", "--bare", "--quiet", "--initial-branch=main", remote)
    return remote


def publish_docs(
    tmp_path: Path, remote: Path, tag: str, html: str
) -> subprocess.CompletedProcess[str]:
    page = tmp_path / "index.html"
    page.write_text(html)
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}" && publish_docs {tag} "{page}"'],
        env=os.environ | NO_TOKENS | IDENTITY | {"SBT2_PAGES_REMOTE": str(remote)},
        check=False,
        capture_output=True,
        text=True,
    )


def pages_file(remote: Path, path: str) -> str:
    return git("--git-dir", remote, "show", f"gh-pages:{path}")


@pytest.mark.integration
def test_first_docs_publish_creates_the_pages_branch(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    git("--git-dir", remote, "symbolic-ref", "HEAD", "refs/heads/main")

    done = publish_docs(tmp_path, remote, "v1.2.3", "<h1>docs</h1>")

    assert done.returncode == 0, done.stderr
    assert pages_file(remote, "v1.2.3/index.html") == "<h1>docs</h1>"
    assert pages_file(remote, "latest/index.html") == "<h1>docs</h1>"
    assert pages_file(remote, ".nojekyll") == ""
    assert git("--git-dir", remote, "branch", "--list").split() == ["gh-pages"]
