from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from personal_hermes.oauth.google import (
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_USERINFO_TIMEOUT_SECONDS,
    GOOGLE_USERINFO_URL,
    GoogleOAuthError,
    GoogleOAuthConfig,
    GoogleOAuthService,
    GoogleTokenBundle,
)


UNSET = object()


class FakeCredentials:
    def __init__(
        self,
        *,
        token="access",
        refresh_token="refresh",
        scopes=UNSET,
        expiry=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
    ) -> None:
        self.token = token
        self.refresh_token = refresh_token
        self.scopes = ["scope-a", "scope-b"] if scopes is UNSET else scopes
        self.expiry = expiry


class FakeFlow:
    def __init__(self, credentials=None) -> None:
        self.credentials = credentials or FakeCredentials()
        self.redirect_uri = None
        self.authorization_kwargs = None
        self.code = None

    def authorization_url(self, **kwargs):
        self.authorization_kwargs = kwargs
        return (
            "https://accounts.google.com/o/oauth2/auth?"
            f"access_type={kwargs['access_type']}&"
            f"include_granted_scopes={kwargs['include_granted_scopes']}&"
            f"prompt={kwargs['prompt']}&"
            f"state={kwargs['state']}"
        ), kwargs["state"]

    def fetch_token(self, code: str) -> None:
        self.code = code


def test_authorization_url_uses_offline_access_and_expected_scopes():
    fake_flow = FakeFlow()
    captured = {}

    def flow_factory(*, client_config, scopes):
        captured["client_config"] = client_config
        captured["scopes"] = scopes
        return fake_flow

    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=flow_factory,
    )

    authorization_url = service.authorization_url(state="state-123")

    parsed = urlparse(authorization_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert captured["scopes"] == GOOGLE_OAUTH_SCOPES
    assert "openid" in captured["scopes"]
    assert "email" in captured["scopes"]
    assert "https://www.googleapis.com/auth/gmail.modify" in captured["scopes"]
    assert "https://www.googleapis.com/auth/gmail.send" in captured["scopes"]
    assert (
        "https://www.googleapis.com/auth/calendar.events.readonly"
        in captured["scopes"]
    )
    assert fake_flow.redirect_uri == "https://example.test/oauth/google/callback"
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["state-123"]


def test_exchange_code_returns_token_bundle_from_flow_and_userinfo():
    fake_flow = FakeFlow()

    def fetch_userinfo(access_token: str):
        return {"sub": "google-subject", "email": "person@example.test"}

    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: fake_flow,
        userinfo_fetcher=fetch_userinfo,
    )

    bundle = service.exchange_code(code="oauth-code")

    assert fake_flow.code == "oauth-code"
    assert bundle == GoogleTokenBundle(
        access_token="access",
        refresh_token="refresh",
        granted_scopes=("scope-a", "scope-b"),
        token_expires_at=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
        google_subject="google-subject",
        google_email="person@example.test",
    )


def test_exchange_code_fetches_userinfo_with_access_token():
    fake_flow = FakeFlow()
    seen_access_tokens = []

    def fetch_userinfo(access_token: str):
        seen_access_tokens.append(access_token)
        return {"sub": "google-subject", "email": "person@example.test"}

    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: fake_flow,
        userinfo_fetcher=fetch_userinfo,
    )

    service.exchange_code(code="oauth-code")

    assert seen_access_tokens == ["access"]


def test_exchange_code_defaults_granted_scopes_when_credentials_scopes_absent():
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(FakeCredentials(scopes=None)),
        userinfo_fetcher=lambda access_token: {
            "sub": "google-subject",
            "email": "person@example.test",
        },
    )

    bundle = service.exchange_code(code="oauth-code")

    assert bundle.granted_scopes == GOOGLE_OAUTH_SCOPES


def test_exchange_callback_exchanges_code_when_state_matches():
    fake_flow = FakeFlow()
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: fake_flow,
        userinfo_fetcher=lambda access_token: {
            "sub": "google-subject",
            "email": "person@example.test",
        },
    )

    bundle = service.exchange_callback(
        "https://example.test/oauth/google/callback?code=oauth-code&state=state-123",
        expected_state="state-123",
    )

    assert fake_flow.code == "oauth-code"
    assert bundle.access_token == "access"


@pytest.mark.parametrize(
    ("callback_url", "expected_message"),
    (
        (
            "https://example.test/oauth/google/callback?error=access_denied&state=state-123",
            "rejected callback",
        ),
        (
            "https://example.test/oauth/google/callback?error_description=Nope&state=state-123",
            "rejected callback",
        ),
        (
            "https://example.test/oauth/google/callback?code=oauth-code",
            "missing state",
        ),
        (
            "https://example.test/oauth/google/callback?code=oauth-code&state=wrong",
            "state mismatch",
        ),
        (
            "https://example.test/oauth/google/callback?state=state-123",
            "missing code",
        ),
        (
            "https://example.test/oauth/google/callback?code=&state=state-123",
            "blank code",
        ),
        (
            "https://example.test/oauth/google/callback?code=one&code=two&state=state-123",
            "multiple code values",
        ),
    ),
)
def test_exchange_callback_rejects_invalid_callback(callback_url, expected_message):
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(),
        userinfo_fetcher=lambda access_token: {
            "sub": "google-subject",
            "email": "person@example.test",
        },
    )

    with pytest.raises(GoogleOAuthError, match=expected_message):
        service.exchange_callback(callback_url, expected_state="state-123")


def test_exchange_code_rejects_missing_refresh_token():
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(
            FakeCredentials(refresh_token=None),
        ),
        userinfo_fetcher=lambda access_token: {
            "sub": "google-subject",
            "email": "person@example.test",
        },
    )

    with pytest.raises(GoogleOAuthError, match="missing refresh token"):
        service.exchange_code(code="oauth-code")


def test_exchange_code_rejects_missing_access_token():
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(
            FakeCredentials(token=None),
        ),
        userinfo_fetcher=lambda access_token: {
            "sub": "google-subject",
            "email": "person@example.test",
        },
    )

    with pytest.raises(GoogleOAuthError, match="missing access token"):
        service.exchange_code(code="oauth-code")


@pytest.mark.parametrize(
    ("userinfo", "expected_message"),
    (
        ({}, "missing Google subject"),
        ({"sub": None, "email": "person@example.test"}, "missing Google subject"),
        ({"sub": "", "email": "person@example.test"}, "missing Google subject"),
        ({"sub": "google-subject"}, "missing Google email"),
        ({"sub": "google-subject", "email": None}, "missing Google email"),
        ({"sub": "google-subject", "email": ""}, "missing Google email"),
    ),
)
def test_exchange_code_rejects_missing_or_malformed_userinfo(
    userinfo,
    expected_message,
):
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(),
        userinfo_fetcher=lambda access_token: userinfo,
    )

    with pytest.raises(GoogleOAuthError, match=expected_message):
        service.exchange_code(code="oauth-code")


def test_exchange_code_rejects_non_mapping_userinfo():
    service = GoogleOAuthService(
        GoogleOAuthConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.test/oauth/google/callback",
        ),
        flow_factory=lambda **kwargs: FakeFlow(),
        userinfo_fetcher=lambda access_token: ["not", "a", "mapping"],
    )

    with pytest.raises(GoogleOAuthError, match="malformed payload"):
        service.exchange_code(code="oauth-code")


def test_default_userinfo_fetch_uses_timeout_and_authorization_header(monkeypatch):
    seen_request = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"sub": "google-subject", "email": "person@example.test"}

    def fake_get(url, *, headers, timeout):
        seen_request["url"] = url
        seen_request["headers"] = headers
        seen_request["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    userinfo = GoogleOAuthService._fetch_userinfo("access-token")

    assert userinfo == {"sub": "google-subject", "email": "person@example.test"}
    assert seen_request == {
        "url": GOOGLE_USERINFO_URL,
        "headers": {"Authorization": "Bearer access-token"},
        "timeout": GOOGLE_USERINFO_TIMEOUT_SECONDS,
    }


def test_default_userinfo_fetch_raises_controlled_error_on_http_failure(monkeypatch):
    request = httpx.Request("GET", GOOGLE_USERINFO_URL)

    def fake_get(url, *, headers, timeout):
        raise httpx.RequestError("network down", request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GoogleOAuthError, match="userinfo request failed"):
        GoogleOAuthService._fetch_userinfo("access-token")


def test_default_userinfo_fetch_raises_controlled_error_on_non_2xx(monkeypatch):
    request = httpx.Request("GET", GOOGLE_USERINFO_URL)
    response = httpx.Response(401, request=request)

    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "unauthorized",
                request=request,
                response=response,
            )

        def json(self):
            return {"sub": "google-subject", "email": "person@example.test"}

    monkeypatch.setattr(httpx, "get", lambda url, *, headers, timeout: FakeResponse())

    with pytest.raises(GoogleOAuthError, match="userinfo request failed"):
        GoogleOAuthService._fetch_userinfo("access-token")


def test_default_userinfo_fetch_rejects_malformed_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(httpx, "get", lambda url, *, headers, timeout: FakeResponse())

    with pytest.raises(GoogleOAuthError, match="malformed JSON"):
        GoogleOAuthService._fetch_userinfo("access-token")


def test_default_userinfo_fetch_rejects_non_mapping_payload(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return ["not", "a", "mapping"]

    monkeypatch.setattr(httpx, "get", lambda url, *, headers, timeout: FakeResponse())

    with pytest.raises(GoogleOAuthError, match="malformed payload"):
        GoogleOAuthService._fetch_userinfo("access-token")
