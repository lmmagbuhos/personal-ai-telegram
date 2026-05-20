"""Test the wiring of calendar event creation into the router."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.actions import CalendarActionService
from personal_hermes.calendar.edit import CalendarEditService
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
        self.deleted = []
        self.updated = []
        self._events = []

    def with_access_token(self, token):
        return self

    def create_calendar_event(self, *, title, start_at, end_at, timezone):
        self.created.append((title, start_at, end_at, timezone))

        class E:
            id = "evt1"

        return E()

    def list_calendar_events(self, start, end):
        """Return any events set via set_events."""
        return self._events

    def set_events(self, events):
        """Set events to be returned by list_calendar_events."""
        self._events = events

    def delete_calendar_event(self, *, event_id):
        """Record the deleted event id."""
        self.deleted.append(event_id)

    def update_calendar_event(self, *, event_id, **fields):
        """Record the updated event id and fields."""
        self.updated.append((event_id, fields))

        class E:
            id = event_id

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


def test_cancel_event_routing_multiuser(tmp_path):
    """Test that the router wires calendar event cancellation in multiuser mode."""
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

    # 2. Build a CalendarEditService with fakes
    tg = FakeTelegram()
    client = FakeClient()

    # Create a fake calendar event to list
    class FakeEvent:
        def __init__(self, event_id, title, start_at, end_at):
            self.id = event_id
            self.title = title
            self.start_at = start_at
            self.end_at = end_at

    # Set up the client to return an event on the target date
    event = FakeEvent(
        "evt_to_cancel",
        "Team Meeting",
        datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
    )
    client.set_events([event])

    calendar_edit_service = CalendarEditService(
        openclaw_client=client,
        telegram=tg,
        store=store,
        timezone=TZ,
        resolve_access_token=lambda user_id, *, now: "tok",
    )

    # 3. Build the AssistantRouter for multiuser mode
    router = AssistantRouter(
        telegram=tg,
        calendar_service=SimpleStub(),  # Not needed for cancel path
        mail_action_service=SimpleStub(),  # Not needed for cancel path
        store=store,
        oauth_service=object(),  # Non-None to enter multiuser branch
        calendar_edit_service=calendar_edit_service,
        timezone=TZ,
    )

    # 4. Send a message that looks like a cancel-event request
    message = TelegramMessage(
        chat_id=2,
        user_id=1,
        message_id=100,
        text="cancel an event today",
    )
    router.handle_event(message, now=now)

    # Assert: the fake telegram received a message with a cal_pick button
    assert len(tg.sent_messages) == 1
    sent = tg.sent_messages[0]
    assert "cancel" in sent["text"].lower() or "event" in sent["text"].lower()
    assert sent["buttons"] is not None
    # Extract the callback data from the first button
    buttons_flat = [btn for row in sent["buttons"] for btn in row]
    pick_btn = buttons_flat[0]
    assert isinstance(pick_btn, tuple)
    assert pick_btn[1].startswith("cal_pick:")

    # 5. Send the cal_pick callback to select the event
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=100,
        callback_query_id="q1",
        data="cal_pick:0",
    )
    tg.sent_messages.clear()  # Clear prior messages
    router.handle_event(callback, now=now)

    # Assert: should now have confirmation buttons
    # The service sends a message with cal_del_ok/cal_del_no buttons
    assert len(tg.sent_messages) >= 1
    sent_confirm = tg.sent_messages[-1]
    assert sent_confirm["buttons"] is not None
    buttons_flat = [btn for row in sent_confirm["buttons"] for btn in row]
    del_ok_btn = next(
        (btn for btn in buttons_flat if isinstance(btn, tuple) and btn[1] == "cal_del_ok"),
        None,
    )
    assert del_ok_btn is not None

    # 6. Send the cal_del_ok callback to confirm deletion
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=101,
        callback_query_id="q2",
        data="cal_del_ok",
    )
    router.handle_event(callback, now=now)

    # Assert: the fake client recorded the deleted event id
    assert len(client.deleted) == 1
    assert client.deleted[0] == "evt_to_cancel"


def test_edit_event_routing_multiuser(tmp_path):
    """Test that the router wires calendar event editing in multiuser mode."""
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

    # 2. Build a CalendarEditService with fakes
    tg = FakeTelegram()
    client = FakeClient()

    # Create a fake calendar event to edit
    class FakeEvent:
        def __init__(self, event_id, title, start_at, end_at):
            self.id = event_id
            self.title = title
            self.start_at = start_at
            self.end_at = end_at

    # Set up the client to return an event on the target date
    event = FakeEvent(
        "e1",
        "Standup",
        datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 20, 10, 30, tzinfo=UTC),
    )
    client.set_events([event])

    calendar_edit_service = CalendarEditService(
        openclaw_client=client,
        telegram=tg,
        store=store,
        timezone=TZ,
        resolve_access_token=lambda user_id, *, now: "tok",
    )

    # 3. Build the AssistantRouter for multiuser mode
    router = AssistantRouter(
        telegram=tg,
        calendar_service=SimpleStub(),  # Not needed for edit path
        mail_action_service=SimpleStub(),  # Not needed for edit path
        store=store,
        oauth_service=object(),  # Non-None to enter multiuser branch
        calendar_edit_service=calendar_edit_service,
        timezone=TZ,
    )

    # 4. Send a message that looks like an edit-event request
    message = TelegramMessage(
        chat_id=2,
        user_id=1,
        message_id=100,
        text="edit an event on May 20",
    )
    router.handle_event(message, now=now)

    # Assert: the fake telegram received a message with a cal_pick button
    assert len(tg.sent_messages) == 1
    sent = tg.sent_messages[0]
    assert "edit" in sent["text"].lower() or "event" in sent["text"].lower()
    assert sent["buttons"] is not None
    # Extract the callback data from the first button
    buttons_flat = [btn for row in sent["buttons"] for btn in row]
    pick_btn = buttons_flat[0]
    assert isinstance(pick_btn, tuple)
    assert pick_btn[1] == "cal_pick:0"

    # 5. Send the cal_pick callback to select the event (triggers field-choice display)
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=100,
        callback_query_id="q1",
        data="cal_pick:0",
    )
    tg.sent_messages.clear()  # Clear prior messages
    router.handle_event(callback, now=now)

    # Assert: should now have field-choice buttons
    # The service sends messages with cal_field buttons
    assert len(tg.sent_messages) >= 1
    sent_fields = tg.sent_messages[-1]
    assert sent_fields["buttons"] is not None
    buttons_flat = [btn for row in sent_fields["buttons"] for btn in row]
    title_btn = next(
        (btn for btn in buttons_flat if isinstance(btn, tuple) and btn[1] == "cal_field:title"),
        None,
    )
    assert title_btn is not None

    # 6. Send the cal_field:title callback to choose the field to edit
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=101,
        callback_query_id="q2",
        data="cal_field:title",
    )
    tg.sent_messages.clear()  # Clear prior messages
    router.handle_event(callback, now=now)

    # Assert: should prompt for the new value
    assert len(tg.sent_messages) >= 1
    sent_prompt = tg.sent_messages[-1]
    assert "new title" in sent_prompt["text"].lower() or "send" in sent_prompt["text"].lower()

    # 7. Send a message with the new value (typed by user)
    message = TelegramMessage(
        chat_id=2,
        user_id=1,
        message_id=102,
        text="Renamed standup",
    )
    tg.sent_messages.clear()  # Clear prior messages
    router.handle_event(message, now=now)

    # Assert: the router should route this to handle_value and show confirmation
    assert len(tg.sent_messages) >= 1
    sent_confirm = tg.sent_messages[-1]
    assert "Renamed standup" in sent_confirm["text"]
    assert sent_confirm["buttons"] is not None
    buttons_flat = [btn for row in sent_confirm["buttons"] for btn in row]
    confirm_btn = next(
        (btn for btn in buttons_flat if isinstance(btn, tuple) and btn[1] == "cal_edit_ok"),
        None,
    )
    assert confirm_btn is not None

    # 8. Send the cal_edit_ok callback to confirm the edit
    callback = TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=103,
        callback_query_id="q3",
        data="cal_edit_ok",
    )
    router.handle_event(callback, now=now)

    # Assert: the fake client recorded the update with the new summary
    assert len(client.updated) == 1
    event_id, fields = client.updated[0]
    assert event_id == "e1"
    assert fields.get("summary") == "Renamed standup"
