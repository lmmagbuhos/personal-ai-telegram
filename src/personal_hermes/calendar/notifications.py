from datetime import date, datetime, timedelta

from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.storage.store import StateStore


class CalendarNotificationService:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def events_for_daily_agenda(
        self,
        agenda_date: date,
        events: list[CalendarEvent],
        *,
        now: datetime,
    ) -> list[CalendarEvent]:
        if not self.store.mark_agenda_sent(agenda_date, sent_at=now):
            return []
        return events

    def events_due_for_reminder(
        self,
        events: list[CalendarEvent],
        *,
        now: datetime,
        lead_minutes: int,
    ) -> list[CalendarEvent]:
        due: list[CalendarEvent] = []
        window_end = now + timedelta(minutes=lead_minutes)
        for event in events:
            if event.all_day:
                continue
            if not now <= event.start_at <= window_end:
                continue
            if self.store.mark_calendar_reminder_sent(
                event_id=event.id,
                event_start_at=event.start_at,
                sent_at=now,
            ):
                due.append(event)
        return due
