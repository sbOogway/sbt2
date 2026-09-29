from datetime import UTC, date, datetime, time

type Moment = date | datetime | str


def utc(moment: Moment) -> datetime:
    """A TOML date or datetime as an aware UTC datetime; naive values are UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        moment = datetime.combine(moment, time())
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
