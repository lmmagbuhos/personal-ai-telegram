from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import parse_date_range
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class CalendarEditService:
    def __init__(self, *, openclaw_client, telegram, store: StateStore | None,
                 timezone: ZoneInfo, resolve_access_token=None) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.timezone = timezone
        self.resolve_access_token = resolve_access_token

    def start(self, message: TelegramMessage, *, operation: str, user_id, now: datetime,
              today: date | None = None) -> bool:
        if self.store is None:
            return False
        today = today or now.astimezone(self.timezone).date()
        target_date, _ = parse_date_range(message.text, today=today)

        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.send_message(chat_id=message.chat_id, text="Connect Google first with /connect.")
            return True

        day_start = datetime.combine(target_date, time.min, tzinfo=self.timezone)
        day_end = day_start + timedelta(days=1)
        events = client.list_calendar_events(day_start.astimezone(UTC), day_end.astimezone(UTC))
        events = sorted(events, key=lambda e: e.start_at)
        if not events:
            self.telegram.send_message(
                chat_id=message.chat_id,
                text=f"No events on {target_date.strftime('%a, %b %d')}.",
            )
            return True

        candidates = [
            {"id": e.id, "title": e.title,
             "start": e.start_at.isoformat(), "end": e.end_at.isoformat()}
            for e in events
        ]
        verb = "cancel" if operation == "cancel" else "edit"
        buttons = []
        for idx, e in enumerate(events):
            label = f"{e.start_at.astimezone(self.timezone).strftime('%H:%M')} {e.title}"[:60]
            buttons.append([(label, f"cal_pick:{idx}")])
        self.telegram.send_message(
            chat_id=message.chat_id,
            text=f"Which event do you want to {verb}?",
            buttons=buttons,
        )
        self.store.set_conversation_state(
            user_id=user_id, telegram_chat_id=message.chat_id,
            state="cal_select", payload={"op": operation, "candidates": candidates},
            updated_at=now,
        )
        return True

    def handle_callback(self, callback: TelegramCallback, *, user_id, now: datetime) -> None:
        if self.store is None:
            self._answer_expired(callback)
            return
        state = self.store.get_conversation_state(callback.chat_id, user_id=user_id)
        if state is None:
            self._answer_expired(callback)
            return
        action, _, value = callback.data.partition(":")
        if action == "cal_pick":
            self._pick(callback, state, index=int(value), user_id=user_id, now=now)
        elif action == "cal_del_ok":
            self._delete(callback, state, user_id=user_id, now=now)
        elif action == "cal_del_no":
            self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Cancelled.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")
        else:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unsupported action")

    def _pick(self, callback: TelegramCallback, state, *, index: int, user_id, now: datetime) -> None:
        candidates = state.payload.get("candidates", [])
        if index < 0 or index >= len(candidates):
            self._answer_expired(callback)
            return
        event = candidates[index]
        op = state.payload["op"]
        if op == "cancel":
            self.store.set_conversation_state(
                user_id=user_id, telegram_chat_id=callback.chat_id,
                state="cal_confirm_delete", payload={"op": "cancel", "event": event}, updated_at=now,
            )
            self.telegram.edit_message(
                chat_id=callback.chat_id, message_id=callback.message_id,
                text=f"Cancel '{event['title']}'?",
            )
            self.telegram.send_message(
                chat_id=callback.chat_id, text="Confirm?",
                buttons=[[("Confirm cancel", "cal_del_ok"), ("Keep it", "cal_del_no")]],
            )
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id)
        else:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Not supported yet")

    def _delete(self, callback: TelegramCallback, state, *, user_id, now: datetime) -> None:
        event = state.payload.get("event")
        if not event:
            self._answer_expired(callback)
            return
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        try:
            client.delete_calendar_event(event_id=event["id"])
        except Exception:
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Couldn't cancel the event right now.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Failed")
            self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
            return
        self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text=f"Cancelled '{event['title']}'.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")

    def _answer_expired(self, callback: TelegramCallback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="That selection expired — start again.",
        )

    def _client_for_user(self, user_id, *, now):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        access_token = self.resolve_access_token(user_id, now=now)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)
