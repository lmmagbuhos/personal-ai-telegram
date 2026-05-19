from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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

    def queue_message(self, text: str, *, update_id: int) -> None:
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

    def queue_callback(self, data: str, *, update_id: int) -> None:
        self.updates.append(
            {
                "update_id": update_id,
                "callback_query": {
                    "id": f"callback-{update_id}",
                    "from": {"id": USER_ID},
                    "message": {"message_id": 100, "chat": {"id": CHAT_ID}},
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
        raise RuntimeError(f"unexpected Telegram method: {method}")


class FakeGogRunner:
    def __init__(self, *, now: datetime) -> None:
        self.now = now
        self.sent_replies = []

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
        return {"ok": True}


def main() -> int:
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as tmpdir:
        components, telegram, gog = _make_components(Path(tmpdir), now=now)

        telegram.queue_message("What dates am I available this week?", update_id=1)
        components.scheduler.run_telegram_poll_job()

        components.scheduler.run_gmail_poll_job()
        telegram.queue_callback("edit_reply:1", update_id=2)
        components.scheduler.run_telegram_poll_job()
        telegram.queue_message("Tomorrow at 3 PM works for me.", update_id=3)
        components.scheduler.run_telegram_poll_job()
        telegram.queue_callback("send_reply:1", update_id=4)
        components.scheduler.run_telegram_poll_job()

        components.scheduler.run_calendar_reminder_job()

        print("Local dry run completed")
        print(f"telegram_messages={len(telegram.sent_messages)}")
        print(f"edited_messages={len(telegram.edited_messages)}")
        print(f"answered_callbacks={len(telegram.answered_callbacks)}")
        print(f"sent_replies={len(gog.sent_replies)}")
    return 0


def _make_components(tmpdir: Path, *, now: datetime):
    telegram = FakeTelegramGateway()
    gog = FakeGogRunner(now=now)
    settings = Settings(
        telegram_bot_token="telegram-token",
        telegram_authorized_chat_id=CHAT_ID,
        telegram_authorized_user_id=USER_ID,
        sqlite_database_path=str(tmpdir / "assistant.sqlite3"),
        gog_executable="gog",
        gog_account="lmmagbuhos@oakdriveventures.com",
        gog_client="default",
        timezone="UTC",
    )
    components = build_components(
        settings,
        telegram_gateway=telegram,
        command_runner=gog,
        now_provider=lambda: now,
    )
    return components, telegram, gog


def _command_after_global_options(args):
    command = list(args[1:])
    while command and command[0] in {"--account", "--client"}:
        command = command[2:]
    return command


if __name__ == "__main__":
    raise SystemExit(main())
