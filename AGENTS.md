# AGENTS.md

- Do not add unnecessary comments to the source code.
- Write a comment only for what the code cannot say itself: a non-obvious reason, a workaround, or an external constraint.
- Do not comment what the code already makes clear.
- Do not narrate changes in comments ("added X", "now uses Y").
- Do not leave commented-out code.
- Keep pre-commit configured in the repo.
- Run the pre-commit hooks before every commit, and fix what they report.
- Do not bypass the hooks (`--no-verify`, disabling or skipping hooks).
