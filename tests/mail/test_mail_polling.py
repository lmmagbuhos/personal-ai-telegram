from datetime import UTC, datetime, timedelta

from personal_hermes.mail.service import MailPollingService
from personal_hermes.openclaw.types import EmailMessage
from personal_hermes.storage.store import StateStore


class FakeOpenClawClient:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self.messages = messages
        self.access_tokens: list[str] = []
        self.calls: list[str | None] = []
        self.message_calls = 0

    def list_new_inbox_messages(self, since_cursor: str | None) -> list[EmailMessage]:
        self.calls.append(since_cursor)
        self.message_calls += 1
        return self.messages

    def with_access_token(self, access_token: str) -> "FakeOpenClawClient":
        self.access_tokens.append(access_token)
        return self


class FakeTelegramAdapter:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.next_message_id = 100

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        self.sent_messages.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        message_id = self.next_message_id
        self.next_message_id += 1
        return message_id


def make_email(
    email_id: str,
    *,
    subject: str = "Question",
    body_text: str = "Can you confirm this works?",
    sender: str = "Alex <alex@example.com>",
) -> EmailMessage:
    return EmailMessage(
        id=email_id,
        thread_id=f"thread-{email_id}",
        subject=subject,
        sender=sender,
        to=("me@example.com",),
        cc=(),
        sent_at=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
        snippet=body_text,
        body_text=body_text,
        is_unread=True,
        message_id=f"<{email_id}@example.com>",
    )


def test_poll_notifies_all_new_emails_and_creates_pending_reply_when_suggested(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    openclaw = FakeOpenClawClient(
        [
            make_email("msg-1", body_text="Can you confirm this works?"),
            make_email("msg-2", subject="Newsletter", body_text="Weekly update"),
        ]
    )
    telegram = FakeTelegramAdapter()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    service = MailPollingService(
        openclaw_client=openclaw,
        telegram=telegram,
        store=store,
        authorized_chat_id=123,
        pending_reply_expiry_days=7,
    )

    result = service.poll(since_cursor="after:2026/05/18", now=now)

    assert result.notified_count == 2
    assert result.pending_reply_count == 1
    assert len(telegram.sent_messages) == 2
    assert "Suggested reply:" in telegram.sent_messages[0]["text"]
    assert "Suggested reply:" not in telegram.sent_messages[1]["text"]
    assert telegram.sent_messages[0]["buttons"] == [
        [("Send reply", "send_reply:1"), ("Edit reply", "edit_reply:1")],
        [("Ignore", "ignore_reply:1"), ("Mark read", "mark_read:msg-1")],
    ]
    assert telegram.sent_messages[1]["buttons"] == [
        [("Ignore", "ignore_reply:0"), ("Mark read", "mark_read:msg-2")]
    ]
    pending = store.get_pending_reply(1, now=now)
    assert pending is not None
    assert pending.email_id == "msg-1"
    assert pending.expires_at == now + timedelta(days=7)


def test_poll_suppresses_duplicate_notifications(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    openclaw = FakeOpenClawClient([make_email("msg-1")])
    telegram = FakeTelegramAdapter()
    service = MailPollingService(
        openclaw_client=openclaw,
        telegram=telegram,
        store=store,
        authorized_chat_id=123,
        pending_reply_expiry_days=7,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    first = service.poll(since_cursor=None, now=now)
    second = service.poll(since_cursor=None, now=now)

    assert first.notified_count == 1
    assert second.notified_count == 0
    assert len(telegram.sent_messages) == 1


def test_poll_uses_access_token_for_user_context(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    openclaw = FakeOpenClawClient(
        [make_email("msg-1", body_text="Can you confirm this works?")]
    )
    telegram = FakeTelegramAdapter()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    user = store.upsert_user_from_telegram(
        telegram_user_id=7,
        telegram_chat_id=7,
        display_name=None,
        username=None,
        now=now,
    )
    service = MailPollingService(
        openclaw_client=openclaw,
        telegram=telegram,
        store=store,
        authorized_chat_id=123,
        default_user_id=user.id,
        pending_reply_expiry_days=7,
        resolve_access_token=lambda user_id, now: (
            "token-7" if user_id == user.id else None
        ),
    )

    service.poll(since_cursor=None, user_id=user.id, now=now)

    assert openclaw.access_tokens == ["token-7"]
    assert openclaw.message_calls == 1
