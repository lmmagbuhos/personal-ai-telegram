from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.service import CalendarService
from personal_hermes.openclaw.types import CalendarEvent


class FakeOpenClawClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.calls: list[tuple[datetime, datetime]] = []

    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        self.calls.append((start_at, end_at))
        return self.events


def test_calendar_service_returns_grouped_availability_for_this_week():
    client = FakeOpenClawClient(
        [
            CalendarEvent(
                id="event-1",
                title="Meeting",
                start_at=datetime.fromisoformat("2026-05-19T10:00:00+08:00"),
                end_at=datetime.fromisoformat("2026-05-19T10:30:00+08:00"),
                all_day=False,
            ),
            CalendarEvent(
                id="event-2",
                title="Busy day",
                start_at=datetime.fromisoformat("2026-05-20T09:00:00+08:00"),
                end_at=datetime.fromisoformat("2026-05-20T17:00:00+08:00"),
                all_day=False,
            ),
        ]
    )
    service = CalendarService(
        openclaw_client=client,
        timezone=ZoneInfo("Asia/Manila"),
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    result = service.availability_for("this week", today=date(2026, 5, 19))

    assert "Monday" in result.fully_available
    assert "Tuesday" in result.partly_available
    assert "Wednesday" in result.busy
    assert client.calls == [
        (
            datetime(2026, 5, 17, 16, 0, tzinfo=UTC),
            datetime(2026, 5, 24, 16, 0, tzinfo=UTC),
        )
    ]
