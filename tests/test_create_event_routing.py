"""Test the wiring of calendar event creation into the router."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.actions import CalendarActionService
from personal_hermes.calendar.event_request import EventDraft
from personal_hermes.router import AssistantRouter
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage

TZ = ZoneInfo("Asia/Manila")


class FakeTelegram:
    """Fake Telegram for testing."""

    def __init__(self):
        self.sent_messages = []
        self.edits = []
        self.answers = []

    def is_authorized(self, event):
        return True

    def send_message(self, *, chat_id, text, buttons=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "buttons": buttons})

    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append(text)

    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append(text)


class FakeClient:
    """Fake OpenClaw client for testing."""

    def __init__(self):
        self.created = []

    def with_access_token(self, token):
        return self

    def create_calendar_event(self, *, title, start_at, end_at, timezone):
        self.created.append((title, start_at, end_at, timezone))

        class E:
            id = "evt1"

        return E()


class SimpleStub:
    """A simple stub that ignores all calls."""

    pass


def test_create_event_routing_multiuser(tmp_path):
    """Test that the router wires calendar event creation in multiuser mode."""
    # 1. Build a real StateStore with an active user
    store = StateStore(str(tmp_path / "t.sqlite3"))
    store.initialize()

    now = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)
    user = store.upsert_user_from_telegram(
        telegram_user_id=1,
        telegram_chat_id=2,
        display_name=None,
        username=None,
        now=now,
    )
    # Activate the user so the multiuser path processes their messages
    store.activate_user(user.id, now=now)

    # 2. Build a CalendarActionService with fakes
    tg = FakeTelegram()
    client = FakeClient()
    calendar_action_service = CalendarActionService(
        openclaw_client=client,
        telegram=tg,
        store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )

    # 3. Build the AssistantRouter for multiuser mode
    router = AssistantRouter(
        telegram=tg,
        calendar_service=SimpleStub(),  # Not needed for create path
        mail_action_service=SimpleStub(),  # Not needed for create path
        store=store,
        oauth_service=object(),  # Non-None to enter multiuser branch
        calendar_action_service=calendar_action_service,
        timezone=TZ,
    )

    # 4. Send a message that looks like a create-event request
    message = TelegramMessage(
        chat_id=2,
        user_id=1,
        message_id=100,
        text="appointment today 9AM-9:30AM dentist",
    )
    router.handle_event(message, now=now)

    # Assert: the fake telegram received a confirmation message with buttons
    assert len(tg.sent_messages) == 1
    sent = tg.sent_messages[0]
    assert "dentist" in sent["text"]
    assert sent["buttons"] is not None
    # Extract the pending_id from the callback data
    buttons_flat = [btn for row in sent["buttons"] for btn in row]
    confirm_btn = next((btn for btn in buttons_flat if isinstance(btn, tuple) and "Confirm" in btn[0]), None)
    assert confirm_btn is not None
    callback_data = confirm_btn[1]  # e.g., "cal_confirm:123"
    assert callback_data.startswith("cal_confirm:")
    pending_id = int(callback_data.split(":")[1])

    # 5. Send a confirmation callback
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=100,
        callback_query_id="q1",
        data=f"cal_confirm:{pending_id}",
    )
    router.handle_event(callback, now=now)

    # Assert: the FakeClient recorded the event creation
    assert len(client.created) == 1
    title, start_at, end_at, timezone = client.created[0]
    assert title == "dentist"
    assert start_at.hour == 9
    assert start_at.minute == 0
    assert end_at.hour == 9
    assert end_at.minute == 30
    assert timezone == "Asia/Manila"
