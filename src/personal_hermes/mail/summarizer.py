import re
from email.utils import parseaddr

from personal_hermes.openclaw.types import EmailMessage

NON_REPLY_SUBJECT_MARKERS = (
    "newsletter",
    "receipt",
    "invoice",
    "automated alert",
    "alert",
    "notification",
)
REPLY_MARKERS = (
    "?",
    "please ",
    "can you",
    "could you",
    "would you",
    "are you available",
    "available",
    "confirm",
    "let me know",
    "review",
    "schedule",
    "meeting",
    "meet",
)


def summarize_email(message: EmailMessage, *, max_length: int = 180) -> str:
    body = _compact_text(message.body_text or message.snippet)
    summary = f"{message.sender} sent '{message.subject}': {body}"
    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 3].rstrip() + "..."


def is_reply_worthy(message: EmailMessage) -> bool:
    sender = message.sender.lower()
    subject = message.subject.lower()
    body = message.body_text.lower()

    if "no-reply" in sender or "noreply" in sender:
        return False
    if any(marker in subject for marker in NON_REPLY_SUBJECT_MARKERS):
        return False
    return any(marker in body or marker in subject for marker in REPLY_MARKERS)


def generate_suggested_reply(message: EmailMessage) -> str | None:
    if not is_reply_worthy(message):
        return None
    name, _address = parseaddr(message.sender)
    first_name = (name or "there").split()[0].strip(",")
    return (
        f"Hi {first_name}, thanks for reaching out. "
        "I will review this and get back to you."
    )


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
