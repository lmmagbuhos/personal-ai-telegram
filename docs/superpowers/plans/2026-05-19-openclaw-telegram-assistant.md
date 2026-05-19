# OpenClaw Telegram Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user Python Telegram assistant that uses OpenClaw to access Gmail and Google Calendar, polls for updates, sends Telegram notifications, answers availability questions, and sends approved email replies.

**Architecture:** A long-running Python service with focused adapters and services. Telegram, OpenClaw, scheduling, and persistence are separated so polling can later be replaced with webhooks without rewriting assistant logic.

**Tech Stack:** Python 3.11+, SQLite, pytest, python-dotenv, pydantic-settings, python-telegram-bot or direct Telegram HTTP client, httpx, APScheduler or asyncio scheduler.

---

## Phase 0: Project Bootstrap

**Purpose:** Create the Python project skeleton, dependency management, test harness, and configuration loading.

**Files:**

- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/personal_hermes/__init__.py`
- Create: `src/personal_hermes/config.py`
- Create: `tests/test_config.py`

**Tasks:**

- [ ] Create package metadata and dependencies in `pyproject.toml`.
- [ ] Add `.env.example` with every config key from the design spec and safe sample values.
- [ ] Add `.gitignore` for `.env`, SQLite databases, Python caches, virtualenvs, and test artifacts.
- [ ] Implement `Settings` in `src/personal_hermes/config.py` using environment variables.
- [ ] Write config tests for defaults: timezone `Asia/Manila`, Gmail polling `300`, calendar polling `300`, agenda time `08:00`, reminder lead `30`, pending reply expiry `7`.
- [ ] Run `python -m pytest tests/test_config.py -v`.
- [ ] Commit with message `chore: bootstrap Python assistant project`.

**Acceptance Criteria:**

- `python -m pytest` runs successfully.
- No secrets are committed.
- A developer can copy `.env.example` to `.env` and see all required variables.

---

## Phase 1: Verify OpenClaw API Surface

**Purpose:** Confirm exact OpenClaw endpoints, auth method, request/response formats, and whether Gmail/Calendar operations are direct API calls, tool calls, or SDK calls.

**Files:**

- Create: `docs/openclaw-api-notes.md`
- Create: `src/personal_hermes/openclaw/types.py`
- Create: `src/personal_hermes/openclaw/client.py`
- Create: `tests/openclaw/test_client_contract.py`

**Tasks:**

- [ ] Inspect current OpenClaw docs and account/API credentials available to the project.
- [ ] Record confirmed Gmail read, Gmail send, Gmail mark-read, Calendar list-events, and Calendar event fields in `docs/openclaw-api-notes.md`.
- [ ] Define stable internal dataclasses in `openclaw/types.py`: `EmailMessage`, `CalendarEvent`, `SendEmailReplyRequest`.
- [ ] Implement `OpenClawClient` method signatures only after confirming the API:
  - `list_new_inbox_messages(since_cursor: str | None) -> list[EmailMessage]`
  - `get_email_message(email_id: str) -> EmailMessage`
  - `send_thread_reply(request: SendEmailReplyRequest) -> str`
  - `mark_email_read(email_id: str) -> None`
  - `list_calendar_events(start_at: datetime, end_at: datetime) -> list[CalendarEvent]`
- [ ] Write mocked contract tests proving the client maps external OpenClaw responses into internal types.
- [ ] Run `python -m pytest tests/openclaw/test_client_contract.py -v`.
- [ ] Commit with message `feat: add OpenClaw client contract`.

**Acceptance Criteria:**

- The implementation no longer depends on guessed OpenClaw response shapes.
- All other phases can code against internal OpenClaw types without knowing external API details.

---

## Phase 2: SQLite State Store

**Purpose:** Persist deduplication records, pending replies, audit logs, reminders, agenda sends, and conversation state.

**Files:**

- Create: `src/personal_hermes/storage/schema.sql`
- Create: `src/personal_hermes/storage/store.py`
- Create: `tests/storage/test_store.py`

**Tasks:**

- [ ] Create SQLite schema for `seen_emails`, `pending_replies`, `reply_audit_log`, `calendar_agenda_notifications`, `calendar_reminders`, and `conversation_state`.
- [ ] Implement idempotent database initialization.
- [ ] Implement methods for seen-email tracking, pending reply lifecycle, audit logging, agenda deduplication, reminder deduplication, and conversation state.
- [ ] Write tests using temporary SQLite files.
- [ ] Run `python -m pytest tests/storage/test_store.py -v`.
- [ ] Commit with message `feat: add SQLite state store`.

**Acceptance Criteria:**

- Duplicate emails, agenda messages, and calendar reminders can be detected reliably.
- Pending replies can transition through `pending`, `sent`, `failed`, `ignored`, and `expired`.

---

## Phase 3: Telegram Adapter And Authorization

**Purpose:** Add Telegram polling, outbound messages, inline buttons, and strict single-user authorization.

**Files:**

- Create: `src/personal_hermes/telegram/types.py`
- Create: `src/personal_hermes/telegram/adapter.py`
- Create: `tests/telegram/test_authorization.py`
- Create: `tests/telegram/test_adapter_formatting.py`

**Tasks:**

- [ ] Define internal Telegram event types for user messages and callback button actions.
- [ ] Implement authorization checks using configured chat ID and user ID.
- [ ] Implement message formatting helpers for email notifications, sent-reply confirmations, daily agendas, event reminders, and availability answers.
- [ ] Implement adapter methods for polling updates, sending messages, editing messages, answering callbacks, and sending inline buttons.
- [ ] Write tests for authorized and unauthorized message/callback handling.
- [ ] Write formatting tests that assert required email/calendar fields appear in Telegram text.
- [ ] Run `python -m pytest tests/telegram -v`.
- [ ] Commit with message `feat: add Telegram adapter`.

**Acceptance Criteria:**

- Unauthorized Telegram users cannot trigger any assistant behavior.
- Email notifications include inline buttons for `Send reply`, `Edit reply`, `Ignore`, and `Mark read`.

---

## Phase 4: Calendar Availability Service

**Purpose:** Answer Telegram availability questions based on Google Calendar events.

**Files:**

- Create: `src/personal_hermes/calendar/availability.py`
- Create: `src/personal_hermes/calendar/service.py`
- Create: `tests/calendar/test_availability.py`
- Create: `tests/calendar/test_calendar_service.py`

**Tasks:**

- [ ] Implement date-range parsing for `today`, `tomorrow`, weekday names, and `this week`.
- [ ] Implement availability classification using 9 AM-5 PM `Asia/Manila` and a 2-hour minimum free block.
- [ ] Treat Monday through Sunday as the range for `this week`.
- [ ] Normalize event times to the configured timezone before classification.
- [ ] Write tests for fully available, partly available, busy, all-day events, overlapping events, and events outside working hours.
- [ ] Run `python -m pytest tests/calendar/test_availability.py tests/calendar/test_calendar_service.py -v`.
- [ ] Commit with message `feat: add calendar availability service`.

**Acceptance Criteria:**

- The service classifies days exactly as approved in the design spec.
- Calendar availability can be tested without Telegram or OpenClaw network calls.

---

## Phase 5: Calendar Agenda And Reminder Polling

**Purpose:** Notify the user every day at 8:00 AM and 30 minutes before upcoming events.

**Files:**

- Create: `src/personal_hermes/calendar/notifications.py`
- Create: `tests/calendar/test_notifications.py`

**Tasks:**

- [ ] Implement daily agenda generation for events scheduled on the current local date.
- [ ] Implement agenda deduplication using `calendar_agenda_notifications`.
- [ ] Implement upcoming-event detection using the configured reminder lead time.
- [ ] Implement reminder deduplication using `event_id` plus `event_start_at`.
- [ ] Write tests for agenda sent once per day, no duplicate 30-minute reminders, changed event start time, and empty-day agenda behavior.
- [ ] Run `python -m pytest tests/calendar/test_notifications.py -v`.
- [ ] Commit with message `feat: add calendar notification service`.

**Acceptance Criteria:**

- The daily agenda is sent once per date.
- An event reminder is sent once per event start time when it falls inside the reminder window.

---

## Phase 6: Gmail Polling And Notifications

**Purpose:** Poll all new inbox emails and notify the user in Telegram once per email/thread.

**Files:**

- Create: `src/personal_hermes/mail/service.py`
- Create: `src/personal_hermes/mail/summarizer.py`
- Create: `tests/mail/test_mail_polling.py`
- Create: `tests/mail/test_summarizer.py`

**Tasks:**

- [ ] Implement email deduplication against `seen_emails`.
- [ ] Implement compact summaries from email sender, subject, and plain-text body.
- [ ] Implement reply-worthiness detection for version 1:
  - reply-worthy when the email contains a direct question, request, invitation, scheduling language, or asks for confirmation;
  - not reply-worthy for newsletters, receipts, automated alerts, and no-reply senders.
- [ ] Generate a conservative suggested reply when reply-worthy.
- [ ] Store suggested replies as pending actions with 7-day expiry.
- [ ] Send Telegram notifications for all new inbox emails, including those without suggested replies.
- [ ] Write tests for all-new-email notifications, duplicate suppression, reply-worthy detection, and no-reply/newsletter suppression of suggestions.
- [ ] Run `python -m pytest tests/mail -v`.
- [ ] Commit with message `feat: add Gmail polling notifications`.

**Acceptance Criteria:**

- Every new inbox email produces one Telegram notification.
- Suggested replies are created only when there is a plausible reason to reply.
- Duplicate polling cycles do not duplicate Telegram notifications.

---

## Phase 7: Email Reply Approval And Edit Flow

**Purpose:** Send Gmail replies only after explicit Telegram approval, with optional edit-before-send.

**Files:**

- Create: `src/personal_hermes/mail/actions.py`
- Create: `tests/mail/test_reply_actions.py`
- Modify: `src/personal_hermes/storage/store.py`
- Modify: `src/personal_hermes/telegram/adapter.py`

**Tasks:**

- [ ] Implement `Send reply` callback handling.
- [ ] Validate Telegram authorization before loading pending reply state.
- [ ] Reject expired, already sent, ignored, or missing pending replies.
- [ ] Call `OpenClawClient.send_thread_reply`.
- [ ] Record `reply_audit_log`.
- [ ] Mark pending reply as `sent`.
- [ ] Implement `Ignore` callback to mark pending reply as `ignored`.
- [ ] Implement `Mark read` callback to call OpenClaw Gmail mark-read and update Telegram.
- [ ] Implement `Edit reply` state transition in `conversation_state`.
- [ ] Accept the next authorized Telegram text message as the edited reply.
- [ ] Show `Send edited reply` and `Cancel` buttons.
- [ ] Write tests for send success, unauthorized callback rejection, expired reply rejection, duplicate send rejection, ignore, mark read, edit, cancel, and send edited reply.
- [ ] Run `python -m pytest tests/mail/test_reply_actions.py -v`.
- [ ] Commit with message `feat: add email reply approval flow`.

**Acceptance Criteria:**

- No email can be sent without a valid Telegram callback from the configured user.
- Edited replies replace the original pending reply only after the user submits replacement text.

---

## Phase 8: Assistant Router

**Purpose:** Connect Telegram events to calendar, Gmail, and action services.

**Files:**

- Create: `src/personal_hermes/router.py`
- Create: `tests/test_router.py`

**Tasks:**

- [ ] Route calendar availability messages to `CalendarService`.
- [ ] Route callback data for email actions to `MailActionService`.
- [ ] Route edit-flow messages based on `conversation_state`.
- [ ] Respond with a concise fallback message for unsupported commands.
- [ ] Write tests for calendar question routing, callback routing, edit-flow routing, unauthorized event rejection, and fallback behavior.
- [ ] Run `python -m pytest tests/test_router.py -v`.
- [ ] Commit with message `feat: add assistant router`.

**Acceptance Criteria:**

- Telegram update handling is centralized.
- Services remain testable without Telegram polling.

---

## Phase 9: Scheduler And App Entrypoint

**Purpose:** Run Telegram polling, Gmail polling, daily agenda, and reminder checks as one service.

**Files:**

- Create: `src/personal_hermes/scheduler.py`
- Create: `src/personal_hermes/app.py`
- Create: `src/personal_hermes/__main__.py`
- Create: `tests/test_scheduler.py`

**Tasks:**

- [ ] Implement scheduler jobs for Gmail polling every `GMAIL_POLL_INTERVAL_SECONDS`.
- [ ] Implement scheduler jobs for calendar reminders every `CALENDAR_POLL_INTERVAL_SECONDS`.
- [ ] Implement daily agenda trigger at `DAILY_AGENDA_TIME` in configured timezone.
- [ ] Implement Telegram polling loop using `TELEGRAM_POLL_INTERVAL_SECONDS`.
- [ ] Implement graceful shutdown on SIGINT/SIGTERM.
- [ ] Write scheduler tests using fake clock or injected time provider.
- [ ] Run `python -m pytest tests/test_scheduler.py -v`.
- [ ] Commit with message `feat: add assistant runtime scheduler`.

**Acceptance Criteria:**

- Running `python -m personal_hermes` starts the assistant process.
- Scheduler jobs can be tested without waiting in real time.

---

## Phase 10: End-To-End Local Dry Run

**Purpose:** Prove the pipeline with mocked OpenClaw and Telegram clients before connecting real credentials.

**Files:**

- Create: `tests/e2e/test_assistant_pipeline.py`
- Create: `scripts/run_local_dry_run.py`

**Tasks:**

- [ ] Build fake Telegram and OpenClaw clients for deterministic local runs.
- [ ] Test Telegram calendar question to availability response.
- [ ] Test Gmail poll to Telegram notification.
- [ ] Test Telegram `Send reply` callback to OpenClaw send call.
- [ ] Test Telegram edit flow to OpenClaw send call.
- [ ] Test calendar reminder poll to Telegram reminder.
- [ ] Run `python -m pytest tests/e2e/test_assistant_pipeline.py -v`.
- [ ] Run `python scripts/run_local_dry_run.py`.
- [ ] Commit with message `test: add assistant dry-run pipeline`.

**Acceptance Criteria:**

- The full assistant behavior is proven without external network calls.
- Failures identify the component that broke instead of failing as one opaque loop.

---

## Phase 11: Real Credential Smoke Test

**Purpose:** Connect the app to the real Telegram bot and OpenClaw account with safe, limited actions.

**Files:**

- Modify: `README.md`
- Create: `docs/operations/smoke-test.md`

**Tasks:**

- [ ] Document how to create Telegram bot token and identify authorized chat/user IDs.
- [ ] Document how to configure OpenClaw credentials.
- [ ] Start the assistant with real `.env`.
- [ ] Send a Telegram availability question and verify Calendar response.
- [ ] Send a controlled test email to the connected Gmail account and verify Telegram notification.
- [ ] Use `Ignore` on the first real test email.
- [ ] Send a second controlled test email that expects a reply.
- [ ] Use `Edit reply`, submit a harmless edited reply, and press `Send edited reply`.
- [ ] Verify the reply appears in Gmail.
- [ ] Verify no full email body appears in logs.
- [ ] Commit with message `docs: add smoke test procedure`.

**Acceptance Criteria:**

- Real Telegram and OpenClaw credentials work.
- At least one controlled Gmail reply is sent only after explicit Telegram approval.
- Logs do not expose full email bodies by default.

---

## Phase 12: Server Runbook

**Purpose:** Make the service repeatable to run on this server.

**Files:**

- Create: `docs/operations/server-runbook.md`
- Create: `deployment/personal-hermes.service.example`
- Modify: `README.md`

**Tasks:**

- [ ] Document direct development startup command.
- [ ] Add sample `systemd` unit that runs `python -m personal_hermes`.
- [ ] Document where `.env` should live on the server.
- [ ] Document how to view logs.
- [ ] Document how to restart the service.
- [ ] Document how to change polling intervals.
- [ ] Document webhook upgrade notes and which adapters would change.
- [ ] Commit with message `docs: add server runbook`.

**Acceptance Criteria:**

- The assistant can be restarted after server reboot using documented steps.
- Polling intervals can be changed without code edits.

---

## Final Verification

Run these commands before declaring implementation complete:

```bash
python -m pytest -v
python -m personal_hermes --check-config
git status --short
```

Expected results:

- All tests pass.
- Config check reports required secrets are present or clearly identifies missing ones.
- Git status only shows intentional uncommitted operational files such as a local `.env`, if any.

## Phase Dependencies

- Phase 0 must happen first.
- Phase 1 must happen before real OpenClaw integration work.
- Phase 2 must happen before Gmail or Calendar deduplication.
- Phases 3, 4, 5, and 6 can be implemented after Phase 2.
- Phase 7 depends on Phases 2, 3, and 6.
- Phase 8 depends on Phases 3, 4, and 7.
- Phase 9 depends on Phases 5, 6, and 8.
- Phase 10 depends on Phase 9.
- Phase 11 depends on Phase 10.
- Phase 12 can begin after Phase 9 and finish after Phase 11.

## Self-Review

- Spec coverage: The plan covers Telegram polling, OpenClaw Gmail/Calendar access, calendar availability, daily agenda, 30-minute reminders, Gmail notifications, suggested replies, inline approval, edit-before-send, SQLite state, safety rules, tests, and server operations.
- Scope check: The plan keeps the first version single-user and polling-based. Multi-user support, public HTTPS webhooks, Gmail Pub/Sub, billing, and dashboards remain out of scope.
- Type consistency: The OpenClaw internal types are introduced before service code depends on them. Storage states are defined before reply actions use them.

