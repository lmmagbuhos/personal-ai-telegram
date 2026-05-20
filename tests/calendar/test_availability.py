from datetime import date, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import (
    AvailabilityStatus,
    DaySchedule,
    classify_day,
    day_schedule,
    free_slots,
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


# free_slots tests
FS_TZ = ZoneInfo("Asia/Manila")


def fs_ev(h1, m1, h2, m2, *, all_day=False, title="x"):
    return CalendarEvent(
        id="e", title=title,
        start_at=datetime(2026, 5, 21, h1, m1, tzinfo=FS_TZ),
        end_at=datetime(2026, 5, 21, h2, m2, tzinfo=FS_TZ),
        all_day=all_day,
    )


def fs_slots(events):
    return free_slots(
        target_date=datetime(2026, 5, 21, tzinfo=FS_TZ).date(),
        events=events, timezone=FS_TZ,
        workday_start="09:00", workday_end="17:00", min_free_block_minutes=60,
    )


def test_free_slots_empty_day_is_whole_workday():
    assert fs_slots([]) == [(datetime(2026, 5, 21, 9, 0, tzinfo=FS_TZ), datetime(2026, 5, 21, 17, 0, tzinfo=FS_TZ))]


def test_free_slots_gaps_around_events():
    slots = fs_slots([fs_ev(9, 0, 9, 30), fs_ev(14, 0, 15, 0)])
    assert slots == [
        (datetime(2026, 5, 21, 9, 30, tzinfo=FS_TZ), datetime(2026, 5, 21, 14, 0, tzinfo=FS_TZ)),
        (datetime(2026, 5, 21, 15, 0, tzinfo=FS_TZ), datetime(2026, 5, 21, 17, 0, tzinfo=FS_TZ)),
    ]


def test_free_slots_ignores_all_day_events():
    assert fs_slots([fs_ev(0, 0, 23, 59, all_day=True), fs_ev(9, 0, 10, 0)]) == [
        (datetime(2026, 5, 21, 10, 0, tzinfo=FS_TZ), datetime(2026, 5, 21, 17, 0, tzinfo=FS_TZ)),
    ]


def test_free_slots_drops_gaps_below_min_block():
    assert fs_slots([fs_ev(9, 30, 10, 0), fs_ev(10, 0, 17, 0)]) == []


# day_schedule tests
def _ds_schedule(events):
    return day_schedule(
        target_date=datetime(2026, 5, 21, tzinfo=FS_TZ).date(),
        events=events, timezone=FS_TZ,
        workday_start="09:00", workday_end="17:00", min_free_block_minutes=60,
    )


def test_day_schedule_splits_all_day_and_timed_and_sorts():
    s = _ds_schedule([
        fs_ev(14, 0, 15, 0, title="late"),
        fs_ev(9, 0, 9, 30, title="early"),
        fs_ev(0, 0, 23, 59, all_day=True, title="bday"),
    ])
    assert [e.title for e in s.all_day_events] == ["bday"]
    assert [e.title for e in s.timed_events] == ["early", "late"]
    assert s.status == AvailabilityStatus.PARTLY_AVAILABLE
    assert s.free_slots


def test_day_schedule_no_timed_events_is_fully_available():
    s = _ds_schedule([fs_ev(0, 0, 23, 59, all_day=True, title="bday")])
    assert s.status == AvailabilityStatus.FULLY_AVAILABLE
    assert s.timed_events == []


def test_day_schedule_no_free_slots_is_busy():
    s = _ds_schedule([fs_ev(9, 0, 17, 0)])
    assert s.status == AvailabilityStatus.BUSY
    assert s.free_slots == []

