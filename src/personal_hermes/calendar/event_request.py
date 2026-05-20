from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_TRIGGERS = ("appointment", "schedule", "meeting", "book", "add event", "create event")
_DEFAULT_DURATION = timedelta(minutes=60)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
# Matches "9AM", "9:30am", "14:00", "2pm".
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
_RANGE_RE = re.compile(rf"{_TIME}\s*(?:-|to|until)\s*{_TIME}", re.IGNORECASE)
_SINGLE_RE = re.compile(rf"(?:at\s+)?{_TIME}", re.IGNORECASE)


@dataclass(frozen=True)
class EventDraft:
    title: str
    start_at: datetime
    end_at: datetime


def parse_event_request(text: str, *, now: datetime, tz: ZoneInfo) -> EventDraft | None:
    lowered = text.lower()
    if not any(trigger in lowered for trigger in _TRIGGERS):
        return None

    target_date = _resolve_date(lowered, now=now)
    times, leftover = _extract_times(text, target_date, tz)
    if times is None:
        return None
    start_at, end_at = times

    title = _extract_title(leftover)
    if not title:
        return None
    return EventDraft(title=title, start_at=start_at, end_at=end_at)


def _resolve_date(lowered: str, *, now: datetime):
    today = now.date()
    if "tomorrow" in lowered:
        return today + timedelta(days=1)
    for name, weekday in _WEEKDAYS.items():
        if name in lowered:
            ahead = (weekday - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
    return today  # default / explicit "today"


def _to_dt(hour, minute, meridiem, date, tz) -> datetime:
    hour = int(hour)
    minute = int(minute) if minute else 0
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    return datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz)


def _extract_times(text, date, tz):
    match = _RANGE_RE.search(text)
    if match:
        h1, m1, ap1, h2, m2, ap2 = match.groups()
        ap1 = ap1 or ap2  # "9-9:30am" -> apply pm/am to both if one is missing
        ap2 = ap2 or ap1
        start = _to_dt(h1, m1, ap1, date, tz)
        end = _to_dt(h2, m2, ap2, date, tz)
        leftover = (text[: match.start()] + " " + text[match.end():])
        return (start, end), leftover

    match = _SINGLE_RE.search(text)
    if match:
        h, m, ap = match.groups()
        start = _to_dt(h, m, ap, date, tz)
        leftover = (text[: match.start()] + " " + text[match.end():])
        return (start, start + _DEFAULT_DURATION), leftover

    return None, text


def _extract_title(leftover: str) -> str:
    words = []
    skip = {
        "appointment", "schedule", "meeting", "book", "add", "create", "event",
        "today", "tomorrow", "at", "from", "to", "until", "a", "an", "the",
        "for", "minutes", "minute", "min", "mins", "hour", "hours",
        *(_WEEKDAYS.keys()),
    }
    for word in leftover.split():
        cleaned = word.strip(",.-").lower()
        if cleaned and cleaned not in skip and not any(c.isdigit() for c in cleaned):
            words.append(word.strip(",.-"))
    return " ".join(words).strip()
