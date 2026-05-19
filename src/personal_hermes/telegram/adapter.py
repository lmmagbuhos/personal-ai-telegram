from collections.abc import Sequence
from dataclasses import dataclass

from personal_hermes.openclaw.types import CalendarEvent, EmailMessage
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage

ButtonGrid = list[list[tuple[str, str]]]


@dataclass(frozen=True)
class TelegramAdapter:
    bot_token: str
    authorized_chat_id: int
    authorized_user_id: int

    def is_authorized(self, event: TelegramMessage | TelegramCallback) -> bool:
        return (
            event.chat_id == self.authorized_chat_id
            and event.user_id == self.authorized_user_id
        )


def format_email_notification(
    message: EmailMessage,
    *,
    summary: str,
    suggested_reply: str | None,
) -> str:
    parts = [
        "New email",
        f"From: {message.sender}",
        f"Subject: {message.subject}",
        f"Summary: {summary}",
    ]
    if suggested_reply:
        parts.append(f"Suggested reply: {suggested_reply}")
    return "\n".join(parts)


def email_action_buttons(*, pending_reply_id: int, email_id: str) -> ButtonGrid:
    return [
        [
            ("Send reply", f"send_reply:{pending_reply_id}"),
            ("Edit reply", f"edit_reply:{pending_reply_id}"),
        ],
        [
            ("Ignore", f"ignore_reply:{pending_reply_id}"),
            ("Mark read", f"mark_read:{email_id}"),
        ],
    ]


def format_daily_agenda(events: Sequence[CalendarEvent]) -> str:
    if not events:
        return "Today's agenda\nNo events scheduled."

    lines = ["Today's agenda"]
    for event in events:
        time_range = _format_event_time_range(event)
        details = f"- {time_range} {event.title}"
        if event.location:
            details = f"{details} ({event.location})"
        if event.html_link:
            details = f"{details}\n  {event.html_link}"
        lines.append(details)
    return "\n".join(lines)


def format_event_reminder(event: CalendarEvent, *, lead_minutes: int) -> str:
    lines = [
        f"Reminder: {event.title} starts in {lead_minutes} minutes",
        f"Time: {event.start_at.strftime('%H:%M')}",
    ]
    if event.location:
        lines.append(f"Location: {event.location}")
    if event.html_link:
        lines.append(event.html_link)
    return "\n".join(lines)


def format_availability_answer(
    *,
    fully_available: Sequence[str],
    partly_available: Sequence[str],
    busy: Sequence[str],
) -> str:
    return "\n".join(
        [
            f"Fully available: {_format_list(fully_available)}",
            f"Partly available: {_format_list(partly_available)}",
            f"Busy: {_format_list(busy)}",
        ]
    )


def _format_event_time_range(event: CalendarEvent) -> str:
    if event.all_day:
        return "All day"
    return f"{event.start_at.strftime('%H:%M')}-{event.end_at.strftime('%H:%M')}"


def _format_list(values: Sequence[str]) -> str:
    if not values:
        return "None"
    return ", ".join(values)
