# OpenClaw API Notes

Date checked: 2026-05-19

## Decision

I could not confirm a proprietary OpenClaw REST API for Gmail or Calendar operations.
The current public OpenClaw docs describe skills as instruction/tool packages, not a
stable external REST surface. The official Skills page says OpenClaw skills are files
that teach the assistant which commands to use, and lists the `gog` skill as the
Google Workspace path for Gmail, Calendar, Drive, and Contacts:

- https://www.getopenclaw.ai/docs/skills
- https://www.getopenclaw.ai/integrations/google-calendar

Local inspection found `~/.openclaw` config and gateway state, but no installed
`gog`, Gmail, Calendar, `claw`, or `gmail-bridge` skill files under the checked local
paths. The current shell also did not expose `CLAWEMAIL_CREDENTIALS`,
`OPENCLAW_*`, `GMAIL_*`, or `GOOGLE_*` environment variables. Secrets were not
recorded here.

For Phase 1, `OpenClawClient` is implemented against the confirmed Google
Workspace REST API shapes used by the OpenClaw/ClawEmail skill path, with a bearer
token injected into the client. This keeps external mapping isolated so a later
OpenClaw bridge, `gog` CLI wrapper, or proprietary API can replace the transport
without changing application services.

## Authentication

Confirmed method for this contract:

- HTTP `Authorization: Bearer <access token>`.
- Access token is injected into `OpenClawClient(access_token=...)`.
- The client does not read credentials from disk and does not refresh OAuth tokens.

Expected OpenClaw/ClawEmail credential helper from public skill leads:

- `CLAWEMAIL_CREDENTIALS`
- `~/.openclaw/skills/claw/scripts/token.sh`

Those helper files were not present in the local OpenClaw paths checked during this
phase.

## Gmail Read

List inbox/unread messages:

- Method: `GET`
- Endpoint: `https://gmail.googleapis.com/gmail/v1/users/me/messages`
- Query:
  - `q=in:inbox is:unread`
  - if `since_cursor` is provided, the client appends `after:<since_cursor>` to the
    Gmail search query
  - `maxResults=25`
- Response: `messages[]` entries contain only `id` and `threadId`, so the client
  fetches each message with `messages.get`.

Fetch message details:

- Method: `GET`
- Endpoint: `https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}`
- Query: `format=full`
- Confirmed fields mapped:
  - `id`
  - `threadId`
  - `labelIds`
  - `snippet`
  - `internalDate`
  - `payload.headers[]`
  - `payload.parts[]`
  - `payload.body.data` / nested part `body.data`

Internal mapping:

- `EmailMessage.id` from `id`
- `EmailMessage.thread_id` from `threadId`
- `EmailMessage.subject` from `Subject`
- `EmailMessage.sender` from `From`
- `EmailMessage.to` from `To`
- `EmailMessage.cc` from `Cc`
- `EmailMessage.sent_at` from `Date`, falling back to `internalDate`
- `EmailMessage.snippet` from `snippet`
- `EmailMessage.body_text` from decoded `text/plain` MIME part data
- `EmailMessage.is_unread` from whether `UNREAD` is in `labelIds`
- `EmailMessage.message_id` from `Message-ID`
- `EmailMessage.references` from `References`

References:

- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages

## Gmail Send Reply

Send message:

- Method: `POST`
- Endpoint: `https://gmail.googleapis.com/gmail/v1/users/me/messages/send`
- Body:
  - `raw`: RFC 2822 email, base64url encoded
  - `threadId`: Gmail thread ID

Reply headers:

- `To`
- `Cc` if present
- `Bcc` if present
- `Subject`, prefixed with `Re:` if needed
- `In-Reply-To`
- `References`

Google documents that adding a message to a thread requires the requested
`threadId`, RFC 2822 compliant `References` and `In-Reply-To` headers, and matching
subject headers.

Internal request:

- `SendEmailReplyRequest.thread_id`
- `SendEmailReplyRequest.to`
- `SendEmailReplyRequest.subject`
- `SendEmailReplyRequest.body_text`
- `SendEmailReplyRequest.in_reply_to`
- `SendEmailReplyRequest.references`
- optional `cc` and `bcc`

Return value:

- Sent Gmail message `id`.

References:

- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages

## Gmail Mark Read

Mark read is a label modification:

- Method: `POST`
- Endpoint: `https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}/modify`
- Body: `{"removeLabelIds": ["UNREAD"]}`

Internal result:

- `OpenClawClient.mark_email_read(email_id)` returns `None` after a successful
  response.

Reference:

- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify

## Calendar List Events

List events:

- Method: `GET`
- Endpoint: `https://www.googleapis.com/calendar/v3/calendars/primary/events`
- Query:
  - `timeMin=<start_at RFC3339>`
  - `timeMax=<end_at RFC3339>`
  - `singleEvents=true`
  - `orderBy=startTime`

Confirmed fields mapped:

- `id`
- `summary`
- `start.dateTime`
- `start.date`
- `start.timeZone`
- `end.dateTime`
- `end.date`
- `end.timeZone`
- `location`
- `description`
- `htmlLink`
- `attendees[].displayName`
- `attendees[].email`
- `attendees[].responseStatus`

Internal mapping:

- `CalendarEvent.id` from `id`
- `CalendarEvent.title` from `summary`
- `CalendarEvent.start_at` from `start.dateTime` or all-day `start.date`
- `CalendarEvent.end_at` from `end.dateTime` or all-day `end.date`
- `CalendarEvent.all_day` is true when `start.date` is used
- `CalendarEvent.timezone` from start/end `timeZone`
- `CalendarEvent.location` from `location`
- `CalendarEvent.description` from `description`
- `CalendarEvent.html_link` from `htmlLink`
- `CalendarEvent.attendees` from attendee display name, email, and response status

Reference:

- https://developers.google.com/workspace/calendar/api/v3/reference/events/list

## Unsupported Or Unconfirmed

These were not implemented because exact local/current API details were not
confirmed:

- Proprietary OpenClaw cloud REST endpoints for Gmail/Calendar.
- `gmail-bridge` HTTP endpoints at `http://127.0.0.1:8787`.
- Local `gog` CLI command output parsing.
- OAuth refresh-token handling.
- Gmail Pub/Sub watch/history flows.

Later phases should depend only on `EmailMessage`, `CalendarEvent`,
`SendEmailReplyRequest`, and `OpenClawClient` method signatures.
