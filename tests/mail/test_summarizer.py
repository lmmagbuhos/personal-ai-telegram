from datetime import datetime

from personal_hermes.mail.summarizer import (
    generate_suggested_reply,
    is_reply_worthy,
    summarize_email,
)
from personal_hermes.openclaw.types import EmailMessage


def email(
    *,
    sender: str = "Alex <alex@example.com>",
    subject: str = "Meeting",
    body_text: str = "Can we meet tomorrow?",
) -> EmailMessage:
    return EmailMessage(
        id="msg-1",
        thread_id="thread-1",
        subject=subject,
        sender=sender,
        to=("me@example.com",),
        cc=(),
        sent_at=datetime.fromisoformat("2026-05-19T08:00:00+00:00"),
        snippet=body_text[:80],
        body_text=body_text,
        is_unread=True,
    )


def test_summarize_email_uses_sender_subject_and_compact_body():
    summary = summarize_email(
        email(
            sender="Alex <alex@example.com>",
            subject="Project update",
            body_text="Hello,\n\nCan we meet tomorrow to discuss the project timeline?\nThanks.",
        )
    )

    assert summary == (
        "Alex <alex@example.com> sent 'Project update': "
        "Hello, Can we meet tomorrow to discuss the project timeline? Thanks."
    )


def test_summary_is_truncated():
    summary = summarize_email(email(body_text="A" * 240))

    assert summary.endswith("...")
    assert len(summary) <= 180


def test_reply_worthy_detects_questions_requests_and_scheduling():
    assert is_reply_worthy(email(body_text="Can you confirm this works?")) is True
    assert is_reply_worthy(email(body_text="Please review the attached file.")) is True
    assert is_reply_worthy(email(body_text="Are you available tomorrow?")) is True
    assert is_reply_worthy(email(body_text="Let me know if this is okay.")) is True


def test_reply_worthy_rejects_newsletters_receipts_alerts_and_no_reply_senders():
    assert is_reply_worthy(email(sender="no-reply@example.com", body_text="Can you read this?")) is False
    assert is_reply_worthy(email(subject="Newsletter: Weekly updates", body_text="Can you read this?")) is False
    assert is_reply_worthy(email(subject="Receipt for your payment", body_text="Please keep this.")) is False
    assert is_reply_worthy(email(subject="Automated alert", body_text="Please check logs.")) is False


def test_generate_suggested_reply_returns_conservative_reply_for_reply_worthy_email():
    reply = generate_suggested_reply(
        email(sender="Alex <alex@example.com>", body_text="Can we meet tomorrow?")
    )

    assert reply == "Hi Alex, thanks for reaching out. I will review this and get back to you."


def test_generate_suggested_reply_returns_none_for_non_reply_worthy_email():
    assert generate_suggested_reply(email(subject="Newsletter", body_text="Weekly update")) is None

