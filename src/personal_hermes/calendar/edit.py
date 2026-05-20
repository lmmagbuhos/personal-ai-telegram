import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import parse_date_range
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class CalendarEditService:
    _FIELD_LABELS = {"time": "time", "title": "title", "location": "location", "description": "description"}

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
        elif action == "cal_field":
            self._choose_field(callback, state, field=value, user_id=user_id, now=now)
        elif action == "cal_edit_ok":
            self._apply_edit(callback, state, user_id=user_id, now=now)
        elif action == "cal_edit_no":
            self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Edit cancelled.")
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
        else:  # op == "edit"
            self.store.set_conversation_state(
                user_id=user_id, telegram_chat_id=callback.chat_id,
                state="cal_choose_field", payload={"op": "edit", "event": event}, updated_at=now,
            )
            self.telegram.edit_message(
                chat_id=callback.chat_id, message_id=callback.message_id,
                text=f"Editing '{event['title']}'. What do you want to change?",
            )
            self.telegram.send_message(
                chat_id=callback.chat_id, text="Choose a field:",
                buttons=[
                    [("Time", "cal_field:time"), ("Title", "cal_field:title")],
                    [("Location", "cal_field:location"), ("Description", "cal_field:description")],
                ],
            )
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id)

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

    def _apply_edit(self, callback: TelegramCallback, state, *, user_id, now) -> None:
        event = state.payload.get("event")
        field = state.payload.get("field")
        new_value = state.payload.get("new_value")
        if not event or not field or new_value is None:
            self._answer_expired(callback)
            return
        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        kwargs = {"event_id": event["id"]}
        if field == "time":
            kwargs["start_at"] = datetime.fromisoformat(new_value["start"])
            kwargs["end_at"] = datetime.fromisoformat(new_value["end"])
            kwargs["timezone"] = getattr(self.timezone, "key", None) or str(self.timezone)
        elif field == "title":
            kwargs["summary"] = new_value["text"]
        elif field == "location":
            kwargs["location"] = new_value["text"]
        elif field == "description":
            kwargs["description"] = new_value["text"]
        try:
            client.update_calendar_event(**kwargs)
        except Exception:
            self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Couldn't update the event right now.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Failed")
            return
        self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text=f"Updated '{event['title']}'.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Updated")

    def _choose_field(self, callback: TelegramCallback, state, *, field, user_id, now: datetime) -> None:
        event = state.payload.get("event")
        if not event or field not in self._FIELD_LABELS:
            self._answer_expired(callback)
            return
        self.store.set_conversation_state(
            user_id=user_id, telegram_chat_id=callback.chat_id,
            state="cal_edit_value", payload={"op": "edit", "event": event, "field": field},
            updated_at=now,
        )
        self.telegram.send_message(
            chat_id=callback.chat_id,
            text=f"Send the new {self._FIELD_LABELS[field]}"
                 + (" (e.g. `3pm` or `3-3:30pm`)." if field == "time" else "."),
        )
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id)

    def _answer_expired(self, callback: TelegramCallback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="That selection expired — start again.",
        )

    def handle_value(self, message: TelegramMessage, *, user_id, now: datetime) -> bool:
        if self.store is None:
            return False
        state = self.store.get_conversation_state(message.chat_id, user_id=user_id)
        if state is None or state.state != "cal_edit_value":
            return False
        field = state.payload["field"]
        event = state.payload["event"]
        if field == "time":
            parsed = self._parse_new_time(message.text, event=event)
            if parsed is None:
                self.telegram.send_message(
                    chat_id=message.chat_id,
                    text="I couldn't read that time — send e.g. `3pm` or `3-3:30pm`.",
                )
                return True
            start_at, end_at = parsed
            new_value = {"start": start_at.isoformat(), "end": end_at.isoformat()}
            shown = f"{start_at.strftime('%H:%M')}–{end_at.strftime('%H:%M')}"
        else:
            new_value = {"text": message.text.strip()}
            shown = message.text.strip()
        self.store.set_conversation_state(
            user_id=user_id, telegram_chat_id=message.chat_id, state="cal_confirm_edit",
            payload={"op": "edit", "event": event, "field": field, "new_value": new_value},
            updated_at=now,
        )
        self.telegram.send_message(
            chat_id=message.chat_id,
            text=f"Change {field} to {shown}?",
            buttons=[[("Confirm", "cal_edit_ok"), ("Cancel", "cal_edit_no")]],
        )
        return True

    def _parse_new_time(self, text, *, event):
        start_dt = datetime.fromisoformat(event["start"]).astimezone(self.timezone)
        end_dt = datetime.fromisoformat(event["end"]).astimezone(self.timezone)
        duration = end_dt - start_dt
        target_date = start_dt.date()
        t = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
        rng = re.search(rf"{t}\s*(?:-|to|until)\s*{t}", text, re.IGNORECASE)

        def to_dt(h, m, ap):
            h = int(h); m = int(m) if m else 0
            if ap:
                ap = ap.lower()
                if ap == "pm" and h != 12:
                    h += 12
                elif ap == "am" and h == 12:
                    h = 0
            return datetime(target_date.year, target_date.month, target_date.day, h, m, tzinfo=self.timezone)

        if rng:
            h1, m1, ap1, h2, m2, ap2 = rng.groups()
            s = to_dt(h1, m1, ap1 or ap2)
            e = to_dt(h2, m2, ap2 or ap1)
            if e <= s:
                if ap1 is None and ap2 is not None:
                    s = to_dt(h1, m1, "am" if ap2.lower() == "pm" else "pm")
                elif ap2 is None and ap1 is not None:
                    e = to_dt(h2, m2, "am" if ap1.lower() == "pm" else "pm")
            if e <= s:
                return None
            return s, e
        single = re.search(rf"(?:at\s+)?{t}", text, re.IGNORECASE)
        if single:
            h, m, ap = single.groups()
            s = to_dt(h, m, ap)
            return s, s + duration
        return None

    def _client_for_user(self, user_id, *, now):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        access_token = self.resolve_access_token(user_id, now=now)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)
