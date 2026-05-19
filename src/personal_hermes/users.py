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
