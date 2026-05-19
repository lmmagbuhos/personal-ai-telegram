from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from personal_hermes.oauth.google import (
    GOOGLE_OAUTH_SCOPES,
    GoogleOAuthConfig,
    GoogleOAuthService,
    GoogleTokenBundle,
)


class FakeCredentials:
    token = "access"
    refresh_token = "refresh"
    scopes = ["scope-a", "scope-b"]
    expiry = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)


class FakeFlow:
    credentials = FakeCredentials()

    def __init__(self) -> None:
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
