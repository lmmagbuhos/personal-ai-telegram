# Phase 11 Smoke Test

Use this procedure to prove the assistant works with real Telegram, Gmail, and Google Calendar credentials. Run it from the project root.

No GitHub push is required for this procedure.

## 1. Confirm Google Workspace Access

The OpenClaw `gog` CLI uses a file keyring on this server, so load the keyring password before running live `gog` commands:

```bash
set -a
. /home/claude-team/.config/gogcli/keyring.env
set +a
```

Verify OAuth:

```bash
/home/claude-team/.local/bin/gog --account lmmagbuhos@oakdriveventures.com --client default auth doctor --check
```

Expected result:

- `status ok`

Verify Google Calendar read access:

```bash
/home/claude-team/.local/bin/gog --account lmmagbuhos@oakdriveventures.com --client default calendar events primary --from 2026-05-19T00:00:00+08:00 --to 2026-05-20T00:00:00+08:00 --json --all-pages --no-input
```

Expected result:

- JSON output with an `events` list.

Verify Gmail read access:

```bash
/home/claude-team/.local/bin/gog --account lmmagbuhos@oakdriveventures.com --client default gmail messages search in:inbox --json --max 1 --include-body --body-format text --no-input
```

Expected result:

- JSON output with a `messages` list.

## 2. Configure Telegram

Create a Telegram bot with BotFather and place the token in `.env`.

Then identify the authorized chat ID and user ID:

1. Send any message to the bot from the Telegram account that should control the assistant.
2. Run:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

3. Copy:
   - `message.chat.id` to `TELEGRAM_AUTHORIZED_CHAT_ID`
   - `message.from.id` to `TELEGRAM_AUTHORIZED_USER_ID`

The `.env` file should include:

```bash
TELEGRAM_BOT_TOKEN=replace-with-real-token
TELEGRAM_AUTHORIZED_CHAT_ID=replace-with-chat-id
TELEGRAM_AUTHORIZED_USER_ID=replace-with-user-id
SQLITE_DATABASE_PATH=var/personal-hermes.sqlite3
GOG_EXECUTABLE=/home/claude-team/.local/bin/gog
GOG_ACCOUNT=lmmagbuhos@oakdriveventures.com
GOG_CLIENT=default
TIMEZONE=Asia/Manila
```

Do not commit `.env`.

## 3. Check App Configuration

```bash
. .venv/bin/activate
python -m personal_hermes --check-config
```

Expected result:

- `Configuration OK`

## 4. Start The Assistant

In the same shell where `GOG_KEYRING_PASSWORD` is loaded:

```bash
. .venv/bin/activate
python -m personal_hermes --run
```

Keep this process running during the smoke test.

## 5. Test Google Calendar Through Telegram

Send this Telegram message to the bot:

```text
What dates am I available this week?
```

Expected result:

- The bot replies with:
  - `Fully available: ...`
  - `Partly available: ...`
  - `Busy: ...`

This proves Telegram routing, OpenClaw Calendar access, and the availability service are connected.

## 6. Test Gmail Notification

Send a controlled test email to `lmmagbuhos@oakdriveventures.com`.

Example subject:

```text
OpenClaw smoke test - please confirm
```

Example body:

```text
Hi, can you confirm you received this test message?
```

Wait for the next Gmail polling interval. The default is 5 minutes.

Expected result:

- Telegram receives a `New email` notification.
- The notification includes inline buttons:
  - `Send reply`
  - `Edit reply`
  - `Ignore`
  - `Mark read`

Use `Ignore` on the first test email to prove a non-sending action.

## 7. Test Gmail Mark Read

Send a second controlled test email.

When Telegram notifies about it, press:

```text
Mark read
```

Expected result:

- Telegram callback answer says `Marked read`.
- Gmail no longer shows the email as unread.

## 8. Test Edited Gmail Reply

Send a third controlled test email that asks for a reply.

When Telegram notifies about it:

1. Press `Edit reply`.
2. Send a harmless edited reply in Telegram, for example:

```text
Confirmed. This is a controlled OpenClaw smoke-test reply.
```

3. Press `Send edited reply`.

Expected result:

- Telegram message changes to `Reply sent.`
- The reply appears in the Gmail thread.
- The reply is sent only after the explicit Telegram callback.

## 9. Test Calendar Reminder Job

Create a temporary Google Calendar event that starts about 30 minutes from now.

Keep the assistant running until the next calendar polling interval. The default is 5 minutes.

Expected result:

- Telegram receives a reminder like:

```text
Reminder: <event title> starts in 30 minutes
```

## 10. Stop The Assistant

Press `Ctrl+C` in the assistant terminal.

## Notes

- Full email bodies should not be printed to logs by default.
- If Telegram responds late, check the polling intervals in `.env`.
- If Gmail or Calendar commands fail, first rerun `gog auth doctor --check` with `GOG_KEYRING_PASSWORD` loaded.
