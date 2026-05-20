# Multi-User OAuth Setup Guide

This guide walks through setting up personal-hermes for multi-user mode with Google OAuth integration.

## Prerequisites

- Python 3.11+
- Virtual environment with dependencies installed
- A public domain (https required) to host the OAuth callback
- Google Cloud Project with OAuth 2.0 credentials

---

## Step 1: Create Google OAuth 2.0 Application

### 1.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable these APIs:
   - Gmail API
   - Google Calendar API
   - Google+ API

### 1.2 Create OAuth 2.0 Credentials

1. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
2. Choose application type: **Web application**
3. Set **Authorized redirect URIs** to:
   ```
   https://your-domain.com/oauth/google/callback
   ```
   (Replace `your-domain.com` with your actual public domain)

4. Copy:
   - **Client ID** → `GOOGLE_OAUTH_CLIENT_ID`
   - **Client Secret** → `GOOGLE_OAUTH_CLIENT_SECRET`

---

## Step 2: Generate Token Encryption Key

The `TOKEN_ENCRYPTION_KEY` is a Fernet cipher key used to encrypt Google OAuth tokens at rest.

### Generate a new key (Python)

```bash
source .venv/bin/activate
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This outputs a 44-character base64 string. Example:
```
VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=
```

Copy this entire string (including the `=` padding) to `TOKEN_ENCRYPTION_KEY`.

⚠️ **IMPORTANT**: Keep this key secure. Losing it means you cannot decrypt stored Google tokens.

---

## Step 3: Configure .env File

Create or update `.env` in the project root:

```bash
# Core Telegram Configuration
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_AUTHORIZED_CHAT_ID=your-telegram-chat-id
TELEGRAM_AUTHORIZED_USER_ID=your-telegram-user-id
SQLITE_DATABASE_PATH=var/personal-hermes.sqlite3

# OpenClaw executable used for per-user access-token commands
GOG_EXECUTABLE=/home/claude-team/.local/bin/gog

# Time & Work Schedule
TIMEZONE=Asia/Manila
WORKDAY_START=09:00
WORKDAY_END=17:00
MIN_FREE_BLOCK_MINUTES=120

# Polling Intervals (seconds)
TELEGRAM_POLL_INTERVAL_SECONDS=2
GMAIL_POLL_INTERVAL_SECONDS=300
CALENDAR_POLL_INTERVAL_SECONDS=300
DAILY_AGENDA_TIME=08:00
REMINDER_LEAD_MINUTES=30
PENDING_REPLY_EXPIRY_DAYS=7

# Debug Settings
DEBUG_EMAIL_BODY_LOGGING=false

# ============================================================================
# MULTI-USER OAUTH CONFIGURATION
# ============================================================================

# Multi-user mode is the only supported runtime mode
MULTIUSER_ENABLED=true

# Public domain where callback handler is accessible (HTTPS required)
PUBLIC_BASE_URL=https://your-domain.com

# Google OAuth 2.0 Credentials (from Google Cloud Console)
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret

# OAuth callback path (usually doesn't need to change)
GOOGLE_OAUTH_REDIRECT_PATH=/oauth/google/callback

# Token encryption key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
TOKEN_ENCRYPTION_KEY=VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=

# Invite-only mode
INVITE_ONLY=true

# Comma-separated Telegram user IDs allowed to use /connect (if INVITE_ONLY=true)
INVITED_TELEGRAM_USER_IDS=123456789,987654321

# OAuth session timeout (minutes before /connect link expires)
OAUTH_SESSION_TTL_MINUTES=15

# OAuth callback web server (usually localhost for development)
OAUTH_HOST=0.0.0.0
OAUTH_PORT=8080
```

---

## Step 4: Validate Configuration

Run the configuration check:

```bash
source .venv/bin/activate
python -m personal_hermes --check-config
```

**Expected output:**
```
Configuration OK
```

**If validation fails**, the error message will indicate which settings are missing or invalid.

### Common validation errors:

| Error | Fix |
|-------|-----|
| `PUBLIC_BASE_URL must be an absolute http(s) URL` | Set `PUBLIC_BASE_URL=https://...` (not http://) |
| `TOKEN_ENCRYPTION_KEY` is missing | Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_OAUTH_CLIENT_ID` is missing | Get from Google Cloud Console |
| `GOOGLE_OAUTH_REDIRECT_PATH must start with /` | Ensure value starts with `/` |

---

## Step 5: Database Initialization

The `--check-config` command automatically initializes the SQLite database and applies schema migrations:

```bash
python -m personal_hermes --check-config
```

**Verify migration:**

```bash
sqlite3 var/personal-hermes.sqlite3
PRAGMA user_version;        -- Should output: 3
.tables                     -- Should show: users, oauth_sessions, google_accounts, ...
.exit
```

---

## Step 6: Start the Assistant

Start the assistant with multi-user OAuth support:

```bash
source .venv/bin/activate

# Start the assistant
python -m personal_hermes --run
```

The output should show:
```
...
[APScheduler] Starting scheduler...
[APScheduler] Added job ...
```

---

## Step 7: Test the OAuth Flow

### Test /connect Command

1. Send `/connect` in Telegram
2. Bot responds with a Google authorization URL
3. Click the URL and authorize the app
4. You're redirected to a success page
5. Telegram confirms: "Google connected."

### Test /status Command

1. Send `/status`
2. Bot responds with: `Connected to Google as your-email@gmail.com.`

### Test /disconnect Command

1. Send `/disconnect`
2. Bot confirms: `Google disconnected.`

---

## Step 8: Verify Multi-User Isolation

### Test with 2 Users

1. **User A (Telegram ID: 111111)**
   - Send `/connect`
   - Connect Google account A
   - Send `/status` → Confirms account A

2. **User B (Telegram ID: 222222)**
   - Send `/connect`
   - Connect Google account B
   - Send `/status` → Confirms account B

3. **Test Email Isolation**
   - Send email to account A's inbox
   - Only User A receives Telegram notification
   - Send email to account B's inbox
   - Only User B receives Telegram notification

---

## Configuration Reference

### Required

| Setting | Example | Notes |
|---------|---------|-------|
| `MULTIUSER_ENABLED` | `true` | Enable multi-user mode |
| `PUBLIC_BASE_URL` | `https://hermes.example.com` | Must be HTTPS, accessible from internet |
| `GOOGLE_OAUTH_CLIENT_ID` | `123...@apps.googleusercontent.com` | From Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | `GOCSP...` | From Google Cloud Console |
| `TOKEN_ENCRYPTION_KEY` | `VT1P...=` | 44-char base64 Fernet key |

### Optional

| Setting | Default | Notes |
|---------|---------|-------|
| `GOOGLE_OAUTH_REDIRECT_PATH` | `/oauth/google/callback` | Rarely needs to change |
| `OAUTH_HOST` | `0.0.0.0` | Callback server bind address |
| `OAUTH_PORT` | `8080` | Callback server port |
| `INVITE_ONLY` | `true` | Restrict access to allowlist |
| `INVITED_TELEGRAM_USER_IDS` | empty | Comma-separated allowlist if `INVITE_ONLY=true` |
| `OAUTH_SESSION_TTL_MINUTES` | `15` | How long `/connect` link stays valid |

---

## Troubleshooting

### OAuth callback fails with "Connection expired"

- OAuth session TTL (default 15 minutes) has elapsed
- User must send `/connect` again to get a new link

### OAuth callback fails with "Connection failed"

- Google OAuth credentials are incorrect
- Check `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
- Verify redirect URI in Google Cloud Console matches `PUBLIC_BASE_URL + GOOGLE_OAUTH_REDIRECT_PATH`

### Token encryption/decryption fails

- `TOKEN_ENCRYPTION_KEY` is corrupted or missing padding
- Must be exactly 44 characters
- Must be generated with `Fernet.generate_key().decode()`

### User sees "Connect Google first with /connect"

- User's Google account is not connected or status is "revoked"
- If previous account exists, check status with `/status`
- If needed, send `/connect` to reconnect

### Database migration fails

- Existing v1 database has incompatible schema
- Migration should auto-apply on `--check-config`
- If stuck, backup database and manually run migration:
  ```bash
  sqlite3 var/personal-hermes.sqlite3 < migrations/upgrade_schema.sql
  ```

---

## Security Notes

1. **TOKEN_ENCRYPTION_KEY** is the master encryption key for Google OAuth tokens
   - Store securely (e.g., in a secrets manager)
   - Rotate periodically for compliance
   - Losing it means token re-encryption is required

2. **GOOGLE_OAUTH_CLIENT_SECRET** should never be committed to version control
   - Use `.env` file (in `.gitignore`)
   - In production, use environment variables from secrets manager

3. **PUBLIC_BASE_URL** must use HTTPS
   - HTTP will fail OAuth token validation
   - Use a valid certificate (e.g., Let's Encrypt)

4. **INVITE_ONLY** mode is recommended
   - Prevent unauthorized users from connecting
   - Manage allowlist explicitly

---

## Next Steps

- Review [smoke-test.md](./smoke-test.md) for full integration testing
- Monitor logs during initial user onboarding
- Consider enabling per-user rate limiting (future enhancement)
- Set up automated token rotation policy (future enhancement)
