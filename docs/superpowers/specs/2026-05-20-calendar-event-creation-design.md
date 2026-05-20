# Calendar Event Creation via Telegram — Design

## Overview

Let a connected user create a Google Calendar event by messaging the bot in
free-form text (e.g. *"appointment today 9AM-9:30AM dentist"*). The bot extracts
the event details, asks the user to confirm, and on confirmation writes the event
to the user's primary calendar using their per-user OAuth token.

The primary goal of this iteration is to **prove the end-to-end write pipeline**:
Telegram message → parse → confirm → event created in the real calendar. The
free-form parser is intentionally a rule-based MVP and is designed to be replaced
by an LLM natural-language parser in a later, unified change (see Future Work).

## Scope

### In Scope
- Detect a create-event intent in a free-form Telegram message.
- Rule-based extraction of: title, start time, end time (tz-aware), for common
  phrasings (`today`/`tomorrow`/weekday + a time range, with a default duration
  when no end is given).
- A confirm-before-write step using inline Confirm/Cancel buttons (mirrors the
  existing email-reply approval flow).
- Create the event on the user's `primary` calendar via the `gog calendar create`
  command, using the per-user OAuth access token.
- Add the `calendar.events` OAuth scope (write) and require re-consent.

### Out of Scope (deferred)
- LLM / natural-language parsing (this MVP is rule-based; the parser interface is
  the seam for the later LLM swap).
- Per-user timezones (single configured `TIMEZONE` is used for now).
- Recurring events, attendees, location, reminders, event color.
- Editing or deleting existing events.

## Design Decisions (settled during brainstorming)
- **Parsing:** rule-based, free-form, best-effort now; swappable for an LLM later.
  Main goal is proving the pipeline, not parser sophistication.
- **Safety:** confirm-before-write with inline buttons (creating an event is a
  mutating action, and rule-based parsing can misread input).
- **Architecture:** mirror the existing email-reply flow (`MailActionService` +
  `pending_replies` table + router callback handling).
- **Scope:** keep `calendar.readonly` (needed for gog's CalendarList resolution)
  and add `calendar.events` (least privilege; full `calendar` would over-grant).

## Components

1. **`src/personal_hermes/calendar/event_request.py` — parser (swappable seam)**
   - `parse_event_request(text, *, now, tz) -> EventDraft | None`
   - `EventDraft = {title: str, start_at: datetime, end_at: datetime}` (tz-aware).
   - Returns `None` when the text is not a create-event request, so the router
     falls through to existing handlers (availability, generic help).
   - Rule-based: trigger words (`appointment`, `schedule`, `meeting`, `book`,
     `add event`, `create event`); date (`today`/`tomorrow`/weekday); time range
     (`9AM-9:30AM`, `9:00-9:30`, `at 9am for 30 min`); default 60-minute duration
     when only a start is given; title = remaining text.
   - The signature/return type are the interface the future LLM parser implements.

2. **`src/personal_hermes/calendar/actions.py` — `CalendarActionService`**
   (parallel to `MailActionService`)
   - `prepare_event(user_id, draft, now)` → stores a pending draft, returns its id.
   - `confirm_event(callback, *, user_id, now)` → loads the draft, resolves the
     user's access token, calls the gog create, replies success/failure, clears
     the pending draft.
   - `cancel_event(callback, *, user_id, now)` → clears pending, acknowledges.

3. **`OpenClawClient.create_calendar_event(draft)`** — new method wrapping
   `gog calendar create primary --summary <title> --from <RFC3339>
   --to <RFC3339> --start-timezone <tz> --end-timezone <tz> --json --no-input`,
   using the existing `with_access_token(token)` to pass the per-user token.

4. **`pending_calendar_events` table** (mirrors `pending_replies`):
   `id, user_id, title, start_at, end_at, timezone, status, created_at,
   expires_at, telegram_message_id`. Store methods:
   `create_pending_calendar_event`, `get_pending_calendar_event`,
   `mark_pending_calendar_event_status` (or delete). Short TTL (~15 minutes).

5. **Router wiring** (`router.py`, multi-user path)
   - Message path: after the existing email edit-flow handler
     (`_handle_edit_flow_message`) and **before** the availability check, call
     `parse_event_request`. If it returns a draft → `prepare_event` → send a
     confirmation message with Confirm/Cancel buttons
     (`callback_data`: `cal_confirm:<id>`, `cal_cancel:<id>`), then return.
   - Callback path: extend `_handle_callback` to route `cal_confirm:` /
     `cal_cancel:` prefixes to `CalendarActionService` (the existing mail-reply
     callbacks keep their current routing).
   - Ordering rationale: edit-flow first (don't interrupt an in-progress email
     edit), then create-intent; if the parser returns `None`, fall through to the
     availability check and then the generic help reply (existing behavior
     unchanged).

6. **OAuth scope** (`oauth/google.py`): add
   `https://www.googleapis.com/auth/calendar.events` to `GOOGLE_OAUTH_SCOPES`;
   update scope tests; users must re-`/connect`. The existing `_granted_scopes`
   check enforces that a user who hasn't re-consented cannot create events yet.

## Data Flow

1. User: *"appointment today 9AM-9:30AM dentist"* (multi-user, active account).
2. Router: not a command → `parse_event_request` →
   `EventDraft(title="dentist", 09:00–09:30 Asia/Manila)`.
3. `prepare_event` stores the pending draft (TTL ~15 min).
4. Bot replies: *"Create 'dentist' today 09:00–09:30 (Asia/Manila)? [Confirm]
   [Cancel]"*.
5. Confirm tapped → callback routed by prefix → `confirm_event` → resolve token →
   `OpenClawClient.with_access_token(token).create_calendar_event(draft)` →
   `gog calendar create`.
6. On success: edit the confirmation message to *"✅ Created 'dentist' today
   09:00–09:30"*; clear pending. On Cancel: clear pending, acknowledge.

## Timezone

Resolve relative phrasing ("today 9AM") against the configured `TIMEZONE`
(Asia/Manila) to produce tz-aware datetimes. Per-user timezones are future work.

## Error Handling

Every failure produces a clear Telegram reply — never silence:
- Parser returns `None` → not a create request; falls through (no error).
- Create-intent detected but time unparseable → hint: *"I couldn't read the time —
  try 'appointment today 9-9:30'."*
- Confirm tapped but pending draft expired/missing → *"That request expired,
  please send it again."*
- No active Google account → existing *"Connect Google first with /connect."*
- `gog`/Google write fails → *"Couldn't create the event right now."* (pending
  cleared so it can't half-apply); underlying error logged.
- Confirm/Cancel are idempotent: a second tap after completion reports it's already
  handled.

## Testing (TDD, mirroring existing structure)

- `tests/calendar/test_event_request.py` — parser: varied phrasings,
  today/tomorrow/weekday, time ranges, default duration, and **non-matching text
  returns `None`** (so other messages are not hijacked).
- `tests/calendar/test_calendar_actions.py` — `prepare` stores the draft;
  `confirm` resolves the token and calls the client with correct RFC3339 args +
  timezone; `cancel` clears.
- `tests/openclaw/` — `create_calendar_event` builds the exact `gog` arg list
  (mocked command runner).
- `tests/e2e/` — message → confirmation sent; Confirm → event created; Cancel →
  cleared; expired draft handled.

## Future Work
- Replace the rule-based `parse_event_request` with an LLM (Claude API) parser
  behind the same interface — part of the planned unified natural-language layer
  that will also cover availability questions and email actions.
- Per-user timezones; recurring events; attendees/location/reminders; edit/delete.
