# Multiuser Google OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Personal Hermes from a single-user Telegram assistant into an invite-only multiuser Telegram assistant where each user connects their own Google account through OAuth.

**Architecture:** Add user, OAuth session, Google account, and invite storage around the existing SQLite `StateStore`. Add a Google OAuth/web runtime and direct Google API client path, then migrate router, mail, calendar notification, and scheduler behavior to accept `user_id` while preserving the current single-user `gog` flow as a bootstrap fallback until the migration is complete.

**Tech Stack:** Python 3.11, SQLite, pytest, pydantic-settings, httpx, python-telegram-bot, APScheduler, FastAPI/Uvicorn for the OAuth callback, cryptography Fernet for token encryption, google-auth/google-auth-oauthlib/google-api-python-client for Google OAuth and Gmail/Calendar clients.

---

## References

- Design spec: `docs/superpowers/specs/2026-05-19-multiuser-google-oauth-design.md`
- Google OAuth web-server docs: https://developers.google.com/identity/protocols/oauth2/web-server
- Gmail scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Calendar scopes: https://developers.google.com/resources/api-libraries/documentation/calendar/v3/python/latest/index.html

Use these scopes for the first implementation:

```python
GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events.readonly",
)
```

`gmail.modify` is required because the product reads messages and optionally marks them read. `gmail.send` is required for approved replies. `calendar.events.readonly` is enough for agenda, reminders, and availability reads.

## File Structure

Create:

- `src/personal_hermes/users.py`: dataclasses and user/invite status constants.
- `src/personal_hermes/oauth/__init__.py`: OAuth package marker.
- `src/personal_hermes/oauth/crypto.py`: Fernet token encryption/decryption.
- `src/personal_hermes/oauth/google.py`: OAuth URL generation, callback token exchange, credential refresh, token revocation, Gmail/Calendar API adapter.
- `src/personal_hermes/oauth/web.py`: FastAPI callback app and success/error pages.
- `tests/users/test_user_store.py`: user, invite, and Google account store tests.
- `tests/oauth/test_crypto.py`: token encryption tests.
- `tests/oauth/test_google_oauth.py`: OAuth URL, callback exchange, refresh, and revoke behavior with mocked HTTP/client seams.
- `tests/oauth/test_web.py`: OAuth callback HTTP behavior using FastAPI test client.
- `tests/multiuser/test_router_onboarding.py`: `/connect`, `/status`, `/disconnect`, and access policy tests.
- `tests/multiuser/test_user_scoped_services.py`: user-scoped mail, calendar, and pending reply ownership tests.
- `tests/multiuser/test_scheduler.py`: per-user scheduler isolation tests.

Modify:

- `pyproject.toml`: add Google, FastAPI, Uvicorn, Cryptography, and HTTP test dependencies.
- `.env.example`: add OAuth, token encryption, public base URL, invite policy, and allowlist settings.
- `src/personal_hermes/config.py`: add settings and validation for multiuser/OAuth config.
- `src/personal_hermes/storage/schema.sql`: add new tables and `user_id` columns.
- `src/personal_hermes/storage/store.py`: add user, invite, OAuth session, Google account, and user-scoped state APIs.
- `src/personal_hermes/router.py`: replace global authorization with user resolution; add `/connect`, `/status`, `/disconnect`.
- `src/personal_hermes/mail/service.py`: accept `user_id`, `chat_id`, and user-scoped store calls.
- `src/personal_hermes/mail/actions.py`: enforce pending reply ownership and active Google account.
- `src/personal_hermes/calendar/notifications.py`: accept `user_id` for dedupe records.
- `src/personal_hermes/scheduler.py`: add multiuser scheduler loop while keeping Telegram polling global.
- `src/personal_hermes/app.py`: build user/OAuth components, optionally start OAuth web app, and wire multiuser dependencies.
- `src/personal_hermes/__main__.py`: expose the updated CLI behavior if needed.
- Existing tests under `tests/`: update old single-user calls to pass bootstrap `user_id=1` or use compatibility wrappers.

## Task 1: Dependencies And Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/personal_hermes/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add tests for required OAuth values when multiuser is enabled and invite allowlist parsing:

```python
def test_multiuser_oauth_settings_parse_allowlist(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USER_ID", "456")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", "/tmp/hermes.sqlite3")
    monkeypatch.setenv("MULTIUSER_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://hermes.example.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "a" * 44)
    monkeypatch.setenv("INVITE_ONLY", "true")
    monkeypatch.setenv("INVITED_TELEGRAM_USER_IDS", "111,222")

    settings = Settings(_env_file=None)

    assert settings.multiuser_enabled is True
    assert settings.public_base_url == "https://hermes.example.com"
    assert settings.invited_telegram_user_ids_tuple == (111, 222)
```

- [ ] **Step 2: Run config tests and verify failure**

Run: `python -m pytest tests/test_config.py -v`

Expected: FAIL because `multiuser_enabled`, `public_base_url`, and allowlist properties are not defined.

- [ ] **Step 3: Add dependencies**

Update `pyproject.toml`:

```toml
dependencies = [
    "apscheduler>=3.10,<4",
    "cryptography>=42.0,<46",
    "fastapi>=0.111,<1",
    "google-api-python-client>=2.130,<3",
    "google-auth>=2.29,<3",
    "google-auth-oauthlib>=1.2,<2",
    "httpx>=0.27,<1",
    "pydantic-settings>=2.0,<3",
    "python-dotenv>=1.0,<2",
    "python-telegram-bot>=21.0,<23",
    "uvicorn>=0.29,<1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<10",
    "pytest-mock>=3.14,<4",
]
```

- [ ] **Step 4: Add settings**

Add fields and allowlist parsing to `Settings`:

```python
multiuser_enabled: bool = False
public_base_url: str | None = None
google_oauth_client_id: str | None = None
google_oauth_client_secret: str | None = None
google_oauth_redirect_path: str = "/oauth/google/callback"
token_encryption_key: str | None = None
invite_only: bool = True
invited_telegram_user_ids: str = ""
oauth_session_ttl_minutes: PositiveInt = 15
oauth_host: str = "127.0.0.1"
oauth_port: PositiveInt = 8080

@property
def google_oauth_redirect_url(self) -> str | None:
    if not self.public_base_url:
        return None
    return self.public_base_url.rstrip("/") + self.google_oauth_redirect_path

@property
def invited_telegram_user_ids_tuple(self) -> tuple[int, ...]:
    values = []
    for raw in self.invited_telegram_user_ids.split(","):
        raw = raw.strip()
        if raw:
            values.append(int(raw))
    return tuple(values)
```

- [ ] **Step 5: Update `.env.example`**

Add:

```dotenv
MULTIUSER_ENABLED=false
PUBLIC_BASE_URL=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_PATH=/oauth/google/callback
TOKEN_ENCRYPTION_KEY=
INVITE_ONLY=true
INVITED_TELEGRAM_USER_IDS=
OAUTH_SESSION_TTL_MINUTES=15
OAUTH_HOST=127.0.0.1
OAUTH_PORT=8080
```

- [ ] **Step 6: Run config tests**

Run: `python -m pytest tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example src/personal_hermes/config.py tests/test_config.py
git commit -m "feat: add multiuser oauth configuration"
```

## Task 2: User, Invite, OAuth Session, And Google Account Storage

**Files:**
- Create: `src/personal_hermes/users.py`
- Modify: `src/personal_hermes/storage/schema.sql`
- Modify: `src/personal_hermes/storage/store.py`
- Test: `tests/users/test_user_store.py`

- [ ] **Step 1: Write failing storage tests**

Create tests covering user upsert, invite policy, OAuth session single-use, and Google account status:

```python
from datetime import UTC, datetime, timedelta

from personal_hermes.storage.store import StateStore


def test_user_upsert_and_lookup_by_telegram_identity(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()

    user = store.upsert_user_from_telegram(
        telegram_user_id=456,
        telegram_chat_id=123,
        display_name="Mann",
        username="mann",
        now=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
    )

    loaded = store.get_user_by_telegram(telegram_user_id=456, telegram_chat_id=123)
    assert loaded == user
    assert loaded.status == "pending"


def test_oauth_session_is_single_use_and_bound_to_telegram_user(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    store.create_oauth_session(
        state="state-1",
        telegram_user_id=456,
        telegram_chat_id=123,
        expires_at=now + timedelta(minutes=15),
        created_at=now,
    )

    session = store.consume_oauth_session("state-1", now=now)
    assert session is not None
    assert session.telegram_user_id == 456
    assert store.consume_oauth_session("state-1", now=now) is None
```

- [ ] **Step 2: Run storage tests and verify failure**

Run: `python -m pytest tests/users/test_user_store.py -v`

Expected: FAIL because the user storage APIs do not exist.

- [ ] **Step 3: Create user dataclasses**

Add `src/personal_hermes/users.py`:

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: int
    telegram_user_id: int
    telegram_chat_id: int
    display_name: str | None
    username: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OAuthSession:
    state: str
    telegram_user_id: int
    telegram_chat_id: int
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class GoogleAccount:
    user_id: int
    google_subject: str
    google_email: str
    encrypted_access_token: str
    encrypted_refresh_token: str
    granted_scopes: tuple[str, ...]
    token_expires_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add schema**

Add tables to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    display_name TEXT,
    username TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (telegram_user_id, telegram_chat_id)
);

CREATE TABLE IF NOT EXISTS oauth_sessions (
    state TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    google_subject TEXT NOT NULL,
    google_email TEXT NOT NULL,
    encrypted_access_token TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    granted_scopes TEXT NOT NULL,
    token_expires_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'reauth_required', 'revoked')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 5: Implement store methods**

Add methods to `StateStore`:

```python
def upsert_user_from_telegram(
    self,
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
    display_name: str | None,
    username: str | None,
    now: datetime,
) -> User:
    pass


def get_user_by_telegram(
    self,
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
) -> User | None:
    pass


def activate_user(self, user_id: int, *, now: datetime) -> bool:
    pass


def list_active_google_users(self) -> list[User]:
    pass


def create_oauth_session(
    self,
    *,
    state: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    expires_at: datetime,
    created_at: datetime,
) -> None:
    pass


def consume_oauth_session(self, state: str, *, now: datetime) -> OAuthSession | None:
    pass


def save_google_account(
    self,
    *,
    user_id: int,
    google_subject: str,
    google_email: str,
    encrypted_access_token: str,
    encrypted_refresh_token: str,
    granted_scopes: tuple[str, ...],
    token_expires_at: datetime | None,
    now: datetime,
) -> None:
    pass


def get_google_account(self, user_id: int) -> GoogleAccount | None:
    pass


def mark_google_account_status(self, user_id: int, status: str, *, now: datetime) -> bool:
    pass
```

Implementation details:

```python
def _scopes_to_text(scopes: tuple[str, ...]) -> str:
    return json.dumps(list(scopes))


def _scopes_from_text(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value))
```

- [ ] **Step 6: Run storage tests**

Run: `python -m pytest tests/users/test_user_store.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/personal_hermes/users.py src/personal_hermes/storage/schema.sql src/personal_hermes/storage/store.py tests/users/test_user_store.py
git commit -m "feat: add multiuser storage"
```

## Task 3: Token Encryption

**Files:**
- Create: `src/personal_hermes/oauth/__init__.py`
- Create: `src/personal_hermes/oauth/crypto.py`
- Test: `tests/oauth/test_crypto.py`

- [ ] **Step 1: Write failing encryption tests**

```python
from cryptography.fernet import Fernet

from personal_hermes.oauth.crypto import TokenCipher


def test_token_cipher_round_trips_without_plaintext_leakage():
    cipher = TokenCipher(Fernet.generate_key().decode("ascii"))

    encrypted = cipher.encrypt("refresh-token")

    assert encrypted != "refresh-token"
    assert cipher.decrypt(encrypted) == "refresh-token"
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/oauth/test_crypto.py -v`

Expected: FAIL because `TokenCipher` does not exist.

- [ ] **Step 3: Implement `TokenCipher`**

```python
from cryptography.fernet import Fernet


class TokenCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
```

- [ ] **Step 4: Run encryption tests**

Run: `python -m pytest tests/oauth/test_crypto.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/oauth/__init__.py src/personal_hermes/oauth/crypto.py tests/oauth/test_crypto.py
git commit -m "feat: encrypt google oauth tokens"
```

## Task 4: Google OAuth Client

**Files:**
- Create: `src/personal_hermes/oauth/google.py`
- Test: `tests/oauth/test_google_oauth.py`

- [ ] **Step 1: Write failing OAuth URL test**

```python
from personal_hermes.oauth.google import GoogleOAuthConfig, GoogleOAuthService


def test_authorization_url_uses_offline_access_and_expected_scopes():
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://hermes.example.com/oauth/google/callback",
        )
    )

    url = service.authorization_url(state="state-1")

    assert "access_type=offline" in url
    assert "include_granted_scopes=true" in url
    assert "state=state-1" in url
    assert "gmail.modify" in url
    assert "calendar.events.readonly" in url
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/oauth/test_google_oauth.py -v`

Expected: FAIL because `GoogleOAuthService` does not exist.

- [ ] **Step 3: Implement OAuth config and URL generation**

```python
from dataclasses import dataclass

from google_auth_oauthlib.flow import Flow


GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events.readonly",
)


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


class GoogleOAuthService:
    def __init__(self, config: GoogleOAuthConfig) -> None:
        self.config = config

    def authorization_url(self, *, state: str) -> str:
        flow = self._flow()
        url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=state,
            prompt="consent",
        )
        return url

    def _flow(self) -> Flow:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=GOOGLE_OAUTH_SCOPES,
        )
        flow.redirect_uri = self.config.redirect_uri
        return flow
```

- [ ] **Step 4: Add callback exchange seam test**

Add a test using a fake flow factory:

```python
def test_exchange_callback_returns_token_bundle():
    service = GoogleOAuthService(config, flow_factory=lambda: FakeFlow())

    bundle = service.exchange_callback("https://hermes.example.com/oauth/google/callback?code=abc&state=s")

    assert bundle.access_token == "access"
    assert bundle.refresh_token == "refresh"
    assert bundle.google_email == "user@example.com"
```

- [ ] **Step 5: Implement exchange seam**

Add `GoogleTokenBundle` and allow `flow_factory` injection so tests do not hit Google:

```python
@dataclass(frozen=True)
class GoogleTokenBundle:
    access_token: str
    refresh_token: str
    granted_scopes: tuple[str, ...]
    token_expires_at: datetime | None
    google_subject: str
    google_email: str
```

Fetch user info from `https://openidconnect.googleapis.com/v1/userinfo` with `httpx.Client` using the access token, or inject a `userinfo_fetcher` callable in tests.

- [ ] **Step 6: Run OAuth tests**

Run: `python -m pytest tests/oauth/test_google_oauth.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/personal_hermes/oauth/google.py tests/oauth/test_google_oauth.py
git commit -m "feat: add google oauth service"
```

## Task 5: OAuth Callback Web Runtime

**Files:**
- Create: `src/personal_hermes/oauth/web.py`
- Test: `tests/oauth/test_web.py`

- [ ] **Step 1: Write failing callback test**

```python
from fastapi.testclient import TestClient

from personal_hermes.oauth.web import create_oauth_app


def test_google_callback_consumes_session_and_stores_account(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    store.create_oauth_session(
        state="state-1",
        telegram_user_id=456,
        telegram_chat_id=123,
        expires_at=now + timedelta(minutes=15),
        created_at=now,
    )
    oauth = FakeOAuthService()
    cipher = FakeTokenCipher()
    telegram = FakeTelegram()

    app = create_oauth_app(store=store, oauth=oauth, token_cipher=cipher, telegram=telegram)
    response = TestClient(app).get("/oauth/google/callback?state=state-1&code=abc")

    assert response.status_code == 200
    assert "connected" in response.text.lower()
    account = store.get_google_account(user_id=1)
    assert account.google_email == "user@example.com"
    assert telegram.sent[0]["text"] == "Google connected."
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/oauth/test_web.py -v`

Expected: FAIL because `create_oauth_app` does not exist.

- [ ] **Step 3: Implement FastAPI callback**

```python
from datetime import UTC, datetime

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse


def create_oauth_app(*, store, oauth, token_cipher, telegram) -> FastAPI:
    app = FastAPI()

    @app.get("/oauth/google/callback", response_class=HTMLResponse)
    def google_callback(state: str = Query(...), code: str = Query(...)):
        now = datetime.now(tz=UTC)
        session = store.consume_oauth_session(state, now=now)
        if session is None:
            return HTMLResponse("<h1>Connection expired</h1><p>Return to Telegram and run /connect again.</p>", status_code=400)

        user = store.upsert_user_from_telegram(
            telegram_user_id=session.telegram_user_id,
            telegram_chat_id=session.telegram_chat_id,
            display_name=None,
            username=None,
            now=now,
        )
        bundle = oauth.exchange_code(code=code)
        store.save_google_account(
            user_id=user.id,
            google_subject=bundle.google_subject,
            google_email=bundle.google_email,
            encrypted_access_token=token_cipher.encrypt(bundle.access_token),
            encrypted_refresh_token=token_cipher.encrypt(bundle.refresh_token),
            granted_scopes=bundle.granted_scopes,
            token_expires_at=bundle.token_expires_at,
            now=now,
        )
        store.activate_user(user.id, now=now)
        telegram.send_message(chat_id=session.telegram_chat_id, text="Google connected.")
        return HTMLResponse("<h1>Google connected</h1><p>You can return to Telegram.</p>")

    return app
```

- [ ] **Step 4: Run callback tests**

Run: `python -m pytest tests/oauth/test_web.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/oauth/web.py tests/oauth/test_web.py
git commit -m "feat: add google oauth callback app"
```

## Task 6: Telegram Onboarding Commands

**Files:**
- Modify: `src/personal_hermes/router.py`
- Test: `tests/multiuser/test_router_onboarding.py`
- Update: `tests/test_router.py`

- [ ] **Step 1: Write failing `/connect` test**

```python
def test_connect_creates_oauth_session_and_sends_google_link(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    telegram = FakeTelegram()
    oauth = FakeOAuthService(url="https://accounts.google.com/o/oauth2/auth?state=abc")
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=store,
        oauth_service=oauth,
        invite_only=False,
        invited_telegram_user_ids=(),
        oauth_session_ttl_minutes=15,
    )

    router.handle_event(TelegramMessage(chat_id=123, user_id=456, message_id=1, text="/connect"), now=NOW)

    assert "https://accounts.google.com" in telegram.sent[0]["text"]
    assert store.get_user_by_telegram(telegram_user_id=456, telegram_chat_id=123) is not None
```

- [ ] **Step 2: Write failing `/status` and invite-only tests**

```python
def test_uninvited_user_receives_invite_only_message():
    router = make_router(invited_user_ids=(999,))

    router.handle_event(message("/connect", user_id=456), now=NOW)

    assert "invite-only" in router.telegram.sent[0]["text"]


def test_status_reports_reauth_required(tmp_path):
    store = connected_store_with_google_status(tmp_path, status="reauth_required")
    router = make_router(store=store)

    router.handle_event(message("/status"), now=NOW)

    assert "reconnect" in router.telegram.sent[0]["text"].lower()
```

- [ ] **Step 3: Run router onboarding tests and verify failure**

Run: `python -m pytest tests/multiuser/test_router_onboarding.py -v`

Expected: FAIL because onboarding dependencies and commands do not exist.

- [ ] **Step 4: Add router dependencies**

Extend `AssistantRouter.__init__`:

```python
def __init__(
    *,
    telegram,
    calendar_service,
    mail_action_service,
    store,
    oauth_service=None,
    invite_only: bool = True,
    invited_telegram_user_ids: tuple[int, ...] = (),
    oauth_session_ttl_minutes: int = 15,
) -> None:
```

- [ ] **Step 5: Implement command handling before availability routing**

```python
if event.text == "/connect":
    self._handle_connect(event, now=now)
    return
if event.text == "/status":
    self._handle_status(event)
    return
if event.text == "/disconnect":
    self._handle_disconnect(event, now=now)
    return
```

Use `secrets.token_urlsafe(32)` for state and `oauth_service.authorization_url(state=state)` for the link.

- [ ] **Step 6: Update legacy authorization behavior**

For multiuser mode, replace `telegram.is_authorized(event)` with:

```python
user = self.store.get_user_by_telegram(
    telegram_user_id=event.user_id,
    telegram_chat_id=event.chat_id,
)
if user is None or user.status != "active":
    self.telegram.send_message(chat_id=event.chat_id, text="Connect Google first with /connect.")
    return
```

Keep existing single-user authorization in tests by constructing router without `oauth_service` and with old `telegram.is_authorized`.

- [ ] **Step 7: Run router tests**

Run: `python -m pytest tests/test_router.py tests/multiuser/test_router_onboarding.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/personal_hermes/router.py tests/test_router.py tests/multiuser/test_router_onboarding.py
git commit -m "feat: add telegram google onboarding commands"
```

## Task 7: User-Scoped Store APIs For Existing State

**Files:**
- Modify: `src/personal_hermes/storage/schema.sql`
- Modify: `src/personal_hermes/storage/store.py`
- Update: `tests/storage/test_store.py`

- [ ] **Step 1: Add failing user-scoped dedupe tests**

```python
def test_seen_email_deduplication_is_user_scoped(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    payload = {
        "email_id": "msg-1",
        "thread_id": "thread-1",
        "subject": "Subject",
        "sender": "sender@example.com",
        "telegram_message_id": 10,
        "first_seen_at": now,
    }

    assert store.mark_email_seen(user_id=1, **payload) is True
    assert store.mark_email_seen(user_id=1, **payload) is False
    assert store.mark_email_seen(user_id=2, **payload) is True
```

- [ ] **Step 2: Run storage tests and verify failure**

Run: `python -m pytest tests/storage/test_store.py -v`

Expected: FAIL because current tables have no `user_id`.

- [ ] **Step 3: Modify schema**

Change existing tables so primary keys include `user_id`:

```sql
CREATE TABLE IF NOT EXISTS seen_emails (
    user_id INTEGER NOT NULL,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    telegram_message_id INTEGER,
    PRIMARY KEY (user_id, email_id)
);
```

Apply the same pattern:

- `calendar_agenda_notifications`: `PRIMARY KEY (user_id, agenda_date)`
- `calendar_reminders`: `PRIMARY KEY (user_id, event_id, event_start_at)`
- `conversation_state`: `PRIMARY KEY (user_id, telegram_chat_id)`

Add `user_id INTEGER NOT NULL` to `pending_replies` and `reply_audit_log`.

- [ ] **Step 4: Update store signatures**

Update current methods to require `user_id`:

```python
def mark_email_seen(
    self,
    *,
    user_id: int,
    email_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    telegram_message_id: int | None,
    first_seen_at: datetime,
) -> bool
def has_seen_email(self, *, user_id: int, email_id: str) -> bool
def create_pending_reply(
    self,
    *,
    user_id: int,
    email_id: str,
    thread_id: str,
    reply_text: str,
    created_at: datetime,
    expires_at: datetime,
    telegram_message_id: int | None,
) -> int
def get_pending_reply(self, pending_reply_id: int, *, user_id: int | None = None, now: datetime | None = None) -> PendingReply | None
def mark_agenda_sent(self, agenda_date: date, *, user_id: int, sent_at: datetime) -> bool
def mark_calendar_reminder_sent(self, *, user_id: int, event_id: str, event_start_at: datetime, sent_at: datetime) -> bool
```

Add `user_id` to the `PendingReply` and `ConversationState` dataclasses.

- [ ] **Step 5: Run storage tests**

Run: `python -m pytest tests/storage/test_store.py tests/users/test_user_store.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/personal_hermes/storage/schema.sql src/personal_hermes/storage/store.py tests/storage/test_store.py tests/users/test_user_store.py
git commit -m "feat: scope assistant state by user"
```

## Task 8: User-Scoped Mail And Reply Actions

**Files:**
- Modify: `src/personal_hermes/mail/service.py`
- Modify: `src/personal_hermes/mail/actions.py`
- Test: `tests/multiuser/test_user_scoped_services.py`
- Update: `tests/mail/test_mail_polling.py`
- Update: `tests/mail/test_reply_actions.py`

- [ ] **Step 1: Write failing mail scoping tests**

```python
def test_mail_polling_sends_to_user_chat_and_dedupes_per_user(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = MailPollingService(openclaw_client=client, telegram=telegram, store=store, pending_reply_expiry_days=7)

    service.poll(user_id=1, chat_id=123, since_cursor=None, now=NOW)
    service.poll(user_id=2, chat_id=999, since_cursor=None, now=NOW)

    assert [sent["chat_id"] for sent in telegram.sent] == [123, 999]
```

- [ ] **Step 2: Write failing reply ownership test**

```python
def test_reply_action_rejects_pending_reply_owned_by_another_user(tmp_path):
    pending_id = store.create_pending_reply(
        user_id=1,
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Suggested reply",
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
        telegram_message_id=77,
    )
    service.handle_callback(callback_from_user_2, user_id=2, now=NOW)

    assert telegram.answers[0]["text"] == "Reply is no longer pending"
    assert client.sent_replies == []
```

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/multiuser/test_user_scoped_services.py tests/mail/test_mail_polling.py tests/mail/test_reply_actions.py -v`

Expected: FAIL because services do not accept `user_id`.

- [ ] **Step 4: Update `MailPollingService`**

Remove `authorized_chat_id` from constructor. Change poll signature:

```python
def poll(self, *, user_id: int, chat_id: int, since_cursor: str | None, now: datetime) -> MailPollResult:
```

Use `user_id` in `has_seen_email`, `create_pending_reply`, and `mark_email_seen`. Use `chat_id` for `telegram.send_message`.

- [ ] **Step 5: Update `MailActionService`**

Change callback entrypoint:

```python
def handle_callback(self, callback: TelegramCallback, *, user_id: int, now: datetime) -> None:
```

Use `store.get_pending_reply(pending_reply_id, user_id=user_id, now=now)`.

For `mark_read`, verify the email is seen for that user before calling Google:

```python
if not self.store.has_seen_email(user_id=user_id, email_id=email_id):
    self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Email not found")
    return
```

- [ ] **Step 6: Update router callback calls**

When routing connected callbacks:

```python
self.mail_action_service.handle_callback(callback, user_id=user.id, now=now)
```

- [ ] **Step 7: Run mail tests**

Run: `python -m pytest tests/mail tests/multiuser/test_user_scoped_services.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/personal_hermes/mail/service.py src/personal_hermes/mail/actions.py src/personal_hermes/router.py tests/mail tests/multiuser/test_user_scoped_services.py
git commit -m "feat: scope mail actions by user"
```

## Task 9: User-Scoped Calendar Notifications

**Files:**
- Modify: `src/personal_hermes/calendar/notifications.py`
- Update: `tests/calendar/test_notifications.py`
- Update: `tests/multiuser/test_user_scoped_services.py`

- [ ] **Step 1: Write failing calendar scoping test**

```python
def test_calendar_reminder_deduplication_is_user_scoped(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    service = CalendarNotificationService(store)
    event = make_event("event-1", NOW + timedelta(minutes=30))

    assert service.events_due_for_reminder([event], user_id=1, now=NOW, lead_minutes=30) == [event]
    assert service.events_due_for_reminder([event], user_id=1, now=NOW, lead_minutes=30) == []
    assert service.events_due_for_reminder([event], user_id=2, now=NOW, lead_minutes=30) == [event]
```

- [ ] **Step 2: Run calendar tests and verify failure**

Run: `python -m pytest tests/calendar/test_notifications.py tests/multiuser/test_user_scoped_services.py -v`

Expected: FAIL because notification service does not accept `user_id`.

- [ ] **Step 3: Update notification service signatures**

```python
def events_for_daily_agenda(self, agenda_date: date, events: list[CalendarEvent], *, user_id: int, now: datetime) -> list[CalendarEvent]:
def events_due_for_reminder(self, events: list[CalendarEvent], *, user_id: int, now: datetime, lead_minutes: int) -> list[CalendarEvent]:
```

Pass `user_id` into store dedupe methods.

- [ ] **Step 4: Run calendar tests**

Run: `python -m pytest tests/calendar/test_notifications.py tests/multiuser/test_user_scoped_services.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/calendar/notifications.py tests/calendar/test_notifications.py tests/multiuser/test_user_scoped_services.py
git commit -m "feat: scope calendar notifications by user"
```

## Task 10: Direct Google API Account Provider

**Files:**
- Modify: `src/personal_hermes/oauth/google.py`
- Test: `tests/oauth/test_google_oauth.py`

- [ ] **Step 1: Write failing provider test**

```python
def test_google_account_provider_decrypts_tokens_and_builds_clients(tmp_path):
    account = save_account(store, user_id=1, encrypted_access_token="enc-access", encrypted_refresh_token="enc-refresh")
    provider = GoogleAccountProvider(store=store, token_cipher=FakeCipher(), client_builder=FakeClientBuilder())

    client = provider.client_for_user(1)

    assert client.user_id == 1
    assert client.access_token == "access"
```

- [ ] **Step 2: Run provider test and verify failure**

Run: `python -m pytest tests/oauth/test_google_oauth.py -v`

Expected: FAIL because `GoogleAccountProvider` does not exist.

- [ ] **Step 3: Implement provider**

Add:

```python
class GoogleAccountProvider:
    def __init__(self, *, store: StateStore, token_cipher: TokenCipher, config: GoogleOAuthConfig, client_builder=None) -> None:
        self.store = store
        self.token_cipher = token_cipher
        self.config = config
        self.client_builder = client_builder or GoogleApiClient

    def client_for_user(self, user_id: int):
        account = self.store.get_google_account(user_id)
        if account is None or account.status != "active":
            raise GoogleAccountUnavailable(user_id)
        return self.client_builder(
            access_token=self.token_cipher.decrypt(account.encrypted_access_token),
            refresh_token=self.token_cipher.decrypt(account.encrypted_refresh_token),
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=account.granted_scopes,
        )
```

Add `GoogleApiClient` methods matching existing OpenClaw client protocols:

```python
def list_new_inbox_messages(self, since_cursor: str | None) -> list[EmailMessage]:
    query = "in:inbox"
    if since_cursor:
        query = f"{query} {since_cursor}"
    return self._gmail_list_messages(query)


def get_email_message(self, email_id: str) -> EmailMessage:
    return self._gmail_get_message(email_id)


def send_thread_reply(self, request: SendEmailReplyRequest) -> str:
    return self._gmail_send_reply(request)


def mark_email_read(self, email_id: str) -> None:
    self._gmail_modify_labels(email_id, remove_label_ids=["UNREAD"])


def list_calendar_events(self, start_at: datetime, end_at: datetime) -> list[CalendarEvent]:
    return self._calendar_list_events(start_at=start_at, end_at=end_at)
```

- [ ] **Step 4: Run OAuth tests**

Run: `python -m pytest tests/oauth/test_google_oauth.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/personal_hermes/oauth/google.py tests/oauth/test_google_oauth.py
git commit -m "feat: add user google account provider"
```

## Task 11: Per-User Scheduler Isolation

**Files:**
- Modify: `src/personal_hermes/scheduler.py`
- Test: `tests/multiuser/test_scheduler.py`
- Update: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler isolation test**

```python
def test_multiuser_gmail_job_continues_after_one_user_failure():
    users = [
        User(
            id=1,
            telegram_user_id=456,
            telegram_chat_id=123,
            display_name="One",
            username="one",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        ),
        User(
            id=2,
            telegram_user_id=789,
            telegram_chat_id=999,
            display_name="Two",
            username="two",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    scheduler = make_multiuser_scheduler(users=users, provider=FailingThenWorkingProvider())

    scheduler.run_gmail_poll_job()

    assert scheduler.mail_polling_service.calls == [(2, 999)]
    assert scheduler.errors[0].user_id == 1
```

- [ ] **Step 2: Run scheduler tests and verify failure**

Run: `python -m pytest tests/multiuser/test_scheduler.py tests/test_scheduler.py -v`

Expected: FAIL because scheduler has no user iteration.

- [ ] **Step 3: Add provider protocols**

```python
class ActiveUserStore(Protocol):
    def list_active_google_users(self) -> list[User]:
        pass


class GoogleClientProvider(Protocol):
    def client_for_user(self, user_id: int):
        pass
```

- [ ] **Step 4: Update scheduler constructor**

Add optional multiuser dependencies:

```python
store: ActiveUserStore | None = None
google_account_provider: GoogleClientProvider | None = None
```

- [ ] **Step 5: Update job methods**

When `google_account_provider` is present:

```python
for user in self.store.list_active_google_users():
    try:
        client = self.google_account_provider.client_for_user(user.id)
        self.mail_polling_service.openclaw_client = client
        self.mail_polling_service.poll(user_id=user.id, chat_id=user.telegram_chat_id, since_cursor=since_cursor, now=now)
    except Exception:
        logger.exception("Gmail poll failed for user_id=%s", user.id)
```

Use the same per-user pattern for daily agenda and reminders. Keep the current single-user path when no provider is configured.

- [ ] **Step 6: Run scheduler tests**

Run: `python -m pytest tests/test_scheduler.py tests/multiuser/test_scheduler.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/personal_hermes/scheduler.py tests/test_scheduler.py tests/multiuser/test_scheduler.py
git commit -m "feat: run scheduler jobs per connected user"
```

## Task 12: App Wiring And Runtime Commands

**Files:**
- Modify: `src/personal_hermes/app.py`
- Modify: `src/personal_hermes/__main__.py`
- Update: `tests/test_app.py`

- [ ] **Step 1: Write failing app wiring test**

```python
def test_build_components_wires_multiuser_oauth_when_enabled(tmp_path, monkeypatch):
    settings = make_settings(
        sqlite_database_path=str(tmp_path / "state.sqlite3"),
        multiuser_enabled=True,
        public_base_url="https://hermes.example.com",
        google_oauth_client_id="client-id",
        google_oauth_client_secret="client-secret",
        token_encryption_key=Fernet.generate_key().decode("ascii"),
    )

    components = build_components(settings)

    assert components.oauth_service is not None
    assert components.google_account_provider is not None
```

- [ ] **Step 2: Run app tests and verify failure**

Run: `python -m pytest tests/test_app.py -v`

Expected: FAIL because `AppComponents` lacks OAuth fields.

- [ ] **Step 3: Extend `AppComponents`**

Add:

```python
oauth_service: GoogleOAuthService | None = None
oauth_app: FastAPI | None = None
token_cipher: TokenCipher | None = None
google_account_provider: GoogleAccountProvider | None = None
```

- [ ] **Step 4: Wire multiuser dependencies in `build_components`**

When `settings.multiuser_enabled` is true:

```python
token_cipher = TokenCipher(settings.token_encryption_key)
oauth_config = GoogleOAuthConfig(
    client_id=settings.google_oauth_client_id,
    client_secret=settings.google_oauth_client_secret,
    redirect_uri=settings.google_oauth_redirect_url,
)
oauth_service = GoogleOAuthService(oauth_config)
google_account_provider = GoogleAccountProvider(store=store, token_cipher=token_cipher, config=oauth_config)
oauth_app = create_oauth_app(store=store, oauth=oauth_service, token_cipher=token_cipher, telegram=telegram)
```

Pass `oauth_service`, invite settings, and TTL to `AssistantRouter`. Pass `store` and `google_account_provider` to `AssistantScheduler`.

- [ ] **Step 5: Add runtime start behavior**

For the first implementation, keep one process and start the OAuth app in a background thread before starting APScheduler:

```python
def start_runtime(components: AppComponents) -> None:
    if components.oauth_app is not None:
        thread = threading.Thread(
            target=lambda: uvicorn.run(
                components.oauth_app,
                host=components.settings.oauth_host,
                port=components.settings.oauth_port,
            ),
            daemon=True,
        )
        thread.start()
    job_scheduler = BlockingScheduler(timezone=components.settings.timezone)
    configure_job_schedule(components, job_scheduler)
    job_scheduler.start()
```

- [ ] **Step 6: Run app tests**

Run: `python -m pytest tests/test_app.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/personal_hermes/app.py src/personal_hermes/__main__.py tests/test_app.py
git commit -m "feat: wire multiuser oauth runtime"
```

## Task 13: Migration Bootstrap And Backfill

**Files:**
- Modify: `src/personal_hermes/storage/store.py`
- Modify: `src/personal_hermes/app.py`
- Test: `tests/storage/test_store.py`

- [ ] **Step 1: Write failing bootstrap test**

```python
def test_bootstrap_user_backfills_existing_single_user_rows(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    insert_legacy_seen_email_without_user_id(store.database_path, email_id="msg-1")

    user = store.bootstrap_single_user(
        telegram_user_id=456,
        telegram_chat_id=123,
        now=NOW,
    )

    assert user.id > 0
    assert store.has_seen_email(user_id=user.id, email_id="msg-1") is True
```

- [ ] **Step 2: Run bootstrap test and verify failure**

Run: `python -m pytest tests/storage/test_store.py -v`

Expected: FAIL because bootstrap/backfill does not exist.

- [ ] **Step 3: Implement bootstrap**

Because SQLite schemas are created fresh in current tests, implement bootstrap for the current schema by creating an active user and using it in single-user app wiring:

```python
def bootstrap_single_user(self, *, telegram_user_id: int, telegram_chat_id: int, now: datetime) -> User:
    user = self.upsert_user_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        display_name=None,
        username=None,
        now=now,
    )
    self.activate_user(user.id, now=now)
    return user
```

If production has a legacy DB, run a one-off SQL migration before deploying this branch. The current test DBs are disposable, so no destructive in-place migration is required for local development.

- [ ] **Step 4: Wire bootstrap in `build_components` for single-user mode**

When `multiuser_enabled` is false, create a bootstrap user and pass `bootstrap_user.id` into legacy service calls so updated user-scoped store methods still work.

- [ ] **Step 5: Run storage and app tests**

Run: `python -m pytest tests/storage/test_store.py tests/test_app.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/personal_hermes/storage/store.py src/personal_hermes/app.py tests/storage/test_store.py tests/test_app.py
git commit -m "feat: bootstrap single user during migration"
```

## Task 14: Disconnect And Token Revocation

**Files:**
- Modify: `src/personal_hermes/oauth/google.py`
- Modify: `src/personal_hermes/router.py`
- Test: `tests/oauth/test_google_oauth.py`
- Test: `tests/multiuser/test_router_onboarding.py`

- [ ] **Step 1: Write failing revoke test**

```python
def test_disconnect_revokes_google_token_and_marks_account_revoked(tmp_path):
    store = connected_store(tmp_path)
    oauth = FakeOAuthService()
    router = make_router(store=store, oauth=oauth)

    router.handle_event(message("/disconnect"), now=NOW)

    assert store.get_google_account(1).status == "revoked"
    assert oauth.revoked_tokens == ["refresh-token"]
    assert "disconnected" in router.telegram.sent[0]["text"].lower()
```

- [ ] **Step 2: Run disconnect tests and verify failure**

Run: `python -m pytest tests/oauth/test_google_oauth.py tests/multiuser/test_router_onboarding.py -v`

Expected: FAIL because revocation is not implemented.

- [ ] **Step 3: Implement token revocation**

Add to `GoogleOAuthService`:

```python
def revoke_token(self, token: str) -> bool:
    response = httpx.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": token},
        timeout=10,
    )
    return response.status_code in (200, 400)
```

Treat `400` as already-invalid for local disconnect purposes.

- [ ] **Step 4: Implement `/disconnect`**

In router:

```python
account = self.store.get_google_account(user.id)
if account is not None:
    refresh_token = self.token_cipher.decrypt(account.encrypted_refresh_token)
    self.oauth_service.revoke_token(refresh_token)
    self.store.mark_google_account_status(user.id, "revoked", now=now)
self.store.mark_user_status(user.id, "revoked", now=now)
self.telegram.send_message(chat_id=event.chat_id, text="Google disconnected.")
```

- [ ] **Step 5: Run disconnect tests**

Run: `python -m pytest tests/oauth/test_google_oauth.py tests/multiuser/test_router_onboarding.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/personal_hermes/oauth/google.py src/personal_hermes/router.py tests/oauth/test_google_oauth.py tests/multiuser/test_router_onboarding.py
git commit -m "feat: disconnect google accounts"
```

## Task 15: End-To-End Test Pass And Documentation

**Files:**
- Modify: `README.md`
- Create or Modify: `docs/operations/smoke-test.md`
- Update: tests as needed for final integration

- [ ] **Step 1: Update README**

Document:

```markdown
## Multiuser Google OAuth

Set `MULTIUSER_ENABLED=true` to let Telegram users connect their own Google accounts.
Users start onboarding with `/connect`.
The OAuth callback runs on `OAUTH_HOST:OAUTH_PORT` and must be reachable at `PUBLIC_BASE_URL`.
For invite-only beta, set `INVITE_ONLY=true` and list Telegram user IDs in `INVITED_TELEGRAM_USER_IDS`.
```

- [ ] **Step 2: Update smoke test**

Add checks:

```markdown
1. Start the service with `MULTIUSER_ENABLED=true`.
2. Send `/connect` from an invited Telegram user.
3. Confirm the bot returns a Google authorization URL.
4. Complete Google consent.
5. Confirm Telegram receives `Google connected.`
6. Send `/status` and confirm it reports the Google account email.
7. Send `/disconnect` and confirm background jobs skip the user.
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest`

Expected: all tests PASS.

- [ ] **Step 4: Run config check**

Run: `python -m personal_hermes --check-config`

Expected in a fully configured environment: `Configuration OK`.

If local OAuth secrets are intentionally missing and `MULTIUSER_ENABLED=false`, expected: `Configuration OK` for single-user mode.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations/smoke-test.md tests src pyproject.toml .env.example
git commit -m "docs: add multiuser oauth operations guide"
```

## Final Verification

- [ ] Run `python -m pytest`.
- [ ] Run `python -m personal_hermes --check-config` with single-user settings.
- [ ] Run `python -m personal_hermes --check-config` with multiuser OAuth settings.
- [ ] Inspect `git status --short` and confirm only intended files are modified.
