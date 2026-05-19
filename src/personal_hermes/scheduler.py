from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Protocol

from personal_hermes.calendar.notifications import CalendarNotificationService
from personal_hermes.mail.service import MailPollingService
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.adapter import format_daily_agenda, format_event_reminder
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class CalendarEventClient(Protocol):
    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        ...


class SchedulerTelegramAdapter(Protocol):
    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        ...

    def poll_updates(self, *, timeout_seconds: int) -> list[TelegramMessage | TelegramCallback]:
        ...


class SchedulerRouter(Protocol):
    def handle_event(
        self,
        event: TelegramMessage | TelegramCallback,
        *,
        now: datetime,
    ) -> None:
        ...


class AssistantScheduler:
    def __init__(
        self,
        *,
        mail_polling_service: MailPollingService,
        openclaw_client: CalendarEventClient,
        calendar_notifications: CalendarNotificationService,
        telegram: SchedulerTelegramAdapter,
        router: SchedulerRouter,
        authorized_chat_id: int,
        reminder_lead_minutes: int,
        telegram_poll_timeout_seconds: int,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.mail_polling_service = mail_polling_service
        self.openclaw_client = openclaw_client
        self.calendar_notifications = calendar_notifications
        self.telegram = telegram
        self.router = router
        self.authorized_chat_id = authorized_chat_id
        self.reminder_lead_minutes = reminder_lead_minutes
        self.telegram_poll_timeout_seconds = telegram_poll_timeout_seconds
        self.now_provider = now_provider or (lambda: datetime.now(tz=UTC))

    def run_gmail_poll_job(self, *, since_cursor: str | None = None) -> None:
        self.mail_polling_service.poll(since_cursor=since_cursor, now=self.now_provider())

    def run_daily_agenda_job(self) -> None:
        now = self.now_provider()
        day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo or UTC)
        day_end = day_start + timedelta(days=1)
        events = self.openclaw_client.list_calendar_events(day_start, day_end)
        agenda_events = self.calendar_notifications.events_for_daily_agenda(
            now.date(),
            events,
            now=now,
        )
        self.telegram.send_message(
            chat_id=self.authorized_chat_id,
            text=format_daily_agenda(agenda_events),
        )

    def run_calendar_reminder_job(self) -> None:
        now = self.now_provider()
        window_end = now + timedelta(minutes=self.reminder_lead_minutes)
        events = self.openclaw_client.list_calendar_events(now, window_end)
        due_events = self.calendar_notifications.events_due_for_reminder(
            events,
            now=now,
            lead_minutes=self.reminder_lead_minutes,
        )
        for event in due_events:
            self.telegram.send_message(
                chat_id=self.authorized_chat_id,
                text=format_event_reminder(
                    event,
                    lead_minutes=self.reminder_lead_minutes,
                ),
            )

    def run_telegram_poll_job(self) -> None:
        now = self.now_provider()
        for event in self.telegram.poll_updates(
            timeout_seconds=self.telegram_poll_timeout_seconds
        ):
            self.router.handle_event(event, now=now)
