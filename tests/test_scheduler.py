from datetime import UTC, date, datetime, timedelta

from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.scheduler import AssistantScheduler
from personal_hermes.users import User
from personal_hermes.telegram.types import TelegramMessage


class FakeMailPollingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, datetime]] = []

    def poll(self, *, since_cursor: str | None, now: datetime):
        self.calls.append((since_cursor, now))


class FakeOpenClawClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self.events = events
        self.calls: list[tuple[datetime, datetime]] = []

    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        self.calls.append((start_at, end_at))
        return self.events


class FakeCalendarNotificationService:
    def __init__(self) -> None:
        self.agenda_calls: list[tuple[date, list[CalendarEvent], datetime]] = []
        self.reminder_calls: list[tuple[list[CalendarEvent], datetime, int]] = []
        self.agenda_result: list[CalendarEvent] = []
        self.reminder_result: list[CalendarEvent] = []

    def events_for_daily_agenda(self, agenda_date, events, *, now):
        self.agenda_calls.append((agenda_date, events, now))
        return self.agenda_result

    def events_due_for_reminder(self, events, *, now, lead_minutes):
        self.reminder_calls.append((events, now, lead_minutes))
        return self.reminder_result


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.events: list[TelegramMessage] = []

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        self.sent.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        return 1

    def poll_updates(self, *, timeout_seconds: int):
        return self.events


class FakeRouter:
    def __init__(self) -> None:
        self.events: list[tuple[TelegramMessage, datetime]] = []

    def handle_event(self, event, *, now: datetime) -> None:
        self.events.append((event, now))


class FakeMultiuserStore:
    def __init__(self, users: list[User]) -> None:
        self._users = users

    def list_active_google_users(self) -> list[User]:
        return self._users


def make_event(event_id: str, start_at: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=event_id,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        all_day=False,
        location="Meet",
    )


def make_scheduler(now: datetime, events: list[CalendarEvent] | None = None):
    openclaw = FakeOpenClawClient(events or [])
    mail = FakeMailPollingService()
    calendar_notifications = FakeCalendarNotificationService()
    telegram = FakeTelegram()
    router = FakeRouter()
    scheduler = AssistantScheduler(
        mail_polling_service=mail,
        openclaw_client=openclaw,
        calendar_notifications=calendar_notifications,
        telegram=telegram,
        router=router,
        authorized_chat_id=123,
        reminder_lead_minutes=30,
        telegram_poll_timeout_seconds=2,
        now_provider=lambda: now,
    )
    return scheduler, mail, openclaw, calendar_notifications, telegram, router


def test_run_gmail_poll_job_calls_mail_polling_service():
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    scheduler, mail, *_ = make_scheduler(now)

    scheduler.run_gmail_poll_job(since_cursor="after:2026/05/18")

    assert mail.calls == [("after:2026/05/18", now)]


def test_run_daily_agenda_job_fetches_day_events_and_sends_agenda():
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    event = make_event("Planning", now + timedelta(hours=1))
    scheduler, _mail, openclaw, calendar_notifications, telegram, _router = make_scheduler(
        now,
        events=[event],
    )
    calendar_notifications.agenda_result = [event]

    scheduler.run_daily_agenda_job()

    assert openclaw.calls == [
        (datetime(2026, 5, 19, 0, 0, tzinfo=UTC), datetime(2026, 5, 20, 0, 0, tzinfo=UTC))
    ]
    assert calendar_notifications.agenda_calls == [(date(2026, 5, 19), [event], now)]
    assert "Today's agenda" in telegram.sent[0]["text"]
    assert "Planning" in telegram.sent[0]["text"]


def test_run_calendar_reminder_job_fetches_window_and_sends_reminders():
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    event = make_event("Planning", now + timedelta(minutes=30))
    scheduler, _mail, openclaw, calendar_notifications, telegram, _router = make_scheduler(
        now,
        events=[event],
    )
    calendar_notifications.reminder_result = [event]

    scheduler.run_calendar_reminder_job()

    assert openclaw.calls == [(now, now + timedelta(minutes=30))]
    assert calendar_notifications.reminder_calls == [([event], now, 30)]
    assert "Reminder" in telegram.sent[0]["text"]
    assert "Planning" in telegram.sent[0]["text"]


def test_run_telegram_poll_job_dispatches_events_to_router():
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    scheduler, _mail, _openclaw, _calendar_notifications, telegram, router = make_scheduler(now)
    event = TelegramMessage(chat_id=123, user_id=456, message_id=1, text="hello")
    telegram.events = [event]

    scheduler.run_telegram_poll_job()

    assert router.events == [(event, now)]


class FakeMailPollerForMultiuser:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, datetime, int, int]] = []

    def poll(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        since_cursor: str | None,
        now: datetime,
    ) -> None:
        self.calls.append((since_cursor, now, user_id, chat_id))


def test_run_gmail_poll_job_runs_each_active_user_when_multiuser_enabled():
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    openclaw = FakeOpenClawClient([])
    notifier = FakeTelegram()
    calendar_notifications = FakeCalendarNotificationService()
    mail = FakeMailPollerForMultiuser()
    router = FakeRouter()
    users = [
        User(
            id=1,
            telegram_user_id=111,
            telegram_chat_id=1111,
            display_name="A",
            username="a",
            status="active",
            created_at=now,
            updated_at=now,
        ),
        User(
            id=2,
            telegram_user_id=222,
            telegram_chat_id=2222,
            display_name="B",
            username="b",
            status="active",
            created_at=now,
            updated_at=now,
        ),
    ]
    store = FakeMultiuserStore(users)

    scheduler = AssistantScheduler(
        mail_polling_service=mail,
        openclaw_client=openclaw,
        calendar_notifications=calendar_notifications,
        telegram=notifier,
        router=router,
        authorized_chat_id=999,
        reminder_lead_minutes=30,
        telegram_poll_timeout_seconds=2,
        store=store,
        multiuser_enabled=True,
        now_provider=lambda: now,
    )

    scheduler.run_gmail_poll_job(since_cursor=None)

    assert mail.calls == [
        (None, now, 1, 1111),
        (None, now, 2, 2222),
    ]
