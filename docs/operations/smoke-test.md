# Phase 11 Smoke Test

Use this procedure to prove the assistant works with real Telegram, Gmail, and Google Calendar credentials. Run it from the project root.

No GitHub push is required for this procedure.

## 1. Confirm Multi-User OAuth Configuration

Personal Hermes uses per-user Google OAuth tokens. The legacy process-level
`gog --account ... --client ...` token is not part of the supported runtime.

The `.env` file must include:

```bash
TELEGRAM_BOT_TOKEN=replace-with-real-token
SQLITE_DATABASE_PATH=var/personal-hermes.sqlite3
GOG_EXECUTABLE=/home/claude-team/.local/bin/gog
TIMEZONE=Asia/Manila
MULTIUSER_ENABLED=true
PUBLIC_BASE_URL=https://your-public-domain.example.com
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
TOKEN_ENCRYPTION_KEY=...
INVITE_ONLY=true
INVITED_TELEGRAM_USER_IDS=replace-with-telegram-user-id
MINIMAX_API_KEY=replace-with-minimax-api-key
MINIMAX_MODEL=MiniMax-M2.7
```

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

Place the Telegram user ID in `INVITED_TELEGRAM_USER_IDS` when `INVITE_ONLY=true`.

Do not commit `.env`.

## 3. Check App Configuration

```bash
. .venv/bin/activate
python -m personal_hermes --check-config
```

Expected result:

- `Configuration OK`

## 4. Start The Assistant

```bash
. .venv/bin/activate
python -m personal_hermes --run
```

Keep this process running during the smoke test.

## 5. Connect Google In Telegram

Send this Telegram message to the bot:

```text
/connect
```

Expected result:

- The bot replies with a Google authorization URL.
- Complete the OAuth flow in the browser.
- Telegram confirms `Google connected.`

Then send:

```text
/status
```

Expected result:

- The bot replies with `Connected to Google as ...`.

Send:

```text
Can you check whether I have anything later today?
```

Expected result:

- The bot returns a calendar schedule or availability response through MiniMax-priority routing.
- If MiniMax is unavailable, direct phrases like `what's on my calendar today?` should still work through the rule-based fallback.

## 6. Test Google Calendar Through Telegram

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

## 7. Test Gmail Notification

Send a controlled test email to the Google account connected in `/connect`.

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

## 8. Test Gmail Mark Read

Send a second controlled test email.

When Telegram notifies about it, press:

```text
Mark read
```

Expected result:

- Telegram callback answer says `Marked read`.
- Gmail no longer shows the email as unread.

## 9. Test Edited Gmail Reply

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

## 10. Test Calendar Reminder Job

Create a temporary Google Calendar event that starts about 30 minutes from now.

Keep the assistant running until the next calendar polling interval. The default is 5 minutes.

Expected result:

- Telegram receives a reminder like:

```text
Reminder: <event title> starts in 30 minutes
```

## 11. Stop The Assistant

Press `Ctrl+C` in the assistant terminal.

## 12. Confirm Database Schema

```bash
sqlite3 "$SQLITE_DATABASE_PATH" "PRAGMA user_version;"
sqlite3 "$SQLITE_DATABASE_PATH" "PRAGMA table_info(seen_emails);"
sqlite3 "$SQLITE_DATABASE_PATH" "SELECT id, telegram_user_id, telegram_chat_id FROM users;"
```

Expected:

- `user_version` is `3`.
- `seen_emails` shows a `user_id` column.

## Notes

- Full email bodies should not be printed to logs by default.
- If Telegram responds late, check the polling intervals in `.env`.
- If Gmail or Calendar commands fail, confirm the Telegram user is connected with `/status`, then reconnect with `/connect` if needed.
