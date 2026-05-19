from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx
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


@dataclass(frozen=True)
class GoogleTokenBundle:
    access_token: str
    refresh_token: str
    granted_scopes: tuple[str, ...]
    token_expires_at: datetime | None
    google_subject: str
    google_email: str


class GoogleCredentials(Protocol):
    token: str
    refresh_token: str
    scopes: list[str] | tuple[str, ...] | None
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
        flow.fetch_token(code=code)

        credentials = flow.credentials
        userinfo = self._userinfo_fetcher(credentials.token)

        return GoogleTokenBundle(
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            granted_scopes=tuple(credentials.scopes or ()),
            token_expires_at=credentials.expiry,
            google_subject=str(userinfo["sub"]),
            google_email=str(userinfo["email"]),
        )

    def exchange_callback(self, callback_url: str) -> GoogleTokenBundle:
        query = parse_qs(urlparse(callback_url).query)
        code = query.get("code", [None])[0]
        if code is None:
            raise ValueError("Google OAuth callback URL is missing code")

        return self.exchange_code(code=code)

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
        response = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()
