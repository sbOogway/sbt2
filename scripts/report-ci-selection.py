import json
import os
from pathlib import Path

import yaml


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern.removesuffix("/**")
        return path == prefix or path.startswith(f"{prefix}/")
    if any(character in pattern for character in "*?["):
        raise ValueError(f"Unsupported report pattern: {pattern}")
    return path == pattern


def _path_reason(step: dict, files: list[str]) -> str:
    condition = next(rule for rule in step["when"] if rule["event"] == "pull_request")
    patterns = condition["path"]["include"]
    if not files:
        return "RUN: empty file list; run all checks for safety"
    matched = [
        path for path in files if any(_matches(path, pattern) for pattern in patterns)
    ]
    if matched:
        return f"RUN: affected files: {', '.join(matched)}"
    return f"SKIP: no changed file matches: {', '.join(patterns)}"


def _step_reason(step: dict, context: dict) -> str:
    if "when" not in step:
        return "RUN: required on every CI run"
    if context["event"] != "pull_request":
        return f"RUN: full checks for {context['event']}"
    if context["files"] is None:
        return "SERVER FILTER: changed-file list is not exported; see Woodpecker step status"
    return _path_reason(step, context["files"])


def main() -> None:
    workflow = yaml.safe_load(Path(".woodpecker/ci.yaml").read_text())
    exported_files = os.environ.get("CI_PIPELINE_FILES")
    context = {
        "event": os.environ["CI_PIPELINE_EVENT"],
        "files": json.loads(exported_files) if exported_files is not None else None,
    }
    for step in workflow["steps"]:
        print(f"{step['name']}: {_step_reason(step, context)}")


if __name__ == "__main__":
    main()
