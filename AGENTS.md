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

## Pre-commit

- Keep pre-commit configured in the repo.
- Run the pre-commit hooks before every commit, and fix what they report.
- Do not bypass the hooks (`--no-verify`, disabling or skipping hooks).
