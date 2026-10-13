from datetime import datetime, timedelta
from typing import ClassVar, override

from run_strategies import OnSchedule

from sbt2.core.strategy import IV_LOOKBACK, NoParams
from sbt2.core.strategy.chain import MultipleChainsError


class ReadChains(OnSchedule):
    """Notes, at each tick, the underlyings of the contracts of each chain."""

    seen: ClassVar[dict[datetime, dict[str, set[str]]]] = {}

    @override
    def on_schedule(self, now: datetime) -> None:
        self.seen[now] = {
            code: {each.underlying.code for each in chain.contracts()}
            for code, chain in self.chains.items()
        }


class ReadTheChain(OnSchedule):
    """Asks for ``chain`` at each tick and notes the error it raises."""

    errors: ClassVar[list[str]] = []

    @override
    def on_schedule(self, now: datetime) -> None:
        try:
            _ = self.chain
        except MultipleChainsError as error:
            self.errors.append(str(error))


class ReadChainRanks(OnSchedule):
    """Notes the IV rank of each chain at each tick."""

    ranks: ClassVar[dict[datetime, dict[str, float]]] = {}

    @classmethod
    @override
    def iv_lookback(cls, params: NoParams) -> timedelta:
        return IV_LOOKBACK

    @override
    def on_schedule(self, now: datetime) -> None:
        self.ranks[now] = {code: chain.iv_rank() for code, chain in self.chains.items()}
