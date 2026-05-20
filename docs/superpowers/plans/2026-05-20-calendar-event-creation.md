# Calendar Event Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a connected user create a Google Calendar event from a free-form Telegram message, with a confirm-before-write step.

**Architecture:** Mirror the existing email-reply flow. A rule-based parser turns a message into an `EventDraft`; the router stores a pending draft and sends Confirm/Cancel buttons; on Confirm, `CalendarActionService` resolves the user's OAuth token and calls `gog calendar create`. The parser is isolated behind one function so an LLM can replace it later.

**Tech Stack:** Python 3.11+, pytest, SQLite (`schema.sql`), the `gog` CLI via `OpenClawClient`, `python-telegram-bot`-style adapter.

---

## File Structure

- **Create** `src/personal_hermes/calendar/event_request.py` — `EventDraft` + `parse_event_request` (rule-based; the LLM-swap seam).
- **Create** `src/personal_hermes/calendar/actions.py` — `CalendarActionService` (prepare draft, handle Confirm/Cancel callbacks, create event).
- **Modify** `src/personal_hermes/oauth/google.py` — add `calendar.events` scope.
- **Modify** `src/personal_hermes/openclaw/client.py` — add `create_calendar_event` + arg builder.
- **Modify** `src/personal_hermes/storage/schema.sql` — add `pending_calendar_events` table.
- **Modify** `src/personal_hermes/storage/store.py` — `PendingCalendarEvent` dataclass + create/get/mark/expire methods + row mapper.
- **Modify** `src/personal_hermes/router.py` — detect create-intent in messages; route `cal_confirm:`/`cal_cancel:` callbacks.
- **Modify** `src/personal_hermes/app.py` — construct `CalendarActionService`, pass it + timezone into `AssistantRouter`.
- **Tests:** `tests/oauth/test_google_oauth.py`, `tests/calendar/test_event_request.py` (new), `tests/openclaw/test_create_calendar_event.py` (new), `tests/storage/test_pending_calendar_events.py` (new), `tests/calendar/test_calendar_actions.py` (new), `tests/e2e/test_assistant_pipeline.py`.

Run all tests with: `source .venv/bin/activate && python -m pytest -q`

---

## Task 1: Add the `calendar.events` OAuth scope

**Files:**
- Modify: `src/personal_hermes/oauth/google.py:15-26`
- Test: `tests/oauth/test_google_oauth.py:64-98`

- [ ] **Step 1: Update the scope assertion test**

In `tests/oauth/test_google_oauth.py`, in `test_authorization_url_uses_offline_access_and_expected_scopes`, add after the existing `calendar.readonly` assertion:

```python
    assert (
        "https://www.googleapis.com/auth/calendar.events"
        in captured["scopes"]
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/oauth/test_google_oauth.py::test_authorization_url_uses_offline_access_and_expected_scopes -v`
Expected: FAIL (`calendar.events` not in scopes).

- [ ] **Step 3: Add the scope**

In `src/personal_hermes/oauth/google.py`, change `GOOGLE_OAUTH_SCOPES` to:

```python
GOOGLE_OAUTH_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)
```

- [ ] **Step 4: Update the granted-scopes mock test**

In `tests/oauth/test_google_oauth.py`, in `test_exchange_code_uses_normalized_actual_granted_scopes`, add `"https://www.googleapis.com/auth/calendar.events"` to the `granted_scopes` list so it still equals `GOOGLE_OAUTH_SCOPES`.

- [ ] **Step 5: Run the OAuth tests**

Run: `python -m pytest tests/oauth/test_google_oauth.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/personal_hermes/oauth/google.py tests/oauth/test_google_oauth.py
git commit -m "feat: request calendar.events scope for event creation"
```

---

## Task 2: EventDraft + rule-based parser

**Files:**
- Create: `src/personal_hermes/calendar/event_request.py`
- Test: `tests/calendar/test_event_request.py`

- [ ] **Step 1: Write failing tests**

Create `tests/calendar/test_event_request.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.event_request import EventDraft, parse_event_request

TZ = ZoneInfo("Asia/Manila")
# A Wednesday at 08:00 local time.
NOW = datetime(2026, 5, 20, 8, 0, tzinfo=TZ)


def test_parses_today_time_range_and_title():
    draft = parse_event_request("appointment today 9AM-9:30AM dentist", now=NOW, tz=TZ)
    assert draft == EventDraft(
        title="dentist",
        start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
        end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ),
    )


def test_defaults_to_60_minutes_when_no_end():
    draft = parse_event_request("schedule meeting tomorrow at 2pm review", now=NOW, tz=TZ)
    assert draft is not None
    assert draft.start_at == datetime(2026, 5, 21, 14, 0, tzinfo=TZ)
    assert draft.end_at == datetime(2026, 5, 21, 15, 0, tzinfo=TZ)
    assert draft.title == "review"


def test_returns_none_for_non_event_text():
    assert parse_event_request("what dates am I free this week?", now=NOW, tz=TZ) is None
    assert parse_event_request("hello there", now=NOW, tz=TZ) is None


def test_returns_none_when_intent_present_but_no_time():
    assert parse_event_request("schedule a dentist appointment", now=NOW, tz=TZ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/calendar/test_event_request.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the parser**

Create `src/personal_hermes/calendar/event_request.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_TRIGGERS = ("appointment", "schedule", "meeting", "book", "add event", "create event")
_DEFAULT_DURATION = timedelta(minutes=60)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
# Matches "9AM", "9:30am", "14:00", "2pm".
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
_RANGE_RE = re.compile(rf"{_TIME}\s*(?:-|to|until)\s*{_TIME}", re.IGNORECASE)
_SINGLE_RE = re.compile(rf"(?:at\s+)?{_TIME}", re.IGNORECASE)


@dataclass(frozen=True)
class EventDraft:
    title: str
    start_at: datetime
    end_at: datetime


def parse_event_request(text: str, *, now: datetime, tz: ZoneInfo) -> EventDraft | None:
    lowered = text.lower()
    if not any(trigger in lowered for trigger in _TRIGGERS):
        return None

    target_date = _resolve_date(lowered, now=now)
    times, leftover = _extract_times(text, target_date, tz)
    if times is None:
        return None
    start_at, end_at = times

    title = _extract_title(leftover)
    if not title:
        return None
    return EventDraft(title=title, start_at=start_at, end_at=end_at)


def _resolve_date(lowered: str, *, now: datetime):
    today = now.date()
    if "tomorrow" in lowered:
        return today + timedelta(days=1)
    for name, weekday in _WEEKDAYS.items():
        if name in lowered:
            ahead = (weekday - today.weekday()) % 7
            return today + timedelta(days=ahead or 7)
    return today  # default / explicit "today"


def _to_dt(hour, minute, meridiem, date, tz) -> datetime:
    hour = int(hour)
    minute = int(minute) if minute else 0
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    return datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz)


def _extract_times(text, date, tz):
    match = _RANGE_RE.search(text)
    if match:
        h1, m1, ap1, h2, m2, ap2 = match.groups()
        ap1 = ap1 or ap2  # "9-9:30am" -> apply pm/am to both if one is missing
        ap2 = ap2 or ap1
        start = _to_dt(h1, m1, ap1, date, tz)
        end = _to_dt(h2, m2, ap2, date, tz)
        leftover = (text[: match.start()] + " " + text[match.end():])
        return (start, end), leftover

    match = _SINGLE_RE.search(text)
    if match:
        h, m, ap = match.groups()
        start = _to_dt(h, m, ap, date, tz)
        leftover = (text[: match.start()] + " " + text[match.end():])
        return (start, start + _DEFAULT_DURATION), leftover

    return None, text


def _extract_title(leftover: str) -> str:
    words = []
    skip = {
        "appointment", "schedule", "meeting", "book", "add", "create", "event",
        "today", "tomorrow", "at", "from", "to", "until", "a", "an", "the",
        "for", "minutes", "minute", "min", "mins", "hour", "hours",
        *(_WEEKDAYS.keys()),
    }
    for word in leftover.split():
        cleaned = word.strip(",.-").lower()
        if cleaned and cleaned not in skip and not any(c.isdigit() for c in cleaned):
            words.append(word.strip(",.-"))
    return " ".join(words).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/calendar/test_event_request.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/event_request.py tests/calendar/test_event_request.py
git commit -m "feat: add rule-based event-request parser"
```

---

## Task 3: OpenClawClient.create_calendar_event

**Files:**
- Modify: `src/personal_hermes/openclaw/client.py` (add method near `list_calendar_events`, and an arg builder near `_list_calendar_events_args`)
- Test: `tests/openclaw/test_create_calendar_event.py`

- [ ] **Step 1: Write the failing test**

Create `tests/openclaw/test_create_calendar_event.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from personal_hermes.openclaw.client import OpenClawClient

TZ = ZoneInfo("Asia/Manila")


def test_create_calendar_event_builds_gog_args():
    captured = {}

    def runner(args, *, input_text=None):
        captured["args"] = args
        return {"id": "evt123", "htmlLink": "https://cal/evt123"}

    client = OpenClawClient(command_runner=runner, executable="gog").with_access_token("tok")
    event = client.create_calendar_event(
        title="dentist",
        start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
        end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ),
    )

    args = captured["args"]
    assert args[0] == "gog"
    assert "--access-token" in args and "tok" in args
    assert args[args.index("calendar") + 1] == "create"
    assert "primary" in args
    assert "--summary" in args and "dentist" in args
    assert "--from" in args and "2026-05-20T09:00:00+08:00" in args
    assert "--to" in args and "2026-05-20T09:30:00+08:00" in args
    assert "--start-timezone" in args and "Asia/Manila" in args
    assert "--no-input" in args and "--json" in args
    assert event.id == "evt123"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/openclaw/test_create_calendar_event.py -v`
Expected: FAIL (`create_calendar_event` not defined).

- [ ] **Step 3: Implement the method**

In `src/personal_hermes/openclaw/client.py`, add after `list_calendar_events` (around line 81):

```python
    def create_calendar_event(
        self, *, title: str, start_at: datetime, end_at: datetime
    ) -> CalendarEvent:
        payload = self._run(self._create_calendar_event_args(title, start_at, end_at))
        if not isinstance(payload, dict):
            raise OpenClawCommandError("gog calendar create returned a non-object value")
        return self._map_calendar_event(payload)
```

And add after `_list_calendar_events_args` (around line 173):

```python
    def _create_calendar_event_args(
        self, title: str, start_at: datetime, end_at: datetime
    ) -> list[str]:
        tz = start_at.tzinfo
        tz_name = getattr(tz, "key", None) or str(tz)
        return self._base_args() + [
            "calendar",
            "create",
            "primary",
            "--summary",
            title,
            "--from",
            start_at.isoformat(),
            "--to",
            end_at.isoformat(),
            "--start-timezone",
            tz_name,
            "--end-timezone",
            tz_name,
            "--json",
            "--no-input",
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/openclaw/test_create_calendar_event.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/openclaw/client.py tests/openclaw/test_create_calendar_event.py
git commit -m "feat: add gog calendar create wrapper"
```

---

## Task 4: pending_calendar_events table + store methods

**Files:**
- Modify: `src/personal_hermes/storage/schema.sql`
- Modify: `src/personal_hermes/storage/store.py` (add dataclass + methods + row mapper)
- Test: `tests/storage/test_pending_calendar_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/storage/test_pending_calendar_events.py`:

```python
from datetime import datetime, timedelta, UTC

from personal_hermes.storage.store import StateStore


def _store(tmp_path):
    store = StateStore(str(tmp_path / "t.sqlite3"))
    store.initialize()
    return store


def _user(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2,
        display_name=None, username=None, now=datetime.now(tz=UTC),
    ).id


def test_create_and_get_pending_event(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    now = datetime.now(tz=UTC)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="dentist",
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
        timezone="Asia/Manila", created_at=now, expires_at=now + timedelta(minutes=15),
        telegram_message_id=99,
    )
    pending = store.get_pending_calendar_event(pid, user_id=uid, now=now)
    assert pending is not None
    assert pending.title == "dentist"
    assert pending.status == "pending"


def test_expired_pending_event_returns_none(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="x", start_at=past, end_at=past,
        timezone="UTC", created_at=past, expires_at=past, telegram_message_id=None,
    )
    assert store.get_pending_calendar_event(pid, user_id=uid, now=datetime.now(tz=UTC)) is None


def test_mark_created_changes_status(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    now = datetime.now(tz=UTC)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="x", start_at=now, end_at=now, timezone="UTC",
        created_at=now, expires_at=now + timedelta(minutes=15), telegram_message_id=None,
    )
    assert store.mark_pending_calendar_event_created(pid) is True
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "created"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/storage/test_pending_calendar_events.py -v`
Expected: FAIL (`create_pending_calendar_event` not defined).

- [ ] **Step 3: Add the table to schema.sql**

In `src/personal_hermes/storage/schema.sql`, add (mirrors `pending_replies`):

```sql
CREATE TABLE IF NOT EXISTS pending_calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'created', 'failed', 'cancelled', 'expired')
    ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    telegram_message_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

(Run on every `initialize()` via `executescript`, so existing DBs get it too.)

- [ ] **Step 4: Add the dataclass + methods to store.py**

Near the other dataclasses (top of `store.py`, after `PendingReply`):

```python
@dataclass(frozen=True)
class PendingCalendarEvent:
    id: int
    user_id: int
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    status: str
    created_at: datetime
    expires_at: datetime
    telegram_message_id: int | None
```

Add these methods inside `StateStore` (model on `create_pending_reply`/`get_pending_reply`):

```python
    def create_pending_calendar_event(
        self, *, user_id: int | None = None, title: str,
        start_at: datetime, end_at: datetime, timezone: str,
        created_at: datetime, expires_at: datetime, telegram_message_id: int | None,
    ) -> int:
        user_id = self._resolve_user_id(user_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pending_calendar_events (
                    user_id, title, start_at, end_at, timezone, status,
                    created_at, expires_at, telegram_message_id
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    user_id, title,
                    self._datetime_to_text(start_at), self._datetime_to_text(end_at),
                    timezone, self._datetime_to_text(created_at),
                    self._datetime_to_text(expires_at), telegram_message_id,
                ),
            )
            return int(cursor.lastrowid)

    def get_pending_calendar_event(
        self, pending_id: int, *, user_id: int | None = None, now: datetime | None = None,
    ) -> "PendingCalendarEvent | None":
        if now is not None:
            self.expire_pending_calendar_events(now)
        where = "id = ?"
        params: list[Any] = [pending_id]
        if user_id is not None:
            where += " AND user_id = ?"
            params.append(user_id)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM pending_calendar_events WHERE {where}", params
            ).fetchone()
        if row is None:
            return None
        pending = self._pending_calendar_event_from_row(row)
        if now is not None and pending.status == "expired":
            return None
        return pending

    def mark_pending_calendar_event_created(self, pending_id: int) -> bool:
        return self._update_pending_calendar_event_status(pending_id, "created")

    def mark_pending_calendar_event_failed(self, pending_id: int) -> bool:
        return self._update_pending_calendar_event_status(pending_id, "failed")

    def mark_pending_calendar_event_cancelled(self, pending_id: int) -> bool:
        return self._update_pending_calendar_event_status(pending_id, "cancelled")

    def expire_pending_calendar_events(self, now: datetime) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_calendar_events
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (self._datetime_to_text(now),),
            )
            return cursor.rowcount

    def _update_pending_calendar_event_status(self, pending_id: int, status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE pending_calendar_events SET status = ? WHERE id = ?",
                (status, pending_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _pending_calendar_event_from_row(row: sqlite3.Row) -> "PendingCalendarEvent":
        return PendingCalendarEvent(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            title=row["title"],
            start_at=StateStore._text_to_datetime(row["start_at"]),
            end_at=StateStore._text_to_datetime(row["end_at"]),
            timezone=row["timezone"],
            status=row["status"],
            created_at=StateStore._text_to_datetime(row["created_at"]),
            expires_at=StateStore._text_to_datetime(row["expires_at"]),
            telegram_message_id=row["telegram_message_id"],
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/storage/test_pending_calendar_events.py -v`
Expected: PASS (all 3).

- [ ] **Step 6: Commit**

```bash
git add src/personal_hermes/storage/schema.sql src/personal_hermes/storage/store.py tests/storage/test_pending_calendar_events.py
git commit -m "feat: add pending_calendar_events storage"
```

---

## Task 5: CalendarActionService

**Files:**
- Create: `src/personal_hermes/calendar/actions.py`
- Test: `tests/calendar/test_calendar_actions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/calendar/test_calendar_actions.py`:

```python
from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from personal_hermes.calendar.actions import CalendarActionService
from personal_hermes.calendar.event_request import EventDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback

TZ = ZoneInfo("Asia/Manila")


class FakeTelegram:
    def __init__(self):
        self.edits = []
        self.answers = []
    def is_authorized(self, event):
        return True
    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append(text)
    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append(text)


class FakeClient:
    def __init__(self):
        self.created = []
    def with_access_token(self, token):
        return self
    def create_calendar_event(self, *, title, start_at, end_at):
        self.created.append((title, start_at, end_at))
        class E: id = "evt1"
        return E()


def _store(tmp_path):
    store = StateStore(str(tmp_path / "t.sqlite3")); store.initialize()
    return store


def _uid(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2, display_name=None,
        username=None, now=datetime.now(tz=UTC)).id


def test_confirm_creates_event_and_marks_created(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram(); client = FakeClient()
    svc = CalendarActionService(
        openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )
    now = datetime.now(tz=UTC)
    draft = EventDraft(title="dentist",
                       start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
                       end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ))
    pid = svc.prepare_event(user_id=uid, draft=draft, telegram_message_id=5, now=now)

    cb = TelegramCallback(chat_id=2, user_id=1, message_id=5,
                          callback_query_id="q", data=f"cal_confirm:{pid}")
    svc.handle_callback(cb, user_id=uid, now=now)

    assert client.created and client.created[0][0] == "dentist"
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "created"
    assert any("Created" in e for e in tg.edits)


def test_cancel_marks_cancelled_and_does_not_create(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram(); client = FakeClient()
    svc = CalendarActionService(
        openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )
    now = datetime.now(tz=UTC)
    draft = EventDraft(title="x",
                       start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
                       end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ))
    pid = svc.prepare_event(user_id=uid, draft=draft, telegram_message_id=5, now=now)
    cb = TelegramCallback(chat_id=2, user_id=1, message_id=5,
                          callback_query_id="q", data=f"cal_cancel:{pid}")
    svc.handle_callback(cb, user_id=uid, now=now)

    assert client.created == []
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "cancelled"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/calendar/test_calendar_actions.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the service**

Create `src/personal_hermes/calendar/actions.py`:

```python
from datetime import datetime, timedelta
from typing import Protocol

from personal_hermes.calendar.event_request import EventDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback


class CalendarWriteClient(Protocol):
    def create_calendar_event(self, *, title: str, start_at: datetime, end_at: datetime): ...


class CalendarActionTelegram(Protocol):
    def is_authorized(self, event: TelegramCallback) -> bool: ...
    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None: ...
    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None: ...


class CalendarActionService:
    def __init__(self, *, openclaw_client, telegram, store: StateStore | None,
                 resolve_access_token=None) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.resolve_access_token = resolve_access_token

    def prepare_event(self, *, user_id, draft: EventDraft, telegram_message_id, now: datetime) -> int:
        assert self.store is not None
        tz_name = getattr(draft.start_at.tzinfo, "key", None) or str(draft.start_at.tzinfo)
        return self.store.create_pending_calendar_event(
            user_id=user_id, title=draft.title,
            start_at=draft.start_at, end_at=draft.end_at, timezone=tz_name,
            created_at=now, expires_at=now + timedelta(minutes=15),
            telegram_message_id=telegram_message_id,
        )

    def handle_callback(self, callback: TelegramCallback, *, user_id=None, now: datetime) -> None:
        if not self.telegram.is_authorized(callback):
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unauthorized")
            return
        action, _, value = callback.data.partition(":")
        if action == "cal_confirm":
            self._confirm(callback, pending_id=int(value), user_id=user_id, now=now)
        elif action == "cal_cancel":
            self._cancel(callback, pending_id=int(value), user_id=user_id, now=now)
        else:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unsupported action")

    def _confirm(self, callback, *, pending_id, user_id, now) -> None:
        if self.store is None:
            self._answer_expired(callback); return
        pending = self.store.get_pending_calendar_event(pending_id, user_id=user_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_expired(callback); return

        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        try:
            client.create_calendar_event(
                title=pending.title, start_at=pending.start_at, end_at=pending.end_at)
        except Exception:
            self.store.mark_pending_calendar_event_failed(pending_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id,
                                       text="Couldn't create the event right now.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Failed")
            return
        self.store.mark_pending_calendar_event_created(pending_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id,
                                   text=f"Created '{pending.title}'.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Created")

    def _cancel(self, callback, *, pending_id, user_id, now) -> None:
        if self.store is None:
            self._answer_expired(callback); return
        pending = self.store.get_pending_calendar_event(pending_id, user_id=user_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_expired(callback); return
        self.store.mark_pending_calendar_event_cancelled(pending_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Cancelled.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")

    def _client_for_user(self, user_id, *, now):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        access_token = self.resolve_access_token(user_id, now=now)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)

    def _answer_expired(self, callback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="That request expired, please send it again.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/calendar/test_calendar_actions.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/actions.py tests/calendar/test_calendar_actions.py
git commit -m "feat: add CalendarActionService for confirm/create flow"
```

---

## Task 6: Router wiring + app wiring

**Files:**
- Modify: `src/personal_hermes/router.py` (constructor; message path; callback routing)
- Modify: `src/personal_hermes/app.py` (construct service; pass into router)
- Test: `tests/e2e/test_assistant_pipeline.py` (add one create-flow test)

- [ ] **Step 1: Write the failing e2e test**

Add to `tests/e2e/test_assistant_pipeline.py` a test that builds the router with a `CalendarActionService` (using fakes like the existing tests in that file), sends the message `"appointment today 9AM-9:30AM dentist"` as an active multi-user, asserts a confirmation message with `cal_confirm:`/`cal_cancel:` buttons was sent, then sends a `cal_confirm:<id>` callback and asserts the fake client recorded a created event. (Follow the construction style already used by the other tests in this file.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/e2e/test_assistant_pipeline.py -k create -v`
Expected: FAIL (`calendar_action_service` not accepted / no confirmation sent).

- [ ] **Step 3: Extend the router constructor**

In `src/personal_hermes/router.py`, add params to `AssistantRouter.__init__` (after `mail_action_service`):

```python
        calendar_action_service=None,
        timezone=None,
```

and store them:

```python
        self.calendar_action_service = calendar_action_service
        self.timezone = timezone
```

- [ ] **Step 4: Add create-intent handling in the message path**

In `handle_event`, in **both** branches, immediately **after** the `_handle_edit_flow_message(...)` check and **before** the `_looks_like_availability_question` check, insert:

```python
            if self._handle_create_event(event, user_id=user_id, now=now):
                return
```

(In the single-user branch use `user_id=None`.) Then add the method:

```python
    def _handle_create_event(self, event, *, user_id=None, now) -> bool:
        if (self.calendar_action_service is None or self.store is None
                or self.timezone is None or not isinstance(event, TelegramMessage)):
            return False
        from personal_hermes.calendar.event_request import parse_event_request
        draft = parse_event_request(event.text, now=now, tz=self.timezone)
        if draft is None:
            return False
        pending_id = self.calendar_action_service.prepare_event(
            user_id=user_id, draft=draft, telegram_message_id=event.message_id, now=now)
        start = draft.start_at.strftime("%a %H:%M")
        end = draft.end_at.strftime("%H:%M")
        self.telegram.send_message(
            chat_id=event.chat_id,
            text=f"Create '{draft.title}' {start}-{end}?",
            buttons=[[("Confirm", f"cal_confirm:{pending_id}"),
                      ("Cancel", f"cal_cancel:{pending_id}")]],
        )
        return True
```

- [ ] **Step 5: Route the new callbacks**

In `_handle_callback`, before the `mail_action_service` delegation, add:

```python
        if action in ("cal_confirm", "cal_cancel") and self.calendar_action_service is not None:
            self.calendar_action_service.handle_callback(callback, user_id=user_id, now=now)
            return
```

- [ ] **Step 6: Wire it in app.py**

In `build_components` (`src/personal_hermes/app.py`), after `mail_action_service = MailActionService(...)` is constructed, add:

```python
    calendar_action_service = CalendarActionService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        resolve_access_token=resolve_access_token,
    )
```

Add the import at the top: `from personal_hermes.calendar.actions import CalendarActionService`.
Then in the `AssistantRouter(...)` call add:

```python
        calendar_action_service=calendar_action_service,
        timezone=ZoneInfo(settings.timezone),
```

(`ZoneInfo` is already imported in `app.py`.)

- [ ] **Step 7: Run the e2e test + full suite**

Run: `python -m pytest tests/e2e/test_assistant_pipeline.py -k create -v && python -m pytest -q`
Expected: the new test PASSES. Pre-existing failures unrelated to this work may remain (see note below); no *new* failures.

- [ ] **Step 8: Commit**

```bash
git add src/personal_hermes/router.py src/personal_hermes/app.py tests/e2e/test_assistant_pipeline.py
git commit -m "feat: wire calendar event creation into the router"
```

---

## Task 7: Manual end-to-end verification

- [ ] **Step 1: Re-consent for the new scope.** Restart the app, then in Telegram run `/connect` again and grant the new "manage events" permission (existing tokens lack `calendar.events`). If Google blocks the scope, add `https://www.googleapis.com/auth/calendar.events` under OAuth consent screen → Data access, then retry.

- [ ] **Step 2: Create an event.** Send `appointment today 9AM-9:30AM dentist`. Expect a "Create 'dentist' …? [Confirm] [Cancel]" reply.

- [ ] **Step 3: Confirm.** Tap **Confirm**. Expect "Created 'dentist'." and verify the event appears in Google Calendar.

- [ ] **Step 4: Cancel path.** Send another request, tap **Cancel**, confirm no event is created.

---

## Notes
- **Pre-existing test failures:** `tests/e2e/test_assistant_pipeline.py` (4) and `tests/test_app.py` (1) fail on the current baseline for unrelated reasons (gog fixtures). Don't treat them as regressions; only ensure no *new* failures appear.
- **Simplification vs spec (intentional, YAGNI):** the spec mentions a tailored "I couldn't read the time" hint when intent is detected but no time is parseable. To keep the parser's interface a clean `EventDraft | None`, this MVP returns `None` in that case, so the message falls through to the existing generic help reply rather than a tailored hint. A distinct hint can be added later (e.g., the parser returning a richer result) — deferred with the LLM work.
- **LLM swap (future):** replace `parse_event_request` with a Claude-API implementation behind the same signature; nothing else in this design needs to change.
