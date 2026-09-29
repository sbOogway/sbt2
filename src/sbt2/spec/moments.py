from datetime import UTC, date, datetime, time, timedelta

type Moment = date | datetime | str

_DAY = timedelta(days=1)


def utc(moment: Moment) -> datetime:
    """A TOML date or datetime as an aware UTC datetime; naive values are UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        moment = datetime.combine(moment, time())
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def floor_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def nearest_day(moment: datetime) -> datetime:
    midnight = floor_day(moment)
    return midnight + _DAY if moment - midnight >= _DAY / 2 else midnight
