import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "check-protocol-breaking.sh"

ISOLATED = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=os.environ | ISOLATED,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@pytest.mark.integration
def test_a_hook_in_a_linked_worktree_leaves_the_repo_not_bare(tmp_path: Path) -> None:
    repo, worktree = tmp_path / "repo", tmp_path / "worktree"
    git(tmp_path, "init", "--quiet", str(repo))
    git(repo, "commit", "--quiet", "--allow-empty", "--message", "start")
    git(repo, "worktree", "add", "--quiet", str(worktree))
    # git sets GIT_DIR for hooks; refusing https keeps the script's fetch offline
    hook = {"GIT_DIR": str(repo / ".git" / "worktrees" / "worktree")}
    offline = {"GIT_ALLOW_PROTOCOL": "file"}

    subprocess.run(
        [str(SCRIPT)],
        cwd=worktree,
        env=os.environ | ISOLATED | hook | offline,
        check=False,
        capture_output=True,
    )

    assert git(repo, "config", "core.bare") == "false"
