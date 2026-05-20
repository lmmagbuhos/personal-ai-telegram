# Gmail CRUD Completion - Design

## Overview

Round out Gmail from notification-only reply handling into on-demand CRUD from
Telegram. The bot should support reading/searching mail, organizing selected
messages, trashing messages with confirmation, and composing new outbound mail
through a draft-first safety flow.

The core principle is the same as Calendar CRUD: Telegram conversations collect
intent and confirmation, while deterministic services perform the Google action.
The future LLM layer can replace natural-language routing later, but it should
call the same stable Gmail service methods and state-machine flows.

## Scope

### In Scope

- On-demand Gmail read/search:
  - "show unread emails"
  - "search emails from Alex"
  - "find email about invoice"
  - result list with inline buttons
  - full message detail view after selecting a result
- Message actions from a selected email:
  - mark read
  - mark unread
  - archive
  - trash, with confirmation
  - star and unstar
  - add label
  - remove label
- Draft-first compose:
  - collect recipient, subject, and body
  - create a Gmail draft
  - show a Telegram preview
  - send only after tapping a Send button
  - edit or discard the draft before sending
- `OpenClawClient` wrappers for the needed `gog gmail` commands.
- Multiuser access-token support using the existing resolver pattern.
- Conversation-state persistence with save-before-send-buttons guard.

### Out of Scope

- Permanent delete. Trash is the destructive limit for this pass.
- Attachments.
- HTML email authoring.
- Bulk actions by query. All destructive or organizing actions apply to selected
  messages only.
- Contacts/People lookup. Recipient extraction is simple text parsing for now.
- LLM-driven interpretation. This pass stays rule-based but prepares stable
  service boundaries for the later LLM layer.

## Design Decisions

- **Draft-first always:** New outbound email is never sent directly from free
  text. The bot creates a Gmail draft, previews it, then sends only after a
  button confirmation.
- **Buttons depend on persisted state:** Any message that includes selection
  buttons must be sent only after `conversation_state` is written and read back.
  If state cannot be saved, the bot sends a plain failure message instead of
  buttons that would later expire.
- **One selected-message state:** Search/list results and selected-message views
  use `conversation_state`, keyed by `(user_id, telegram_chat_id)`, matching the
  calendar fix.
- **Star/unstar is label modification:** Gmail star is implemented as adding or
  removing the `STARRED` label using `gog gmail messages modify`.
- **Labels are explicit text input:** Add/remove label starts with a selected
  email, then prompts the user for a label name. The first pass does not present
  a label picker.
- **Safety confirmations:** Trash and draft send/discard require buttons.
  Archive, mark read/unread, and star/unstar can execute directly from a
  selected-message action button because they are reversible or low risk.

## Components

### OpenClawClient

Add Gmail methods:

- `search_email_messages(query: str, *, max_results: int = 10) -> list[EmailMessage]`
  - `gog gmail messages search <query> --json --max <n> --include-body --body-format text --no-input`
- `archive_email(email_id: str) -> None`
  - `gog gmail archive <messageId> --json --no-input`
- `mark_email_unread(email_id: str) -> None`
  - `gog gmail unread <messageId> --json --no-input`
- `trash_email(email_id: str) -> None`
  - `gog gmail trash <messageId> --json --no-input -y`
- `modify_email_labels(email_id: str, *, add=(), remove=()) -> None`
  - `gog gmail messages modify <messageId> --add <labels> --remove <labels> --json --no-input`
- `create_email_draft(*, to: tuple[str, ...], subject: str, body_text: str, cc: tuple[str, ...] = (), bcc: tuple[str, ...] = ()) -> GmailDraft`
  - `gog gmail drafts create --to <recipients> --subject <subject> --body-file - --json --no-input`
  - include `--cc` and `--bcc` only when values are present
- `update_email_draft(draft_id: str, *, to: tuple[str, ...] | None = None, subject: str | None = None, body_text: str | None = None, cc: tuple[str, ...] | None = None, bcc: tuple[str, ...] | None = None) -> GmailDraft`
  - `gog gmail drafts update <draftId> --body-file - --json --no-input`
  - include `--to`, `--subject`, `--cc`, and `--bcc` only for fields being changed
- `send_email_draft(draft_id: str) -> str`
  - `gog gmail drafts send <draftId> --json --no-input`
- `delete_email_draft(draft_id: str) -> None`
  - `gog gmail drafts delete <draftId> --json --no-input -y`

Add a small `GmailDraft` dataclass in `openclaw/types.py`:

- `id`
- `message_id`
- `thread_id`
- `to`
- `cc`
- `bcc`
- `subject`
- `body_text`

Mapping should tolerate response envelopes such as `{"draft": {...}}` and direct
object responses.

### GmailReadService

Responsible for on-demand search/list and selected-message views.

Entry points:

- `start_search(message, *, user_id, now) -> bool`
- `handle_callback(callback, *, user_id, now) -> None`

Flow:

1. Router detects a Gmail read/search request.
2. Service builds a simple Gmail query:
   - unread list -> `in:inbox is:unread`
   - generic search -> user-provided terms
   - from search -> `from:<term>` when recognizable
3. Fetch up to 10 messages.
4. Save state:
   - state: `gmail_search_results`
   - payload: message candidates with id, thread id, sender, subject, snippet,
     sent time, unread flag
5. Read state back. If it is missing or malformed, send a plain failure message.
6. Send buttons: `mail_pick:<idx>`.
7. On pick, fetch full message by id, save:
   - state: `gmail_selected_message`
   - payload: selected message metadata
8. Show detail plus action buttons:
   - Mark read / unread
   - Archive
   - Trash
   - Star / Unstar
   - Add label / Remove label
   - Reply using the existing reply flow where applicable

### GmailMessageActionService

Extends or complements the existing `MailActionService`. It handles selected
message organization actions and label text prompts.

Callback verbs:

- `mail_pick:<idx>`
- `mail_read`
- `mail_unread`
- `mail_archive`
- `mail_trash`
- `mail_trash_ok`
- `mail_trash_no`
- `mail_star`
- `mail_unstar`
- `mail_label_add`
- `mail_label_remove`

Text-value states:

- `gmail_label_value_add`
- `gmail_label_value_remove`

Error behavior:

- Missing selected-message state -> `That selection expired - start again.`
- Google disconnected -> `Connect Google first with /connect.`
- gog failure -> preserve selected-message state and answer with the matching
  failure message:
  - read/unread/archive/star/unstar/label: `Couldn't update that email right now.`
  - trash: `Couldn't trash that email right now.`

### GmailDraftService

Responsible for brand-new outbound email and draft lifecycle.

Entry points:

- `start_compose(message, *, user_id, now) -> bool`
- `handle_value(message, *, user_id, now) -> bool`
- `handle_callback(callback, *, user_id, now) -> None`

States:

- `gmail_compose_collect_to`
- `gmail_compose_collect_subject`
- `gmail_compose_collect_body`
- `gmail_draft_preview`
- `gmail_draft_edit_field`
- `gmail_draft_edit_value`

Flow:

1. Router detects compose intent.
2. Service extracts any recipient/subject/body that is obvious from the message.
3. Missing fields are collected one message at a time.
4. Once all required fields exist, create a Gmail draft.
5. Save `gmail_draft_preview` with draft id and preview fields.
6. Read state back, then send preview buttons:
   - `draft_send`
   - `draft_edit`
   - `draft_discard`
7. `draft_send` sends the Gmail draft and clears state.
8. `draft_discard` asks for confirmation, then deletes the draft and clears
   state.
9. `draft_edit` shows field buttons:
   - To
   - Subject
   - Body
10. After field value input, update the Gmail draft and return to preview.

Callback verbs:

- `draft_send`
- `draft_edit`
- `draft_edit_to`
- `draft_edit_subject`
- `draft_edit_body`
- `draft_discard`
- `draft_discard_ok`
- `draft_discard_no`

## Router Integration

Router ordering after commands and callbacks:

1. Existing email reply edit value flow.
2. Calendar edit value flow.
3. Gmail draft value flow.
4. Gmail label value flow.
5. Calendar cancel/edit/create.
6. Gmail read/search intent.
7. Gmail compose intent.
8. Calendar schedule/availability.
9. Fallback.

Callback routing:

- `mail_*` -> Gmail read/message action service
- `draft_*` -> Gmail draft service
- existing `send_reply`, `edit_reply`, `ignore_reply`, `mark_read` remain
  supported
- Calendar `cal_*` remains unchanged

The later LLM layer should produce the same high-level intents that these router
branches use, so replacing keyword checks will not require changing Gmail
services.

## Data Flow

### Search and Organize

Telegram message -> router Gmail search intent -> `GmailReadService` ->
OpenClaw search -> save candidates -> send result buttons -> user picks ->
fetch full message -> save selected message -> show action buttons -> selected
action -> OpenClaw operation -> Telegram confirmation.

### Compose

Telegram message -> router Gmail compose intent -> collect missing fields ->
OpenClaw draft create -> save draft preview -> send preview buttons -> user
sends/edits/discards -> OpenClaw draft operation -> Telegram confirmation.

## Error Handling

- No search results: `No matching emails found.`
- Missing state on pick/action: `That selection expired - start again.`
- State write/readback failure: `Couldn't start that Gmail action right now. Try again.`
- Missing compose recipient: prompt for recipient.
- Missing compose subject: prompt for subject.
- Missing compose body: prompt for body.
- Invalid recipient text: prompt again with `name@example.com`.
- gog search/get failure: `Couldn't read Gmail right now.`
- gog organize failure: `Couldn't update that email right now.`
- gog draft create failure: `Couldn't create that draft right now.`
- gog draft update failure: `Couldn't update that draft right now.`
- gog draft send failure: `Couldn't send that draft right now.`
- gog draft delete failure: `Couldn't discard that draft right now.`
- Google disconnected: `Connect Google first with /connect.`

## Testing

- `OpenClawClient` contract tests for every new Gmail command wrapper.
- Gmail search service tests:
  - unread query
  - generic query
  - no results
  - state write/readback guard
  - selection opens full message
- Gmail message action tests:
  - mark read
  - mark unread
  - archive
  - trash confirm/cancel
  - star/unstar via `STARRED`
  - add/remove label via text prompt
  - expired selection
  - multiuser token use
- Gmail draft service tests:
  - compose with all fields
  - compose with missing fields collected sequentially
  - create draft before preview buttons
  - send draft only after button confirmation
  - edit to/subject/body
  - discard confirm/cancel
  - expired draft state
  - multiuser token use
- Router tests:
  - Gmail read/search routes before fallback
  - Gmail compose routes before fallback
  - Gmail value states take priority over new intents
  - Gmail callbacks route to the right services
- Local simulation:
  - use fake Telegram and fake OpenClaw over a copied SQLite DB, mirroring the
    calendar regression test style.
- Real-gog smoke:
  - search unread
  - create draft
  - update draft
  - discard draft
  - create a controlled message and archive/trash/label it if safe.

## Implementation Phasing

1. OpenClaw Gmail wrappers and types.
2. Gmail read/search + selected-message view.
3. Message actions: read/unread/archive/trash/star/unstar/label.
4. Draft-first compose/create/preview/send/discard.
5. Draft edit.
6. Router integration and local end-to-end simulation.
7. Real-gog smoke checklist.
