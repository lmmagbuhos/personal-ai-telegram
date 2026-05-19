from personal_hermes.config import Settings


def test_settings_defaults(monkeypatch):
    default_keys = [
        "TIMEZONE",
        "GMAIL_POLL_INTERVAL_SECONDS",
        "CALENDAR_POLL_INTERVAL_SECONDS",
        "DAILY_AGENDA_TIME",
        "REMINDER_LEAD_MINUTES",
        "PENDING_REPLY_EXPIRY_DAYS",
    ]
    for key in default_keys:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_CHAT_ID", "123456")
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USER_ID", "789012")
    monkeypatch.setenv("OPENCLAW_API_KEY", "test-openclaw-key")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", "var/test.sqlite3")

    settings = Settings(_env_file=None)

    assert settings.timezone == "Asia/Manila"
    assert settings.gmail_poll_interval_seconds == 300
    assert settings.calendar_poll_interval_seconds == 300
    assert settings.daily_agenda_time == "08:00"
    assert settings.reminder_lead_minutes == 30
    assert settings.pending_reply_expiry_days == 7
