from datetime import datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.event_request import EventDraft, parse_event_request

TZ = ZoneInfo("Asia/Manila")
# A Wednesday at 08:00 local time.
NOW = datetime(2026, 5, 20, 8, 0, tzinfo=TZ)


def test_parses_today_time_range_and_title():
    draft = parse_event_request("appointment today 9AM-9:30AM dentist", now=NOW, tz=TZ)
    assert draft == EventDraft(
        title="dentist",
        start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
        end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ),
    )


def test_defaults_to_60_minutes_when_no_end():
    draft = parse_event_request("schedule meeting tomorrow at 2pm review", now=NOW, tz=TZ)
    assert draft is not None
    assert draft.start_at == datetime(2026, 5, 21, 14, 0, tzinfo=TZ)
    assert draft.end_at == datetime(2026, 5, 21, 15, 0, tzinfo=TZ)
    assert draft.title == "review"


def test_returns_none_for_non_event_text():
    assert parse_event_request("what dates am I free this week?", now=NOW, tz=TZ) is None
    assert parse_event_request("hello there", now=NOW, tz=TZ) is None


def test_returns_none_when_intent_present_but_no_time():
    assert parse_event_request("schedule a dentist appointment", now=NOW, tz=TZ) is None


def test_infers_am_start_when_only_end_has_meridiem():
    draft = parse_event_request("schedule 9-5pm standup", now=NOW, tz=TZ)
    assert draft is not None
    assert draft.start_at == datetime(2026, 5, 20, 9, 0, tzinfo=TZ)
    assert draft.end_at == datetime(2026, 5, 20, 17, 0, tzinfo=TZ)
    assert draft.title == "standup"


def test_returns_none_for_impossible_backwards_range():
    # Both ends lack meridiem and resolve to end <= start; ambiguous -> None.
    assert parse_event_request("schedule 9-5 review", now=NOW, tz=TZ) is None
