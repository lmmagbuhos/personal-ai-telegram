from datetime import datetime
from zoneinfo import ZoneInfo

from personal_hermes.openclaw.client import OpenClawClient

TZ = ZoneInfo("Asia/Manila")


def test_create_calendar_event_builds_gog_args():
    captured = {}

    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"event": {"id": "evt123", "summary": "dentist",
                          "start": {"dateTime": "2026-05-20T09:00:00+08:00", "timeZone": "Asia/Manila"},
                          "end": {"dateTime": "2026-05-20T09:30:00+08:00", "timeZone": "Asia/Manila"},
                          "htmlLink": "https://cal/evt123"}}

    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    event = client.create_calendar_event(
        title="dentist",
        start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
        end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ),
    )

    args = captured["args"]
    assert args[0] == "gog"
    assert "--access-token" in args and "tok" in args
    assert args[args.index("calendar") + 1] == "create"
    assert "primary" in args
    assert "--summary" in args and "dentist" in args
    assert "--from" in args and "2026-05-20T09:00:00+08:00" in args
    assert "--to" in args and "2026-05-20T09:30:00+08:00" in args
    assert "--start-timezone" in args and "Asia/Manila" in args
    assert "--no-input" in args and "--json" in args
    assert event.id == "evt123"
