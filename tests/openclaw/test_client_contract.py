import json
from datetime import UTC, datetime
from email import message_from_string

import httpx

from personal_hermes.openclaw.client import OpenClawClient
from personal_hermes.openclaw.types import (
    CalendarEvent,
    EmailMessage,
    SendEmailReplyRequest,
)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return OpenClawClient(access_token="test-token", http_client=http_client)


def test_list_new_inbox_messages_fetches_full_gmail_messages_and_maps_internal_type():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == "/gmail/v1/users/me/messages":
            assert request.headers["authorization"] == "Bearer test-token"
            assert request.url.params["q"] == "in:inbox is:unread after:2026/05/18"
            assert request.url.params["maxResults"] == "25"
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "msg-1", "threadId": "thread-1"},
                    ]
                },
            )

        if request.url.path == "/gmail/v1/users/me/messages/msg-1":
            assert request.url.params["format"] == "full"
            return httpx.Response(200, json=gmail_message_payload())

        return httpx.Response(404)

    client = make_client(handler)

    messages = client.list_new_inbox_messages(since_cursor="2026/05/18")

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
    assert [request.url.path for request in requests] == [
        "/gmail/v1/users/me/messages",
        "/gmail/v1/users/me/messages/msg-1",
    ]


def test_get_email_message_maps_nested_plain_text_part():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/gmail/v1/users/me/messages/msg-1"
        assert request.url.params["format"] == "full"
        return httpx.Response(200, json=gmail_message_payload())

    client = make_client(handler)

    message = client.get_email_message("msg-1")

    assert message.id == "msg-1"
    assert message.thread_id == "thread-1"
    assert message.subject == "Project update"
    assert message.body_text == "Hello Hermes,\nCan we meet tomorrow?\n"
    assert message.is_unread is True


def test_send_thread_reply_request_contains_thread_and_reply_headers():
    observed_json = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_json
        assert request.method == "POST"
        assert request.url.path == "/gmail/v1/users/me/messages/send"
        observed_json = json.loads(request.content)
        return httpx.Response(200, json={"id": "sent-msg-1", "threadId": "thread-1"})

    client = make_client(handler)

    client.send_thread_reply(
        SendEmailReplyRequest(
            thread_id="thread-1",
            to=("alex@example.com",),
            subject="Project update",
            body_text="Tomorrow works for me.",
            in_reply_to="<source-message@example.com>",
            references=("<previous-message@example.com>", "<source-message@example.com>"),
        )
    )

    assert observed_json is not None
    assert observed_json["threadId"] == "thread-1"
    decoded = OpenClawClient.decode_gmail_raw_message(observed_json["raw"])
    email_message = message_from_string(decoded)
    assert email_message["To"] == "alex@example.com"
    assert email_message["Subject"] == "Re: Project update"
    assert email_message["In-Reply-To"] == "<source-message@example.com>"
    assert (
        email_message["References"]
        == "<previous-message@example.com> <source-message@example.com>"
    )
    assert email_message.get_payload().strip() == "Tomorrow works for me."


def test_mark_email_read_removes_unread_label():
    observed_json = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_json
        assert request.method == "POST"
        assert request.url.path == "/gmail/v1/users/me/messages/msg-1/modify"
        observed_json = json.loads(request.content)
        return httpx.Response(200, json={"id": "msg-1"})

    client = make_client(handler)

    assert client.mark_email_read("msg-1") is None
    assert observed_json == {"removeLabelIds": ["UNREAD"]}


def test_list_calendar_events_maps_google_event_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/calendar/v3/calendars/primary/events"
        assert request.url.params["singleEvents"] == "true"
        assert request.url.params["orderBy"] == "startTime"
        assert request.url.params["timeMin"] == "2026-05-19T00:00:00+00:00"
        assert request.url.params["timeMax"] == "2026-05-20T00:00:00+00:00"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "event-1",
                        "summary": "Planning",
                        "description": "Sprint planning",
                        "location": "Meet",
                        "htmlLink": "https://calendar.google.com/event",
                        "start": {
                            "dateTime": "2026-05-19T09:00:00+08:00",
                            "timeZone": "Asia/Manila",
                        },
                        "end": {
                            "dateTime": "2026-05-19T10:00:00+08:00",
                            "timeZone": "Asia/Manila",
                        },
                        "attendees": [
                            {
                                "email": "alex@example.com",
                                "displayName": "Alex",
                                "responseStatus": "accepted",
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
            },
        )

    client = make_client(handler)

    events = client.list_calendar_events(
        datetime(2026, 5, 19, tzinfo=UTC),
        datetime(2026, 5, 20, tzinfo=UTC),
    )

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


def gmail_message_payload():
    return {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Quick project update",
        "internalDate": "1779099300000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Project update"},
                {"name": "From", "value": "Alex Sender <alex@example.com>"},
                {"name": "To", "value": "Hermes User <me@example.com>"},
                {"name": "Date", "value": "Mon, 18 May 2026 10:15:00 +0000"},
                {"name": "Message-ID", "value": "<source-message@example.com>"},
                {"name": "References", "value": "<previous-message@example.com>"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": "SGVsbG8gSGVybWVzLApDYW4gd2UgbWVldCB0b21vcnJvdz8K"
                            },
                        },
                        {
                            "mimeType": "text/html",
                            "body": {"data": "PHA-SGVsbG88L3A-"},
                        },
                    ],
                }
            ],
        },
    }
