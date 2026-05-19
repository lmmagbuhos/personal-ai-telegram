from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = Field(min_length=1)
    telegram_authorized_chat_id: int
    telegram_authorized_user_id: int
    openclaw_api_key: str = Field(min_length=1)
    openclaw_base_url: str = Field(min_length=1)
    sqlite_database_path: str = Field(min_length=1)

    timezone: str = "Asia/Manila"
    workday_start: str = "09:00"
    workday_end: str = "17:00"
    min_free_block_minutes: int = 120
    telegram_poll_interval_seconds: int = 2
    gmail_poll_interval_seconds: int = 300
    calendar_poll_interval_seconds: int = 300
    daily_agenda_time: str = "08:00"
    reminder_lead_minutes: int = 30
    pending_reply_expiry_days: int = 7
    debug_email_body_logging: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
