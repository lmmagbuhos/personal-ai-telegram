import pytest
from pydantic import ValidationError

from personal_hermes.config import Settings


REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "test-telegram-token",
    "TELEGRAM_AUTHORIZED_CHAT_ID": "123456",
    "TELEGRAM_AUTHORIZED_USER_ID": "789012",
    "SQLITE_DATABASE_PATH": "var/test.sqlite3",
}


def set_required_env(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_settings_defaults(monkeypatch):
    default_keys = [
        "TIMEZONE",
        "GMAIL_POLL_INTERVAL_SECONDS",
        "CALENDAR_POLL_INTERVAL_SECONDS",
        "DAILY_AGENDA_TIME",
        "REMINDER_LEAD_MINUTES",
        "PENDING_REPLY_EXPIRY_DAYS",
        "WORKDAY_START",
        "WORKDAY_END",
        "MIN_FREE_BLOCK_MINUTES",
        "TELEGRAM_POLL_INTERVAL_SECONDS",
        "DEBUG_EMAIL_BODY_LOGGING",
        "GOG_EXECUTABLE",
        "GOG_ACCOUNT",
        "GOG_CLIENT",
    ]
    for key in default_keys:
        monkeypatch.delenv(key, raising=False)

    set_required_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.timezone == "Asia/Manila"
    assert settings.workday_start == "09:00"
    assert settings.workday_end == "17:00"
    assert settings.min_free_block_minutes == 120
    assert settings.telegram_poll_interval_seconds == 2
    assert settings.gmail_poll_interval_seconds == 300
    assert settings.calendar_poll_interval_seconds == 300
    assert settings.daily_agenda_time == "08:00"
    assert settings.reminder_lead_minutes == 30
    assert settings.pending_reply_expiry_days == 7
    assert settings.debug_email_body_logging is False
    assert settings.gog_executable == "gog"
    assert settings.gog_account is None
    assert settings.gog_client is None


def test_settings_do_not_require_openclaw_rest_credentials(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.delenv("OPENCLAW_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_BASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.gog_executable == "gog"


@pytest.mark.parametrize(
    "key",
    [
        "WORKDAY_START",
        "WORKDAY_END",
        "DAILY_AGENDA_TIME",
    ],
)
def test_time_settings_must_use_hh_mm_format(monkeypatch, key):
    set_required_env(monkeypatch)
    monkeypatch.setenv(key, "25:99")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "key",
    [
        "MIN_FREE_BLOCK_MINUTES",
        "TELEGRAM_POLL_INTERVAL_SECONDS",
        "GMAIL_POLL_INTERVAL_SECONDS",
        "CALENDAR_POLL_INTERVAL_SECONDS",
        "REMINDER_LEAD_MINUTES",
        "PENDING_REPLY_EXPIRY_DAYS",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_interval_and_count_settings_must_be_positive(monkeypatch, key, value):
    set_required_env(monkeypatch)
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
