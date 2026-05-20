from datetime import datetime, date
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import DaySchedule, AvailabilityStatus
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.adapter import format_schedule

TZ = ZoneInfo("Asia/Manila")

def _ev(h1, m1, h2, m2, title, all_day=False):
    return CalendarEvent(id="e", title=title, all_day=all_day,
        start_at=datetime(2026,5,21,h1,m1,tzinfo=TZ), end_at=datetime(2026,5,21,h2,m2,tzinfo=TZ))

def test_format_single_day_lists_events_and_free_slots():
    day = DaySchedule(
        date=date(2026,5,21),
        all_day_events=[_ev(0,0,0,0,"Birthday",all_day=True)],
        timed_events=[_ev(9,0,9,30,"Standup")],
        free_slots=[(datetime(2026,5,21,9,30,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))],
        status=AvailabilityStatus.PARTLY_AVAILABLE,
    )
    text = format_schedule([day], timezone=TZ)
    assert "Standup" in text
    assert "09:00" in text and "09:30" in text
    assert "Birthday" in text
    assert "17:00" in text  # free slot end

def test_format_empty_single_day():
    day = DaySchedule(date=date(2026,5,21), all_day_events=[], timed_events=[],
        free_slots=[(datetime(2026,5,21,9,0,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))],
        status=AvailabilityStatus.FULLY_AVAILABLE)
    text = format_schedule([day], timezone=TZ)
    assert "No events" in text or "free" in text.lower()

def test_format_week_is_compact_per_day():
    days = [
        DaySchedule(date=date(2026,5,21), all_day_events=[], timed_events=[_ev(9,0,9,30,"A")],
            free_slots=[(datetime(2026,5,21,9,30,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))],
            status=AvailabilityStatus.PARTLY_AVAILABLE),
        DaySchedule(date=date(2026,5,22), all_day_events=[], timed_events=[],
            free_slots=[(datetime(2026,5,22,9,0,tzinfo=TZ), datetime(2026,5,22,17,0,tzinfo=TZ))],
            status=AvailabilityStatus.FULLY_AVAILABLE),
    ]
    text = format_schedule(days, timezone=TZ)
    # compact mode should not print the per-event title line for the week view
    assert "event(s)" in text
