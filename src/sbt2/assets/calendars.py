from datetime import UTC, date, datetime, timedelta

_RESOLUTION = timedelta(microseconds=1)


class AlwaysOpen:
    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        start, end = _utc(start), _utc(end)
        if end <= start:
            return []
        first = start.date()
        last = (end - _RESOLUTION).date()
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError(f"naive datetime {moment} has no time zone")
    return moment.astimezone(UTC)
