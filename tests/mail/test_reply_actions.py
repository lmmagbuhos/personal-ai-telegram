from datetime import UTC, datetime, timedelta

from personal_hermes.mail.actions import MailActionService
from personal_hermes.openclaw.types import EmailMessage, SendEmailReplyRequest
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback


class FakeOpenClawClient:
    def __init__(self) -> None:
        self.sent_replies: list[SendEmailReplyRequest] = []
        self.marked_read: list[str] = []

    def get_email_message(self, email_id: str) -> EmailMessage:
        return EmailMessage(
            id=email_id,
            thread_id="thread-1",
            subject="Project update",
            sender="Alex Sender <alex@example.com>",
            to=("Hermes User <me@example.com>",),
            cc=(),
            sent_at=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
            snippet="Can we meet?",
            body_text="Can we meet?",
            is_unread=True,
            message_id="<msg-1@example.com>",
        )

    def send_thread_reply(self, request: SendEmailReplyRequest) -> str:
        self.sent_replies.append(request)
        return "sent-msg-1"

    def mark_email_read(self, email_id: str) -> None:
        self.marked_read.append(email_id)


class FakeTelegramAdapter:
    def __init__(self, authorized: bool = True) -> None:
        self.authorized = authorized
        self.edits: list[dict] = []
        self.answers: list[dict] = []

    def is_authorized(self, event) -> bool:
        return self.authorized

    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})

    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append({"callback_query_id": callback_query_id, "text": text})


def callback(data: str) -> TelegramCallback:
    return TelegramCallback(
        chat_id=123,
        user_id=456,
        message_id=77,
        callback_query_id="callback-1",
        data=data,
    )


def create_pending(store: StateStore, now: datetime) -> int:
    return store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Suggested reply",
        created_at=now,
        expires_at=now + timedelta(days=7),
        telegram_message_id=77,
    )


def test_send_reply_requires_authorized_callback(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    openclaw = FakeOpenClawClient()
    telegram = FakeTelegramAdapter(authorized=False)
    service = MailActionService(openclaw_client=openclaw, telegram=telegram, store=store)

    service.handle_callback(callback("send_reply:1"), now=datetime(2026, 5, 19, tzinfo=UTC))

    assert openclaw.sent_replies == []
    assert telegram.answers == [{"callback_query_id": "callback-1", "text": "Unauthorized"}]


def test_send_reply_sends_pending_reply_once_and_audits(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    pending_id = create_pending(store, now)
    openclaw = FakeOpenClawClient()
    telegram = FakeTelegramAdapter()
    service = MailActionService(openclaw_client=openclaw, telegram=telegram, store=store)

    service.handle_callback(callback(f"send_reply:{pending_id}"), now=now)
    service.handle_callback(callback(f"send_reply:{pending_id}"), now=now)

    assert openclaw.sent_replies == [
        SendEmailReplyRequest(
            thread_id="thread-1",
            to=("alex@example.com",),
            subject="Re: Project update",
            body_text="Suggested reply",
            in_reply_to="<msg-1@example.com>",
        )
    ]
    assert store.get_pending_reply(pending_id).status == "sent"
    assert store.count_reply_audits() == 1
    assert "Reply sent" in telegram.edits[0]["text"]
    assert telegram.answers[0]["text"] == "Reply sent"
    assert telegram.answers[1]["text"] == "Reply is no longer pending"


def test_expired_reply_is_not_sent(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    pending_id = store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Suggested reply",
        created_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1),
        telegram_message_id=77,
    )
    openclaw = FakeOpenClawClient()
    telegram = FakeTelegramAdapter()
    service = MailActionService(openclaw_client=openclaw, telegram=telegram, store=store)

    service.handle_callback(callback(f"send_reply:{pending_id}"), now=now)

    assert openclaw.sent_replies == []
    assert telegram.answers == [
        {"callback_query_id": "callback-1", "text": "Reply is no longer pending"}
    ]


def test_ignore_reply_marks_pending_ignored(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    pending_id = create_pending(store, now)
    service = MailActionService(
        openclaw_client=FakeOpenClawClient(),
        telegram=FakeTelegramAdapter(),
        store=store,
    )

    service.handle_callback(callback(f"ignore_reply:{pending_id}"), now=now)

    assert store.get_pending_reply(pending_id).status == "ignored"


def test_mark_read_calls_openclaw_and_updates_telegram():
    openclaw = FakeOpenClawClient()
    telegram = FakeTelegramAdapter()
    service = MailActionService(openclaw_client=openclaw, telegram=telegram, store=None)

    service.handle_callback(callback("mark_read:msg-1"), now=datetime(2026, 5, 19, tzinfo=UTC))

    assert openclaw.marked_read == ["msg-1"]
    assert telegram.answers == [{"callback_query_id": "callback-1", "text": "Marked read"}]
