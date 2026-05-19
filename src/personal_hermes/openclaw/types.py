from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    sent_at: datetime
    snippet: str
    body_text: str
    is_unread: bool
    message_id: str | None = None
    references: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    timezone: str | None = None
    location: str | None = None
    description: str | None = None
    html_link: str | None = None
    attendees: tuple[tuple[str | None, str | None, str | None], ...] = field(
        default_factory=tuple
    )


@dataclass(frozen=True)
class SendEmailReplyRequest:
    thread_id: str
    to: tuple[str, ...]
    subject: str
    body_text: str
    in_reply_to: str
    references: tuple[str, ...] = field(default_factory=tuple)
    cc: tuple[str, ...] = field(default_factory=tuple)
    bcc: tuple[str, ...] = field(default_factory=tuple)
