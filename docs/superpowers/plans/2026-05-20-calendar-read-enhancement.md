# Calendar Read Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare free/busy-days answer with an on-demand "show my schedule" that lists each day's actual events plus the computed free time slots.

**Architecture:** Extend the pure functions in `calendar/availability.py` to return free intervals and a per-day schedule (all-day events are informational/non-blocking; free slots come from timed events only). `CalendarService.schedule_for` builds a `DaySchedule` per day reusing the existing event fetch. A new `format_schedule` renders single-day full detail vs week compact. The router's existing availability intent routes to this richer view.

**Tech Stack:** Python 3.11+, pytest, `zoneinfo`, the existing `gog`-backed `OpenClawClient`.

This is Plan 1 of 2 for Calendar CRUD completion (spec: `docs/superpowers/specs/2026-05-20-calendar-crud-completion-design.md`). Plan 2 covers Cancel + Edit.

---

## File Structure
- **Modify** `src/personal_hermes/calendar/availability.py` — add `free_slots()`, `DaySchedule`, `day_schedule()`.
- **Modify** `src/personal_hermes/calendar/service.py` — add `CalendarService.schedule_for()`.
- **Modify** `src/personal_hermes/telegram/adapter.py` — add `format_schedule()` (alongside `format_availability_answer`).
- **Modify** `src/personal_hermes/router.py` — route the availability/schedule intent to `schedule_for` + `format_schedule`; expand trigger words.
- **Tests:** `tests/calendar/test_availability.py` (existing — add cases), `tests/calendar/test_calendar_service.py` (existing — add a case), `tests/telegram/` or existing adapter test for the formatter, `tests/e2e/test_assistant_pipeline.py` (router intent).

Run all: `source .venv/bin/activate && python -m pytest -q`

---

## Task 1: `free_slots()` in availability.py

**Files:**
- Modify: `src/personal_hermes/calendar/availability.py`
- Test: `tests/calendar/test_availability.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/calendar/test_availability.py` (import `free_slots`, `datetime`, `timedelta`, `ZoneInfo`, and the existing `CalendarEvent`):

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from personal_hermes.calendar.availability import free_slots
from personal_hermes.openclaw.types import CalendarEvent

TZ = ZoneInfo("Asia/Manila")

def _ev(h1, m1, h2, m2, *, all_day=False, title="x"):
    return CalendarEvent(
        id="e", title=title,
        start_at=datetime(2026, 5, 21, h1, m1, tzinfo=TZ),
        end_at=datetime(2026, 5, 21, h2, m2, tzinfo=TZ),
        all_day=all_day,
    )

def _slots(events):
    return free_slots(
        target_date=datetime(2026, 5, 21, tzinfo=TZ).date(),
        events=events, timezone=TZ,
        workday_start="09:00", workday_end="17:00", min_free_block_minutes=60,
    )

def test_free_slots_empty_day_is_whole_workday():
    assert _slots([]) == [(datetime(2026,5,21,9,0,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))]

def test_free_slots_gaps_around_events():
    slots = _slots([_ev(9,0,9,30), _ev(14,0,15,0)])
    assert slots == [
        (datetime(2026,5,21,9,30,tzinfo=TZ), datetime(2026,5,21,14,0,tzinfo=TZ)),
        (datetime(2026,5,21,15,0,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ)),
    ]

def test_free_slots_ignores_all_day_events():
    # all-day event present but only a timed event should shape free slots
    assert _slots([_ev(0,0,23,59, all_day=True), _ev(9,0,10,0)]) == [
        (datetime(2026,5,21,10,0,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ)),
    ]

def test_free_slots_drops_gaps_below_min_block():
    # 09:00-09:30 then 10:00-17:00 busy -> the 30-min gap is below 60 and dropped
    assert _slots([_ev(9,30,10,0), _ev(10,0,17,0)]) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_availability.py -k free_slots -v`
Expected: FAIL (`free_slots` not defined).

- [ ] **Step 3: Implement**

In `src/personal_hermes/calendar/availability.py`, add (reusing the existing `_event_intersects_date` and `_busy_ranges`):

```python
def free_slots(
    *,
    target_date: date,
    events: list[CalendarEvent],
    timezone: ZoneInfo,
    workday_start: str,
    workday_end: str,
    min_free_block_minutes: int,
) -> list[tuple[datetime, datetime]]:
    timed = [
        event
        for event in events
        if not event.all_day and _event_intersects_date(event, target_date, timezone)
    ]
    work_start = datetime.combine(
        target_date, time.fromisoformat(workday_start), tzinfo=timezone
    )
    work_end = datetime.combine(
        target_date, time.fromisoformat(workday_end), tzinfo=timezone
    )
    busy = _busy_ranges(timed, work_start, work_end, timezone)
    threshold = timedelta(minutes=min_free_block_minutes)

    slots: list[tuple[datetime, datetime]] = []
    cursor = work_start
    for start_at, end_at in busy:
        if start_at - cursor >= threshold:
            slots.append((cursor, start_at))
        if end_at > cursor:
            cursor = end_at
    if work_end - cursor >= threshold:
        slots.append((cursor, work_end))
    return slots
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_availability.py -k free_slots -v`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/availability.py tests/calendar/test_availability.py
git commit -m "feat: compute calendar free slots from timed events"
```

---

## Task 2: `DaySchedule` + `day_schedule()`

**Files:**
- Modify: `src/personal_hermes/calendar/availability.py`
- Test: `tests/calendar/test_availability.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/calendar/test_availability.py`:

```python
from personal_hermes.calendar.availability import DaySchedule, day_schedule, AvailabilityStatus

def _schedule(events):
    return day_schedule(
        target_date=datetime(2026, 5, 21, tzinfo=TZ).date(),
        events=events, timezone=TZ,
        workday_start="09:00", workday_end="17:00", min_free_block_minutes=60,
    )

def test_day_schedule_splits_all_day_and_timed_and_sorts():
    s = _schedule([_ev(14,0,15,0, title="late"), _ev(9,0,9,30, title="early"), _ev(0,0,0,0, all_day=True, title="bday")])
    assert [e.title for e in s.all_day_events] == ["bday"]
    assert [e.title for e in s.timed_events] == ["early", "late"]
    assert s.status == AvailabilityStatus.PARTLY_AVAILABLE
    assert s.free_slots  # non-empty

def test_day_schedule_no_timed_events_is_fully_available():
    s = _schedule([_ev(0,0,0,0, all_day=True, title="bday")])
    assert s.status == AvailabilityStatus.FULLY_AVAILABLE
    assert s.timed_events == []

def test_day_schedule_no_free_slots_is_busy():
    s = _schedule([_ev(9,0,17,0)])
    assert s.status == AvailabilityStatus.BUSY
    assert s.free_slots == []
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_availability.py -k day_schedule -v`
Expected: FAIL (`DaySchedule`/`day_schedule` not defined).

- [ ] **Step 3: Implement**

Add the import `from dataclasses import dataclass` at the top of `availability.py` (if not present), then add:

```python
@dataclass(frozen=True)
class DaySchedule:
    date: date
    all_day_events: list[CalendarEvent]
    timed_events: list[CalendarEvent]
    free_slots: list[tuple[datetime, datetime]]
    status: AvailabilityStatus


def day_schedule(
    *,
    target_date: date,
    events: list[CalendarEvent],
    timezone: ZoneInfo,
    workday_start: str,
    workday_end: str,
    min_free_block_minutes: int,
) -> DaySchedule:
    relevant = [
        event for event in events if _event_intersects_date(event, target_date, timezone)
    ]
    all_day_events = [event for event in relevant if event.all_day]
    timed_events = sorted(
        (event for event in relevant if not event.all_day),
        key=lambda event: event.start_at,
    )
    slots = free_slots(
        target_date=target_date,
        events=timed_events,
        timezone=timezone,
        workday_start=workday_start,
        workday_end=workday_end,
        min_free_block_minutes=min_free_block_minutes,
    )
    if not timed_events:
        status = AvailabilityStatus.FULLY_AVAILABLE
    elif slots:
        status = AvailabilityStatus.PARTLY_AVAILABLE
    else:
        status = AvailabilityStatus.BUSY
    return DaySchedule(
        date=target_date,
        all_day_events=all_day_events,
        timed_events=timed_events,
        free_slots=slots,
        status=status,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_availability.py -k day_schedule -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/availability.py tests/calendar/test_availability.py
git commit -m "feat: add DaySchedule and day_schedule"
```

---

## Task 3: `CalendarService.schedule_for()`

**Files:**
- Modify: `src/personal_hermes/calendar/service.py`
- Test: `tests/calendar/test_calendar_service.py`

**Context:** read the existing `_availability_for` in `service.py` first — it already does: `parse_date_range` → build UTC `start_at`/`end_at` → resolve the user's access token → `openclaw_client.with_access_token(...)` → `list_calendar_events(start_at_utc, end_at_utc)`. `schedule_for` mirrors that fetch, then calls `day_schedule` per day. The existing test file shows how to construct a `CalendarService` with a fake calendar client.

- [ ] **Step 1: Write the failing test**

Add to `tests/calendar/test_calendar_service.py` (self-contained — `CalendarService.__init__` is keyword-only: `openclaw_client, timezone, workday_start, workday_end, min_free_block_minutes, resolve_access_token=None`; with `resolve_access_token=None` and `user_id=None`, `schedule_for` uses the client directly):

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from personal_hermes.calendar.service import CalendarService
from personal_hermes.calendar.availability import AvailabilityStatus
from personal_hermes.openclaw.types import CalendarEvent

_TZ = ZoneInfo("Asia/Manila")


class _FakeClient:
    def __init__(self, events):
        self._events = events
    def list_calendar_events(self, start_at, end_at):
        return self._events


def test_schedule_for_returns_day_schedules_with_events_and_free_slots():
    event = CalendarEvent(
        id="e", title="Standup", all_day=False,
        start_at=datetime(2026, 5, 21, 9, 0, tzinfo=_TZ),
        end_at=datetime(2026, 5, 21, 9, 30, tzinfo=_TZ),
    )
    service = CalendarService(
        openclaw_client=_FakeClient([event]),
        timezone=_TZ, workday_start="09:00", workday_end="17:00",
        min_free_block_minutes=60,
    )
    schedules = service.schedule_for("today", today=date(2026, 5, 21))
    assert len(schedules) == 1
    day = schedules[0]
    assert [e.title for e in day.timed_events] == ["Standup"]
    assert day.free_slots  # has free time after the standup
    assert day.status == AvailabilityStatus.PARTLY_AVAILABLE
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/calendar/test_calendar_service.py -k schedule_for -v`
Expected: FAIL (`schedule_for` not defined).

- [ ] **Step 3: Implement**

In `src/personal_hermes/calendar/service.py`, add `from personal_hermes.calendar.availability import DaySchedule, day_schedule` (alongside the existing availability imports) and add this method to `CalendarService` (mirror the fetch in `_availability_for`):

```python
    def schedule_for(
        self, text: str, *, today: date, user_id: int | None = None
    ) -> list[DaySchedule]:
        start_date, end_date = parse_date_range(text, today=today)
        start_at = datetime.combine(start_date, time.min, tzinfo=self.timezone)
        end_at = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=self.timezone
        )
        openclaw_client = self.openclaw_client
        if self.resolve_access_token is not None and user_id is not None:
            access_token = self.resolve_access_token(user_id, now=datetime.now(tz=UTC))
            if access_token is None:
                return []
            if hasattr(openclaw_client, "with_access_token"):
                openclaw_client = openclaw_client.with_access_token(access_token)

        events = openclaw_client.list_calendar_events(
            start_at.astimezone(UTC), end_at.astimezone(UTC)
        )

        schedules: list[DaySchedule] = []
        current = start_date
        while current <= end_date:
            schedules.append(
                day_schedule(
                    target_date=current,
                    events=events,
                    timezone=self.timezone,
                    workday_start=self.workday_start,
                    workday_end=self.workday_end,
                    min_free_block_minutes=self.min_free_block_minutes,
                )
            )
            current += timedelta(days=1)
        return schedules
```

(`UTC`, `datetime`, `time`, `timedelta`, `date`, `parse_date_range` are already imported in `service.py`; verify and add any missing import.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/calendar/test_calendar_service.py -k schedule_for -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/service.py tests/calendar/test_calendar_service.py
git commit -m "feat: add CalendarService.schedule_for"
```

---

## Task 4: `format_schedule()` formatter

**Files:**
- Modify: `src/personal_hermes/telegram/adapter.py`
- Test: `tests/telegram/test_format_schedule.py` (create) — or add to the existing adapter test module if one covers `format_availability_answer`.

- [ ] **Step 1: Write the failing test**

Create `tests/telegram/test_format_schedule.py`:

```python
from datetime import datetime, date
from zoneinfo import ZoneInfo

from personal_hermes.calendar.availability import DaySchedule, AvailabilityStatus
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.adapter import format_schedule

TZ = ZoneInfo("Asia/Manila")

def _ev(h1, m1, h2, m2, title, all_day=False):
    return CalendarEvent(id="e", title=title, all_day=all_day,
        start_at=datetime(2026,5,21,h1,m1,tzinfo=TZ), end_at=datetime(2026,5,21,h2,m2,tzinfo=TZ))

def test_format_single_day_lists_events_and_free_slots():
    day = DaySchedule(
        date=date(2026,5,21),
        all_day_events=[_ev(0,0,0,0,"Birthday",all_day=True)],
        timed_events=[_ev(9,0,9,30,"Standup")],
        free_slots=[(datetime(2026,5,21,9,30,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))],
        status=AvailabilityStatus.PARTLY_AVAILABLE,
    )
    text = format_schedule([day], timezone=TZ)
    assert "Standup" in text
    assert "09:00" in text and "09:30" in text
    assert "Birthday" in text
    assert "09:30" in text and "17:00" in text  # free slot

def test_format_empty_single_day():
    day = DaySchedule(date=date(2026,5,21), all_day_events=[], timed_events=[],
        free_slots=[(datetime(2026,5,21,9,0,tzinfo=TZ), datetime(2026,5,21,17,0,tzinfo=TZ))],
        status=AvailabilityStatus.FULLY_AVAILABLE)
    text = format_schedule([day], timezone=TZ)
    assert "No events" in text or "free" in text.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/telegram/test_format_schedule.py -v`
Expected: FAIL (`format_schedule` not defined).

- [ ] **Step 3: Implement**

In `src/personal_hermes/telegram/adapter.py`, add (near `format_availability_answer`):

```python
def format_schedule(schedules, *, timezone) -> str:
    if not schedules:
        return "No schedule to show."
    single = len(schedules) == 1
    lines: list[str] = []
    for day in schedules:
        header = day.date.strftime("%a, %b %d") + f" — {_status_label(day.status)}"
        lines.append(header)
        if single:
            for event in day.timed_events:
                start = event.start_at.astimezone(timezone).strftime("%H:%M")
                end = event.end_at.astimezone(timezone).strftime("%H:%M")
                lines.append(f"  {start}–{end}  {event.title}")
            for event in day.all_day_events:
                lines.append(f"  (all day)   {event.title}")
            if not day.timed_events and not day.all_day_events:
                lines.append("  No events")
            if day.free_slots:
                windows = ", ".join(
                    f"{s.astimezone(timezone).strftime('%H:%M')}–{e.astimezone(timezone).strftime('%H:%M')}"
                    for s, e in day.free_slots
                )
                lines.append(f"  Free: {windows}")
        else:
            count = len(day.timed_events)
            free = ", ".join(
                f"{s.astimezone(timezone).strftime('%H:%M')}–{e.astimezone(timezone).strftime('%H:%M')}"
                for s, e in day.free_slots
            ) or "none"
            lines.append(f"  {count} event(s); free: {free}")
        lines.append("")
    return "\n".join(lines).strip()


def _status_label(status) -> str:
    return {
        "fully_available": "free",
        "partly_available": "partly free",
        "busy": "busy",
    }.get(getattr(status, "value", status), str(status))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/telegram/test_format_schedule.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/telegram/adapter.py tests/telegram/test_format_schedule.py
git commit -m "feat: add format_schedule renderer"
```

---

## Task 5: Route the availability/schedule intent to the rich view

**Files:**
- Modify: `src/personal_hermes/router.py` (the availability handling in `handle_event` — both branches — and `_looks_like_availability_question`)
- Test: `tests/e2e/test_assistant_pipeline.py`

**Context:** the router currently does, in both branches, `if _looks_like_availability_question(event.text): result = self.calendar_service.availability_for(...); self.telegram.send_message(... format_availability_answer(...))`. Replace those with `schedule_for` + `format_schedule`, and import `format_schedule`. Expand the trigger words.

- [ ] **Step 1: Update the existing availability e2e test + add a "what's on" trigger test**

In `tests/e2e/test_assistant_pipeline.py`, `test_telegram_calendar_question_returns_availability_answer` currently asserts `"Fully available:" in ...`. Update it to assert the new rich format instead — e.g. that the reply contains the day header and either an event line or "No events"/"Free". Concretely, change the assertions to:
```python
    assert len(telegram.sent_messages) == 1
    text = telegram.sent_messages[0]["text"]
    assert "Free:" in text or "No events" in text
```
And add a test that "what's on my calendar today?" triggers the same path (asserts a non-empty schedule reply).

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/e2e/test_assistant_pipeline.py -k "calendar_question or whats_on" -v`
Expected: FAIL (still emitting the old `availability_for` format / new trigger not recognized).

- [ ] **Step 3: Implement**

In `src/personal_hermes/router.py`:
- Add `format_schedule` to the import from `personal_hermes.telegram.adapter`.
- Replace BOTH availability blocks (single-user and multi-user) so they call:
```python
            if _looks_like_availability_question(event.text):
                schedules = self.calendar_service.schedule_for(
                    event.text, today=now.date(), user_id=user_id  # user_id=None in single-user branch
                )
                self.telegram.send_message(
                    chat_id=event.chat_id,
                    text=format_schedule(schedules, timezone=self.calendar_service.timezone),
                )
                return
```
(In the single-user branch pass `user_id=None`; in the multi-user branch pass `user_id=user.id`. `self.calendar_service.timezone` already exists.)
- Expand `_looks_like_availability_question` markers to include schedule phrasing:
```python
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
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `python -m pytest tests/e2e/test_assistant_pipeline.py -k "calendar_question or whats_on" -v && python -m pytest -q`
Expected: the targeted tests PASS; full suite all green (no new failures).

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/router.py tests/e2e/test_assistant_pipeline.py
git commit -m "feat: route schedule/availability questions to events + free slots view"
```

---

## Task 6: Real-gog verification

- [ ] **Step 1** Restart the app onto this code; in Telegram send "what's on my calendar today?" and confirm it lists your real events + free windows (create a throwaway event first if your day is empty, then delete it).
- [ ] **Step 2** Try "am I free this week?" and confirm the compact per-day format renders.

---

## Notes
- All-day events are informational (shown, never block free slots) — this changes the old "any all-day ⇒ BUSY" behavior, by design (see spec).
- `availability_for` may now be unused; if so, a follow-up can remove it (and `classify_day` if it has no other callers). Leave them if anything still imports them.
- Plan 2 (Cancel + Edit) builds the write flows on top of this Read view.
