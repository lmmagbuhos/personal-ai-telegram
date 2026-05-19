from datetime import UTC, date, datetime, timedelta

from personal_hermes.calendar.notifications import CalendarNotificationService
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.storage.store import StateStore


def make_event(event_id: str, start_at: datetime, end_at: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=event_id,
        start_at=start_at,
        end_at=end_at,
        all_day=False,
    )


def test_daily_agenda_is_returned_once_per_day(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = CalendarNotificationService(store)
    today = date(2026, 5, 19)
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    events = [make_event("planning", now + timedelta(hours=1), now + timedelta(hours=2))]

    assert service.events_for_daily_agenda(today, events, now=now) == events
    assert service.events_for_daily_agenda(today, events, now=now) == []


def test_daily_agenda_can_send_empty_agenda_once(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = CalendarNotificationService(store)
    today = date(2026, 5, 19)
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    assert service.events_for_daily_agenda(today, [], now=now) == []
    assert store.mark_agenda_sent(today, sent_at=now) is False


def test_upcoming_reminders_are_returned_once_per_event_start(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = CalendarNotificationService(store)
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    due = make_event("due", now + timedelta(minutes=30), now + timedelta(hours=1))
    too_late = make_event("late", now + timedelta(minutes=31), now + timedelta(hours=2))
    already_started = make_event("started", now - timedelta(minutes=1), now + timedelta(minutes=30))

    assert service.events_due_for_reminder(
        [due, too_late, already_started],
        now=now,
        lead_minutes=30,
    ) == [due]
    assert service.events_due_for_reminder(
        [due, too_late, already_started],
        now=now,
        lead_minutes=30,
    ) == []


def test_changed_event_start_time_can_remind_again(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = CalendarNotificationService(store)
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    first = make_event("event-1", now + timedelta(minutes=30), now + timedelta(hours=1))
    moved = make_event("event-1", now + timedelta(minutes=25), now + timedelta(hours=1))

    assert service.events_due_for_reminder([first], now=now, lead_minutes=30) == [first]
    assert service.events_due_for_reminder([moved], now=now, lead_minutes=30) == [moved]

