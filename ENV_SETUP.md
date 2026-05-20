# Environment Variables Setup Guide

## Quick Reference

Personal Hermes now runs in multi-user OAuth mode only. Set these environment variables in `.env`:

### Required

```bash
MULTIUSER_ENABLED=true
PUBLIC_BASE_URL=https://your-domain.com
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret-key
TOKEN_ENCRYPTION_KEY=VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=
```

### Optional (but recommended)

```bash
INVITE_ONLY=true
INVITED_TELEGRAM_USER_IDS=123456789,987654321
OAUTH_SESSION_TTL_MINUTES=15
OAUTH_HOST=0.0.0.0
OAUTH_PORT=8080
MINIMAX_API_KEY=your-minimax-api-key
MINIMAX_MODEL=MiniMax-M2.7
```

---

## How to Generate TOKEN_ENCRYPTION_KEY

The `TOKEN_ENCRYPTION_KEY` encrypts Google OAuth tokens in the database.

### Generate a new key:

```bash
source .venv/bin/activate
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Output example:**
```
VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=
```

Copy the entire string (including the `=` padding) to `.env`:
```bash
TOKEN_ENCRYPTION_KEY=VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=
```

---

## How to Get Google OAuth Credentials

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable APIs:
   - Gmail API
   - Google Calendar API
   - Google+ API

### 2. Create OAuth 2.0 Credentials

1. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
2. Select **Web application**
3. Add **Authorized Redirect URI**:
   ```
   https://your-domain.com/oauth/google/callback
   ```
4. Click **Create**
5. Copy:
   - **Client ID** → `GOOGLE_OAUTH_CLIENT_ID`
   - **Client Secret** → `GOOGLE_OAUTH_CLIENT_SECRET`

### 3. Add to .env

```bash
GOOGLE_OAUTH_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX_AbCdEfGhIjKlMnOpQrStUv
```

---

## Complete .env Template

```bash
# ============================================================================
# TELEGRAM (Required)
# ============================================================================
TELEGRAM_BOT_TOKEN=replace-with-token
SQLITE_DATABASE_PATH=var/personal-hermes.sqlite3

# ============================================================================
# OPENCLAW
# ============================================================================
GOG_EXECUTABLE=gog

# ============================================================================
# SCHEDULE & TIMING
# ============================================================================
TIMEZONE=Asia/Manila
WORKDAY_START=09:00
WORKDAY_END=17:00
MIN_FREE_BLOCK_MINUTES=120

# ============================================================================
# POLLING INTERVALS (seconds)
# ============================================================================
TELEGRAM_POLL_INTERVAL_SECONDS=2
GMAIL_POLL_INTERVAL_SECONDS=300
CALENDAR_POLL_INTERVAL_SECONDS=300
DAILY_AGENDA_TIME=08:00
REMINDER_LEAD_MINUTES=30
PENDING_REPLY_EXPIRY_DAYS=7
DEBUG_EMAIL_BODY_LOGGING=false

# ============================================================================
# MULTI-USER OAUTH - REQUIRED
# ============================================================================
MULTIUSER_ENABLED=true

# Your public domain (HTTPS required)
PUBLIC_BASE_URL=https://your-domain.com

# Google OAuth credentials from Google Cloud Console
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret

# Token encryption key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
TOKEN_ENCRYPTION_KEY=VT1PjN2x5K8qR9mL7pZ3hJ6gY4dA8bE1cF2xW5sT7u4=

# ============================================================================
# MULTI-USER OAUTH - OPTIONAL
# ============================================================================
GOOGLE_OAUTH_REDIRECT_PATH=/oauth/google/callback
INVITE_ONLY=true
INVITED_TELEGRAM_USER_IDS=123456789,987654321
OAUTH_SESSION_TTL_MINUTES=15
OAUTH_HOST=0.0.0.0
OAUTH_PORT=8080

# ============================================================================
# MINIMAX LLM ROUTING - OPTIONAL
# ============================================================================
MINIMAX_API_KEY=your-minimax-api-key
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimax.io/v1
LLM_TIMEOUT_SECONDS=10
```

---

## MiniMax LLM Routing

MiniMax is the priority natural-language parser. When `MINIMAX_API_KEY` is set,
normal Telegram messages are classified by MiniMax first. If MiniMax fails,
returns invalid JSON, or returns `unknown`, the existing rule-based parser is
used as fallback.

```bash
MINIMAX_API_KEY=your-minimax-api-key
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimax.io/v1
LLM_TIMEOUT_SECONDS=10
```

---

## Validation Errors & Solutions

| Error | Solution |
|-------|----------|
| `multiuser runtime is required; set MULTIUSER_ENABLED=true` | Remove `MULTIUSER_ENABLED=false` or set it to `true` |
| `multiuser OAuth settings required: public_base_url, ...` | Set all 4 required vars above |
| `PUBLIC_BASE_URL must be an absolute http(s) URL` | Must start with `https://` (not `http://`) |
| `TOKEN_ENCRYPTION_KEY` is missing | Generate with Fernet command above |
| `GOOGLE_OAUTH_CLIENT_ID` is missing | Get from Google Cloud Console |
| `GOOGLE_OAUTH_REDIRECT_PATH must start with /` | Ensure value starts with `/` |
| `INVITED_TELEGRAM_USER_IDS must be comma-separated integers` | Use format: `123,456,789` |
| `MINIMAX_BASE_URL must be an absolute http(s) URL` | Use `https://api.minimax.io/v1` |

---

## Verify Configuration

```bash
source .venv/bin/activate
python -m personal_hermes --check-config
```

**Expected:**
```
Configuration OK
```

---

## Security Best Practices

1. **Never commit `.env`** to version control
   - Add to `.gitignore`: `echo ".env" >> .gitignore`

2. **Keep TOKEN_ENCRYPTION_KEY safe**
   - Use a secrets manager in production
   - Required to decrypt stored Google tokens
   - Losing it requires token re-encryption

3. **Keep GOOGLE_OAUTH_CLIENT_SECRET safe**
   - Never expose in logs or error messages
   - Use environment variables in production

4. **Use HTTPS for PUBLIC_BASE_URL**
   - OAuth requires HTTPS
   - Use Let's Encrypt for free certificates

5. **Enable INVITE_ONLY in production**
   - Prevent unauthorized user registration
   - Manage allowlist explicitly
