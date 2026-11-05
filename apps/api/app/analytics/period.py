from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

DEFAULT_DAYS = 7
MAX_DAYS = 366


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    first: date
    last: date

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1

    @property
    def start(self) -> datetime:
        return local_midnight(self.first)

    @property
    def end(self) -> datetime:
        return local_midnight(self.last + timedelta(days=1))

    def previous(self) -> "Period":
        last = self.first - timedelta(days=1)
        return Period(last - timedelta(days=self.days - 1), last)

    def dates(self) -> list[date]:
        return [self.first + timedelta(days=i) for i in range(self.days)]


def timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().analytics_timezone)


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone())


def today() -> date:
    return datetime.now(UTC).astimezone(timezone()).date()


def resolve_period(first: date | None, last: date | None) -> Period:
    last = last or today()
    first = first or last - timedelta(days=DEFAULT_DAYS - 1)
    if first > last:
        raise PeriodError("period_invalid")
    if (last - first).days + 1 > MAX_DAYS:
        raise PeriodError("period_too_long")
    return Period(first, last)
