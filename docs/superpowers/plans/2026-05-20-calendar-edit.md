# Calendar Edit (Update) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user edit a calendar event — reschedule (time), or change title / location / description — by picking it from a list, choosing a field, sending the new value, and confirming.

**Architecture:** A `gog calendar update` wrapper on `OpenClawClient`, plus the edit branches of the existing `CalendarEditService` (from Plan 2). The selection list, `cal_pick` callback, and `conversation_state` session are already built; this plan adds the field-choice step, the typed-value step (reusing the email edit-flow value-capture pattern), the confirm step, and the `gog update` call. The router gains an edit-intent detector and routes the new callbacks + the value-input message.

**Tech Stack:** Python 3.11+, pytest, SQLite (`conversation_state`), the `gog`-backed `OpenClawClient`.

This is Plan 3 of 3 for Calendar CRUD (spec: `docs/superpowers/specs/2026-05-20-calendar-crud-completion-design.md`). Plans 1 (Read) and 2 (Cancel) are done.

---

## File Structure
- **Modify** `src/personal_hermes/openclaw/client.py` — add `update_calendar_event` + arg builder.
- **Modify** `src/personal_hermes/calendar/edit.py` — implement the `op=="edit"` branch of `_pick`, the `cal_field` handler, `handle_value`, the `cal_edit_ok`/`cal_edit_no` handlers, and a small `_parse_new_time` helper.
- **Modify** `src/personal_hermes/router.py` — edit-intent detection; route `cal_field`/`cal_edit_ok`/`cal_edit_no` callbacks; route the `cal_edit_value` text input to `handle_value`.
- **Tests:** `tests/openclaw/test_update_calendar_event.py` (new), `tests/calendar/test_calendar_edit.py` (extend), `tests/test_create_event_routing.py` (extend).

**Session states added** (in `conversation_state`):
`cal_select` → (edit pick) `cal_choose_field` → (field chosen) `cal_edit_value` → (value typed) `cal_confirm_edit`.
**Session payload** carries: `op:"edit"`, `event:{id,title,start,end}`, `field:"time"|"title"|"location"|"description"`, `new_value`.
**Callback verbs added:** `cal_field:<field>`, `cal_edit_ok`, `cal_edit_no`.

Run all: `source .venv/bin/activate && python -m pytest -q`

---

## Task 1: `OpenClawClient.update_calendar_event`

**Files:**
- Modify: `src/personal_hermes/openclaw/client.py`
- Test: `tests/openclaw/test_update_calendar_event.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openclaw/test_update_calendar_event.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from personal_hermes.openclaw.client import OpenClawClient

TZ = ZoneInfo("Asia/Manila")


def test_update_only_passes_changed_fields_and_unwraps_envelope():
    captured = {}
    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"event": {"id": "evt1", "summary": "renamed",
                          "start": {"dateTime": "2026-05-21T15:00:00+08:00"},
                          "end": {"dateTime": "2026-05-21T15:30:00+08:00"}}}
    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    ev = client.update_calendar_event(event_id="evt1", summary="renamed")
    args = captured["args"]
    assert args[args.index("calendar") + 1] == "update"
    assert "primary" in args and "evt1" in args
    assert "--summary" in args and "renamed" in args
    assert "--from" not in args and "--to" not in args  # unchanged fields omitted
    assert ev.id == "evt1"


def test_update_time_passes_from_to_and_timezone():
    captured = {}
    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"event": {"id": "evt1"}}
    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    client.update_calendar_event(
        event_id="evt1",
        start_at=datetime(2026,5,21,16,0,tzinfo=TZ),
        end_at=datetime(2026,5,21,16,30,tzinfo=TZ),
        timezone="Asia/Manila",
    )
    args = captured["args"]
    assert "--from" in args and "2026-05-21T16:00:00+08:00" in args
    assert "--to" in args and "2026-05-21T16:30:00+08:00" in args
    assert "--start-timezone" in args and "Asia/Manila" in args
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/openclaw/test_update_calendar_event.py -v`
Expected: FAIL (`update_calendar_event` not defined).

- [ ] **Step 3: Implement**

In `src/personal_hermes/openclaw/client.py`, add after `delete_calendar_event`:
```python
    def update_calendar_event(
        self, *, event_id: str, summary: str | None = None,
        start_at: datetime | None = None, end_at: datetime | None = None,
        location: str | None = None, description: str | None = None,
        timezone: str | None = None,
    ) -> CalendarEvent:
        payload = self._run(self._update_calendar_event_args(
            event_id, summary, start_at, end_at, location, description, timezone))
        if not isinstance(payload, dict):
            raise OpenClawCommandError("gog calendar update returned a non-object value")
        event = payload.get("event", payload)
        if not isinstance(event, dict):
            raise OpenClawCommandError("gog calendar update returned a malformed event")
        return self._map_calendar_event(event)
```
and after `_delete_calendar_event_args`:
```python
    def _update_calendar_event_args(
        self, event_id, summary, start_at, end_at, location, description, timezone
    ) -> list[str]:
        args = self._base_args() + ["calendar", "update", "primary", event_id]
        if summary is not None:
            args += ["--summary", summary]
        if start_at is not None:
            args += ["--from", start_at.isoformat()]
        if end_at is not None:
            args += ["--to", end_at.isoformat()]
        if location is not None:
            args += ["--location", location]
        if description is not None:
            args += ["--description", description]
        if timezone is not None:
            args += ["--start-timezone", timezone, "--end-timezone", timezone]
        args += ["--json", "--no-input"]
        return args
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/openclaw/test_update_calendar_event.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/openclaw/client.py tests/openclaw/test_update_calendar_event.py
git commit -m "feat: add gog calendar update wrapper"
```

---

## Task 2: Edit selection → field choice

**Files:**
- Modify: `src/personal_hermes/calendar/edit.py`
- Test: `tests/calendar/test_calendar_edit.py`

**Context:** `_pick` currently handles `op=="cancel"` and answers "Not supported yet" for edit. Replace the edit branch so it shows field buttons, and add a `cal_field` case to `handle_callback`.

- [ ] **Step 1: Write the failing test**

Add to `tests/calendar/test_calendar_edit.py`:
```python
def _start_edit(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="edit an event today")
    svc.start(msg, operation="edit", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    return store, uid, tg, client, svc

def test_edit_pick_shows_field_buttons(tmp_path):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)
    flat = [b for m in tg.messages for row in (m["buttons"] or []) for b in row]
    cbs = [cb for _label, cb in flat]
    assert "cal_field:time" in cbs and "cal_field:title" in cbs
    assert "cal_field:location" in cbs and "cal_field:description" in cbs
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_choose_field"
    assert state.payload["event"]["id"] == "e2"

def test_edit_choose_field_prompts_for_value(tmp_path):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:0"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_field:title"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_edit_value"
    assert state.payload["field"] == "title"
    assert any("new title" in m["text"].lower() for m in tg.messages)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k "edit_pick or choose_field" -v`
Expected: FAIL (edit pick still says "Not supported yet"; `cal_field` unhandled).

- [ ] **Step 3: Implement**

In `src/personal_hermes/calendar/edit.py`:
1. In `handle_callback`, add a `cal_field` case to the dispatch (alongside `cal_pick`/`cal_del_ok`/`cal_del_no`):
```python
        elif action == "cal_field":
            self._choose_field(callback, state, field=value, user_id=user_id, now=now)
```
2. Replace the `else:` (edit) branch inside `_pick` with:
```python
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
```
3. Add the `_choose_field` method:
```python
    _FIELD_LABELS = {"time": "time", "title": "title", "location": "location", "description": "description"}

    def _choose_field(self, callback, state, *, field, user_id, now) -> None:
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k "edit_pick or choose_field" -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/edit.py tests/calendar/test_calendar_edit.py
git commit -m "feat: add edit field-choice step to CalendarEditService"
```

---

## Task 3: Capture the typed value (`handle_value`)

**Files:**
- Modify: `src/personal_hermes/calendar/edit.py`
- Test: `tests/calendar/test_calendar_edit.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/calendar/test_calendar_edit.py`:
```python
def _to_value_step(tmp_path, field):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)  # picks "Review" (e2)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data=f"cal_field:{field}"), user_id=uid, now=now)
    return store, uid, tg, client, svc

def test_handle_value_title_sets_confirm(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "title")
    now = datetime.now(tz=UTC)
    handled = svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="Sprint review"), user_id=uid, now=now)
    assert handled is True
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_confirm_edit"
    assert state.payload["new_value"] == {"text": "Sprint review"}
    assert any("Sprint review" in m["text"] for m in tg.messages)
    flat = [cb for m in tg.messages for row in (m["buttons"] or []) for _l, cb in row]
    assert "cal_edit_ok" in flat and "cal_edit_no" in flat

def test_handle_value_time_parses_range(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "time")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="4-4:30pm"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_confirm_edit"
    nv = state.payload["new_value"]
    # event e2 is on 2026-05-20; new time 16:00-16:30 local
    assert nv["start"].startswith("2026-05-20T16:00:00")
    assert nv["end"].startswith("2026-05-20T16:30:00")

def test_handle_value_unparseable_time_stays(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "time")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="sometime later"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_edit_value"  # stayed, awaiting a valid time
    assert any("couldn't read" in m["text"].lower() for m in tg.messages)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k handle_value -v`
Expected: FAIL (`handle_value` not defined).

- [ ] **Step 3: Implement**

Add to `src/personal_hermes/calendar/edit.py` (add `import re` at the top):
```python
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
        # Event's local date drives the new time; preserve duration if only a start is given.
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
                if ap == "pm" and h != 12: h += 12
                elif ap == "am" and h == 12: h = 0
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k handle_value -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/edit.py tests/calendar/test_calendar_edit.py
git commit -m "feat: capture and parse the new edit value"
```

---

## Task 4: Apply the edit (`cal_edit_ok` / `cal_edit_no`)

**Files:**
- Modify: `src/personal_hermes/calendar/edit.py`
- Test: `tests/calendar/test_calendar_edit.py`

**Context:** `FakeClient` in the test needs an `update_calendar_event` recorder. Add it to the `FakeClient` class:
```python
    def update_calendar_event(self, *, event_id, **fields):
        self.updated.append((event_id, fields))
        class E: id = event_id
        return E()
```
and `self.updated = []` in its `__init__`.

- [ ] **Step 1: Write the failing test**

Add to `tests/calendar/test_calendar_edit.py` (also update `FakeClient` as above):
```python
def test_confirm_edit_title_updates(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "title")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="Sprint review"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=7,callback_query_id="q",data="cal_edit_ok"), user_id=uid, now=now)
    assert client.updated and client.updated[0][0] == "e2"
    assert client.updated[0][1].get("summary") == "Sprint review"
    assert store.get_conversation_state(2, user_id=uid) is None

def test_confirm_edit_time_updates_with_from_to(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "time")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="4-4:30pm"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=7,callback_query_id="q",data="cal_edit_ok"), user_id=uid, now=now)
    eid, fields = client.updated[0]
    assert eid == "e2"
    assert fields.get("start_at") is not None and fields.get("end_at") is not None
    assert fields.get("timezone") == "Asia/Manila"

def test_cancel_edit_does_not_update(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "title")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="X"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=7,callback_query_id="q",data="cal_edit_no"), user_id=uid, now=now)
    assert client.updated == []
    assert store.get_conversation_state(2, user_id=uid) is None
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -k "confirm_edit or cancel_edit" -v`
Expected: FAIL (`cal_edit_ok`/`cal_edit_no` unhandled).

- [ ] **Step 3: Implement**

In `handle_callback`, add to the dispatch:
```python
        elif action == "cal_edit_ok":
            self._apply_edit(callback, state, user_id=user_id, now=now)
        elif action == "cal_edit_no":
            self.store.clear_conversation_state(callback.chat_id, user_id=user_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Edit cancelled.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")
```
Add the `_apply_edit` method:
```python
    def _apply_edit(self, callback, state, *, user_id, now) -> None:
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_edit.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/edit.py tests/calendar/test_calendar_edit.py
git commit -m "feat: apply calendar edit via gog update"
```

---

## Task 5: Router wiring (edit intent + callbacks + value input)

**Files:**
- Modify: `src/personal_hermes/router.py`
- Test: `tests/test_create_event_routing.py`

**Context:** `calendar_edit_service` is already constructed in `app.py` and passed to the router (Plan 2). `_handle_callback` already routes `cal_pick`/`cal_del_ok`/`cal_del_no`. The router's message path already calls `_handle_edit_flow_message` (email value capture via conversation_state). The `FakeClient` in `tests/test_create_event_routing.py` needs an `update_calendar_event` recorder (add it like the cancel test's `delete_calendar_event`).

- [ ] **Step 1: Write the failing test**

In `tests/test_create_event_routing.py`, add `test_edit_event_routing_multiuser`: mirror the cancel routing test, but send `"edit an event today"`, then `cal_pick:0`, then `cal_field:title`, then a `TelegramMessage` with the new title, then `cal_edit_ok` — all via `router.handle_event(...)` — and assert the fake client recorded an `update_calendar_event` call with `summary` = the new title. (The fake client's `list_calendar_events` should return one event; add `update_calendar_event(self, *, event_id, **fields)` recording to the fake.)

Run `python -m pytest tests/test_create_event_routing.py -k edit_event -v` → confirm FAIL.

- [ ] **Step 2: Implement in `router.py`**
1. Extend the callback routing tuple to include the new verbs:
```python
        if action in ("cal_pick", "cal_del_ok", "cal_del_no", "cal_field", "cal_edit_ok", "cal_edit_no") and self.calendar_edit_service is not None:
            self.calendar_edit_service.handle_callback(callback, user_id=user_id, now=now)
            return
```
2. Add an edit-intent handler:
```python
    def _handle_edit_intent(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_edit_service is None or self.store is None
                or not isinstance(event, TelegramMessage)):
            return False
        lowered = event.text.lower()
        if not (("edit" in lowered or "change" in lowered or "reschedule" in lowered or "move" in lowered)
                and ("event" in lowered or "meeting" in lowered or "appointment" in lowered)):
            return False
        return self.calendar_edit_service.start(event, operation="edit", user_id=user_id, now=now)
```
3. In BOTH branches of `handle_event`, insert the edit-intent check immediately AFTER the `_handle_cancel_event` check and BEFORE `_handle_create_event` (so cancel and edit are recognized before create; match indentation, `user_id=None` single-user / `user.id` multi-user):
```python
            if self._handle_edit_intent(event, user_id=<USER>, now=now):
                return
```
4. Route the in-flight edit-value text input. In BOTH branches, immediately AFTER the `_handle_edit_flow_message(...)` call (email value capture) and before the cancel/edit/create checks, add a calendar-value capture:
```python
            if self.calendar_edit_service is not None and self._handle_calendar_edit_value(event, user_id=<USER>, now=now):
                return
```
and add the helper:
```python
    def _handle_calendar_edit_value(self, event, *, user_id=None, now) -> bool:
        if not isinstance(event, TelegramMessage) or self.store is None:
            return False
        state = self.store.get_conversation_state(event.chat_id, user_id=user_id)
        if state is None or state.state != "cal_edit_value":
            return False
        return self.calendar_edit_service.handle_value(event, user_id=user_id, now=now)
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/test_create_event_routing.py -k "edit_event or cancel" -v && python -m pytest -q`
Expected: targeted tests PASS; full suite all green.

- [ ] **Step 4: Commit**

```bash
git add src/personal_hermes/router.py tests/test_create_event_routing.py
git commit -m "feat: wire calendar edit flow into the router"
```

---

## Task 6: Final review + combined real-gog CRUD verification

- [ ] **Step 1:** `python -m pytest -q` — fully green.
- [ ] **Step 2:** Dispatch a final review of the whole Edit diff (integration coherence: edit/cancel/create intent ordering; the 6 `cal_*` callback verbs routed; `cal_edit_value` message routed to `handle_value`; `update_calendar_event` kwargs match per field; envelope unwrapped; timezone passed explicitly).
- [ ] **Step 3 (combined real-gog test):** restart the app; in Telegram exercise all four: create an event, "what's on my calendar today?", reschedule it ("edit an event today" → Time → `4-4:30pm`), retitle it, then cancel it — verifying each against Google Calendar.

---

## Notes
- The edit-value time parser (`_parse_new_time`) is intentionally a thin, local rule-based parser — it (and the intent triggers) are the throwaway parts the LLM layer will replace; the `update_calendar_event` action is the durable tool.
- Intent ordering in `handle_event`: edit-flow value capture (email + calendar) → cancel → edit → create → schedule/availability → fallback.
