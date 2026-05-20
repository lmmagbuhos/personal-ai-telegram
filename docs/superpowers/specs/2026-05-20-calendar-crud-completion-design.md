# Calendar CRUD Completion — Design

## Overview

Round out the bot's calendar capabilities to full CRUD. Create already exists.
This adds:
- **Read (enhanced):** an on-demand "show my schedule" that lists each day's
  actual events *and* the computed free time slots — replacing today's bare
  free/busy-days answer.
- **Update (full edit):** reschedule an event, or change its title, location, or
  description — selected from a list, confirmed before applying.
- **Delete (cancel):** cancel an event, selected from a list, confirmed first.

Purpose alignment: this is a **personal** Telegram assistant for managing the
user's *own* Gmail and Calendar. Suggestions are limited to everyday personal
calendar actions; enterprise/admin `gog` features (calendar sharing, ACLs,
workspace-user/team listings, working-location) are intentionally excluded.

Parsing stays **thin and rule-based** (a swappable seam); the durable work is the
actions and flows, which will later be driven by an LLM intent layer.

## Scope

### In Scope
- Enhanced read: per-day events (timed + all-day) + free slots; single-day full
  detail, week-range compact summary.
- Full edit (reschedule / retitle / location / description) via a guided,
  button-driven, confirm-before-write flow with event selection from a list.
- Cancel (delete) via list selection + confirmation.
- `gog calendar update` and `gog calendar delete` wrappers (per-user token).

### Out of Scope (deferred)
- LLM / natural-language parsing (parsers stay thin and swappable).
- Recurring-event edits, attendee management.
- Per-user timezones (single configured `TIMEZONE` for now).

## Design Decisions (confirmed during brainstorming)
- **All-day events are informational:** shown in the schedule and selectable for
  edit/cancel, but they do **not** block free-slot computation (changes today's
  "any all-day event ⇒ BUSY" behavior). Free slots are computed from *timed*
  events only.
- **Week-range read is compact:** single-day queries get full per-event detail;
  week queries get a compact per-day block (status + counts + free windows).
- **Event selection is tap-from-a-list:** the user references a day; the bot
  lists that day's events as inline buttons; the user taps one. (No brittle
  NL matching.)
- **Multi-step flow uses `conversation_state`** (no new table); its JSON payload
  holds the in-flight session.

## Components

### Read
- **`calendar/availability.py`** — add:
  - `free_slots(*, target_date, events, timezone, workday_start, workday_end,
    min_free_block_minutes) -> list[tuple[datetime, datetime]]`: extends the
    existing `classify_day` cursor-walk to *collect* gaps ≥ the threshold,
    reusing `_busy_ranges()` (which already clips to the workday and merges
    overlaps). Uses **timed** events only.
  - `day_schedule(...) -> DaySchedule`: returns events split into all-day vs
    timed (sorted), the free slots, and the existing status label.
  - `DaySchedule` dataclass: `{date, all_day_events, timed_events, free_slots,
    status}`.
- **`CalendarService.schedule_for(text, *, today, user_id) -> list[DaySchedule]`**
  — parses the date range (existing `parse_date_range`), fetches events once via
  the user's token (existing path), builds a `DaySchedule` per day. No new gog
  call. `schedule_for` becomes the router's calendar-read entry point;
  `availability_for` is removed if it has no remaining callers, otherwise kept as
  a thin internal helper.
- **Schedule formatter** — a new `format_schedule(...)` alongside the existing
  `format_availability_answer` in `telegram/adapter.py` (the module the current
  availability answer already uses): single-day full detail; week-range compact.
  Display-only (no buttons).
- **Router:** the existing availability intent now routes to `schedule_for` +
  the rich formatter; trigger words expand to include
  `schedule / agenda / what's on / what do I have` alongside the current
  availability words.

### Write (gog wrappers — `OpenClawClient`)
Both use the per-user `--access-token` and unwrap the `{"event": {...}}`
envelope (same as create), and pass the explicit IANA `--start-timezone`:
- `update_calendar_event(*, event_id, summary=None, start_at=None, end_at=None,
  location=None, description=None, timezone=None) -> CalendarEvent`
  → `gog calendar update primary <eventId> [--summary …] [--from …] [--to …]
  [--location …] [--description …] [--start-timezone …] [--end-timezone …]
  --json --no-input` (only flags for changed fields).
- `delete_calendar_event(*, event_id) -> None`
  → `gog calendar delete primary <eventId> --json --no-input -y` (`-y` skips
  gog's own destructive prompt; the Telegram Confirm is the real gate).

### Write flow — `CalendarEditService`
A small state machine in `conversation_state` (payload is JSON). Router routes
`cal_*` callbacks and the in-flight value-input message to it.

**Cancel:**
1. "cancel an event today" → fetch that day's events → none ⇒ "No events on
   \<day\>."; else list as buttons (`cal_pick:<idx>`); session
   `{op:"cancel", candidates:[{id,summary,start,end}…]}`.
2. Tap event → Confirm/Cancel ("Cancel 'Client call' 14:00–15:00?");
   session holds the chosen event.
3. Confirm → resolve token → `delete_calendar_event` → "Cancelled." → clear
   session. Cancel → discard.

**Edit:**
1. "edit an event today" → same selection list (`op:"edit"`).
2. Tap event → field buttons: Time / Title / Location / Description.
3. Tap field → prompt "Send the new \<field>." and set `conversation_state` to
   await the value (reuses the email edit-flow value-capture pattern).
4. Reply → parse (Time → thin time parser: new start keeps original duration, or
   `start–end` range; Title/Location/Description → raw text) → Confirm
   ("Change time to 15:00–16:00?").
5. Confirm → `update_calendar_event` with only that field → "Updated." → clear
   session.

**Callback verbs:** `cal_pick:<idx>`, `cal_del_ok` / `cal_del_no`,
`cal_field:<field>`, `cal_edit_ok` / `cal_edit_no`. The session carries the data
so callback payloads stay tiny.

**Router additions:** message-path detects the edit/cancel intent (thin trigger:
`edit/change/reschedule/cancel/delete` + optional day) and the in-flight
"awaiting edit value" text input; callback-path routes `cal_*` to
`CalendarEditService`. Ordering: command → callback → in-flight value input →
create → edit/cancel → schedule/availability → fallback.

## Data Flow (summary)
- **Read:** message → schedule/availability intent → `schedule_for` (fetch +
  per-day `day_schedule`) → formatter → one message.
- **Cancel:** "cancel \<day\>" → list → tap → confirm → `delete_calendar_event`.
- **Edit:** "edit \<day\>" → list → tap → field → value → confirm →
  `update_calendar_event`.

## Error Handling (every failure → a clear reply; never silent)
- No events on the day → "No events on \<day\>."
- Expired/cleared session on tap/confirm → "That selection expired — start again."
- Unparseable new time → "I couldn't read that time — send e.g. `3pm` or
  `3-3:30pm`." (stay in the value step to retry).
- No active Google account → existing "Connect Google first with /connect."
- gog update/delete failure → "Couldn't update/cancel the event right now."
  (session cleared so it can't half-apply); underlying error is logged.
- Confirm/Cancel idempotent: a second tap after completion reports already handled.

## Edge Cases
- All-day events: listed + selectable, never block free slots.
- Stale selection (event changed/deleted in Google since listing): gog errors →
  surfaced gracefully.
- Timezone: edits pass the explicit stored IANA `--start-timezone` (the fix from
  the create feature), never the round-tripped offset.
- Reschedule duration: new start only → keep original duration; `start–end` → use
  it.
- One in-flight session per user (conversation_state is single-slot): starting a
  new edit/cancel replaces an abandoned one.

## Testing (TDD)
- `calendar/availability.py`: `free_slots` / `day_schedule` — gaps, merges,
  all-day informational, empty day, outside-workday events, min-block filtering.
- `OpenClawClient`: `update_calendar_event` / `delete_calendar_event` build exact
  `gog` args (mocked runner), envelope unwrapped.
- `CalendarEditService`: full state machine — select → field → value → confirm →
  update; select → confirm → delete; cancel paths; expired session; unparseable
  value.
- Router: edit/cancel intent shows the list; `cal_*` callbacks route correctly;
  value-input routes to the service; ordering does not hijack schedule/create.
- Real-gog verification: after unit tests, exercise update + delete against the
  live calendar with a connected token, then clean up test artifacts. (Mocks
  hid real bugs in the create feature — verifying against real `gog` is required.)

## Implementation Phasing
One spec; the implementation plan will sequence it so each phase is shippable:
1. Read enhancement (`free_slots` / `day_schedule` / `schedule_for` / formatter /
   router intent).
2. `gog` update + delete wrappers.
3. Cancel flow (`CalendarEditService` select → confirm → delete + router wiring).
4. Edit flow (field/value steps + confirm → update).
