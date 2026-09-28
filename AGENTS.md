# AGENTS.md

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
- Before starting work on a new issue, ask the user about its open design points with the question tool, and wait for the answers.
- Open a draft pull request on GitHub as soon as the branch has its first commit, linking the issue it addresses.
- Do the work on that branch, then mark the pull request ready for review.
- Stop and wait for the user's code review. Do not merge the pull request yourself.
- Address every review comment with new commits on the same branch, then ask for review again.
- Repeat until the user approves. Only the user decides when the work is done.

## Commits

- Write commit messages in the Conventional Commits format: `type(scope): summary`.
- Use `feat` for a new feature, `fix` for a bug fix, and `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `style` or `revert` for everything else.
- Mark breaking changes with `!` after the type or a `BREAKING CHANGE:` footer.
- Make every commit atomic: one logical change per commit, which builds and passes the tests on its own.
- Do not mix unrelated changes, such as a refactor and a feature, in one commit. Split them.
- Do not rewrite history on a branch under review; add commits instead.

## Pre-commit

- Keep pre-commit configured in the repo.
- Run the pre-commit hooks before every commit, and fix what they report.
- Do not bypass the hooks (`--no-verify`, disabling or skipping hooks).
