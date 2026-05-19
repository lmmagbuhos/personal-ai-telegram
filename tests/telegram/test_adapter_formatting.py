from datetime import datetime

from personal_hermes.openclaw.types import CalendarEvent, EmailMessage
from personal_hermes.telegram.adapter import (
    email_action_buttons,
    format_availability_answer,
    format_daily_agenda,
    format_email_notification,
    format_event_reminder,
)


def test_email_notification_includes_required_fields_and_suggestion():
    message = EmailMessage(
        id="msg-1",
        thread_id="thread-1",
        subject="Project update",
        sender="Alex <alex@example.com>",
        to=("me@example.com",),
        cc=(),
        sent_at=datetime.fromisoformat("2026-05-19T08:00:00+00:00"),
        snippet="Can we meet tomorrow?",
        body_text="Can we meet tomorrow?",
        is_unread=True,
    )

    text = format_email_notification(
        message,
        summary="Alex is asking to meet tomorrow.",
        suggested_reply="Tomorrow works for me.",
    )

    assert "Alex <alex@example.com>" in text
    assert "Project update" in text
    assert "Alex is asking to meet tomorrow." in text
    assert "Tomorrow works for me." in text


def test_email_action_buttons_include_expected_callback_payloads():
    buttons = email_action_buttons(pending_reply_id=9, email_id="msg-1")

    assert buttons == [
        [("Send reply", "send_reply:9"), ("Edit reply", "edit_reply:9")],
        [("Ignore", "ignore_reply:9"), ("Mark read", "mark_read:msg-1")],
    ]


def test_daily_agenda_formats_events_compactly():
    event = CalendarEvent(
        id="event-1",
        title="Planning",
        start_at=datetime.fromisoformat("2026-05-19T09:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-05-19T10:00:00+08:00"),
        all_day=False,
        timezone="Asia/Manila",
        location="Google Meet",
        html_link="https://calendar.google.com/event",
    )

    text = format_daily_agenda([event])

    assert "Today's agenda" in text
    assert "Planning" in text
    assert "09:00" in text
    assert "10:00" in text
    assert "Google Meet" in text


def test_daily_agenda_handles_empty_day():
    assert "No events" in format_daily_agenda([])


def test_event_reminder_formats_start_time_and_location():
    event = CalendarEvent(
        id="event-1",
        title="Planning",
        start_at=datetime.fromisoformat("2026-05-19T09:00:00+08:00"),
        end_at=datetime.fromisoformat("2026-05-19T10:00:00+08:00"),
        all_day=False,
        timezone="Asia/Manila",
        location="Google Meet",
    )

    text = format_event_reminder(event, lead_minutes=30)

    assert "30 minutes" in text
    assert "Planning" in text
    assert "09:00" in text
    assert "Google Meet" in text


def test_availability_answer_formats_groups():
    text = format_availability_answer(
        fully_available=["Monday"],
        partly_available=["Tuesday"],
        busy=["Wednesday"],
    )

    assert "Fully available" in text
    assert "Monday" in text
    assert "Partly available" in text
    assert "Tuesday" in text
    assert "Busy" in text
    assert "Wednesday" in text

