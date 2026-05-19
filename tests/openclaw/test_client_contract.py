import json
from datetime import UTC, datetime
from typing import Any

from personal_hermes.openclaw.client import OpenClawClient
from personal_hermes.openclaw.types import (
    CalendarEvent,
    EmailMessage,
    SendEmailReplyRequest,
)


class FakeCommandRunner:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: list[str], *, input_text: str | None = None) -> Any:
        self.calls.append((args, input_text))
        return self.responses.pop(0)


def test_list_new_inbox_messages_invokes_gog_and_maps_messages():
    runner = FakeCommandRunner(
        [
            {
                "messages": [
                    {
                        "id": "msg-1",
                        "thread_id": "thread-1",
                        "subject": "Project update",
                        "sender": "Alex Sender <alex@example.com>",
                        "to": ["Hermes User <me@example.com>"],
                        "cc": [],
                        "sent_at": "2026-05-18T10:15:00+00:00",
                        "snippet": "Quick project update",
                        "body_text": "Hello Hermes,\nCan we meet tomorrow?\n",
                        "is_unread": True,
                        "message_id": "<source-message@example.com>",
                        "references": ["<previous-message@example.com>"],
                    }
                ]
            }
        ]
    )
    client = OpenClawClient(command_runner=runner)

    messages = client.list_new_inbox_messages(since_cursor="2026-05-18T00:00:00Z")

    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "messages",
                "list",
                "--inbox",
                "--unread",
                "--format",
                "json",
                "--limit",
                "25",
                "--since",
                "2026-05-18T00:00:00Z",
            ],
            None,
        )
    ]
    assert messages == [
        EmailMessage(
            id="msg-1",
            thread_id="thread-1",
            subject="Project update",
            sender="Alex Sender <alex@example.com>",
            to=("Hermes User <me@example.com>",),
            cc=(),
            sent_at=datetime(2026, 5, 18, 10, 15, tzinfo=UTC),
            snippet="Quick project update",
            body_text="Hello Hermes,\nCan we meet tomorrow?\n",
            is_unread=True,
            message_id="<source-message@example.com>",
            references=("<previous-message@example.com>",),
        )
    ]


def test_get_email_message_invokes_gog_and_accepts_camel_case_fields():
    runner = FakeCommandRunner(
        [
            {
                "id": "msg-1",
                "threadId": "thread-1",
                "subject": "Project update",
                "from": "Alex Sender <alex@example.com>",
                "to": "Hermes User <me@example.com>",
                "cc": "Ops <ops@example.com>",
                "sentAt": "2026-05-18T10:15:00+00:00",
                "snippet": "Quick project update",
                "body": "Plain text body",
                "unread": True,
                "messageId": "<source-message@example.com>",
                "references": "<previous-message@example.com> <source-message@example.com>",
            }
        ]
    )
    client = OpenClawClient(command_runner=runner)

    message = client.get_email_message("msg-1")

    assert runner.calls == [
        (
            ["gog", "gmail", "messages", "get", "msg-1", "--format", "json"],
            None,
        )
    ]
    assert message == EmailMessage(
        id="msg-1",
        thread_id="thread-1",
        subject="Project update",
        sender="Alex Sender <alex@example.com>",
        to=("Hermes User <me@example.com>",),
        cc=("Ops <ops@example.com>",),
        sent_at=datetime(2026, 5, 18, 10, 15, tzinfo=UTC),
        snippet="Quick project update",
        body_text="Plain text body",
        is_unread=True,
        message_id="<source-message@example.com>",
        references=("<previous-message@example.com>", "<source-message@example.com>"),
    )


def test_send_thread_reply_invokes_gog_with_structured_json_input():
    runner = FakeCommandRunner([{"id": "sent-msg-1"}])
    client = OpenClawClient(command_runner=runner)

    sent_id = client.send_thread_reply(
        SendEmailReplyRequest(
            thread_id="thread-1",
            to=("alex@example.com",),
            cc=("ops@example.com",),
            bcc=("audit@example.com",),
            subject="Project update",
            body_text="Tomorrow works for me.",
            in_reply_to="<source-message@example.com>",
            references=("<previous-message@example.com>", "<source-message@example.com>"),
        )
    )

    assert sent_id == "sent-msg-1"
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == [
        "gog",
        "gmail",
        "messages",
        "reply",
        "--format",
        "json",
    ]
    assert runner.calls[0][1] is not None
    assert json.loads(runner.calls[0][1]) == {
        "thread_id": "thread-1",
        "to": ["alex@example.com"],
        "cc": ["ops@example.com"],
        "bcc": ["audit@example.com"],
        "subject": "Project update",
        "body_text": "Tomorrow works for me.",
        "in_reply_to": "<source-message@example.com>",
        "references": ["<previous-message@example.com>", "<source-message@example.com>"],
    }


def test_mark_email_read_invokes_gog_command():
    runner = FakeCommandRunner([{"ok": True}])
    client = OpenClawClient(command_runner=runner)

    assert client.mark_email_read("msg-1") is None
    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "messages",
                "mark-read",
                "msg-1",
                "--format",
                "json",
            ],
            None,
        )
    ]


def test_list_calendar_events_invokes_gog_and_maps_events():
    runner = FakeCommandRunner(
        [
            {
                "events": [
                    {
                        "id": "event-1",
                        "title": "Planning",
                        "start_at": "2026-05-19T09:00:00+08:00",
                        "end_at": "2026-05-19T10:00:00+08:00",
                        "all_day": False,
                        "timezone": "Asia/Manila",
                        "location": "Meet",
                        "description": "Sprint planning",
                        "html_link": "https://calendar.google.com/event",
                        "attendees": [
                            {
                                "display_name": "Alex",
                                "email": "alex@example.com",
                                "response_status": "accepted",
                            }
                        ],
                    },
                    {
                        "id": "event-2",
                        "summary": "All day focus",
                        "start": {"date": "2026-05-19"},
                        "end": {"date": "2026-05-20"},
                    },
                ]
            }
        ]
    )
    client = OpenClawClient(command_runner=runner)

    events = client.list_calendar_events(
        datetime(2026, 5, 19, tzinfo=UTC),
        datetime(2026, 5, 20, tzinfo=UTC),
    )

    assert runner.calls == [
        (
            [
                "gog",
                "calendar",
                "events",
                "list",
                "--format",
                "json",
                "--start",
                "2026-05-19T00:00:00+00:00",
                "--end",
                "2026-05-20T00:00:00+00:00",
            ],
            None,
        )
    ]
    assert events == [
        CalendarEvent(
            id="event-1",
            title="Planning",
            start_at=datetime.fromisoformat("2026-05-19T09:00:00+08:00"),
            end_at=datetime.fromisoformat("2026-05-19T10:00:00+08:00"),
            all_day=False,
            timezone="Asia/Manila",
            location="Meet",
            description="Sprint planning",
            html_link="https://calendar.google.com/event",
            attendees=(("Alex", "alex@example.com", "accepted"),),
        ),
        CalendarEvent(
            id="event-2",
            title="All day focus",
            start_at=datetime.fromisoformat("2026-05-19T00:00:00+00:00"),
            end_at=datetime.fromisoformat("2026-05-20T00:00:00+00:00"),
            all_day=True,
            timezone=None,
            location=None,
            description=None,
            html_link=None,
            attendees=(),
        ),
    ]
