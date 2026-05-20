# Calendar Cancel (Delete) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user cancel (delete) a calendar event by picking it from a list of that day's events and confirming.

**Architecture:** A `gog calendar delete` wrapper on `OpenClawClient`, and a new `CalendarEditService` that drives a small state machine stored in the existing `conversation_state` table. The router detects a "cancel" intent, the service lists the day's events as inline buttons, the user taps one, confirms, and the service deletes via the per-user token. This also builds the **event-selection infrastructure** that Plan 3 (Edit) reuses.

**Tech Stack:** Python 3.11+, pytest, SQLite (`conversation_state`), the `gog`-backed `OpenClawClient`.

This is Plan 2 of 3 for Calendar CRUD completion (spec: `docs/superpowers/specs/2026-05-20-calendar-crud-completion-design.md`; Plan 1 = Read, done). Plan 3 = Edit.

---

## File Structure
- **Modify** `src/personal_hermes/openclaw/client.py` — add `delete_calendar_event` + arg builder.
- **Create** `src/personal_hermes/calendar/edit.py` — `CalendarEditService` (selection + cancel flow).
- **Modify** `src/personal_hermes/router.py` — detect the cancel intent; route `cal_pick` / `cal_del_ok` / `cal_del_no` callbacks.
- **Modify** `src/personal_hermes/app.py` — construct `CalendarEditService`; pass it to the router.
- **Tests:** `tests/openclaw/test_delete_calendar_event.py` (new), `tests/calendar/test_calendar_edit.py` (new), `tests/test_create_event_routing.py` or a new router test (cancel intent + callbacks).

**Session shape** stored in `conversation_state.payload` (a JSON dict):
- `op`: `"cancel"`
- `candidates`: list of `{"id": str, "title": str, "start": iso, "end": iso}` (the day's events, in display order)
- `event`: the selected candidate dict (set after `cal_pick`)
**State strings:** `"cal_select"` (list shown) → `"cal_confirm_delete"` (event picked, awaiting confirm).
**Callback verbs:** `cal_pick:<idx>`, `cal_del_ok`, `cal_del_no`.

Run all: `source .venv/bin/activate && python -m pytest -q`

---

## Task 1: `OpenClawClient.delete_calendar_event`

**Files:**
- Modify: `src/personal_hermes/openclaw/client.py`
- Test: `tests/openclaw/test_delete_calendar_event.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openclaw/test_delete_calendar_event.py`:
```python
from personal_hermes.openclaw.client import OpenClawClient


def test_delete_calendar_event_builds_gog_args():
    captured = {}

    def runner(args, *, input_text=None):
        captured["args"] = args
        return {}

    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    client.delete_calendar_event(event_id="evt123")

    args = captured["args"]
    assert args[0] == "gog"
    assert "--access-token" in args and "tok" in args
    assert args[args.index("calendar") + 1] == "delete"
    assert "primary" in args
    assert "evt123" in args
    assert "--no-input" in args
    assert "-y" in args
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/openclaw/test_delete_calendar_event.py -v`
Expected: FAIL (`delete_calendar_event` not defined).

- [ ] **Step 3: Implement**

In `src/personal_hermes/openclaw/client.py`, add after `create_calendar_event`:
```python
    def delete_calendar_event(self, *, event_id: str) -> None:
        self._run(self._delete_calendar_event_args(event_id))
```
and after `_create_calendar_event_args`:
```python
    def _delete_calendar_event_args(self, event_id: str) -> list[str]:
        return self._base_args() + [
            "calendar",
            "delete",
            "primary",
            event_id,
            "--json",
            "--no-input",
            "-y",
        ]
```
(`-y` skips gog's own destructive-action prompt; the Telegram confirmation is the real gate.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/openclaw/test_delete_calendar_event.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/openclaw/client.py tests/openclaw/test_delete_calendar_event.py
git commit -m "feat: add gog calendar delete wrapper"
```

---

## Task 2: `CalendarEditService` — selection list

**Files:**
- Create: `src/personal_hermes/calendar/edit.py`
- Test: `tests/calendar/test_calendar_edit.py`

**Context:** mirror `src/personal_hermes/calendar/actions.py` (`CalendarActionService`) for the `_client_for_user`, telegram, store, resolver structure. `parse_date_range(text, today)` (in `calendar/availability.py`) returns `(start_date, end_date)`; for selection use `start_date` as the target day. `store.set_conversation_state(*, user_id=None, telegram_chat_id, state, payload, updated_at)` persists the session; `payload` is a JSON-able dict. The telegram adapter's `send_message(*, chat_id, text, buttons=None)` takes `buttons` as `list[list[tuple[label, callback_data]]]`.

- [ ] **Step 1: Write the failing test**

Create `tests/calendar/test_calendar_edit.py`:
```python
from datetime import date, datetime, UTC
from zoneinfo import ZoneInfo

from personal_hermes.calendar.edit import CalendarEditService
from personal_hermes.storage.store import StateStore
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.types import TelegramMessage

TZ = ZoneInfo("Asia/Manila")


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.answers = []
    def send_message(self, *, chat_id, text, buttons=None):
        self.messages.append({"text": text, "buttons": buttons})
        return 1
    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append(text)
    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append(text)


class FakeClient:
    def __init__(self, events):
        self._events = events
        self.deleted = []
    def with_access_token(self, token):
        return self
    def list_calendar_events(self, start_at, end_at):
        return self._events
    def delete_calendar_event(self, *, event_id):
        self.deleted.append(event_id)


def _store(tmp_path):
    s = StateStore(str(tmp_path / "t.sqlite3")); s.initialize(); return s

def _uid(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2, display_name=None,
        username=None, now=datetime.now(tz=UTC)).id

def _event(eid, title, h):
    return CalendarEvent(id=eid, title=title, all_day=False,
        start_at=datetime(2026,5,20,h,0,tzinfo=TZ), end_at=datetime(2026,5,20,h,30,tzinfo=TZ))


def test_start_cancel_lists_events_as_buttons(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    handled = svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    assert handled is True
    assert tg.messages, "should send a selection message"
    buttons = tg.messages[0]["buttons"]
    flat = [b for row in buttons for b in row]
    assert any(cb.startswith("cal_pick:") for _label, cb in flat)
    assert any("Standup" in label for label, _cb in flat)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_select"
    assert state.payload["op"] == "cancel"
    assert len(state.payload["candidates"]) == 2


def test_start_cancel_no_events(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    svc = CalendarEditService(openclaw_client=FakeClient([]), telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    handled = svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    assert handled is True
    assert "No events" in tg.messages[0]["text"]
    assert store.get_conversation_state(2, user_id=uid) is None
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k start -v`
Expected: FAIL (module/class not defined).

- [ ] **Step 3: Implement**

Create `src/personal_hermes/calendar/edit.py`:
```python
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
        verb = "Cancel" if operation == "cancel" else "Edit"
        buttons = []
        for idx, e in enumerate(events):
            label = f"{e.start_at.astimezone(self.timezone).strftime('%H:%M')} {e.title}"[:60]
            buttons.append([(label, f"cal_pick:{idx}")])
        self.telegram.send_message(
            chat_id=message.chat_id,
            text=f"Which event do you want to {verb.lower()}?",
            buttons=buttons,
        )
        self.store.set_conversation_state(
            user_id=user_id, telegram_chat_id=message.chat_id,
            state="cal_select", payload={"op": operation, "candidates": candidates},
            updated_at=now,
        )
        return True

    def _client_for_user(self, user_id, *, now):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        access_token = self.resolve_access_token(user_id, now=now)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k start -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/edit.py tests/calendar/test_calendar_edit.py
git commit -m "feat: add CalendarEditService event selection list"
```

---

## Task 3: Cancel callbacks (`cal_pick` → confirm → delete)

**Files:**
- Modify: `src/personal_hermes/calendar/edit.py`
- Test: `tests/calendar/test_calendar_edit.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/calendar/test_calendar_edit.py`:
```python
from personal_hermes.telegram.types import TelegramCallback

def _start_cancel(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    return store, uid, tg, client, svc

def test_pick_then_confirm_deletes_event(tmp_path):
    store, uid, tg, client, svc = _start_cancel(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)
    # a confirm prompt was sent (edit or message) referencing the picked event
    assert any("Review" in t for t in (tg.edits + [m["text"] for m in tg.messages]))
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_ok"), user_id=uid, now=now)
    assert client.deleted == ["e2"]
    assert store.get_conversation_state(2, user_id=uid) is None

def test_pick_then_cancel_does_not_delete(tmp_path):
    store, uid, tg, client, svc = _start_cancel(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:0"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_no"), user_id=uid, now=now)
    assert client.deleted == []
    assert store.get_conversation_state(2, user_id=uid) is None

def test_confirm_without_session_is_expired(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    svc = CalendarEditService(openclaw_client=FakeClient([]), telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_ok"), user_id=uid, now=datetime.now(tz=UTC))
    assert any("expired" in (t or "").lower() for t in tg.answers)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k "pick or confirm or expired" -v`
Expected: FAIL (`handle_callback` not defined).

- [ ] **Step 3: Implement**

Add to `CalendarEditService` in `src/personal_hermes/calendar/edit.py`:
```python
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

    def _pick(self, callback, state, *, index, user_id, now) -> None:
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
            # Edit op is handled in Plan 3; ignore here.
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Not supported yet")

    def _delete(self, callback, state, *, user_id, now) -> None:
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

    def _answer_expired(self, callback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="That selection expired — start again.",
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/edit.py tests/calendar/test_calendar_edit.py
git commit -m "feat: add cancel confirm/delete flow to CalendarEditService"
```

---

## Task 4: Router + app wiring (cancel intent + callbacks)

**Files:**
- Modify: `src/personal_hermes/router.py`
- Modify: `src/personal_hermes/app.py`
- Test: `tests/test_create_event_routing.py` (add a cancel-flow test, mirroring its existing setup)

- [ ] **Step 1: Write the failing test**

In `tests/test_create_event_routing.py` (which already builds an `AssistantRouter` with fakes + a real store + an active user — read it), add a test that:
1. builds the router with a `calendar_edit_service` (a real `CalendarEditService` using a `FakeTelegram` + a fake client returning one event + the store + `resolve_access_token=lambda uid,*,now:"tok"` + `timezone=ZoneInfo("Asia/Manila")`),
2. sends `TelegramMessage(text="cancel an event today")` via `router.handle_event(...)` and asserts a selection message with a `cal_pick:` button was sent,
3. sends the `cal_pick:0` callback then the `cal_del_ok` callback via `router.handle_event(...)` and asserts the fake client recorded the deleted event id.
Name it `test_cancel_event_routing_multiuser`. (Mirror the router construction already in the file; pass `calendar_edit_service=...` as a new keyword.)

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_create_event_routing.py -k cancel -v`
Expected: FAIL (router doesn't accept `calendar_edit_service` / cancel intent not handled).

- [ ] **Step 3: Implement**

In `src/personal_hermes/router.py`:
1. Add `calendar_edit_service=None` to `AssistantRouter.__init__` params and `self.calendar_edit_service = calendar_edit_service`.
2. In `_handle_callback`, before the mail delegation, route the new verbs:
```python
        if action in ("cal_pick", "cal_del_ok", "cal_del_no") and self.calendar_edit_service is not None:
            self.calendar_edit_service.handle_callback(callback, user_id=user_id, now=now)
            return
```
3. Add a cancel-intent handler method:
```python
    def _handle_cancel_event(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_edit_service is None or self.store is None
                or not isinstance(event, TelegramMessage)):
            return False
        lowered = event.text.lower()
        if not (("cancel" in lowered or "delete" in lowered) and ("event" in lowered or "meeting" in lowered or "appointment" in lowered)):
            return False
        return self.calendar_edit_service.start(event, operation="cancel", user_id=user_id, now=now)
```
4. In BOTH branches of `handle_event`, AFTER the `_handle_create_event(...)` call and BEFORE the schedule/availability check, insert (match indentation; single-user uses `user_id=None`, multi-user uses `user_id=user.id`):
```python
            if self._handle_cancel_event(event, user_id=<USER>, now=now):
                return
```

In `src/personal_hermes/app.py`:
- Add import `from personal_hermes.calendar.edit import CalendarEditService`.
- In `build_components`, after `calendar_action_service = CalendarActionService(...)`, add:
```python
    calendar_edit_service = CalendarEditService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        timezone=ZoneInfo(settings.timezone),
        resolve_access_token=resolve_access_token,
    )
```
- In the `AssistantRouter(...)` call, add `calendar_edit_service=calendar_edit_service,`.

- [ ] **Step 4: Run to verify pass + full suite**

Run: `python -m pytest tests/test_create_event_routing.py -k cancel -v && python -m pytest -q`
Expected: targeted test PASSES; full suite all green.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/router.py src/personal_hermes/app.py tests/test_create_event_routing.py
git commit -m "feat: wire cancel-event flow into the router"
```

---

## Task 5: Final review + real-gog verification

- [ ] **Step 1:** Run `python -m pytest -q` — confirm fully green.
- [ ] **Step 2:** Dispatch a final review of the whole Cancel diff (integration coherence: router passes user_id/now; callback verbs match; conversation_state session shape consistent; delete wrapper args).
- [ ] **Step 3 (real gog):** restart the app; in Telegram create a throwaway event, then "cancel an event today" → tap it → Confirm cancel → verify it's gone from Google Calendar.

---

## Notes
- `cal_pick` with an `op == "edit"` session is intentionally a no-op here ("Not supported yet"); Plan 3 (Edit) implements that branch + the field/value steps, reusing this selection infrastructure and the `cal_pick` callback.
- Conversation_state is single-slot per user; starting a cancel replaces any abandoned email-edit or calendar session — acceptable.
