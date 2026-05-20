from datetime import UTC, datetime, timedelta

from personal_hermes.app import build_components
from personal_hermes.config import Settings


CHAT_ID = 123
USER_ID = 456


class FakeTelegramGateway:
    def __init__(self) -> None:
        self.updates = []
        self.sent_messages = []
        self.edited_messages = []
        self.answered_callbacks = []
        self.next_message_id = 100

    def queue_message(self, text: str, *, update_id: int = 1) -> None:
        self.updates.append(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "chat": {"id": CHAT_ID},
                    "from": {"id": USER_ID},
                    "text": text,
                },
            }
        )

    def queue_callback(self, data: str, *, update_id: int = 1) -> None:
        self.updates.append(
            {
                "update_id": update_id,
                "callback_query": {
                    "id": f"callback-{update_id}",
                    "from": {"id": USER_ID},
                    "message": {
                        "message_id": 100,
                        "chat": {"id": CHAT_ID},
                    },
                    "data": data,
                },
            }
        )

    def request(self, method, payload):
        if method == "getUpdates":
            updates = self.updates
            self.updates = []
            return {"ok": True, "result": updates}
        if method == "sendMessage":
            self.next_message_id += 1
            self.sent_messages.append(payload)
            return {"ok": True, "result": {"message_id": self.next_message_id}}
        if method == "editMessageText":
            self.edited_messages.append(payload)
            return {"ok": True, "result": True}
        if method == "answerCallbackQuery":
            self.answered_callbacks.append(payload)
            return {"ok": True, "result": True}
        raise AssertionError(f"unexpected Telegram method: {method}")


class FakeGogRunner:
    def __init__(self, *, now: datetime) -> None:
        self.now = now
        self.sent_replies = []
        self.marked_read = []

    def __call__(self, args, *, input_text=None):
        command = _command_after_global_options(args)
        if command[:4] == ["gmail", "messages", "search", "in:inbox"]:
            return {
                "messages": [
                    {
                        "id": "msg-1",
                        "thread_id": "thread-1",
                        "subject": "Can we meet tomorrow?",
                        "sender": "Alex Sender <alex@example.com>",
                        "to": ["Hermes User <me@example.com>"],
                        "cc": [],
                        "sent_at": self.now.isoformat(),
                        "snippet": "Can we meet tomorrow?",
                        "body_text": "Hi, can we meet tomorrow to discuss the proposal?",
                        "is_unread": True,
                        "message_id": "<msg-1@example.com>",
                    }
                ]
            }
        if command[:2] == ["gmail", "get"]:
            return {
                "id": "msg-1",
                "thread_id": "thread-1",
                "subject": "Can we meet tomorrow?",
                "sender": "Alex Sender <alex@example.com>",
                "to": ["Hermes User <me@example.com>"],
                "cc": [],
                "sent_at": self.now.isoformat(),
                "snippet": "Can we meet tomorrow?",
                "body_text": "Hi, can we meet tomorrow to discuss the proposal?",
                "is_unread": True,
                "message_id": "<msg-1@example.com>",
            }
        if command[:2] == ["gmail", "send"]:
            self.sent_replies.append({"args": args, "body": input_text})
            return {"id": "sent-msg-1"}
        if command[:2] == ["gmail", "mark-read"]:
            self.marked_read.append(command[2])
            return {"ok": True}
        if command[:3] == ["calendar", "events", "primary"]:
            return {
                "events": [
                    {
                        "id": "event-1",
                        "title": "Planning",
                        "start_at": (self.now + timedelta(minutes=30)).isoformat(),
                        "end_at": (self.now + timedelta(minutes=90)).isoformat(),
                        "all_day": False,
                        "timezone": "UTC",
                        "location": "Meet",
                    }
                ]
            }
        raise AssertionError(f"unexpected gog args: {args}")


def make_settings(database_path) -> Settings:
    return Settings(
        telegram_bot_token="telegram-token",
        telegram_authorized_chat_id=CHAT_ID,
        telegram_authorized_user_id=USER_ID,
        sqlite_database_path=str(database_path),
        gog_executable="gog",
        gog_account="lmmagbuhos@oakdriveventures.com",
        gog_client="default",
        timezone="UTC",
        multiuser_enabled=False,
    )


def make_components(tmp_path, *, now):
    telegram = FakeTelegramGateway()
    gog = FakeGogRunner(now=now)
    components = build_components(
        make_settings(tmp_path / "assistant.sqlite3"),
        telegram_gateway=telegram,
        command_runner=gog,
        now_provider=lambda: now,
    )
    return components, telegram, gog


def test_telegram_calendar_question_returns_availability_answer(tmp_path):
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    components, telegram, _gog = make_components(tmp_path, now=now)
    telegram.queue_message("What dates am I available this week?")

    components.scheduler.run_telegram_poll_job()

    assert len(telegram.sent_messages) == 1
    assert "Fully available:" in telegram.sent_messages[0]["text"]
    assert "Busy:" in telegram.sent_messages[0]["text"]


def test_gmail_poll_to_telegram_notification_and_send_reply_callback(tmp_path):
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    components, telegram, gog = make_components(tmp_path, now=now)

    components.scheduler.run_gmail_poll_job()
    telegram.queue_callback("send_reply:1")
    components.scheduler.run_telegram_poll_job()

    assert "New email" in telegram.sent_messages[0]["text"]
    assert telegram.sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Send reply"
    assert gog.sent_replies == [
        {
            "args": [
                "gog",
                "--account",
                "lmmagbuhos@oakdriveventures.com",
                "--client",
                "default",
                "gmail",
                "send",
                "--thread-id",
                "thread-1",
                "--to",
                "alex@example.com",
                "--subject",
                "Re: Can we meet tomorrow?",
                "--body-file",
                "-",
                "--json",
                "--no-input",
                "--reply-to-message-id",
                "<msg-1@example.com>",
            ],
            "body": "Hi Alex, thanks for reaching out. I will review this and get back to you.",
        }
    ]
    assert telegram.edited_messages[0]["text"] == "Reply sent."


def test_edit_flow_replaces_suggested_reply_before_send(tmp_path):
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    components, telegram, gog = make_components(tmp_path, now=now)

    components.scheduler.run_gmail_poll_job()
    telegram.queue_callback("edit_reply:1", update_id=2)
    components.scheduler.run_telegram_poll_job()
    telegram.queue_message("Tomorrow at 3 PM works for me.", update_id=3)
    components.scheduler.run_telegram_poll_job()
    telegram.queue_callback("send_reply:1", update_id=4)
    components.scheduler.run_telegram_poll_job()

    assert telegram.sent_messages[1]["text"] == "Type the edited reply in your next message."
    assert telegram.sent_messages[2]["text"] == "Edited reply saved. Confirm before sending."
    assert gog.sent_replies[0]["body"] == "Tomorrow at 3 PM works for me."


def test_calendar_reminder_poll_sends_upcoming_event_notification(tmp_path):
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    components, telegram, _gog = make_components(tmp_path, now=now)

    components.scheduler.run_calendar_reminder_job()

    assert telegram.sent_messages == [
        {
            "chat_id": CHAT_ID,
            "text": "Reminder: Planning starts in 30 minutes\nTime: 08:30\nLocation: Meet",
        }
    ]


def _command_after_global_options(args):
    command = list(args[1:])
    while command and command[0] in {"--account", "--client"}:
        command = command[2:]
    return command
