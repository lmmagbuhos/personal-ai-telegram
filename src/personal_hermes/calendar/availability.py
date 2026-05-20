from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from personal_hermes.openclaw.types import CalendarEvent


class AvailabilityStatus(StrEnum):
    FULLY_AVAILABLE = "fully_available"
    PARTLY_AVAILABLE = "partly_available"
    BUSY = "busy"


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_date_range(text: str, *, today: date) -> tuple[date, date]:
    normalized = text.strip().lower()
    if "this week" in normalized:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if "tomorrow" in normalized:
        target = today + timedelta(days=1)
        return target, target
    if "today" in normalized:
        return today, today

    for name, weekday in WEEKDAYS.items():
        if name in normalized:
            delta = (weekday - today.weekday()) % 7
            target = today + timedelta(days=delta)
            return target, target

    return today, today


def classify_day(
    *,
    target_date: date,
    events: list[CalendarEvent],
    timezone: ZoneInfo,
    workday_start: str,
    workday_end: str,
    min_free_block_minutes: int,
) -> AvailabilityStatus:
    relevant_events = [
        event for event in events if _event_intersects_date(event, target_date, timezone)
    ]
    if not relevant_events:
        return AvailabilityStatus.FULLY_AVAILABLE
    if any(event.all_day for event in relevant_events):
        return AvailabilityStatus.BUSY

    work_start = datetime.combine(
        target_date, time.fromisoformat(workday_start), tzinfo=timezone
    )
    work_end = datetime.combine(
        target_date, time.fromisoformat(workday_end), tzinfo=timezone
    )
    busy_ranges = _busy_ranges(relevant_events, work_start, work_end, timezone)
    if not busy_ranges:
        return AvailabilityStatus.FULLY_AVAILABLE

    free_threshold = timedelta(minutes=min_free_block_minutes)
    cursor = work_start
    for start_at, end_at in busy_ranges:
        if start_at - cursor >= free_threshold:
            return AvailabilityStatus.PARTLY_AVAILABLE
        if end_at > cursor:
            cursor = end_at

    if work_end - cursor >= free_threshold:
        return AvailabilityStatus.PARTLY_AVAILABLE
    return AvailabilityStatus.BUSY


def _event_intersects_date(
    event: CalendarEvent, target_date: date, timezone: ZoneInfo
) -> bool:
    local_start = event.start_at.astimezone(timezone)
    local_end = event.end_at.astimezone(timezone)
    start_of_day = datetime.combine(target_date, time.min, tzinfo=timezone)
    end_of_day = start_of_day + timedelta(days=1)
    return local_start < end_of_day and local_end > start_of_day


def _busy_ranges(
    events: list[CalendarEvent],
    work_start: datetime,
    work_end: datetime,
    timezone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    for event in events:
        start_at = max(event.start_at.astimezone(timezone), work_start)
        end_at = min(event.end_at.astimezone(timezone), work_end)
        if start_at < end_at:
            ranges.append((start_at, end_at))

    ranges.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for start_at, end_at in ranges:
        if not merged or start_at > merged[-1][1]:
            merged.append((start_at, end_at))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end_at))
    return merged


def free_slots(
    *,
    target_date: date,
    events: list[CalendarEvent],
    timezone: ZoneInfo,
    workday_start: str,
    workday_end: str,
    min_free_block_minutes: int,
) -> list[tuple[datetime, datetime]]:
    timed = [
        event
        for event in events
        if not event.all_day and _event_intersects_date(event, target_date, timezone)
    ]
    work_start = datetime.combine(
        target_date, time.fromisoformat(workday_start), tzinfo=timezone
    )
    work_end = datetime.combine(
        target_date, time.fromisoformat(workday_end), tzinfo=timezone
    )
    busy = _busy_ranges(timed, work_start, work_end, timezone)
    threshold = timedelta(minutes=min_free_block_minutes)

    slots: list[tuple[datetime, datetime]] = []
    cursor = work_start
    for start_at, end_at in busy:
        if start_at - cursor >= threshold:
            slots.append((cursor, start_at))
        if end_at > cursor:
            cursor = end_at
    if work_end - cursor >= threshold:
        slots.append((cursor, work_end))
    return slots


@dataclass(frozen=True)
class DaySchedule:
    date: date
    all_day_events: list[CalendarEvent]
    timed_events: list[CalendarEvent]
    free_slots: list[tuple[datetime, datetime]]
    status: AvailabilityStatus


def day_schedule(
    *,
    target_date: date,
    events: list[CalendarEvent],
    timezone: ZoneInfo,
    workday_start: str,
    workday_end: str,
    min_free_block_minutes: int,
) -> DaySchedule:
    relevant = [
        event for event in events if _event_intersects_date(event, target_date, timezone)
    ]
    all_day_events = [event for event in relevant if event.all_day]
    timed_events = sorted(
        (event for event in relevant if not event.all_day),
        key=lambda event: event.start_at,
    )
    slots = free_slots(
        target_date=target_date,
        events=timed_events,
        timezone=timezone,
        workday_start=workday_start,
        workday_end=workday_end,
        min_free_block_minutes=min_free_block_minutes,
    )
    if not timed_events:
        status = AvailabilityStatus.FULLY_AVAILABLE
    elif slots:
        status = AvailabilityStatus.PARTLY_AVAILABLE
    else:
        status = AvailabilityStatus.BUSY
    return DaySchedule(
        date=target_date,
        all_day_events=all_day_events,
        timed_events=timed_events,
        free_slots=slots,
        status=status,
    )
