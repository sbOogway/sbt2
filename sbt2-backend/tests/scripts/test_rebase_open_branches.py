import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "rebase-open-branches.sh"

# keeps the user's git config, and any hooks it installs, out of the test repos
ISOLATED = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str) -> str:
    env = os.environ | ISOLATED
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def commit(repo: Path, file: str, text: str) -> None:
    (repo / file).write_text(text)
    git(repo, "add", file)
    git(repo, "commit", "--quiet", "--message", f"write {file}")


@dataclass(frozen=True)
class Repos:
    origin: Path
    me: Path
    other: Path

    def branch(self, name: str) -> None:
        """A branch off main in ``me`` with one commit of its own, left unpushed."""
        git(self.me, "switch", "--quiet", "--create", name, "main")
        commit(self.me, f"{name}.txt", name)
        git(self.me, "switch", "--quiet", "main")

    def pushed_branch(self, name: str) -> None:
        self.branch(name)
        git(self.me, "push", "--quiet", "--set-upstream", "origin", name)

    def merge_into_main(self) -> None:
        """Someone else moves main on origin, and ``me`` pulls it."""
        git(self.other, "pull", "--quiet", "--ff-only")
        commit(self.other, "base.txt", "changed on main\n")
        git(self.other, "push", "--quiet", "origin", "main")
        git(self.me, "pull", "--quiet", "--ff-only")

    def run(self, env: dict[str, str] | None = None) -> str:
        """The script's messages after running it in ``me``."""
        done = subprocess.run(
            [str(SCRIPT)],
            cwd=self.me,
            env=os.environ | ISOLATED | (env or {}),
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stderr

    def on_main(self, branch: str) -> bool:
        return is_ancestor(self.me, "main", branch)

    def local(self, branch: str) -> str:
        return git(self.me, "rev-parse", branch)

    def remote(self, branch: str) -> str:
        return git(self.origin, "rev-parse", branch)


def is_ancestor(repo: Path, ancestor: str, branch: str) -> bool:
    env = os.environ | ISOLATED
    args = ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, branch]
    return subprocess.run(args, env=env, check=False).returncode == 0


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    origin, me, other = tmp_path / "origin.git", tmp_path / "me", tmp_path / "other"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch", "main", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(me))
    commit(me, "base.txt", "base\n")
    git(me, "push", "--quiet", "--set-upstream", "origin", "main")
    git(tmp_path, "clone", "--quiet", str(origin), str(other))
    return Repos(origin, me, other)


@pytest.mark.integration
def test_a_pushed_branch_is_rebased_onto_main_and_pushed(repos: Repos) -> None:
    repos.pushed_branch("feature")
    repos.merge_into_main()

    messages = repos.run()

    assert repos.on_main("feature")
    assert repos.remote("feature") == repos.local("feature")
    assert "rebased feature onto main" in messages


@pytest.mark.integration
def test_a_branch_never_pushed_is_rebased_but_not_pushed(repos: Repos) -> None:
    repos.branch("feature")
    repos.merge_into_main()

    repos.run()

    assert repos.on_main("feature")
    assert git(repos.origin, "branch", "--list", "feature") == ""


@pytest.mark.integration
def test_a_conflicting_branch_is_left_as_it_was(repos: Repos) -> None:
    git(repos.me, "switch", "--quiet", "--create", "feature")
    commit(repos.me, "base.txt", "changed on feature\n")
    git(repos.me, "push", "--quiet", "--set-upstream", "origin", "feature")
    git(repos.me, "switch", "--quiet", "main")
    before = repos.local("feature")
    repos.merge_into_main()

    messages = repos.run()

    assert repos.local("feature") == repos.remote("feature") == before
    assert not list((repos.me / ".git").glob("worktrees/*/rebase-merge"))
    assert "skipped feature, it conflicts with main" in messages


@pytest.mark.integration
def test_a_branch_whose_remote_is_ahead_is_left_as_it_was(repos: Repos) -> None:
    repos.pushed_branch("feature")
    git(repos.other, "fetch", "--quiet")
    git(repos.other, "switch", "--quiet", "feature")
    commit(repos.other, "theirs.txt", "pushed by someone else")
    git(repos.other, "push", "--quiet")
    git(repos.other, "switch", "--quiet", "main")
    local, remote = repos.local("feature"), repos.remote("feature")
    repos.merge_into_main()

    messages = repos.run()

    assert (repos.local("feature"), repos.remote("feature")) == (local, remote)
    assert "skipped feature, its remote has commits it lacks" in messages


@pytest.mark.integration
def test_a_branch_checked_out_in_a_worktree_is_left_as_it_was(
    repos: Repos, tmp_path: Path
) -> None:
    repos.pushed_branch("feature")
    git(repos.me, "worktree", "add", "--quiet", str(tmp_path / "feature"), "feature")
    before = repos.local("feature")
    repos.merge_into_main()

    messages = repos.run()

    assert repos.local("feature") == repos.remote("feature") == before
    assert "skipped feature, it is checked out in a worktree" in messages


@pytest.mark.integration
def test_a_branch_that_already_contains_main_is_not_touched(repos: Repos) -> None:
    repos.merge_into_main()
    repos.pushed_branch("feature")
    before = repos.local("feature")

    messages = repos.run()

    assert repos.local("feature") == repos.remote("feature") == before
    assert messages == ""


@pytest.mark.integration
def test_off_main_the_other_branches_are_rebased_too(repos: Repos) -> None:
    repos.pushed_branch("feature")
    repos.pushed_branch("other")
    repos.merge_into_main()
    git(repos.me, "switch", "--quiet", "other")
    before = repos.local("other")

    messages = repos.run()

    assert repos.on_main("feature")
    assert repos.remote("feature") == repos.local("feature")
    assert repos.local("other") == repos.remote("other") == before
    assert "skipped other, it is checked out in a worktree" in messages


@pytest.mark.integration
def test_a_main_not_yet_pulled_is_fetched_first(repos: Repos) -> None:
    repos.pushed_branch("feature")
    git(repos.other, "pull", "--quiet", "--ff-only")
    commit(repos.other, "base.txt", "changed on main\n")
    git(repos.other, "push", "--quiet", "origin", "main")

    repos.run()

    pushed_main = repos.remote("main")
    assert is_ancestor(repos.me, pushed_main, "feature")
    assert repos.remote("feature") == repos.local("feature")


@pytest.mark.integration
def test_it_ignores_the_git_variables_a_hook_is_given(repos: Repos) -> None:
    repos.pushed_branch("feature")
    repos.merge_into_main()
    hook = {"GIT_DIR": str(repos.me / ".git"), "GIT_WORK_TREE": str(repos.me)}

    repos.run(hook)

    assert repos.on_main("feature")
    assert repos.remote("feature") == repos.local("feature")


@pytest.mark.integration
def test_no_temporary_worktrees_are_left_behind(repos: Repos) -> None:
    repos.pushed_branch("clean")
    git(repos.me, "switch", "--quiet", "--create", "conflict")
    commit(repos.me, "base.txt", "changed on conflict\n")
    git(repos.me, "switch", "--quiet", "main")
    repos.merge_into_main()

    repos.run()

    assert git(repos.me, "worktree", "list", "--porcelain").count("worktree ") == 1
