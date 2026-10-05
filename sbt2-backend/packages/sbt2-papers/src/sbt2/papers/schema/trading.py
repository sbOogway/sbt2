from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field as PydanticField
from pydantic import model_validator

from sbt2.papers.schema.core import Field, FieldStatus, Period, Record, check_status

type ParameterValue = Decimal | int | bool | str


class AssetClass(StrEnum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    FUTURES = "futures"
    COMMODITY = "commodity"
    BOND = "bond"
    MULTI = "multi"


class Frequency(StrEnum):
    TICK = "tick"
    MINUTE = "minute"
    HOUR = "hour"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Parameter(Record):
    """A parameter of the strategy."""

    name: str = PydanticField(description="The name of the parameter.")
    value: ParameterValue | None = PydanticField(
        default=None, description="The value the paper uses. Null when missing."
    )
    status: FieldStatus = PydanticField(
        description="stated, inferred or missing, as for a field."
    )
    tried: list[ParameterValue] = PydanticField(
        default_factory=list,
        description="The values or grid the authors searched. Each one counts as a trial.",
    )
    description: str | None = PydanticField(
        default=None, description="What the parameter does."
    )

    @model_validator(mode="after")
    def _value_follows_status(self) -> Self:
        check_status(self.value, self.status)
        return self


class ReportedResult(Record):
    """A performance figure the paper reports."""

    metric: str = PydanticField(
        description="The name of the metric, for example Sharpe ratio."
    )
    value: Decimal | None = PydanticField(
        default=None, description="The reported number. Null when missing."
    )
    status: FieldStatus = PydanticField(
        description="stated, inferred or missing, as for a field."
    )
    period: Period | None = PydanticField(
        default=None, description="The period the figure covers."
    )
    variant: str | None = PydanticField(
        default=None, description="The variant or parameter set the figure is for."
    )
    net_of_costs: bool | None = PydanticField(
        default=None, description="True when the figure is after costs."
    )

    @model_validator(mode="after")
    def _value_follows_status(self) -> Self:
        check_status(self.value, self.status)
        return self


class TradingStrategy(Record):
    """One tradable rule of the paper."""

    name: str = PydanticField(description="A short name that tells the rule apart.")
    instruments: Field[list[str]] = PydanticField(
        description="The instruments or tickers traded."
    )
    asset_class: Field[AssetClass] = PydanticField(description="The asset class.")
    universe_filters: Field[str] = PydanticField(
        description="The rules that select the universe."
    )
    data_frequency: Field[Frequency] = PydanticField(
        description="The frequency of the data the signal uses."
    )
    signal_description: Field[str] = PydanticField(description="The signal, in words.")
    signal_formula: Field[str] = PydanticField(
        description="The signal, as a LaTeX formula."
    )
    lookbacks: Field[str] = PydanticField(description="The lookback windows.")
    portfolio_construction: Field[str] = PydanticField(
        description="How signals become positions."
    )
    rebalancing_frequency: Field[Frequency] = PydanticField(
        description="How often the portfolio changes."
    )
    execution_timing: Field[str] = PydanticField(
        description="When orders fill, for example next open."
    )
    costs: Field[str] = PydanticField(description="The costs the paper assumed.")
    in_sample: Field[Period] = PydanticField(description="The in-sample period.")
    out_of_sample: Field[Period] = PydanticField(
        description="The out-of-sample period."
    )
    parameters: list[Parameter] = PydanticField(
        default_factory=list, description="The parameters of the strategy."
    )
    results: list[ReportedResult] = PydanticField(
        default_factory=list, description="The results the paper reports."
    )
