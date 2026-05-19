from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import (
    AvailabilityStatus,
    classify_day,
    parse_date_range,
)
from personal_hermes.openclaw.types import CalendarEvent


class CalendarClient(Protocol):
    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        ...


@dataclass(frozen=True)
class AvailabilityResult:
    fully_available: list[str]
    partly_available: list[str]
    busy: list[str]


class CalendarService:
    def __init__(
        self,
        *,
        openclaw_client: CalendarClient,
        timezone: ZoneInfo,
        workday_start: str,
        workday_end: str,
        min_free_block_minutes: int,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.timezone = timezone
        self.workday_start = workday_start
        self.workday_end = workday_end
        self.min_free_block_minutes = min_free_block_minutes

    def availability_for(self, text: str, *, today: date) -> AvailabilityResult:
        start_date, end_date = parse_date_range(text, today=today)
        start_at = datetime.combine(start_date, time.min, tzinfo=self.timezone)
        end_at = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=self.timezone
        )
        events = self.openclaw_client.list_calendar_events(
            start_at.astimezone(UTC),
            end_at.astimezone(UTC),
        )

        fully_available: list[str] = []
        partly_available: list[str] = []
        busy: list[str] = []

        current = start_date
        while current <= end_date:
            label = current.strftime("%A")
            status = classify_day(
                target_date=current,
                events=events,
                timezone=self.timezone,
                workday_start=self.workday_start,
                workday_end=self.workday_end,
                min_free_block_minutes=self.min_free_block_minutes,
            )
            if status == AvailabilityStatus.FULLY_AVAILABLE:
                fully_available.append(label)
            elif status == AvailabilityStatus.PARTLY_AVAILABLE:
                partly_available.append(label)
            else:
                busy.append(label)
            current += timedelta(days=1)

        return AvailabilityResult(
            fully_available=fully_available,
            partly_available=partly_available,
            busy=busy,
        )
