from datetime import UTC, date, datetime, timedelta

from personal_hermes.calendar.service import AvailabilityResult
from personal_hermes.router import AssistantRouter
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class FakeTelegram:
    def __init__(self, authorized: bool = True) -> None:
        self.authorized = authorized
        self.sent: list[dict] = []
        self.answers: list[dict] = []

    def is_authorized(self, event) -> bool:
        return self.authorized

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        self.sent.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        return 99

    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append({"callback_query_id": callback_query_id, "text": text})


class FakeCalendarService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def availability_for(self, text: str, *, today: date) -> AvailabilityResult:
        self.calls.append((text, today))
        return AvailabilityResult(
            fully_available=["Monday"],
            partly_available=["Tuesday"],
            busy=["Wednesday"],
        )


class FakeMailActionService:
    def __init__(self) -> None:
        self.callbacks: list[tuple[TelegramCallback, datetime]] = []

    def handle_callback(self, callback: TelegramCallback, *, now: datetime) -> None:
        self.callbacks.append((callback, now))


def message(text: str) -> TelegramMessage:
    return TelegramMessage(chat_id=123, user_id=456, message_id=1, text=text)


def callback(data: str) -> TelegramCallback:
    return TelegramCallback(
        chat_id=123,
        user_id=456,
        message_id=77,
        callback_query_id="callback-1",
        data=data,
    )


def test_unauthorized_event_is_ignored():
    telegram = FakeTelegram(authorized=False)
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
    )

    router.handle_event(
        message("What dates am I available this week?"),
        now=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
    )

    assert telegram.sent == []


def test_calendar_question_routes_to_calendar_service_and_sends_answer():
    telegram = FakeTelegram()
    calendar_service = FakeCalendarService()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=calendar_service,
        mail_action_service=FakeMailActionService(),
        store=None,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(message("What dates am I available this week?"), now=now)

    assert calendar_service.calls == [
        ("What dates am I available this week?", date(2026, 5, 19))
    ]
    assert "Fully available" in telegram.sent[0]["text"]
    assert "Monday" in telegram.sent[0]["text"]


def test_callback_routes_to_mail_action_service():
    mail_actions = FakeMailActionService()
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=mail_actions,
        store=None,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = callback("send_reply:1")

    router.handle_event(event, now=now)

    assert mail_actions.callbacks == [(event, now)]


def test_edit_reply_callback_sets_conversation_state(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    telegram = FakeTelegram()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=store,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(callback("edit_reply:5"), now=now)

    state = store.get_conversation_state(123)
    assert state is not None
    assert state.state == "editing_reply"
    assert state.payload == {"pending_reply_id": 5, "message_id": 77}
    assert "Type the edited reply" in telegram.sent[0]["text"]


def test_next_message_in_edit_flow_updates_pending_reply_and_clears_state(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    pending_id = store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Original",
        created_at=now,
        expires_at=now + timedelta(days=7),
        telegram_message_id=77,
    )
    store.set_conversation_state(
        telegram_chat_id=123,
        state="editing_reply",
        payload={"pending_reply_id": pending_id, "message_id": 77},
        updated_at=now,
    )
    telegram = FakeTelegram()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=store,
    )

    router.handle_event(message("Edited reply text"), now=now)

    pending = store.get_pending_reply(pending_id, now=now)
    assert pending is not None
    assert pending.reply_text == "Edited reply text"
    assert store.get_conversation_state(123) is None
    assert telegram.sent[0]["buttons"] == [
        [("Send edited reply", f"send_reply:{pending_id}"), ("Cancel", f"ignore_reply:{pending_id}")]
    ]


def test_unsupported_message_gets_fallback():
    telegram = FakeTelegram()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
    )

    router.handle_event(message("hello"), now=datetime(2026, 5, 19, 9, 0, tzinfo=UTC))

    assert "I can help with calendar availability" in telegram.sent[0]["text"]

