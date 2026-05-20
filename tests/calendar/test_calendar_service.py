from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.service import CalendarService
from personal_hermes.calendar.availability import AvailabilityStatus
from personal_hermes.openclaw.types import CalendarEvent


class FakeOpenClawClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.access_tokens: list[str] = []
        self.calls: list[tuple[datetime, datetime]] = []
        self.was_called = False

    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        self.was_called = True
        self.calls.append((start_at, end_at))
        return self.events

    def with_access_token(self, access_token: str) -> "FakeOpenClawClient":
        self.access_tokens.append(access_token)
        return self


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


def test_calendar_service_uses_access_token_for_user_context():
    client = FakeOpenClawClient([])

    service = CalendarService(
        openclaw_client=client,
        timezone=ZoneInfo("Asia/Manila"),
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
        resolve_access_token=lambda user_id, now: "token-1" if user_id == 42 else None,
    )

    result = service.availability_for("today", today=date(2026, 5, 19), user_id=42)

    assert client.access_tokens == ["token-1"]
    assert client.was_called is True
    assert result is not None
    assert client.access_tokens == ["token-1"]
    assert client.calls


_SF_TZ = ZoneInfo("Asia/Manila")


class _SFFakeClient:
    def __init__(self, events):
        self._events = events
    def list_calendar_events(self, start_at, end_at):
        return self._events


def test_schedule_for_returns_day_schedules_with_events_and_free_slots():
    event = CalendarEvent(
        id="e", title="Standup", all_day=False,
        start_at=datetime(2026, 5, 21, 9, 0, tzinfo=_SF_TZ),
        end_at=datetime(2026, 5, 21, 9, 30, tzinfo=_SF_TZ),
    )
    service = CalendarService(
        openclaw_client=_SFFakeClient([event]),
        timezone=_SF_TZ, workday_start="09:00", workday_end="17:00",
        min_free_block_minutes=60,
    )
    schedules = service.schedule_for("today", today=date(2026, 5, 21))
    assert len(schedules) == 1
    day = schedules[0]
    assert [e.title for e in day.timed_events] == ["Standup"]
    assert day.free_slots
    assert day.status == AvailabilityStatus.PARTLY_AVAILABLE
