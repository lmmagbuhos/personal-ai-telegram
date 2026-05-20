from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Protocol

from personal_hermes.calendar.service import AvailabilityResult
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.adapter import format_availability_answer, format_schedule
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class RouterTelegramAdapter(Protocol):
    def is_authorized(self, event: TelegramMessage | TelegramCallback) -> bool:
        ...

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        ...


class RouterCalendarService(Protocol):
    def availability_for(
        self,
        text: str,
        *,
        today,
        user_id: int | None = None,
    ) -> AvailabilityResult:
        ...

    def schedule_for(
        self,
        text: str,
        *,
        today,
        user_id: int | None = None,
    ):
        ...


class RouterMailActionService(Protocol):
    def handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        now: datetime,
    ) -> None:
        ...


class RouterOAuthService(Protocol):
    def authorization_url(self, *, state: str) -> str:
        ...


class AssistantRouter:
    def __init__(
        self,
        *,
        telegram: RouterTelegramAdapter,
        calendar_service: RouterCalendarService,
        mail_action_service: RouterMailActionService,
        store: StateStore | None,
        oauth_service: RouterOAuthService | None = None,
        invite_only: bool = True,
        invited_telegram_user_ids: tuple[int, ...] = (),
        oauth_session_ttl_minutes: int = 15,
        calendar_action_service=None,
        calendar_edit_service=None,
        timezone=None,
    ) -> None:
        self.telegram = telegram
        self.calendar_service = calendar_service
        self.mail_action_service = mail_action_service
        self.store = store
        self.oauth_service = oauth_service
        self.invite_only = invite_only
        self.invited_telegram_user_ids = invited_telegram_user_ids
        self.oauth_session_ttl_minutes = oauth_session_ttl_minutes
        self.calendar_action_service = calendar_action_service
        self.calendar_edit_service = calendar_edit_service
        self.timezone = timezone

    def handle_event(
        self,
        event: TelegramMessage | TelegramCallback,
        *,
        now: datetime,
    ) -> None:
        if self.oauth_service is None:
            if not self.telegram.is_authorized(event):
                return

            if isinstance(event, TelegramCallback):
                self._handle_callback(event, now=now)
                return

            if self._handle_edit_flow_message(event, now=now):
                return

            if self._handle_calendar_edit_value(event, user_id=None, now=now):
                return

            if self._handle_cancel_event(event, user_id=None, now=now):
                return

            if self._handle_edit_intent(event, user_id=None, now=now):
                return

            if self._handle_create_event(event, user_id=None, now=now):
                return

            if _looks_like_availability_question(event.text):
                schedules = self.calendar_service.schedule_for(
                    event.text, today=now.date(), user_id=None
                )
                self.telegram.send_message(
                    chat_id=event.chat_id,
                    text=format_schedule(schedules, timezone=self.calendar_service.timezone),
                )
                return

            self.telegram.send_message(
                chat_id=event.chat_id,
                text=(
                    "I can help with calendar availability and email reply actions. "
                    "Try asking: What dates am I available this week?"
                ),
            )
            return

        # Multi-user mode
        if isinstance(event, TelegramMessage) and self._handle_command(event, now=now):
            return

        user = self._resolve_user(event)
        if user is None or user.status != "active":
            if isinstance(event, TelegramMessage):
                self.telegram.send_message(
                    chat_id=event.chat_id,
                    text="Connect Google first with /connect.",
                )
            return

        if isinstance(event, TelegramCallback):
            self._handle_callback(event, user_id=user.id, now=now)
            return

        if self._handle_edit_flow_message(event, user_id=user.id, now=now):
            return

        if self._handle_calendar_edit_value(event, user_id=user.id, now=now):
            return

        if self._handle_cancel_event(event, user_id=user.id, now=now):
            return

        if self._handle_edit_intent(event, user_id=user.id, now=now):
            return

        if self._handle_create_event(event, user_id=user.id, now=now):
            return

        if _looks_like_availability_question(event.text):
            schedules = self.calendar_service.schedule_for(
                event.text, today=now.date(), user_id=user.id
            )
            self.telegram.send_message(
                chat_id=event.chat_id,
                text=format_schedule(schedules, timezone=self.calendar_service.timezone),
            )
            return

        self.telegram.send_message(
            chat_id=event.chat_id,
            text=(
                "I can help with calendar availability and email reply actions. "
                "Try asking: What dates am I available this week?"
            ),
        )

    def _handle_command(self, event: TelegramMessage, *, now: datetime) -> bool:
        if not event.text.startswith("/"):
            return False

        if event.text == "/connect":
            self._handle_connect(event, now=now)
            return True
        if event.text == "/status":
            self._handle_status(event)
            return True
        if event.text == "/disconnect":
            self._handle_disconnect(event, now=now)
            return True
        return False

    def _handle_connect(self, event: TelegramMessage, *, now: datetime) -> None:
        if self.store is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google connect is unavailable right now.",
            )
            return

        if self.invite_only and self.invited_telegram_user_ids:
            if event.user_id not in self.invited_telegram_user_ids:
                self.telegram.send_message(
                    chat_id=event.chat_id,
                    text="This bot is invite-only. Ask an admin to add you.",
                )
                return

        if self.oauth_service is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google OAuth is not configured.",
            )
            return

        user = self.store.upsert_user_from_telegram(
            telegram_user_id=event.user_id,
            telegram_chat_id=event.chat_id,
            display_name=None,
            username=None,
            now=now,
        )
        state = token_urlsafe(32)
        expires_at = now + timedelta(minutes=self.oauth_session_ttl_minutes)
        self.store.create_oauth_session(
            state=state,
            telegram_user_id=user.telegram_user_id,
            telegram_chat_id=user.telegram_chat_id,
            expires_at=expires_at,
            created_at=now,
        )
        self.telegram.send_message(
            chat_id=event.chat_id,
            text=(
                "Connect your Google account using this link:\n"
                f"{self.oauth_service.authorization_url(state=state)}"
            ),
        )

    def _handle_status(self, event: TelegramMessage) -> None:
        if self.store is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google status is unavailable right now.",
            )
            return

        user = self.store.get_user_by_telegram(
            telegram_user_id=event.user_id,
            telegram_chat_id=event.chat_id,
        )
        if user is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="No Telegram user record yet. Send /connect.",
            )
            return

        account = self.store.get_google_account(user.id)
        if account is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google is not connected. Send /connect.",
            )
            return

        if account.status == "active":
            self.telegram.send_message(
                chat_id=event.chat_id,
                text=f"Connected to Google as {account.google_email}.",
            )
            return

        if account.status == "reauth_required":
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google account needs reconnect. Send /connect.",
            )
            return

        self.telegram.send_message(
            chat_id=event.chat_id,
            text="Google is disconnected. Send /connect.",
        )

    def _handle_disconnect(self, event: TelegramMessage, *, now: datetime) -> None:
        if self.store is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google disconnect is unavailable right now.",
            )
            return

        user = self.store.get_user_by_telegram(
            telegram_user_id=event.user_id,
            telegram_chat_id=event.chat_id,
        )
        if user is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="You are not connected.",
            )
            return

        account = self.store.get_google_account(user.id)
        if account is None:
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="You are not connected.",
            )
            return

        if self.store.mark_google_account_status(
            user.id,
            "revoked",
            now=now,
        ):
            self.telegram.send_message(
                chat_id=event.chat_id,
                text="Google disconnected.",
            )
            return

        self.telegram.send_message(chat_id=event.chat_id, text="Disconnect failed.")

    def _handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        now: datetime,
    ) -> None:
        action, _, value = callback.data.partition(":")
        if action == "edit_reply" and self.store is not None:
            self.store.set_conversation_state(
                user_id=user_id,
                telegram_chat_id=callback.chat_id,
                state="editing_reply",
                payload={
                    "pending_reply_id": int(value),
                    "message_id": callback.message_id,
                },
                updated_at=now,
            )
            self.telegram.send_message(
                chat_id=callback.chat_id,
                text="Type the edited reply in your next message.",
            )
            return

        if action in ("cal_pick", "cal_del_ok", "cal_del_no", "cal_field", "cal_edit_ok", "cal_edit_no") and self.calendar_edit_service is not None:
            self.calendar_edit_service.handle_callback(callback, user_id=user_id, now=now)
            return

        if action in ("cal_confirm", "cal_cancel") and self.calendar_action_service is not None:
            self.calendar_action_service.handle_callback(callback, user_id=user_id, now=now)
            return

        if user_id is None:
            self.mail_action_service.handle_callback(callback, now=now)
            return

        try:
            self.mail_action_service.handle_callback(
                callback,
                user_id=user_id,
                now=now,
            )
        except TypeError:
            # Backward-compatible fallback for callback handlers that do not yet
            # accept an explicit user_id argument.
            self.mail_action_service.handle_callback(callback, now=now)

    def _handle_cancel_event(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_edit_service is None or self.store is None
                or not isinstance(event, TelegramMessage)):
            return False
        lowered = event.text.lower()
        if not (("cancel" in lowered or "delete" in lowered)
                and ("event" in lowered or "meeting" in lowered or "appointment" in lowered)):
            return False
        return self.calendar_edit_service.start(event, operation="cancel", user_id=user_id, now=now)

    def _handle_edit_intent(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_edit_service is None or self.store is None
                or not isinstance(event, TelegramMessage)):
            return False
        lowered = event.text.lower()
        if not (("edit" in lowered or "change" in lowered or "reschedule" in lowered or "move" in lowered)
                and ("event" in lowered or "meeting" in lowered or "appointment" in lowered)):
            return False
        return self.calendar_edit_service.start(event, operation="edit", user_id=user_id, now=now)

    def _handle_calendar_edit_value(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_edit_service is None or self.store is None
                or not isinstance(event, TelegramMessage)):
            return False
        state = self.store.get_conversation_state(event.chat_id, user_id=user_id)
        if state is None or state.state != "cal_edit_value":
            return False
        return self.calendar_edit_service.handle_value(event, user_id=user_id, now=now)

    def _handle_create_event(self, event, *, user_id=None, now) -> bool:
        if (
            self.calendar_action_service is None
            or self.store is None
            or self.timezone is None
            or not isinstance(event, TelegramMessage)
        ):
            return False
        from personal_hermes.calendar.event_request import parse_event_request

        draft = parse_event_request(event.text, now=now, tz=self.timezone)
        if draft is None:
            return False
        pending_id = self.calendar_action_service.prepare_event(
            user_id=user_id, draft=draft, telegram_message_id=event.message_id, now=now
        )
        start = draft.start_at.strftime("%a %H:%M")
        end = draft.end_at.strftime("%H:%M")
        self.telegram.send_message(
            chat_id=event.chat_id,
            text=f"Create '{draft.title}' {start}-{end}?",
            buttons=[
                [
                    ("Confirm", f"cal_confirm:{pending_id}"),
                    ("Cancel", f"cal_cancel:{pending_id}"),
                ]
            ],
        )
        return True

    def _handle_edit_flow_message(
        self,
        message: TelegramMessage,
        *,
        user_id: int | None = None,
        now: datetime,
    ) -> bool:
        if self.store is None:
            return False

        state = self.store.get_conversation_state(
            message.chat_id,
            user_id=user_id,
        )
        if state is None or state.state != "editing_reply":
            return False

        pending_reply_id = int(state.payload["pending_reply_id"])
        self.store.update_pending_reply_text(
            pending_reply_id,
            message.text,
            user_id=user_id,
        )
        self.store.clear_conversation_state(
            message.chat_id,
            user_id=user_id,
        )
        self.telegram.send_message(
            chat_id=message.chat_id,
            text="Edited reply saved. Confirm before sending.",
            buttons=[
                [
                    ("Send edited reply", f"send_reply:{pending_reply_id}"),
                    ("Cancel", f"ignore_reply:{pending_reply_id}"),
                ]
            ],
        )
        return True

    def _resolve_user(self, event: TelegramMessage | TelegramCallback):
        if self.store is None:
            return None
        return self.store.get_user_by_telegram(
            telegram_user_id=event.user_id,
            telegram_chat_id=event.chat_id,
        )


def _looks_like_availability_question(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "available", "availability", "free", "this week",
            "tomorrow", "today", "schedule", "agenda",
            "what's on", "whats on", "what do i have",
        )
    )
