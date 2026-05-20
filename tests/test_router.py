from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import DaySchedule, AvailabilityStatus
from personal_hermes.calendar.service import AvailabilityResult
from personal_hermes.llm.intents import LLMIntent, LLMIntentResult
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
        self.timezone = ZoneInfo("UTC")

    def availability_for(self, text: str, *, today: date, user_id: int | None = None) -> AvailabilityResult:
        self.calls.append((text, today))
        return AvailabilityResult(
            fully_available=["Monday"],
            partly_available=["Tuesday"],
            busy=["Wednesday"],
        )

    def schedule_for(self, text: str, *, today: date, user_id: int | None = None) -> list[DaySchedule]:
        self.calls.append((text, today))
        # Return a simple schedule for testing
        return [
            DaySchedule(
                date=today,
                status=AvailabilityStatus.FULLY_AVAILABLE,
                timed_events=[],
                all_day_events=[],
                free_slots=[(datetime(2026, 5, 19, 9, 0, tzinfo=ZoneInfo("UTC")), datetime(2026, 5, 19, 17, 0, tzinfo=ZoneInfo("UTC")))],
            )
        ]


class FakeMailActionService:
    def __init__(self) -> None:
        self.callbacks: list[tuple[TelegramCallback, datetime]] = []

    def handle_callback(self, callback: TelegramCallback, *, now: datetime, user_id=None) -> None:
        self.callbacks.append((callback, now))


class FakeGmailReadService:
    def __init__(self, handled: bool = True) -> None:
        self.handled = handled
        self.messages = []
        self.callbacks = []

    def start_search(self, message, *, user_id, now):
        self.messages.append((message, user_id, now))
        return self.handled

    def handle_callback(self, callback, *, user_id, now):
        self.callbacks.append((callback, user_id, now))


class FakeGmailDraftService:
    def __init__(self, handled: bool = True) -> None:
        self.handled = handled
        self.messages = []
        self.values = []
        self.callbacks = []

    def start_compose(self, message, *, user_id, now):
        self.messages.append((message, user_id, now))
        return self.handled

    def handle_value(self, message, *, user_id, now):
        self.values.append((message, user_id, now))
        return self.handled

    def handle_callback(self, callback, *, user_id, now):
        self.callbacks.append((callback, user_id, now))


class FakeGmailMessageActionService:
    def __init__(self, handled: bool = True) -> None:
        self.handled = handled
        self.values = []
        self.callbacks = []

    def handle_value(self, message, *, user_id, now):
        self.values.append((message, user_id, now))
        return self.handled

    def handle_callback(self, callback, *, user_id, now):
        self.callbacks.append((callback, user_id, now))


class FakeLLMIntentService:
    def __init__(
        self,
        result: LLMIntentResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.messages = []

    def classify(self, text: str) -> LLMIntentResult:
        self.messages.append(text)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


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
    assert "free" in telegram.sent[0]["text"]


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


def test_edit_reply_state_skips_llm(tmp_path):
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
    llm = FakeLLMIntentService(
        LLMIntentResult(intent=LLMIntent.GMAIL_SEARCH, normalized_text="search emails")
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=store,
        llm_intent_service=llm,
    )

    router.handle_event(message("This is my edited reply."), now=now)

    assert llm.messages == []


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


def test_llm_calendar_read_routes_before_rule_fallback():
    telegram = FakeTelegram()
    calendar_service = FakeCalendarService()
    llm = FakeLLMIntentService(
        LLMIntentResult(
            intent=LLMIntent.CALENDAR_READ,
            normalized_text="what is on my calendar today",
        )
    )
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=calendar_service,
        mail_action_service=FakeMailActionService(),
        store=None,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(message("do I have anything later?"), now=now)

    assert llm.messages == ["do I have anything later?"]
    assert calendar_service.calls == [("what is on my calendar today", date(2026, 5, 19))]
    assert "free" in telegram.sent[0]["text"]


def test_llm_gmail_search_routes_to_gmail_read_service():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(
        LLMIntentResult(
            intent=LLMIntent.GMAIL_SEARCH,
            normalized_text="search emails from alex",
        )
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(message("did Alex email me?"), now=now)

    handled_message, user_id, handled_now = gmail_read.messages[0]
    assert handled_message.text == "search emails from alex"
    assert user_id is None
    assert handled_now == now


def test_llm_unknown_falls_back_to_rule_based_routing():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(
        LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("show unread emails")

    router.handle_event(event, now=now)

    assert gmail_read.messages == [(event, None, now)]


def test_llm_error_falls_back_to_rule_based_routing():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(error=RuntimeError("llm unavailable"))
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("show unread emails")

    router.handle_event(event, now=now)

    assert gmail_read.messages == [(event, None, now)]


def test_gmail_search_routes_before_fallback():
    gmail_read = FakeGmailReadService()
    telegram = FakeTelegram()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("show unread emails")

    router.handle_event(event, now=now)

    assert gmail_read.messages == [(event, None, now)]
    assert telegram.sent == []


def test_gmail_compose_routes_before_fallback():
    gmail_drafts = FakeGmailDraftService()
    telegram = FakeTelegram()
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_draft_service=gmail_drafts,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("email alex@example.com subject Hello body Body")

    router.handle_event(event, now=now)

    assert gmail_drafts.messages == [(event, None, now)]
    assert telegram.sent == []


def test_gmail_callbacks_route_to_new_services():
    gmail_read = FakeGmailReadService()
    gmail_actions = FakeGmailMessageActionService()
    gmail_drafts = FakeGmailDraftService()
    mail_actions = FakeMailActionService()
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=mail_actions,
        store=None,
        gmail_read_service=gmail_read,
        gmail_message_action_service=gmail_actions,
        gmail_draft_service=gmail_drafts,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    pick = callback("mail_pick:0")
    archive = callback("mail_archive")
    draft_send = callback("draft_send")
    router.handle_event(pick, now=now)
    router.handle_event(archive, now=now)
    router.handle_event(draft_send, now=now)

    assert gmail_read.callbacks == [(pick, None, now)]
    assert gmail_actions.callbacks == [(archive, None, now)]
    assert gmail_drafts.callbacks == [(draft_send, None, now)]
    assert mail_actions.callbacks == []
