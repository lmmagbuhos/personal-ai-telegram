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

`gog` v0.17.0 is installed on `PATH` in this environment:

```text
v0.17.0 (aee7460 2026-05-15T18:10:07Z)
```

The executable was installed from the upstream `openclaw/gogcli` Linux amd64
release. The archive checksum was verified against the release digest before
installing the binary to `~/.local/bin/gog`.

Credentials are not configured yet. `gog auth status --json --no-input` reports:

```json
{
  "config": {
    "exists": false,
    "path": "/home/claude-team/.config/gogcli/config.json"
  },
  "account": {
    "credentials_exists": false,
    "email": ""
  }
}
```

Real Gmail/Calendar smoke testing remains blocked until OAuth credentials and the
target Google account are configured.

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

## Verified CLI Contract

The following command grammar was verified locally with `gog --help` on v0.17.0:

- Gmail message search:
  - `gog gmail messages search <query> --json --max <n> --no-input`
  - Optional content flags: `--include-body`, `--body-format text`, `--full`.
- Gmail message get:
  - `gog gmail get <messageId> --format full --sanitize-content --json --no-input`
- Gmail send reply:
  - `gog gmail send --thread-id <threadId> --to <recipients> --subject <subject> --body-file - --json --no-input`
  - Optional flags used when present: `--cc`, `--bcc`, `--reply-to-message-id`.
- Gmail mark read:
  - `gog gmail mark-read <messageId> --json --no-input`
- Calendar event listing:
  - `gog calendar events primary --from <iso-datetime> --to <iso-datetime> --json --all-pages --no-input`

Reply sending passes the plain-text reply body to stdin because `gog gmail send`
supports `--body-file -`.

Authentication and setup commands were also verified from help output:

- `gog auth credentials set <credentials>`
- `gog auth add <email> --services gmail,calendar`
- `gog auth list`
- `gog auth doctor --check`

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
