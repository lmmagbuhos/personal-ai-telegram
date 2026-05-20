from datetime import UTC, datetime
from typing import Any

from personal_hermes.openclaw.client import OpenClawClient
from personal_hermes.openclaw.types import (
    CalendarEvent,
    EmailMessage,
    GmailDraft,
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

    messages = client.list_new_inbox_messages(since_cursor="after:2026/05/18")

    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "messages",
                "search",
                "in:inbox after:2026/05/18",
                "--json",
                "--max",
                "25",
                "--include-body",
                "--body-format",
                "text",
                "--no-input",
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
            [
                "gog",
                "gmail",
                "get",
                "msg-1",
                "--format",
                "full",
                "--sanitize-content",
                "--json",
                "--no-input",
            ],
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
        "send",
        "--thread-id",
        "thread-1",
        "--to",
        "alex@example.com",
        "--subject",
        "Project update",
        "--body-file",
        "-",
        "--json",
        "--no-input",
        "--cc",
        "ops@example.com",
        "--bcc",
        "audit@example.com",
        "--reply-to-message-id",
        "<source-message@example.com>",
    ]
    assert runner.calls[0][1] == "Tomorrow works for me."


def test_mark_email_read_invokes_gog_command():
    runner = FakeCommandRunner([{"ok": True}])
    client = OpenClawClient(command_runner=runner)

    assert client.mark_email_read("msg-1") is None
    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "mark-read",
                "msg-1",
                "--json",
                "--no-input",
            ],
            None,
        )
    ]


def test_search_email_messages_invokes_gog_with_body_options():
    runner = FakeCommandRunner([{"messages": [{"id": "msg-1", "subject": "Invoice"}]}])
    client = OpenClawClient(command_runner=runner)

    messages = client.search_email_messages("from:alex invoice", max_results=7)

    assert [message.id for message in messages] == ["msg-1"]
    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "messages",
                "search",
                "from:alex invoice",
                "--json",
                "--max",
                "7",
                "--include-body",
                "--body-format",
                "text",
                "--no-input",
            ],
            None,
        )
    ]


def test_gmail_message_action_wrappers_invoke_gog_commands():
    runner = FakeCommandRunner([{"ok": True}, {"ok": True}, {"ok": True}, {"ok": True}])
    client = OpenClawClient(command_runner=runner)

    assert client.archive_email("msg-1") is None
    assert client.mark_email_unread("msg-2") is None
    assert client.trash_email("msg-3") is None
    assert client.modify_email_labels("msg-4", add=("STARRED", "Work"), remove=("UNREAD",)) is None

    assert runner.calls == [
        (["gog", "gmail", "archive", "msg-1", "--json", "--no-input"], None),
        (["gog", "gmail", "unread", "msg-2", "--json", "--no-input"], None),
        (["gog", "gmail", "trash", "msg-3", "--json", "--no-input", "-y"], None),
        (
            [
                "gog",
                "gmail",
                "messages",
                "modify",
                "msg-4",
                "--add",
                "STARRED,Work",
                "--remove",
                "UNREAD",
                "--json",
                "--no-input",
            ],
            None,
        ),
    ]


def test_create_email_draft_invokes_gog_and_maps_enveloped_draft():
    runner = FakeCommandRunner(
        [
            {
                "draft": {
                    "id": "draft-1",
                    "message": {"id": "msg-1", "threadId": "thread-1"},
                    "to": ["alex@example.com"],
                    "cc": ["ops@example.com"],
                    "bcc": [],
                    "subject": "Hello",
                    "body_text": "Body",
                }
            }
        ]
    )
    client = OpenClawClient(command_runner=runner)

    draft = client.create_email_draft(
        to=("alex@example.com",),
        cc=("ops@example.com",),
        subject="Hello",
        body_text="Body",
    )

    assert draft == GmailDraft(
        id="draft-1",
        message_id="msg-1",
        thread_id="thread-1",
        to=("alex@example.com",),
        cc=("ops@example.com",),
        bcc=(),
        subject="Hello",
        body_text="Body",
    )
    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "drafts",
                "create",
                "--to",
                "alex@example.com",
                "--subject",
                "Hello",
                "--body-file",
                "-",
                "--json",
                "--no-input",
                "--cc",
                "ops@example.com",
            ],
            "Body",
        )
    ]


def test_update_send_and_delete_email_draft_invoke_gog_commands():
    runner = FakeCommandRunner(
        [
            {"id": "draft-1", "message_id": "msg-2", "thread_id": "thread-1", "subject": "New"},
            {"id": "sent-msg-1"},
            {"ok": True},
        ]
    )
    client = OpenClawClient(command_runner=runner)

    draft = client.update_email_draft("draft-1", subject="New", body_text="Updated")
    sent_id = client.send_email_draft("draft-1")
    assert client.delete_email_draft("draft-1") is None

    assert draft.subject == "New"
    assert sent_id == "sent-msg-1"
    assert runner.calls == [
        (
            [
                "gog",
                "gmail",
                "drafts",
                "update",
                "draft-1",
                "--body-file",
                "-",
                "--json",
                "--no-input",
                "--subject",
                "New",
            ],
            "Updated",
        ),
        (["gog", "gmail", "drafts", "send", "draft-1", "--json", "--no-input"], None),
        (["gog", "gmail", "drafts", "delete", "draft-1", "--json", "--no-input", "-y"], None),
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
                "primary",
                "--from",
                "2026-05-19T00:00:00+00:00",
                "--to",
                "2026-05-20T00:00:00+00:00",
                "--json",
                "--all-pages",
                "--no-input",
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


def test_with_access_token_includes_access_token_flag():
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
                    }
                ]
            }
        ]
    )
    client = OpenClawClient(command_runner=runner)
    authed_client = client.with_access_token("secret-token")

    authed_client.list_calendar_events(
        datetime(2026, 5, 19, tzinfo=UTC),
        datetime(2026, 5, 20, tzinfo=UTC),
    )

    assert runner.calls == [
        (
            [
                "gog",
                "--access-token",
                "secret-token",
                "calendar",
                "events",
                "primary",
                "--from",
                "2026-05-19T00:00:00+00:00",
                "--to",
                "2026-05-20T00:00:00+00:00",
                "--json",
                "--all-pages",
                "--no-input",
            ],
            None,
        )
    ]
