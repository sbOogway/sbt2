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
        ["bash", "-c", f'set -euo pipefail; . "{LIB}" && publish_docs {tag} "{page}"'],
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


def add_site_file(tmp_path: Path, remote: Path, name: str, text: str) -> None:
    work = tmp_path / "site"
    git("clone", "--quiet", "--branch", "gh-pages", remote, work)
    (work / name).write_text(text)
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "add site file", cwd=work)
    git("push", "--quiet", "origin", "gh-pages", cwd=work)


@pytest.mark.integration
def test_docs_publish_preserves_other_versions_and_site_files(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    publish_docs(tmp_path, remote, "v1.0.0", "old")
    add_site_file(tmp_path, remote, "CNAME", "docs.example.com")

    done = publish_docs(tmp_path, remote, "v1.1.0", "new")

    assert done.returncode == 0, done.stderr
    assert pages_file(remote, "v1.0.0/index.html") == "old"
    assert pages_file(remote, "v1.1.0/index.html") == "new"
    assert pages_file(remote, "latest/index.html") == "new"
    assert pages_file(remote, "CNAME") == "docs.example.com"


@pytest.mark.integration
def test_repeated_docs_publish_keeps_the_same_commit(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    publish_docs(tmp_path, remote, "v1.2.3", "docs")
    first = git("--git-dir", remote, "rev-parse", "gh-pages")

    done = publish_docs(tmp_path, remote, "v1.2.3", "docs")

    assert done.returncode == 0, done.stderr
    assert git("--git-dir", remote, "rev-parse", "gh-pages") == first


@pytest.mark.integration
def test_older_docs_publish_does_not_replace_latest(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    publish_docs(tmp_path, remote, "v1.10.0", "newer")

    done = publish_docs(tmp_path, remote, "v1.9.0", "older")

    assert done.returncode == 0, done.stderr
    assert pages_file(remote, "v1.9.0/index.html") == "older"
    assert pages_file(remote, "latest/index.html") == "newer"
