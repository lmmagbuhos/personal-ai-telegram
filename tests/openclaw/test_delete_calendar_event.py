from personal_hermes.openclaw.client import OpenClawClient


def test_delete_calendar_event_builds_gog_args():
    captured = {}

    def runner(args, *, input_text=None):
        captured["args"] = args
        return {}

    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    client.delete_calendar_event(event_id="evt123")

    args = captured["args"]
    assert args[0] == "gog"
    assert "--access-token" in args and "tok" in args
    assert args[args.index("calendar") + 1] == "delete"
    assert "primary" in args
    assert "evt123" in args
    assert "--no-input" in args
    assert "-y" in args
