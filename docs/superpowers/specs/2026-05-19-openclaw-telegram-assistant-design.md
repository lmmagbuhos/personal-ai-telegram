# OpenClaw Telegram Assistant Design

Date: 2026-05-19

## Goal

Build a single-user personal assistant that connects to one Google account through OpenClaw and uses Telegram as the communication surface.

The assistant should:

- Answer Google Calendar availability questions from Telegram.
- Send a daily Telegram agenda for the current day.
- Send Telegram reminders before upcoming calendar events.
- Notify the user about all new Gmail inbox messages.
- Summarize new emails and suggest replies when useful.
- Send an approved suggested reply through Gmail when the user presses a Telegram inline button.

The first version prioritizes a working end-to-end pipeline using polling. Webhooks can replace polling later without changing the assistant's core logic.

## Scope

### In Scope

- Single configured Telegram user/chat.
- Single connected Google account.
- Python service running continuously on the current server.
- Telegram long polling for inbound messages and inline button callbacks.
- Gmail polling through OpenClaw.
- Google Calendar polling through OpenClaw for daily agenda and reminders.
- Request-driven calendar availability checks.
- SQLite state store.
- Explicit user approval before sending any email reply.
- Basic edit-before-send flow in Telegram.

### Out of Scope

- Multi-user onboarding.
- Billing.
- Admin dashboard.
- Public HTTPS webhooks.
- Gmail native Pub/Sub integration.
- Automatic email sending without user approval.
- Full Gmail client replacement.

## Recommended Approach

Use a single Python service with polling.

This is the best fit for the first version because the product is single-user, the workspace is empty, and polling avoids public HTTPS setup while the assistant behavior is still being validated. Telegram and Gmail/Calendar event sources should be wrapped behind adapter interfaces so polling can later be replaced by webhooks.

## Architecture

The service is split into focused modules:

- `TelegramAdapter`: talks to Telegram, polls for messages, sends messages, sends inline buttons, receives callback actions.
- `OpenClawClient`: wraps Gmail and Google Calendar operations exposed by OpenClaw.
- `AssistantRouter`: routes inbound Telegram messages and callback actions to the right service.
- `CalendarService`: handles availability queries, daily agenda generation, and pre-event reminders.
- `MailService`: polls Gmail, deduplicates new messages, summarizes emails, prepares suggested replies, and sends approved replies.
- `StateStore`: SQLite persistence for seen emails, pending replies, reminder records, Telegram mappings, and audit logs.
- `Scheduler`: runs periodic jobs for Gmail polling, calendar reminder checks, daily agenda, and cleanup.

Internal event flow:

```text
source adapter -> normalized event -> assistant service -> state update -> Telegram response/action
```

This keeps the core behavior independent from whether events came from polling or webhooks.

## Runtime

The first version runs as a long-running Python process on the current server.

Initial operation can use a direct command during development. A later deployment step can add `systemd`, Docker, or another process manager so the service restarts automatically.

## Telegram Experience

Telegram is the only user interface.

The bot only accepts messages and button callbacks from the configured Telegram chat/user. All other inbound updates are ignored or logged at a minimal metadata level.

Example calendar questions:

- "What dates am I available this week?"
- "Am I free on Friday?"
- "What is my availability tomorrow?"

For new Gmail messages, the bot sends a compact notification:

- Sender
- Subject
- Short summary
- Suggested reply, if the email appears reply-worthy
- Inline buttons:
  - `Send reply`
  - `Edit reply`
  - `Ignore`
  - `Mark read`

Pressing `Send reply` immediately sends the stored suggested reply through Gmail via OpenClaw. The assistant never sends an AI-generated reply without an explicit Telegram button press.

The `Edit reply` button starts a Telegram edit flow:

1. The bot asks the user to type the replacement reply.
2. The next message from the authorized user is stored as the edited pending reply.
3. The bot shows a confirmation with `Send edited reply` and `Cancel`.
4. `Send edited reply` sends the edited text through Gmail.

## Gmail Flow

Gmail is polled through OpenClaw on a configurable interval, defaulting to 5 minutes.

For each new inbox email:

1. Fetch message metadata and enough body content for summary/reply generation.
2. Check SQLite for the email ID or thread ID to avoid duplicate Telegram notifications.
3. Store the email as seen.
4. Create a concise summary.
5. Generate a suggested reply only if the email appears reply-worthy.
6. Store the suggested reply as a pending action.
7. Send the Telegram notification with inline buttons.

When `Send reply` or `Send edited reply` is pressed:

1. Verify the Telegram chat/user is authorized.
2. Load the pending reply from SQLite.
3. Verify the pending reply has not expired and has not already been sent.
4. Send the reply to the original Gmail thread through OpenClaw.
5. Record an audit log entry.
6. Update the Telegram message to show the reply was sent.

Pending replies expire after a configurable period, defaulting to 7 days.

## Calendar Availability Flow

Availability questions are request-driven.

The default timezone is `Asia/Manila`. The default working window is 9:00 AM to 5:00 PM.

For "this week", the assistant interprets the range as Monday through Sunday in `Asia/Manila`.

Availability classifications:

- `Fully available`: no calendar events that day.
- `Partly available`: has events, but at least one free 2-hour block during working hours.
- `Busy`: no free 2-hour block during working hours.

Flow:

1. Parse the requested date or date range.
2. Fetch Google Calendar events for that range through OpenClaw.
3. Normalize all times to `Asia/Manila`.
4. Evaluate each date against the 9 AM-5 PM working window.
5. Reply in Telegram with a compact list of fully available, partly available, and busy dates.

## Calendar Notification Flow

Calendar notifications are scheduled.

Daily agenda:

- Every day at 8:00 AM `Asia/Manila`, fetch the day's events through OpenClaw.
- Send a Telegram agenda with event title, time, location or meeting link when available, and a short description note when available.
- Store an agenda notification record so the same day is not sent twice if the process restarts.

Upcoming event reminders:

- Poll upcoming calendar events on a configurable interval, defaulting to 5 minutes.
- If an event starts within the next 30 minutes, send a Telegram reminder.
- Store reminder records by event ID and start time to avoid duplicate reminders.
- If an event start time changes, treat the new start time as the current source of truth.

## Configuration

Use environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_AUTHORIZED_CHAT_ID`
- `TELEGRAM_AUTHORIZED_USER_ID`
- `OPENCLAW_API_KEY`
- `OPENCLAW_BASE_URL`
- `SQLITE_DATABASE_PATH`
- `TIMEZONE`, default `Asia/Manila`
- `WORKDAY_START`, default `09:00`
- `WORKDAY_END`, default `17:00`
- `MIN_FREE_BLOCK_MINUTES`, default `120`
- `TELEGRAM_POLL_INTERVAL_SECONDS`, default `2`
- `GMAIL_POLL_INTERVAL_SECONDS`, default `300`
- `CALENDAR_POLL_INTERVAL_SECONDS`, default `300`
- `DAILY_AGENDA_TIME`, default `08:00`
- `REMINDER_LEAD_MINUTES`, default `30`
- `PENDING_REPLY_EXPIRY_DAYS`, default `7`
- `DEBUG_EMAIL_BODY_LOGGING`, default `false`

Secrets must stay in `.env` or server-level secret storage and must not be committed.

## Data Model

SQLite tables:

- `seen_emails`
  - `email_id`
  - `thread_id`
  - `subject`
  - `sender`
  - `first_seen_at`
  - `telegram_message_id`
- `pending_replies`
  - `id`
  - `email_id`
  - `thread_id`
  - `reply_text`
  - `status`
  - `created_at`
  - `expires_at`
  - `telegram_message_id`
- `reply_audit_log`
  - `id`
  - `email_id`
  - `thread_id`
  - `recipient`
  - `subject`
  - `telegram_user_id`
  - `telegram_action_id`
  - `sent_at`
- `calendar_agenda_notifications`
  - `agenda_date`
  - `sent_at`
- `calendar_reminders`
  - `event_id`
  - `event_start_at`
  - `sent_at`
- `conversation_state`
  - `telegram_chat_id`
  - `state`
  - `payload_json`
  - `updated_at`

## Safety Rules

- Only the configured Telegram user/chat can use the assistant.
- Unknown Telegram users are ignored.
- Email replies are sent only after explicit inline button approval.
- A pending reply can be sent only once.
- Full email bodies are not logged unless debug logging is explicitly enabled.
- Every sent reply is recorded in an audit log.
- Expired pending replies cannot be sent.
- Callback actions must be validated against stored state, not trusted directly from Telegram payloads.

## Error Handling

- If OpenClaw is unavailable, notify the user only when a user-initiated action fails or when repeated background failures cross a threshold.
- If Gmail polling fails, keep the last successful checkpoint and retry on the next interval.
- If Calendar polling fails before the daily agenda, retry within the next scheduler cycle and avoid duplicate sends.
- If sending an approved email fails, keep the pending reply in a failed state and show a retry option.
- If Telegram sending fails, log metadata and retry transient errors where supported by the Telegram library.

## Testing

Unit tests:

- Calendar availability classification.
- Calendar daily agenda deduplication.
- Calendar 30-minute reminder deduplication.
- Gmail seen-email deduplication.
- Pending reply expiration.
- Send approval authorization.
- Edit-before-send state transitions.
- Router intent handling for calendar questions.

Integration-style tests with mocks:

- Telegram message to calendar answer.
- Gmail poll to Telegram notification.
- Telegram `Send reply` callback to OpenClaw Gmail send.
- Telegram edit flow to OpenClaw Gmail send.
- Calendar reminder poll to Telegram notification.

## OpenClaw Assumptions

The design assumes OpenClaw can expose Gmail read/send capabilities and Google Calendar read capabilities for the connected Google account. The implementation plan must verify the exact OpenClaw API surface before coding the client wrapper.

Reference docs reviewed during design:

- https://www.getopenclaw.ai/docs/skills
- https://openclaw.ai/

## Future Webhook Upgrade

Webhook support can be added later by replacing polling adapters:

- Telegram long polling can become a Telegram webhook endpoint.
- Gmail polling can become an OpenClaw or Google event callback if available.
- Calendar reminder polling may remain scheduled because reminders are time-based even if event sync becomes webhook-driven.

The internal normalized event pipeline should remain unchanged.

