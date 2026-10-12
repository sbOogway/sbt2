from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, override

from sbt2.core.assets.base import QuoteConvention
from sbt2.core.assets.option_quotes import QuoteSettings


class OptionQuotes(QuoteConvention):
    """The quotes of an option venue are made from the marks, the IV and the
    index; its ``quotes`` setting holds the spread model."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        return {**venue, "quotes": asdict(self.settings(venue))}

    def settings(self, venue: Mapping[str, Any]) -> QuoteSettings:
        try:
            return QuoteSettings(**venue.get("quotes", {}))
        except TypeError as error:
            raise ValueError(f"the quotes setting is invalid: {error}") from error
