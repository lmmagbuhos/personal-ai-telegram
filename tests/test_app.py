from pathlib import Path

from personal_hermes.app import build_components, check_config, configure_job_schedule
from personal_hermes.config import Settings


class FakeTelegramGateway:
    def request(self, method, payload):
        raise AssertionError(f"unexpected Telegram request: {method} {payload}")


class FakeJobScheduler:
    def __init__(self) -> None:
        self.jobs = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append((func, trigger, kwargs))


def make_settings(database_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="telegram-token",
        telegram_authorized_chat_id=123,
        telegram_authorized_user_id=456,
        sqlite_database_path=str(database_path),
        gog_executable="gog",
        gog_account="lmmagbuhos@oakdriveventures.com",
        gog_client="default",
        multiuser_enabled=False,
    )


def make_multiuser_settings(database_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="telegram-token",
        telegram_authorized_chat_id=123,
        telegram_authorized_user_id=456,
        sqlite_database_path=str(database_path),
        gog_executable="gog",
        gog_account="lmmagbuhos@oakdriveventures.com",
        gog_client="default",
        multiuser_enabled=True,
        public_base_url="https://hermes.example.com",
        google_oauth_client_id="client-id",
        google_oauth_client_secret="client-secret",
        token_encryption_key="3Qi5g7pADYF_poHyUGd-I3gyoY0u1IsGgqnJcMy6LEw=",
    )


def test_check_config_initializes_sqlite_and_accepts_existing_gog(tmp_path):
    database_path = tmp_path / "state" / "assistant.sqlite3"
    settings = make_settings(database_path)

    result = check_config(settings, executable_resolver=lambda executable: f"/usr/bin/{executable}")

    assert result.ok is True
    assert result.issues == []
    assert database_path.exists()


def test_check_config_reports_missing_gog_executable(tmp_path):
    settings = make_settings(tmp_path / "assistant.sqlite3")

    result = check_config(settings, executable_resolver=lambda _executable: None)

    assert result.ok is False
    assert result.issues == ["gog executable was not found: gog"]


def test_build_components_initializes_store_and_wires_scheduler(tmp_path):
    settings = make_settings(tmp_path / "assistant.sqlite3")
    command_calls = []

    def fake_command_runner(args, *, input_text=None):
        command_calls.append((args, input_text))
        return {"messages": []}

    components = build_components(
        settings,
        telegram_gateway=FakeTelegramGateway(),
        command_runner=fake_command_runner,
    )

    assert components.settings is settings
    assert components.store.database_path == Path(settings.sqlite_database_path)
    assert components.telegram.authorized_chat_id == 123
    assert components.telegram.authorized_user_id == 456
    assert components.scheduler.authorized_chat_id == 123
    assert components.scheduler.telegram_poll_timeout_seconds == 2

    components.scheduler.run_gmail_poll_job()

    assert command_calls == [
        (
            [
                "gog",
                "--account",
                "lmmagbuhos@oakdriveventures.com",
                "--client",
                "default",
                "gmail",
                "messages",
                "search",
                "in:inbox",
                "--json",
                "--max",
                "25",
                "--include-body",
                "--body-format",
                "text",
                "--no-input",
            ],
            None,
        )
    ]


def test_configure_job_schedule_registers_polling_and_daily_agenda_jobs(tmp_path):
    settings = make_settings(tmp_path / "assistant.sqlite3")
    job_scheduler = FakeJobScheduler()
    components = build_components(
        settings,
        telegram_gateway=FakeTelegramGateway(),
        command_runner=lambda _args, input_text=None: {"messages": []},
    )

    configure_job_schedule(components, job_scheduler)

    assert [(trigger, kwargs["id"]) for _func, trigger, kwargs in job_scheduler.jobs] == [
        ("interval", "telegram-poll"),
        ("interval", "gmail-poll"),
        ("interval", "calendar-reminders"),
        ("cron", "daily-agenda"),
    ]
    assert job_scheduler.jobs[0][2]["seconds"] == settings.telegram_poll_interval_seconds
    assert job_scheduler.jobs[1][2]["seconds"] == settings.gmail_poll_interval_seconds
    assert job_scheduler.jobs[2][2]["seconds"] == settings.calendar_poll_interval_seconds
    assert job_scheduler.jobs[3][2]["hour"] == 8
    assert job_scheduler.jobs[3][2]["minute"] == 0


def test_build_components_wires_multiuser_oauth_runtime_dependencies(tmp_path):
    settings = make_multiuser_settings(tmp_path / "assistant.sqlite3")
    command_calls = []

    def fake_command_runner(args, *, input_text=None):
        command_calls.append((args, input_text))
        return {"messages": []}

    components = build_components(
        settings,
        telegram_gateway=FakeTelegramGateway(),
        command_runner=fake_command_runner,
    )

    assert components.oauth_service is not None
    assert components.oauth_app is not None
    assert components.scheduler.multiuser_enabled is True
    assert components.scheduler.store is components.store
    assert command_calls == []
