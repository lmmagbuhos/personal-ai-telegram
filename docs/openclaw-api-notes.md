# OpenClaw API Notes

Date checked: 2026-05-19

## Decision

For this project, OpenClaw Gmail and Calendar access is through the official
OpenClaw Google Workspace `gog` skill/CLI surface, not direct Google Workspace REST
calls from application code.

The public OpenClaw docs describe skills as command/tool packages and list Google
Workspace support through `gog`. Public skill docs indicate `gog` is a CLI for
Gmail and Calendar operations and can return structured/json output.

References checked:

- https://www.getopenclaw.ai/docs/skills
- https://www.getopenclaw.ai/integrations/google-calendar

## Local Runtime Status

`gog` is not currently installed on `PATH` in this environment. Because of that,
real credential and smoke testing is blocked until the OpenClaw Google Workspace
skill and its `gog` CLI are installed and configured here.

Do not treat the Phase 1 adapter as runtime-complete until `gog --help` and the
exact Gmail/Calendar subcommands can be verified locally.

## Adapter Boundary

`OpenClawClient` isolates the OpenClaw dependency behind stable internal types so
later phases do not depend on CLI response shapes:

- `EmailMessage`
- `CalendarEvent`
- `SendEmailReplyRequest`

Application services should call only these methods:

- `list_new_inbox_messages(since_cursor: str | None) -> list[EmailMessage]`
- `get_email_message(email_id: str) -> EmailMessage`
- `send_thread_reply(request: SendEmailReplyRequest) -> str`
- `mark_email_read(email_id: str) -> None`
- `list_calendar_events(start_at: datetime, end_at: datetime) -> list[CalendarEvent]`

The client invokes an injectable command runner with argv lists. The default runner
uses `subprocess.run(...)` without `shell=True`, captures stdout, and parses JSON.
Tests inject a fake runner so command construction and JSON mapping remain
maintainable without requiring local OpenClaw credentials.

## Conservative CLI Contract

The exact `gog` command grammar has not been verified locally because the binary is
missing. Phase 1 therefore uses conservative, isolated command names that should be
confirmed or adjusted after `gog --help` is available:

- `gog gmail messages list --inbox --unread --format json --limit 25 [--since <cursor>]`
- `gog gmail messages get <email-id> --format json`
- `gog gmail messages reply --format json`
- `gog gmail messages mark-read <email-id> --format json`
- `gog calendar events list --format json --start <iso-datetime> --end <iso-datetime>`

Reply sending passes a structured JSON document to stdin with:

- `thread_id`
- `to`
- `cc`
- `bcc`
- `subject`
- `body_text`
- `in_reply_to`
- `references`

If installed `gog` uses different subcommands or payload field names, update only
`OpenClawClient` command construction and mapping helpers. The rest of the project
should continue to use the internal dataclasses.

## Mapping Expectations

Expected Gmail JSON fields are normalized into `EmailMessage`:

- `id`
- `thread_id` or `threadId`
- `subject`
- `sender` or `from`
- `to`
- `cc`
- `sent_at` or `sentAt`
- `snippet`
- `body_text`, `bodyText`, `body`, or `text`
- `is_unread`, `unread`, or labels containing `UNREAD`
- `message_id` or `messageId`
- `references`

Expected Calendar JSON fields are normalized into `CalendarEvent`:

- `id`
- `title` or `summary`
- `start_at` or `startAt`, with fallback to `start.dateTime` / `start.date`
- `end_at` or `endAt`, with fallback to `end.dateTime` / `end.date`
- `all_day` or `allDay`, with fallback to date-only start values
- `timezone` or `timeZone`
- `location`
- `description`
- `html_link`, `htmlLink`, or `url`
- `attendees`

## Explicit Non-Goals

This phase does not document or implement guessed proprietary REST endpoints. It
also does not implement direct Google Workspace REST calls, OAuth token refresh,
Gmail Pub/Sub watch/history flows, or credential discovery.
