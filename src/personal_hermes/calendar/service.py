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
        resolve_access_token=None,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.resolve_access_token = resolve_access_token
        self.timezone = timezone
        self.workday_start = workday_start
        self.workday_end = workday_end
        self.min_free_block_minutes = min_free_block_minutes

    def availability_for(self, text: str, *, today: date, user_id: int | None = None) -> AvailabilityResult:
        return self._availability_for(text, today=today, user_id=user_id)

    def _availability_for(
        self,
        text: str,
        *,
        today: date,
        user_id: int | None = None,
    ) -> AvailabilityResult:
        start_date, end_date = parse_date_range(text, today=today)
        start_at = datetime.combine(start_date, time.min, tzinfo=self.timezone)
        end_at = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=self.timezone
        )
        openclaw_client = self.openclaw_client
        if self.resolve_access_token is not None and user_id is not None:
            try:
                access_token = self.resolve_access_token(user_id, now=datetime.now(tz=UTC))
            except TypeError:
                access_token = self.resolve_access_token(user_id)

            if access_token is None:
                return AvailabilityResult(
                    fully_available=[],
                    partly_available=[],
                    busy=[],
                )

            if hasattr(openclaw_client, "with_access_token"):
                openclaw_client = openclaw_client.with_access_token(access_token)
        events = openclaw_client.list_calendar_events(
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
