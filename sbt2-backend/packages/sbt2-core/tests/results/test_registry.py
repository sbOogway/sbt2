import pytest

from sbt2.core.results import UnknownStoreError, open_store


@pytest.mark.unit
def test_an_unregistered_store_kind_lists_the_known_ones() -> None:
    with pytest.raises(UnknownStoreError, match="nowhere; known: parquet"):
        open_store({"kind": "nowhere"})
