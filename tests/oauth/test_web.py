from datetime import UTC, datetime, timedelta
from cryptography.fernet import Fernet

from fastapi.testclient import TestClient

from personal_hermes.oauth.crypto import TokenCipher
from personal_hermes.oauth.google import GoogleTokenBundle, GoogleOAuthService
from personal_hermes.oauth.web import create_oauth_app
from personal_hermes.storage.store import StateStore


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        self.sent.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        return 123


class FakeOAuthService:
    def __init__(self, bundle: GoogleTokenBundle):
        self.bundle = bundle
        self.calls: list[tuple[str, str]] = []

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.com/o/oauth2/auth?state={state}"

    def exchange_callback(self, callback_url: str, *, expected_state: str) -> GoogleTokenBundle:
        self.calls.append((callback_url, expected_state))
        return self.bundle


def test_google_callback_consumes_session_and_stores_google_account(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    state = "state-1"
    store.create_oauth_session(
        state=state,
        telegram_user_id=123,
        telegram_chat_id=456,
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )
    oauth_service = FakeOAuthService(
        GoogleTokenBundle(
            access_token="access",
            refresh_token="refresh",
            granted_scopes=("openid", "email"),
            token_expires_at=None,
            google_subject="google-subject",
            google_email="user@example.com",
        )
    )
    telegram = FakeTelegram()
    app = create_oauth_app(
        store=store,
        oauth=oauth_service,
        token_cipher=TokenCipher(Fernet.generate_key().decode()),
        telegram=telegram,
        now_provider=lambda: now,
    )

    response = TestClient(app).get(
        "/oauth/google/callback",
        params={"state": state, "code": "auth-code"},
    )

    assert response.status_code == 200
    assert "Google connected" in response.text
    user = store.get_user_by_telegram(telegram_user_id=123, telegram_chat_id=456)
    assert user is not None
    account = store.get_google_account(user.id)
    assert account is not None
    assert account.google_email == "user@example.com"
    assert telegram.sent == [
        {"chat_id": 456, "text": "Google connected.", "buttons": None}
    ]
    assert oauth_service.calls == [
        ("/oauth/google/callback?state=state-1&code=auth-code", state),
    ]


def test_google_callback_returns_error_for_missing_session(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    oauth_service = FakeOAuthService(
        GoogleTokenBundle(
            access_token="access",
            refresh_token="refresh",
            granted_scopes=("openid", "email"),
            token_expires_at=None,
            google_subject="google-subject",
            google_email="user@example.com",
        )
    )
    app = create_oauth_app(
        store=store,
        oauth=oauth_service,
        token_cipher=TokenCipher(Fernet.generate_key().decode()),
        telegram=FakeTelegram(),
    )

    response = TestClient(app).get(
        "/oauth/google/callback",
        params={"state": "missing", "code": "auth-code"},
    )

    assert response.status_code == 400
    assert "Connection expired" in response.text
    assert oauth_service.calls == []
