from datetime import time
from typing import Annotated

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PositiveInt = Annotated[int, Field(gt=0)]


class Settings(BaseSettings):
    telegram_bot_token: str = Field(min_length=1)
    telegram_authorized_chat_id: int
    telegram_authorized_user_id: int
    openclaw_api_key: str = Field(min_length=1)
    openclaw_base_url: AnyHttpUrl
    sqlite_database_path: str = Field(min_length=1)

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
        extra="ignore",
    )
