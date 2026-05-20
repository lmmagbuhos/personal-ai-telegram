import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import formataddr, getaddresses
from typing import Any, Protocol

from personal_hermes.openclaw.types import (
    CalendarEvent,
    EmailMessage,
    SendEmailReplyRequest,
)

JsonValue = dict[str, Any] | list[Any]


class CommandRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
    ) -> JsonValue:
        ...


class OpenClawCommandError(RuntimeError):
    pass


class OpenClawClient:
    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        executable: str = "gog",
        account: str | None = None,
        client: str | None = None,
        access_token: str | None = None,
        inbox_limit: int = 25,
    ) -> None:
        self._command_runner = command_runner or self._run_json_command
        self._executable = executable
        self._account = account
        self._client = client
        self._access_token = access_token
        self._inbox_limit = inbox_limit

    def list_new_inbox_messages(self, since_cursor: str | None) -> list[EmailMessage]:
        payload = self._run(self._list_inbox_args(since_cursor))
        return [
            self._map_email_message(item)
            for item in self._items(payload, "messages")
        ]

    def get_email_message(self, email_id: str) -> EmailMessage:
        payload = self._run(self._get_email_args(email_id))
        if not isinstance(payload, dict):
            raise OpenClawCommandError("gog email get returned a non-object JSON value")
        return self._map_email_message(payload)

    def send_thread_reply(self, request: SendEmailReplyRequest) -> str:
        payload = self._run(
            self._send_reply_args(request),
            input_text=request.body_text,
        )
        if not isinstance(payload, dict) or not payload.get("id"):
            raise OpenClawCommandError("gog reply returned no sent message id")
        return str(payload["id"])

    def mark_email_read(self, email_id: str) -> None:
        self._run(self._mark_email_read_args(email_id))

    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        payload = self._run(self._list_calendar_events_args(start_at, end_at))
        return [
            self._map_calendar_event(item)
            for item in self._items(payload, "events")
        ]

    def create_calendar_event(
        self, *, title: str, start_at: datetime, end_at: datetime, timezone: str
    ) -> CalendarEvent:
        payload = self._run(self._create_calendar_event_args(title, start_at, end_at, timezone))
        if not isinstance(payload, dict):
            raise OpenClawCommandError("gog calendar create returned a non-object value")
        # gog wraps the created event under an "event" key; fall back to the payload
        # itself for forward-compatibility if that envelope is ever absent.
        event = payload.get("event", payload)
        if not isinstance(event, dict):
            raise OpenClawCommandError("gog calendar create returned a malformed event")
        return self._map_calendar_event(event)

    def delete_calendar_event(self, *, event_id: str) -> None:
        self._run(self._delete_calendar_event_args(event_id))

    def with_access_token(self, access_token: str | None) -> "OpenClawClient":
        return OpenClawClient(
            command_runner=self._command_runner,
            executable=self._executable,
            account=self._account,
            client=self._client,
            access_token=access_token,
            inbox_limit=self._inbox_limit,
        )

    def _run(self, args: list[str], *, input_text: str | None = None) -> JsonValue:
        return self._command_runner(args, input_text=input_text)

    def _list_inbox_args(self, since_cursor: str | None) -> list[str]:
        query = "in:inbox"
        if since_cursor:
            query = f"{query} {since_cursor}"

        return self._base_args() + [
            "gmail",
            "messages",
            "search",
            query,
            "--json",
            "--max",
            str(self._inbox_limit),
            "--include-body",
            "--body-format",
            "text",
            "--no-input",
        ]

    def _get_email_args(self, email_id: str) -> list[str]:
        return self._base_args() + [
            "gmail",
            "get",
            email_id,
            "--format",
            "full",
            "--sanitize-content",
            "--json",
            "--no-input",
        ]

    def _send_reply_args(self, request: SendEmailReplyRequest) -> list[str]:
        args = self._base_args() + [
            "gmail",
            "send",
            "--thread-id",
            request.thread_id,
            "--to",
            ",".join(request.to),
            "--subject",
            request.subject,
            "--body-file",
            "-",
            "--json",
            "--no-input",
        ]
        if request.cc:
            args.extend(["--cc", ",".join(request.cc)])
        if request.bcc:
            args.extend(["--bcc", ",".join(request.bcc)])
        if request.in_reply_to:
            args.extend(["--reply-to-message-id", request.in_reply_to])
        return args

    def _mark_email_read_args(self, email_id: str) -> list[str]:
        return self._base_args() + [
            "gmail",
            "mark-read",
            email_id,
            "--json",
            "--no-input",
        ]

    def _list_calendar_events_args(
        self, start_at: datetime, end_at: datetime
    ) -> list[str]:
        return self._base_args() + [
            "calendar",
            "events",
            "primary",
            "--from",
            start_at.isoformat(),
            "--to",
            end_at.isoformat(),
            "--json",
            "--all-pages",
            "--no-input",
        ]

    def _create_calendar_event_args(
        self, title: str, start_at: datetime, end_at: datetime, timezone: str
    ) -> list[str]:
        return self._base_args() + [
            "calendar",
            "create",
            "primary",
            "--summary",
            title,
            "--from",
            start_at.isoformat(),
            "--to",
            end_at.isoformat(),
            "--start-timezone",
            timezone,
            "--end-timezone",
            timezone,
            "--json",
            "--no-input",
        ]

    def _delete_calendar_event_args(self, event_id: str) -> list[str]:
        return self._base_args() + [
            "calendar",
            "delete",
            "primary",
            event_id,
            "--json",
            "--no-input",
            "-y",
        ]

    def _base_args(self) -> list[str]:
        args = [self._executable]
        if self._account:
            args.extend(["--account", self._account])
        if self._client:
            args.extend(["--client", self._client])
        if self._access_token:
            args.extend(["--access-token", self._access_token])
        return args

    @staticmethod
    def _run_json_command(args: list[str], *, input_text: str | None = None) -> JsonValue:
        try:
            completed = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise OpenClawCommandError(
                f"OpenClaw gog CLI executable was not found: {args[0]}"
            ) from exc

        if completed.returncode != 0:
            raise OpenClawCommandError(completed.stderr.strip() or completed.stdout.strip())

        if not completed.stdout.strip():
            return {}

        try:
            decoded = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OpenClawCommandError("gog returned non-JSON output") from exc

        if not isinstance(decoded, dict | list):
            raise OpenClawCommandError("gog returned JSON that is not an object or list")
        return decoded

    @staticmethod
    def _items(payload: JsonValue, key: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        value = payload.get(key) or payload.get("items") or payload.get("results") or []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _map_email_message(self, payload: dict[str, Any]) -> EmailMessage:
        return EmailMessage(
            id=str(payload["id"]),
            thread_id=str(self._first(payload, "thread_id", "threadId", default="")),
            subject=str(self._first(payload, "subject", default="")),
            sender=str(self._first(payload, "sender", "from", default="")),
            to=self._string_tuple(self._first(payload, "to", default=())),
            cc=self._string_tuple(self._first(payload, "cc", default=())),
            sent_at=self._parse_datetime(
                self._first(payload, "sent_at", "sentAt", "date", default=None)
            ),
            snippet=str(self._first(payload, "snippet", default="")),
            body_text=str(
                self._first(payload, "body_text", "bodyText", "body", "text", default="")
            ),
            is_unread=self._is_unread(payload),
            message_id=self._optional_string(
                self._first(payload, "message_id", "messageId", default=None)
            ),
            references=self._references_tuple(
                self._first(payload, "references", default=())
            ),
        )

    def _map_calendar_event(self, payload: dict[str, Any]) -> CalendarEvent:
        start_at, start_all_day, start_timezone = self._calendar_time(payload, "start")
        end_at, _end_all_day, end_timezone = self._calendar_time(payload, "end")

        return CalendarEvent(
            id=str(payload["id"]),
            title=str(self._first(payload, "title", "summary", default="")),
            start_at=start_at,
            end_at=end_at,
            all_day=bool(self._first(payload, "all_day", "allDay", default=start_all_day)),
            timezone=self._optional_string(
                self._first(
                    payload,
                    "timezone",
                    "timeZone",
                    default=start_timezone or end_timezone,
                )
            ),
            location=self._optional_string(self._first(payload, "location", default=None)),
            description=self._optional_string(
                self._first(payload, "description", default=None)
            ),
            html_link=self._optional_string(
                self._first(payload, "html_link", "htmlLink", "url", default=None)
            ),
            attendees=self._map_attendees(payload.get("attendees", [])),
        )

    def _calendar_time(
        self, payload: dict[str, Any], prefix: str
    ) -> tuple[datetime, bool, str | None]:
        direct_value = self._first(payload, f"{prefix}_at", f"{prefix}At", default=None)
        if direct_value:
            return self._parse_datetime(direct_value), False, None

        nested = payload.get(prefix)
        if isinstance(nested, dict):
            if nested.get("dateTime"):
                return (
                    self._parse_datetime(nested["dateTime"]),
                    False,
                    self._optional_string(nested.get("timeZone")),
                )
            if nested.get("date"):
                return (
                    datetime.fromisoformat(str(nested["date"])).replace(tzinfo=UTC),
                    True,
                    self._optional_string(nested.get("timeZone")),
                )

        return datetime.now(tz=UTC), False, None

    @staticmethod
    def _first(payload: dict[str, Any], *keys: str, default: Any) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return default

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed
        return datetime.now(tz=UTC)

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            addresses = []
            for name, address in getaddresses([value]):
                if name and address:
                    addresses.append(formataddr((name, address)))
                elif address:
                    addresses.append(address)
            return tuple(addresses) if addresses else (value,)
        if isinstance(value, Sequence):
            return tuple(str(item) for item in value if item)
        return (str(value),)

    @staticmethod
    def _references_tuple(value: Any) -> tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            return tuple(value.split())
        if isinstance(value, Sequence):
            return tuple(str(item) for item in value if item)
        return (str(value),)

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _is_unread(payload: dict[str, Any]) -> bool:
        if "is_unread" in payload:
            return bool(payload["is_unread"])
        if "unread" in payload:
            return bool(payload["unread"])
        labels = payload.get("labels") or payload.get("labelIds") or []
        return "UNREAD" in labels

    @staticmethod
    def _map_attendees(
        value: Any,
    ) -> tuple[tuple[str | None, str | None, str | None], ...]:
        if not isinstance(value, list):
            return ()

        attendees: list[tuple[str | None, str | None, str | None]] = []
        for attendee in value:
            if isinstance(attendee, dict):
                attendees.append(
                    (
                        OpenClawClient._optional_string(
                            attendee.get("display_name")
                            or attendee.get("displayName")
                            or attendee.get("name")
                        ),
                        OpenClawClient._optional_string(attendee.get("email")),
                        OpenClawClient._optional_string(
                            attendee.get("response_status")
                            or attendee.get("responseStatus")
                            or attendee.get("status")
                        ),
                    )
                )
            elif isinstance(attendee, Sequence) and not isinstance(attendee, str):
                padded = list(attendee[:3]) + [None, None, None]
                attendees.append(
                    (
                        OpenClawClient._optional_string(padded[0]),
                        OpenClawClient._optional_string(padded[1]),
                        OpenClawClient._optional_string(padded[2]),
                    )
                )
        return tuple(attendees)
