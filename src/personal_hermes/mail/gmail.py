from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import getaddresses
from typing import Any, Protocol

from personal_hermes.openclaw.types import EmailMessage, GmailDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class GmailClient(Protocol):
    def search_email_messages(self, query: str, *, max_results: int = 10) -> list[EmailMessage]: ...
    def get_email_message(self, email_id: str) -> EmailMessage: ...
    def mark_email_read(self, email_id: str) -> None: ...
    def mark_email_unread(self, email_id: str) -> None: ...
    def archive_email(self, email_id: str) -> None: ...
    def trash_email(self, email_id: str) -> None: ...
    def modify_email_labels(self, email_id: str, *, add: tuple[str, ...] = (), remove: tuple[str, ...] = ()) -> None: ...
    def create_email_draft(self, *, to: tuple[str, ...], subject: str, body_text: str, cc: tuple[str, ...] = (), bcc: tuple[str, ...] = ()) -> GmailDraft: ...
    def update_email_draft(self, draft_id: str, *, to: tuple[str, ...] | None = None, subject: str | None = None, body_text: str | None = None, cc: tuple[str, ...] | None = None, bcc: tuple[str, ...] | None = None) -> GmailDraft: ...
    def send_email_draft(self, draft_id: str) -> str: ...
    def delete_email_draft(self, draft_id: str) -> None: ...


class GmailTelegram(Protocol):
    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int: ...
    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None: ...
    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None: ...


class GmailServiceBase:
    def __init__(
        self,
        *,
        openclaw_client: GmailClient,
        telegram: GmailTelegram,
        store: StateStore | None,
        resolve_access_token=None,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.resolve_access_token = resolve_access_token

    def _client_for_user(self, user_id: int | None, *, now: datetime):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        try:
            access_token = self.resolve_access_token(user_id, now=now)
        except TypeError:
            access_token = self.resolve_access_token(user_id)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)

    def _state(self, chat_id: int, user_id: int | None):
        if self.store is None:
            return None
        return self.store.get_conversation_state(chat_id, user_id=user_id)

    def _save_state(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        state: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> bool:
        if self.store is None:
            return False
        self.store.set_conversation_state(
            user_id=user_id,
            telegram_chat_id=chat_id,
            state=state,
            payload=payload,
            updated_at=now,
        )
        saved = self.store.get_conversation_state(chat_id, user_id=user_id)
        return saved is not None and saved.state == state

    def _clear_state(self, chat_id: int, user_id: int | None) -> None:
        if self.store is not None:
            self.store.clear_conversation_state(chat_id, user_id=user_id)


class GmailReadService(GmailServiceBase):
    def start_search(
        self,
        message: TelegramMessage,
        *,
        user_id: int | None,
        now: datetime,
    ) -> bool:
        query = _query_from_text(message.text)
        if query is None:
            return False
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.send_message(chat_id=message.chat_id, text="Connect Google first with /connect.")
            return True
        try:
            messages = client.search_email_messages(query, max_results=10)
        except Exception:
            self.telegram.send_message(chat_id=message.chat_id, text="Couldn't read Gmail right now.")
            return True
        if not messages:
            self._clear_state(message.chat_id, user_id)
            self.telegram.send_message(chat_id=message.chat_id, text="No matching emails found.")
            return True

        candidates = [_message_payload(item) for item in messages]
        if not self._save_state(
            chat_id=message.chat_id,
            user_id=user_id,
            state="gmail_search_results",
            payload={"query": query, "candidates": candidates},
            now=now,
        ):
            self.telegram.send_message(
                chat_id=message.chat_id,
                text="Couldn't start that Gmail action right now. Try again.",
            )
            return True
        self.telegram.send_message(
            chat_id=message.chat_id,
            text="Matching emails",
            buttons=[
                [((item["subject"] or item["sender"] or item["id"])[:64], f"mail_pick:{idx}")]
                for idx, item in enumerate(candidates)
            ],
        )
        return True

    def handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None,
        now: datetime,
    ) -> None:
        _action, _sep, value = callback.data.partition(":")
        state = self._state(callback.chat_id, user_id)
        if state is None or state.state != "gmail_search_results":
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="That selection expired - start again.")
            return
        candidates = state.payload.get("candidates", [])
        try:
            candidate = candidates[int(value)]
        except (ValueError, IndexError, TypeError):
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="That selection expired - start again.")
            return
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        try:
            message = client.get_email_message(str(candidate["id"]))
        except Exception:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Couldn't read Gmail right now.")
            return
        payload = _message_payload(message) | {"body_text": message.body_text}
        if not self._save_state(
            chat_id=callback.chat_id,
            user_id=user_id,
            state="gmail_selected_message",
            payload={"message": payload},
            now=now,
        ):
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Couldn't start that Gmail action right now. Try again.")
            return
        self.telegram.send_message(
            chat_id=callback.chat_id,
            text=_format_message_detail(message),
            buttons=_selected_message_buttons(message),
        )
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Opened")


class GmailMessageActionService(GmailServiceBase):
    def handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None,
        now: datetime,
    ) -> None:
        action = callback.data.partition(":")[0]
        if action == "mail_pick":
            GmailReadService(
                openclaw_client=self.openclaw_client,
                telegram=self.telegram,
                store=self.store,
                resolve_access_token=self.resolve_access_token,
            ).handle_callback(callback, user_id=user_id, now=now)
            return

        state = self._state(callback.chat_id, user_id)
        if state is None or state.state != "gmail_selected_message":
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="That selection expired - start again.")
            return
        message = state.payload.get("message", {})
        email_id = str(message.get("id", ""))
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return

        try:
            if action == "mail_read":
                client.mark_email_read(email_id)
                answer = "Marked read"
            elif action == "mail_unread":
                client.mark_email_unread(email_id)
                answer = "Marked unread"
            elif action == "mail_archive":
                client.archive_email(email_id)
                answer = "Archived"
            elif action == "mail_star":
                client.modify_email_labels(email_id, add=("STARRED",))
                answer = "Starred"
            elif action == "mail_unstar":
                client.modify_email_labels(email_id, remove=("STARRED",))
                answer = "Unstarred"
            elif action == "mail_trash":
                self.telegram.send_message(
                    chat_id=callback.chat_id,
                    text="Move this email to trash?",
                    buttons=[[("Trash", "mail_trash_ok"), ("Cancel", "mail_trash_no")]],
                )
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Confirm trash")
                return
            elif action == "mail_trash_ok":
                client.trash_email(email_id)
                self._clear_state(callback.chat_id, user_id)
                answer = "Trashed"
            elif action == "mail_trash_no":
                answer = "Cancelled"
            elif action in ("mail_label_add", "mail_label_remove"):
                suffix = "add" if action.endswith("add") else "remove"
                self._save_state(
                    chat_id=callback.chat_id,
                    user_id=user_id,
                    state=f"gmail_label_value_{suffix}",
                    payload=state.payload,
                    now=now,
                )
                self.telegram.send_message(chat_id=callback.chat_id, text="Type the label name.")
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Label")
                return
            else:
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unsupported action")
                return
        except Exception:
            failure = "Couldn't trash that email right now." if action.startswith("mail_trash") else "Couldn't update that email right now."
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text=failure)
            return

        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text=answer)

    def handle_value(
        self,
        message: TelegramMessage,
        *,
        user_id: int | None,
        now: datetime,
    ) -> bool:
        state = self._state(message.chat_id, user_id)
        if state is None or state.state not in ("gmail_label_value_add", "gmail_label_value_remove"):
            return False
        selected = state.payload.get("message", {})
        email_id = str(selected.get("id", ""))
        label = message.text.strip()
        if not label:
            self.telegram.send_message(chat_id=message.chat_id, text="Type the label name.")
            return True
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.send_message(chat_id=message.chat_id, text="Connect Google first with /connect.")
            return True
        try:
            if state.state.endswith("_add"):
                client.modify_email_labels(email_id, add=(label,))
            else:
                client.modify_email_labels(email_id, remove=(label,))
        except Exception:
            self.telegram.send_message(chat_id=message.chat_id, text="Couldn't update that email right now.")
            return True
        self._save_state(
            chat_id=message.chat_id,
            user_id=user_id,
            state="gmail_selected_message",
            payload=state.payload,
            now=now,
        )
        self.telegram.send_message(chat_id=message.chat_id, text="Email updated.")
        return True


class GmailDraftService(GmailServiceBase):
    def start_compose(
        self,
        message: TelegramMessage,
        *,
        user_id: int | None,
        now: datetime,
    ) -> bool:
        draft = _parse_compose_text(message.text)
        if draft is None:
            return False
        return self._advance_compose(message.chat_id, user_id=user_id, draft=draft, now=now)

    def handle_value(
        self,
        message: TelegramMessage,
        *,
        user_id: int | None,
        now: datetime,
    ) -> bool:
        state = self._state(message.chat_id, user_id)
        if state is None:
            return False
        payload = dict(state.payload)
        if state.state == "gmail_compose_collect_to":
            recipients = _parse_recipients(message.text)
            if not recipients:
                self.telegram.send_message(chat_id=message.chat_id, text="Send me a recipient like name@example.com.")
                return True
            payload["to"] = list(recipients)
            return self._advance_compose(message.chat_id, user_id=user_id, draft=payload, now=now)
        if state.state == "gmail_compose_collect_subject":
            payload["subject"] = message.text.strip()
            return self._advance_compose(message.chat_id, user_id=user_id, draft=payload, now=now)
        if state.state == "gmail_compose_collect_body":
            payload["body_text"] = message.text
            return self._advance_compose(message.chat_id, user_id=user_id, draft=payload, now=now)
        if state.state != "gmail_draft_edit_value":
            return False
        field = str(payload.get("field", ""))
        preview = dict(payload.get("draft", {}))
        return self._update_draft_field(
            message.chat_id,
            user_id=user_id,
            preview=preview,
            field=field,
            value=message.text,
            now=now,
        )

    def handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None,
        now: datetime,
    ) -> None:
        state = self._state(callback.chat_id, user_id)
        if state is None or state.state not in ("gmail_draft_preview", "gmail_draft_edit_field"):
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="That draft expired - start again.")
            return
        preview = dict(state.payload.get("draft", state.payload))
        draft_id = str(preview.get("id", ""))
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        action = callback.data.partition(":")[0]
        try:
            if action == "draft_send":
                client.send_email_draft(draft_id)
                self._clear_state(callback.chat_id, user_id)
                self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Draft sent.")
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Sent")
                return
            if action == "draft_discard":
                self.telegram.send_message(
                    chat_id=callback.chat_id,
                    text="Discard this draft?",
                    buttons=[[("Discard", "draft_discard_ok"), ("Cancel", "draft_discard_no")]],
                )
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Confirm discard")
                return
            if action == "draft_discard_ok":
                client.delete_email_draft(draft_id)
                self._clear_state(callback.chat_id, user_id)
                self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Draft discarded.")
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Discarded")
                return
            if action == "draft_discard_no":
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")
                return
            if action == "draft_edit":
                self._save_state(
                    chat_id=callback.chat_id,
                    user_id=user_id,
                    state="gmail_draft_edit_field",
                    payload={"draft": preview},
                    now=now,
                )
                self.telegram.send_message(
                    chat_id=callback.chat_id,
                    text="Choose a field to edit.",
                    buttons=[[("To", "draft_edit_to"), ("Subject", "draft_edit_subject"), ("Body", "draft_edit_body")]],
                )
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Edit")
                return
            if action.startswith("draft_edit_"):
                field = action.removeprefix("draft_edit_")
                self._save_state(
                    chat_id=callback.chat_id,
                    user_id=user_id,
                    state="gmail_draft_edit_value",
                    payload={"draft": preview, "field": field},
                    now=now,
                )
                self.telegram.send_message(chat_id=callback.chat_id, text=f"Type the new {field}.")
                self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Edit")
                return
        except Exception:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Couldn't update that draft right now.")
            return
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unsupported action")

    def _advance_compose(
        self,
        chat_id: int,
        *,
        user_id: int | None,
        draft: dict[str, Any],
        now: datetime,
    ) -> bool:
        if not draft.get("to"):
            self._save_state(chat_id=chat_id, user_id=user_id, state="gmail_compose_collect_to", payload=draft, now=now)
            self.telegram.send_message(chat_id=chat_id, text="Who should I send it to?")
            return True
        if not draft.get("subject"):
            self._save_state(chat_id=chat_id, user_id=user_id, state="gmail_compose_collect_subject", payload=draft, now=now)
            self.telegram.send_message(chat_id=chat_id, text="What subject should I use?")
            return True
        if not draft.get("body_text"):
            self._save_state(chat_id=chat_id, user_id=user_id, state="gmail_compose_collect_body", payload=draft, now=now)
            self.telegram.send_message(chat_id=chat_id, text="What should the email say?")
            return True
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.send_message(chat_id=chat_id, text="Connect Google first with /connect.")
            return True
        try:
            created = client.create_email_draft(
                to=tuple(draft["to"]),
                subject=str(draft["subject"]),
                body_text=str(draft["body_text"]),
            )
        except Exception:
            self.telegram.send_message(chat_id=chat_id, text="Couldn't create that draft right now.")
            return True
        self._show_preview(chat_id, user_id=user_id, draft=created, now=now)
        return True

    def _update_draft_field(
        self,
        chat_id: int,
        *,
        user_id: int | None,
        preview: dict[str, Any],
        field: str,
        value: str,
        now: datetime,
    ) -> bool:
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.send_message(chat_id=chat_id, text="Connect Google first with /connect.")
            return True
        fields: dict[str, Any]
        if field == "to":
            recipients = _parse_recipients(value)
            if not recipients:
                self.telegram.send_message(chat_id=chat_id, text="Send me a recipient like name@example.com.")
                return True
            fields = {"to": recipients}
        elif field == "subject":
            fields = {"subject": value.strip()}
        elif field == "body":
            fields = {"body_text": value}
        else:
            return False
        try:
            updated = client.update_email_draft(str(preview["id"]), **fields)
        except Exception:
            self.telegram.send_message(chat_id=chat_id, text="Couldn't update that draft right now.")
            return True
        self._show_preview(chat_id, user_id=user_id, draft=updated, now=now)
        return True

    def _show_preview(
        self,
        chat_id: int,
        *,
        user_id: int | None,
        draft: GmailDraft,
        now: datetime,
    ) -> None:
        payload = {"draft": _draft_payload(draft)}
        if not self._save_state(
            chat_id=chat_id,
            user_id=user_id,
            state="gmail_draft_preview",
            payload=payload,
            now=now,
        ):
            self.telegram.send_message(chat_id=chat_id, text="Couldn't start that Gmail action right now. Try again.")
            return
        self.telegram.send_message(
            chat_id=chat_id,
            text=_format_draft_preview(draft),
            buttons=[[("Send", "draft_send"), ("Edit", "draft_edit"), ("Discard", "draft_discard")]],
        )


def _query_from_text(text: str) -> str | None:
    lowered = text.lower().strip()
    if not any(marker in lowered for marker in ("email", "mail", "inbox")):
        return None
    if "unread" in lowered:
        return "in:inbox is:unread"
    match = re.search(r"\bfrom\s+([^\s]+)", text, flags=re.IGNORECASE)
    if match:
        return f"from:{match.group(1)}"
    for prefix in ("search emails", "search email", "find emails", "find email"):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip() or "in:inbox"
    return "in:inbox"


def _parse_compose_text(text: str) -> dict[str, Any] | None:
    lowered = text.lower().strip()
    if not lowered.startswith(("email ", "compose email", "send email")):
        return None
    draft: dict[str, Any] = {}
    recipients = _parse_recipients(text)
    if recipients:
        draft["to"] = list(recipients)
    subject_match = re.search(r"\bsubject\s+(.+?)(?:\s+body\s+|$)", text, flags=re.IGNORECASE)
    if subject_match:
        draft["subject"] = subject_match.group(1).strip()
    body_match = re.search(r"\bbody\s+(.+)$", text, flags=re.IGNORECASE)
    if body_match:
        draft["body_text"] = body_match.group(1).strip()
    return draft


def _parse_recipients(text: str) -> tuple[str, ...]:
    direct = tuple(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
    if direct:
        return direct
    return tuple(address for _name, address in getaddresses([text]) if address and "@" in address)


def _message_payload(message: EmailMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender": message.sender,
        "subject": message.subject,
        "snippet": message.snippet,
        "sent_at": message.sent_at.astimezone(UTC).isoformat(),
        "is_unread": message.is_unread,
    }


def _draft_payload(draft: GmailDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "message_id": draft.message_id,
        "thread_id": draft.thread_id,
        "to": list(draft.to),
        "cc": list(draft.cc),
        "bcc": list(draft.bcc),
        "subject": draft.subject,
        "body_text": draft.body_text,
    }


def _format_message_detail(message: EmailMessage) -> str:
    body = message.body_text or message.snippet
    if len(body) > 1200:
        body = body[:1197] + "..."
    return "\n".join(
        [
            f"From: {message.sender}",
            f"Subject: {message.subject}",
            "",
            body,
        ]
    )


def _selected_message_buttons(message: EmailMessage):
    read_button = ("Mark read", "mail_read") if message.is_unread else ("Mark unread", "mail_unread")
    star_button = ("Star", "mail_star")
    return [
        [read_button, ("Archive", "mail_archive"), ("Trash", "mail_trash")],
        [star_button, ("Unstar", "mail_unstar")],
        [("Add label", "mail_label_add"), ("Remove label", "mail_label_remove")],
    ]


def _format_draft_preview(draft: GmailDraft) -> str:
    return "\n".join(
        [
            "Draft ready",
            f"To: {', '.join(draft.to)}",
            f"Subject: {draft.subject}",
            "",
            draft.body_text,
        ]
    )
