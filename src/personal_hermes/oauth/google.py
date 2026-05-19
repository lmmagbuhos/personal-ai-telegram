from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


GOOGLE_OAUTH_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events.readonly",
)

GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_USERINFO_TIMEOUT_SECONDS = 10.0
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(Exception):
    pass


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleTokenBundle:
    access_token: str
    refresh_token: str
    granted_scopes: tuple[str, ...]
    token_expires_at: datetime | None
    google_subject: str
    google_email: str


class GoogleCredentials(Protocol):
    token: str | None
    refresh_token: str | None
    scopes: list[str] | tuple[str, ...] | None
    granted_scopes: list[str] | tuple[str, ...] | None
    expiry: datetime | None


class GoogleFlow(Protocol):
    credentials: GoogleCredentials
    redirect_uri: str | None

    def authorization_url(self, **kwargs: Any) -> tuple[str, str | None]: ...

    def fetch_token(self, *, code: str) -> Any: ...


class GoogleFlowFactory(Protocol):
    def __call__(
        self, *, client_config: dict[str, Any], scopes: tuple[str, ...]
    ) -> GoogleFlow: ...


class GoogleUserinfoFetcher(Protocol):
    def __call__(self, access_token: str) -> Mapping[str, Any]: ...


class GoogleOAuthService:
    def __init__(
        self,
        config: GoogleOAuthConfig,
        *,
        flow_factory: GoogleFlowFactory | None = None,
        userinfo_fetcher: GoogleUserinfoFetcher | None = None,
    ) -> None:
        self._config = config
        self._flow_factory = flow_factory or self._default_flow_factory
        self._userinfo_fetcher = userinfo_fetcher or self._fetch_userinfo

    def authorization_url(self, *, state: str) -> str:
        flow = self._new_flow()
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return authorization_url

    def exchange_code(self, *, code: str) -> GoogleTokenBundle:
        flow = self._new_flow()
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise GoogleOAuthError("Google OAuth token exchange failed") from exc

        credentials = flow.credentials
        access_token = self._require_non_empty_string(
            credentials.token,
            "Google OAuth credentials are missing access token",
        )
        refresh_token = self._require_non_empty_string(
            credentials.refresh_token,
            "Google OAuth credentials are missing refresh token",
        )
        granted_scopes = self._granted_scopes(credentials)
        userinfo = self._userinfo_fetcher(access_token)
        if not isinstance(userinfo, Mapping):
            raise GoogleOAuthError("Google userinfo returned malformed payload")

        google_subject = self._identity_value(
            userinfo,
            "sub",
            "Google userinfo is missing Google subject",
        )
        google_email = self._identity_value(
            userinfo,
            "email",
            "Google userinfo is missing Google email",
        )

        return GoogleTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scopes=granted_scopes,
            token_expires_at=credentials.expiry,
            google_subject=google_subject,
            google_email=google_email,
        )

    def exchange_callback(
        self,
        callback_url: str,
        *,
        expected_state: str,
    ) -> GoogleTokenBundle:
        query = parse_qs(urlparse(callback_url).query, keep_blank_values=True)
        if "error" in query or "error_description" in query:
            raise GoogleOAuthError("Google OAuth rejected callback")

        state_values = query.get("state")
        if not state_values:
            raise GoogleOAuthError("Google OAuth callback is missing state")
        if len(state_values) != 1 or state_values[0] != expected_state:
            raise GoogleOAuthError("Google OAuth callback state mismatch")

        code_values = query.get("code")
        if not code_values:
            raise GoogleOAuthError("Google OAuth callback is missing code")
        if len(code_values) != 1:
            raise GoogleOAuthError("Google OAuth callback has multiple code values")

        code = code_values[0]
        if not code.strip():
            raise GoogleOAuthError("Google OAuth callback has blank code")

        return self.exchange_code(code=code)

    def refresh_access_token(
        self,
        *,
        refresh_token: str,
        access_token: str | None = None,
    ) -> tuple[str, datetime | None]:
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
            scopes=list(GOOGLE_OAUTH_SCOPES),
        )
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise GoogleOAuthError("Google OAuth token refresh failed") from exc

        token = self._require_non_empty_string(
            credentials.token,
            "Google OAuth token refresh produced empty token",
        )
        return token, credentials.expiry

    def _new_flow(self) -> GoogleFlow:
        flow = self._flow_factory(
            client_config=self._client_config(),
            scopes=GOOGLE_OAUTH_SCOPES,
        )
        flow.redirect_uri = self._config.redirect_uri
        return flow

    def _client_config(self) -> dict[str, Any]:
        return {
            "web": {
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self._config.redirect_uri],
            }
        }

    @staticmethod
    def _default_flow_factory(
        *, client_config: dict[str, Any], scopes: tuple[str, ...]
    ) -> GoogleFlow:
        return Flow.from_client_config(client_config, scopes=scopes)

    @staticmethod
    def _fetch_userinfo(access_token: str) -> Mapping[str, Any]:
        try:
            response = httpx.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=GOOGLE_USERINFO_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise GoogleOAuthError("Google userinfo request failed") from exc
        except httpx.RequestError as exc:
            raise GoogleOAuthError("Google userinfo request failed") from exc
        except ValueError as exc:
            raise GoogleOAuthError("Google userinfo returned malformed JSON") from exc

        if not isinstance(payload, Mapping):
            raise GoogleOAuthError("Google userinfo returned malformed payload")

        GoogleOAuthService._identity_value(
            payload,
            "sub",
            "Google userinfo is missing Google subject",
        )
        GoogleOAuthService._identity_value(
            payload,
            "email",
            "Google userinfo is missing Google email",
        )
        return payload

    @staticmethod
    def _granted_scopes(credentials: GoogleCredentials) -> tuple[str, ...]:
        scopes = credentials.granted_scopes
        if scopes is None:
            raise GoogleOAuthError("Google OAuth credentials are missing granted scopes")

        granted_scopes = tuple(
            scope.strip() for scope in scopes if isinstance(scope, str) and scope.strip()
        )
        if not granted_scopes:
            raise GoogleOAuthError("Google OAuth credentials are missing granted scopes")

        missing_scopes = set(GOOGLE_OAUTH_SCOPES).difference(granted_scopes)
        if missing_scopes:
            raise GoogleOAuthError(
                "Google OAuth credentials are missing required granted scopes"
            )

        return granted_scopes

    @staticmethod
    def _identity_value(
        userinfo: Mapping[str, Any],
        key: str,
        error_message: str,
    ) -> str:
        value = userinfo.get(key)
        return GoogleOAuthService._require_non_empty_string(value, error_message)

    @staticmethod
    def _require_non_empty_string(value: object, error_message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GoogleOAuthError(error_message)
        return value
