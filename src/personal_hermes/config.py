from datetime import time
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PositiveInt = Annotated[int, Field(gt=0)]
TcpPort = Annotated[int, Field(ge=1, le=65535)]


class Settings(BaseSettings):
    telegram_bot_token: str = Field(min_length=1)
    telegram_authorized_chat_id: int | None = None
    telegram_authorized_user_id: int | None = None
    sqlite_database_path: str = Field(min_length=1)
    gog_executable: str = Field(default="gog", min_length=1)
    gog_account: str | None = None
    gog_client: str | None = None

    timezone: str = "Asia/Manila"
    workday_start: str = "09:00"
    workday_end: str = "17:00"
    min_free_block_minutes: PositiveInt = 120
    telegram_poll_interval_seconds: PositiveInt = 2
    gmail_poll_interval_seconds: PositiveInt = 300
    calendar_poll_interval_seconds: PositiveInt = 300
    daily_agenda_time: str = "08:00"
    reminder_lead_minutes: PositiveInt = 30
    pending_reply_expiry_days: PositiveInt = 7
    debug_email_body_logging: bool = False
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
    oauth_port: TcpPort = 8080

    @property
    def google_oauth_redirect_url(self) -> str | None:
        if not self.public_base_url:
            return None
        return self.public_base_url.rstrip("/") + self.google_oauth_redirect_path

    @property
    def invited_telegram_user_ids_tuple(self) -> tuple[int, ...]:
        values: list[int] = []
        for raw in self.invited_telegram_user_ids.split(","):
            raw = raw.strip()
            if raw:
                values.append(int(raw))
        return tuple(values)

    @model_validator(mode="after")
    def validate_telegram_and_multiuser_settings(self) -> "Settings":
        # Single-user mode requires Telegram authorization fields
        if not self.multiuser_enabled:
            missing = []
            if self.telegram_authorized_chat_id is None:
                missing.append("telegram_authorized_chat_id")
            if self.telegram_authorized_user_id is None:
                missing.append("telegram_authorized_user_id")
            if missing:
                raise ValueError(
                    "These fields are required in single-user mode: "
                    + ", ".join(missing)
                )
            return self

        # Multi-user mode requires OAuth settings
        missing = [
            name
            for name in (
                "public_base_url",
                "google_oauth_client_id",
                "google_oauth_client_secret",
                "token_encryption_key",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                "multiuser OAuth settings required when multiuser_enabled is true: "
                + ", ".join(missing)
            )
        return self

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return value

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("public_base_url must be an absolute http(s) URL")
        return value

    @field_validator("google_oauth_redirect_path")
    @classmethod
    def validate_google_oauth_redirect_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("google_oauth_redirect_path must start with /")
        return value

    @field_validator("invited_telegram_user_ids")
    @classmethod
    def validate_invited_telegram_user_ids(cls, value: str) -> str:
        for raw in value.split(","):
            raw = raw.strip()
            if raw:
                int(raw)
        return value

    @field_validator("workday_start", "workday_end", "daily_agenda_time")
    @classmethod
    def validate_hh_mm(cls, value: str) -> str:
        time.fromisoformat(value)
        if len(value) != 5:
            raise ValueError("time must use HH:MM format")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
