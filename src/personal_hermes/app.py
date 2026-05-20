import argparse
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
import uvicorn

from personal_hermes.calendar.actions import CalendarActionService
from personal_hermes.calendar.edit import CalendarEditService
from personal_hermes.calendar.notifications import CalendarNotificationService
from personal_hermes.calendar.service import CalendarService
from personal_hermes.config import Settings
from personal_hermes.oauth.crypto import TokenCipher
from personal_hermes.oauth.google import GoogleOAuthConfig, GoogleOAuthService
from personal_hermes.oauth.web import create_oauth_app
from personal_hermes.mail.actions import MailActionService
from personal_hermes.mail.service import MailPollingService
from personal_hermes.openclaw.client import CommandRunner, OpenClawClient
from personal_hermes.router import AssistantRouter
from personal_hermes.scheduler import AssistantScheduler
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.adapter import TelegramAdapter, TelegramGateway


@dataclass(frozen=True)
class ConfigCheckResult:
    ok: bool
    issues: list[str]


@dataclass(frozen=True)
class AppComponents:
    settings: Settings
    store: StateStore
    openclaw_client: OpenClawClient
    telegram: TelegramAdapter
    calendar_service: CalendarService
    calendar_notifications: CalendarNotificationService
    mail_polling_service: MailPollingService
    mail_action_service: MailActionService
    router: AssistantRouter
    scheduler: AssistantScheduler
    oauth_service: GoogleOAuthService | None = None
    oauth_app: object | None = None


ExecutableResolver = Callable[[str], str | None]


class JobScheduler(Protocol):
    def add_job(self, func: Callable[[], None], trigger: str, **kwargs) -> None:
        ...


class GoogleAccessTokenResolver:
    def __init__(
        self,
        *,
        store: StateStore,
        token_cipher: TokenCipher,
        oauth_service: GoogleOAuthService,
        refresh_margin: timedelta = timedelta(minutes=5),
    ) -> None:
        self.store = store
        self.token_cipher = token_cipher
        self.oauth_service = oauth_service
        self.refresh_margin = refresh_margin

    def __call__(self, user_id: int, *, now: datetime) -> str | None:
        account = self.store.get_google_account(user_id)
        if account is None or account.status != "active":
            return None

        try:
            access_token = self.token_cipher.decrypt(account.encrypted_access_token)
            refresh_token = self.token_cipher.decrypt(account.encrypted_refresh_token)
        except Exception:
            self.store.mark_google_account_status(
                user_id=user_id,
                status="reauth_required",
                now=now,
            )
            return None

        expires_at = account.token_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            # Stored expiry is naive; treat it as UTC so it compares with the aware `now`.
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at is not None and expires_at <= now + self.refresh_margin:
            try:
                access_token, token_expires_at = self.oauth_service.refresh_access_token(
                    refresh_token=refresh_token,
                    access_token=access_token,
                )
            except Exception:
                self.store.mark_google_account_status(
                    user_id=user_id,
                    status="reauth_required",
                    now=now,
                )
                return None

            self.store.save_google_account(
                user_id=user_id,
                google_subject=account.google_subject,
                google_email=account.google_email,
                encrypted_access_token=self.token_cipher.encrypt(access_token),
                encrypted_refresh_token=self.token_cipher.encrypt(refresh_token),
                granted_scopes=account.granted_scopes,
                token_expires_at=token_expires_at,
                now=now,
            )

        return access_token


def check_config(
    settings: Settings,
    *,
    executable_resolver: ExecutableResolver = shutil.which,
) -> ConfigCheckResult:
    issues: list[str] = []

    if executable_resolver(settings.gog_executable) is None:
        issues.append(f"gog executable was not found: {settings.gog_executable}")

    StateStore(settings.sqlite_database_path).initialize()

    return ConfigCheckResult(ok=not issues, issues=issues)


def configure_job_schedule(
    components: AppComponents,
    job_scheduler: JobScheduler,
) -> None:
    settings = components.settings
    agenda_hour, agenda_minute = _parse_hh_mm(settings.daily_agenda_time)

    job_scheduler.add_job(
        components.scheduler.run_telegram_poll_job,
        "interval",
        id="telegram-poll",
        seconds=settings.telegram_poll_interval_seconds,
        max_instances=1,
        coalesce=True,
    )
    job_scheduler.add_job(
        components.scheduler.run_gmail_poll_job,
        "interval",
        id="gmail-poll",
        seconds=settings.gmail_poll_interval_seconds,
        max_instances=1,
        coalesce=True,
    )
    job_scheduler.add_job(
        components.scheduler.run_calendar_reminder_job,
        "interval",
        id="calendar-reminders",
        seconds=settings.calendar_poll_interval_seconds,
        max_instances=1,
        coalesce=True,
    )
    job_scheduler.add_job(
        components.scheduler.run_daily_agenda_job,
        "cron",
        id="daily-agenda",
        hour=agenda_hour,
        minute=agenda_minute,
        max_instances=1,
        coalesce=True,
    )


def start_runtime(components: AppComponents) -> None:
    if components.oauth_app is not None:
        threading.Thread(
            target=lambda: uvicorn.run(
                components.oauth_app,
                host=components.settings.oauth_host,
                port=components.settings.oauth_port,
                log_level="error",
            ),
            daemon=True,
        ).start()

    job_scheduler = BlockingScheduler(timezone=components.settings.timezone)
    configure_job_schedule(components, job_scheduler)
    job_scheduler.start()


def build_components(
    settings: Settings,
    *,
    telegram_gateway: TelegramGateway | None = None,
    command_runner: CommandRunner | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> AppComponents:
    store = StateStore(settings.sqlite_database_path)
    store.initialize()
    oauth_service = None
    oauth_app = None
    resolve_access_token = None

    openclaw_client = OpenClawClient(
        command_runner=command_runner,
        executable=settings.gog_executable,
        account=settings.gog_account,
        client=settings.gog_client,
    )
    telegram = TelegramAdapter(
        bot_token=settings.telegram_bot_token,
        authorized_chat_id=settings.telegram_authorized_chat_id,
        authorized_user_id=settings.telegram_authorized_user_id,
        gateway=telegram_gateway,
    )

    if settings.multiuser_enabled:
        assert settings.google_oauth_client_id is not None
        assert settings.google_oauth_client_secret is not None
        assert settings.google_oauth_redirect_url is not None
        assert settings.token_encryption_key is not None

        oauth_service = GoogleOAuthService(
            GoogleOAuthConfig(
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                redirect_uri=settings.google_oauth_redirect_url,
            )
        )
        token_cipher = TokenCipher(settings.token_encryption_key)
        resolve_access_token = GoogleAccessTokenResolver(
            store=store,
            token_cipher=token_cipher,
            oauth_service=oauth_service,
        )
        oauth_app = create_oauth_app(
            store=store,
            oauth=oauth_service,
            token_cipher=token_cipher,
            telegram=telegram,
        )

    calendar_service = CalendarService(
        openclaw_client=openclaw_client,
        timezone=ZoneInfo(settings.timezone),
        workday_start=settings.workday_start,
        workday_end=settings.workday_end,
        min_free_block_minutes=settings.min_free_block_minutes,
        resolve_access_token=resolve_access_token,
    )

    calendar_notifications = CalendarNotificationService(store)
    mail_polling_service = MailPollingService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        authorized_chat_id=settings.telegram_authorized_chat_id,
        pending_reply_expiry_days=settings.pending_reply_expiry_days,
        resolve_access_token=resolve_access_token,
    )
    mail_action_service = MailActionService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        resolve_access_token=resolve_access_token,
    )
    calendar_action_service = CalendarActionService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        resolve_access_token=resolve_access_token,
    )
    calendar_edit_service = CalendarEditService(
        openclaw_client=openclaw_client,
        telegram=telegram,
        store=store,
        timezone=ZoneInfo(settings.timezone),
        resolve_access_token=resolve_access_token,
    )
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=calendar_service,
        mail_action_service=mail_action_service,
        store=store,
        oauth_service=oauth_service,
        invite_only=settings.invite_only,
        invited_telegram_user_ids=settings.invited_telegram_user_ids_tuple,
        oauth_session_ttl_minutes=settings.oauth_session_ttl_minutes,
        calendar_action_service=calendar_action_service,
        calendar_edit_service=calendar_edit_service,
        timezone=ZoneInfo(settings.timezone),
    )
    scheduler = AssistantScheduler(
        mail_polling_service=mail_polling_service,
        openclaw_client=openclaw_client,
        calendar_notifications=calendar_notifications,
        telegram=telegram,
        router=router,
        authorized_chat_id=settings.telegram_authorized_chat_id,
        reminder_lead_minutes=settings.reminder_lead_minutes,
        telegram_poll_timeout_seconds=settings.telegram_poll_interval_seconds,
        resolve_access_token=resolve_access_token,
        store=store if settings.multiuser_enabled else None,
        multiuser_enabled=settings.multiuser_enabled,
        now_provider=now_provider,
    )

    return AppComponents(
        settings=settings,
        store=store,
        openclaw_client=openclaw_client,
        telegram=telegram,
        calendar_service=calendar_service,
        calendar_notifications=calendar_notifications,
        mail_polling_service=mail_polling_service,
        mail_action_service=mail_action_service,
        router=router,
        scheduler=scheduler,
        oauth_service=oauth_service,
        oauth_app=oauth_app,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="personal-hermes")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="validate local configuration and initialize the SQLite database",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="start the Telegram, Gmail, and Calendar polling runtime",
    )
    args = parser.parse_args(argv)

    settings = Settings()
    if args.check_config:
        result = check_config(settings)
        if result.ok:
            print("Configuration OK")
            return 0
        for issue in result.issues:
            print(f"Configuration issue: {issue}")
        return 1

    components = build_components(settings)
    start_runtime(components)
    return 0


def _parse_hh_mm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", maxsplit=1)
    return int(hour), int(minute)
