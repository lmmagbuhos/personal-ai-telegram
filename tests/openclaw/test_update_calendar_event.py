from datetime import datetime
from zoneinfo import ZoneInfo
from personal_hermes.openclaw.client import OpenClawClient

TZ = ZoneInfo("Asia/Manila")


def test_update_only_passes_changed_fields_and_unwraps_envelope():
    captured = {}
    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"event": {"id": "evt1", "summary": "renamed",
                          "start": {"dateTime": "2026-05-21T15:00:00+08:00"},
                          "end": {"dateTime": "2026-05-21T15:30:00+08:00"}}}
    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    ev = client.update_calendar_event(event_id="evt1", summary="renamed")
    args = captured["args"]
    assert args[args.index("calendar") + 1] == "update"
    assert "primary" in args and "evt1" in args
    assert "--summary" in args and "renamed" in args
    assert "--from" not in args and "--to" not in args
    assert ev.id == "evt1"


def test_update_time_passes_from_to_and_timezone():
    captured = {}
    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"event": {"id": "evt1"}}
    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    client.update_calendar_event(
        event_id="evt1",
        start_at=datetime(2026,5,21,16,0,tzinfo=TZ),
        end_at=datetime(2026,5,21,16,30,tzinfo=TZ),
        timezone="Asia/Manila",
    )
    args = captured["args"]
    assert "--from" in args and "2026-05-21T16:00:00+08:00" in args
    assert "--to" in args and "2026-05-21T16:30:00+08:00" in args
    assert "--start-timezone" in args and "Asia/Manila" in args
