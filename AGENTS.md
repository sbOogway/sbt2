# AGENTS.md

## Communication

- Use ASD-STE100 Simplified Technical English for all user-facing text.
- Be brief in all user-facing text, pull requests, reports and documentation.

## Comments

- Do not add unnecessary comments to the source code.
- Write a comment only for what the code cannot say itself: a non-obvious reason, a workaround, or an external constraint.
- Do not comment what the code already makes clear.
- Do not narrate changes in comments ("added X", "now uses Y").
- Do not leave commented-out code.

## Functions

- Keep functions short. When a function does more than one thing, split it.
- Split a function whenever a part of it can be extracted and named for what it does.
- Keep each function at a single level of abstraction.
- Give a function at most 3 arguments.
- When a function needs more than 3 arguments, group the ones that belong together into an object and pass that instead.
- Do not use boolean flag arguments to switch behaviour; write separate functions.

## Modules

- Make modules deep: a small, simple public interface hiding as much functionality as possible.
- Do not write shallow modules or pass-through functions that only forward calls.
- Modules talk to each other only through their public interfaces.
- Do not import another module's internals.
- Keep coupling loose: depend on interfaces (protocols or abstract types), not on concrete implementations.
- Split functions inside a module freely, but do not grow its public interface to do so.

## Workflow

- Start every feature or issue on a new branch from an up-to-date `main`. Never commit to `main` directly.
- Name the branch after the change type and topic, e.g. `feat/funding-ingest`, `fix/snapshot-grid`.
- Before creating the branch, settle the design questions and prepare the test plan (see below). Treat the test plan as approved without asking the user.
- Open a draft pull request on GitHub as soon as the branch has its first commit, linking the issue it addresses and including the approved test plan.
- Do the work on that branch, then mark the pull request ready for review.
- Stop and wait for the user's code review. Do not merge the pull request yourself.
- Address every review comment with new commits on the same branch, then ask for review again.
- Repeat until the user approves. Only the user decides when the work is done.

## Wiki

- Do not update the wiki when you implement an issue or do similar work.
- Update the wiki only when the user explicitly tells you to.

## Design questions

- Ask only about decisions that change a public interface, observable behaviour or a data format, or that are costly to reverse.
- Do not ask when the issue, the code or these rules already settle the answer.
- Ask with the question tool and wait for the answers.
- Settle every other decision yourself with the conventional option, and list it as an assumption next to the test plan.
- Do not ask for permission to proceed or to confirm a plan in general.

## Test-driven development

- Use it for `feat` and `fix` work. A fix starts with a test that reproduces the bug.
- A refactor adds no tests and must keep the existing ones passing unchanged. `docs`, `chore`, `ci` and `build` work skip it.
- After the design questions, prepare the test plan and treat it as approved before writing any code.
- Group the plan by module under test. For each test give:
  - its signature, e.g. `def test_unknown_classes_list_the_known_profiles() -> None:`
  - its markers: one level (`unit`, `integration` or `e2e`) and any kinds that apply (`characterization`, `golden`, `live`, `realdata`)
  - a plain-language description of the setup, the action and the expected outcome
- Work one behaviour at a time: write its tests, run them and check that they fail for the expected reason, implement until they pass, then commit before starting the next.
- Commit each behaviour's tests together with the code that makes them pass. Never commit failing tests.
- Do not build the whole feature first and split it into commits afterwards.
- If a test turns out to be missing or wrong during implementation, update the plan and continue.
- Edge-case tests that do not change the agreed behaviour can be added without asking. List them in the pull request description.

## Commits

- Write commit messages in the Conventional Commits format: `type(scope): summary`.
- Use `feat` for a new feature, `fix` for a bug fix, and `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `style` or `revert` for everything else.
- Mark breaking changes with `!` after the type or a `BREAKING CHANGE:` footer.
- Make every commit atomic: one logical change per commit, which builds and passes the tests on its own.
- Do not mix unrelated changes, such as a refactor and a feature, in one commit. Split them.
- Do not rewrite the commits of a branch under review; answer review comments with new commits.
- Rebasing a branch onto `main` is allowed. The post-merge hook does it for every open branch after `main` is pulled.

## Pre-commit

- Keep pre-commit configured in the repo.
- Run the pre-commit hooks before every commit, and fix what they report.
- Do not bypass the hooks (`--no-verify`, disabling or skipping hooks).

## Subagents

Use this when the user hands over issues or other tasks. The coordinator is the Claude session the user chats with. It runs inside herdr and controls the other agents with the `herdr` CLI.

### Coordinator

- Use the chat with the user only for communication. Do no code, git, GitHub or research work yourself.
- Give the research for design questions and test plans to an agent. Keep the decisions and the test plan yourself.
- Give every task to an agent in herdr, also small tasks, read-only research and pull request review.
- Pick the agent kind (e.g. `claude`, `codex`, `opencode`), the model and the thinking effort to fit each task.
- Settle the design questions with the user before you start a worker. Prepare the test plans and treat them as approved. Only purely mechanical test changes in a `refactor` (renames, calls adapted to a new API, identical assertions) may be approved by the coordinator.
- Give each issue its own herdr worktree workspace (`herdr worktree create`), with the branch cut from an up-to-date `origin/main`. Run the worker in the pane of that workspace.
- Before you send input to an agent, check its state (`herdr agent get` or `herdr agent read`). The user may have typed there.
- Run the work in waves. Issues that touch the same files, or depend on each other, never run in the same wave. They run one after the other. There is no fixed limit on parallel workers. Start the next wave only after the user has merged the previous one.
- Let a reviewer agent review every pull request against the issue, these rules and the bigger picture. Judge its findings, and send the fixes to the worker, to be made as new commits on its branch. Close the reviewer's pane when it finishes.
- Tell the user, in the chat and with a push notification, when a pull request is ready, when a decision is theirs, and about blockers or major problems.
- When you hand a pull request over to the user, first read the worker's final report. Then close its pane and remove its worktree, so the user can check out the branch.
- Send fixes for the user's review to a new worker. Give it a herdr worktree workspace on the existing pull request branch.
- Never merge a pull request, and never merge `main` into a branch. When a branch conflicts with `main`, ask the user how to resolve it.

### Worker brief

Every brief contains:

- The issue number, and the instruction to read the issue and `AGENTS.md` first and follow them strictly.
- The bigger picture: where the change fits in the milestones and in the library design on the wiki, and which existing code to take as a model of style.
- The branch name.
- The approved test plan, or for a `refactor` the delegated rule for mechanical test changes. If a test turns out to need more, stop and report it instead of changing it.
- The process: one behaviour at a time, atomic Conventional Commits, `prek run` and `git add -A` before every commit, `make check` fully passing and pyright clean.
- The attribution: commit and pull request footers name the real agent and model that did the work.
- The temp files: write them (e.g. pull request bodies) with `mktemp` or with the issue number in the name, never with a generic name.
- The pull request: a draft after the first commit, titled like the issue, with a summary, `Closes #N`, the test plan, the assumptions it settled and notes. Mark it ready when done.
- The wiki: do not edit it.
- The limits: never merge, never force-push or rewrite pushed history, never merge `main` into the branch, never change the global git config. On a conflict or a failing push, stop and report.
- The final report: the worker's last message in its pane, which the coordinator reads with `herdr agent read`. Short, with the pull request URL, the commits, the test results, the test files changed and any deviation or problem, candidly.
