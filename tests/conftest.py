import pytest

from sbt2 import pickling


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Rewrite the golden-run files from this run instead of checking them.",
    )


LEVELS = {"unit", "integration", "e2e"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        levels = LEVELS & {mark.name for mark in item.iter_markers()}
        if len(levels) != 1:
            raise pytest.UsageError(
                f"{item.nodeid} must be marked with exactly one of {sorted(LEVELS)}"
            )


@pytest.fixture(autouse=True, scope="session")
def pickle_reducers() -> None:
    pickling.register()
