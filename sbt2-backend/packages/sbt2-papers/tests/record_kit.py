from datetime import date
from decimal import Decimal

from sbt2.papers.schema import (
    AssetClass,
    Field,
    FieldStatus,
    Frequency,
    Paper,
    PaperRecord,
    Parameter,
    Period,
    ReportedResult,
    TradingStrategy,
)


def stated[T](value: T) -> Field[T]:
    return Field[T](value=value, status=FieldStatus.STATED)


NO_TEXT = Field[str](status=FieldStatus.MISSING)
NO_PERIOD = Field[Period](status=FieldStatus.MISSING)


def make_paper() -> Paper:
    return Paper(
        title="Time series momentum",
        authors=["A. Author", "B. Author"],
        first_published=date(2011, 5, 1),
        arxiv_id="1105.00001",
        doi="10.1000/tsmom",
    )


def make_strategy(name: str = "tsmom") -> TradingStrategy:
    sample = Period(start=date(1985, 1, 1), end=date(2009, 12, 31))
    return TradingStrategy(
        name=name,
        instruments=stated(["ES", "ZN"]),
        asset_class=stated(AssetClass.FUTURES),
        universe_filters=NO_TEXT,
        data_frequency=stated(Frequency.DAILY),
        signal_description=stated("Sign of the past return."),
        signal_formula=stated(r"s_t = \operatorname{sign}(r_{t-12,t})"),
        lookbacks=stated("12 months"),
        portfolio_construction=stated("Equal risk."),
        rebalancing_frequency=stated(Frequency.MONTHLY),
        execution_timing=stated("next open"),
        costs=NO_TEXT,
        in_sample=stated(sample),
        out_of_sample=NO_PERIOD,
        parameters=[
            Parameter(
                name="lookback",
                value=12,
                status=FieldStatus.STATED,
                tried=[1, 3, 6, 12],
                description="Months of past return.",
            ),
            Parameter(name="target volatility", status=FieldStatus.MISSING),
        ],
        results=[
            ReportedResult(
                metric="Sharpe ratio",
                value=Decimal("1.25"),
                status=FieldStatus.STATED,
                period=sample,
                variant="12 months",
                net_of_costs=False,
            ),
            ReportedResult(metric="Annual return", status=FieldStatus.MISSING),
        ],
    )


def make_record() -> PaperRecord:
    return PaperRecord(
        schema_version=1,
        paper=make_paper(),
        strategies=[make_strategy("tsmom"), make_strategy("tsmom long only")],
    )
