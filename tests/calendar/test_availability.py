from datetime import date, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import (
    AvailabilityStatus,
    classify_day,
    parse_date_range,
)
from personal_hermes.openclaw.types import CalendarEvent


MANILA = ZoneInfo("Asia/Manila")


def event(
    event_id: str,
    start: str,
    end: str,
    *,
    all_day: bool = False,
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=event_id,
        start_at=datetime.fromisoformat(start),
        end_at=datetime.fromisoformat(end),
        all_day=all_day,
    )


def test_day_with_no_events_is_fully_available():
    result = classify_day(
        target_date=date(2026, 5, 19),
        events=[],
        timezone=MANILA,
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    assert result == AvailabilityStatus.FULLY_AVAILABLE


def test_day_with_one_short_event_and_two_hour_gap_is_partly_available():
    result = classify_day(
        target_date=date(2026, 5, 19),
        events=[
            event("standup", "2026-05-19T10:00:00+08:00", "2026-05-19T10:30:00+08:00")
        ],
        timezone=MANILA,
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    assert result == AvailabilityStatus.PARTLY_AVAILABLE


def test_day_without_two_hour_gap_is_busy():
    result = classify_day(
        target_date=date(2026, 5, 19),
        events=[
            event("one", "2026-05-19T09:00:00+08:00", "2026-05-19T10:30:00+08:00"),
            event("two", "2026-05-19T11:30:00+08:00", "2026-05-19T13:30:00+08:00"),
            event("three", "2026-05-19T15:00:00+08:00", "2026-05-19T17:00:00+08:00"),
        ],
        timezone=MANILA,
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    assert result == AvailabilityStatus.BUSY


def test_events_outside_working_hours_do_not_block_availability():
    result = classify_day(
        target_date=date(2026, 5, 19),
        events=[
            event("early", "2026-05-19T07:00:00+08:00", "2026-05-19T08:00:00+08:00"),
            event("late", "2026-05-19T18:00:00+08:00", "2026-05-19T19:00:00+08:00"),
        ],
        timezone=MANILA,
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    assert result == AvailabilityStatus.FULLY_AVAILABLE


def test_all_day_event_makes_day_busy():
    result = classify_day(
        target_date=date(2026, 5, 19),
        events=[
            event("holiday", "2026-05-19T00:00:00+08:00", "2026-05-20T00:00:00+08:00", all_day=True)
        ],
        timezone=MANILA,
        workday_start="09:00",
        workday_end="17:00",
        min_free_block_minutes=120,
    )

    assert result == AvailabilityStatus.BUSY


def test_parse_date_range_supports_today_tomorrow_weekday_and_this_week():
    today = date(2026, 5, 19)  # Tuesday

    assert parse_date_range("today", today=today) == (today, today)
    assert parse_date_range("tomorrow", today=today) == (
        date(2026, 5, 20),
        date(2026, 5, 20),
    )
    assert parse_date_range("friday", today=today) == (
        date(2026, 5, 22),
        date(2026, 5, 22),
    )
    assert parse_date_range("this week", today=today) == (
        date(2026, 5, 18),
        date(2026, 5, 24),
    )

