import base64
from datetime import UTC, datetime
from email.message import EmailMessage as MimeEmailMessage
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from typing import Any

import httpx

from personal_hermes.openclaw.types import (
    CalendarEvent,
    EmailMessage,
    SendEmailReplyRequest,
)


class OpenClawClient:
    def __init__(
        self,
        access_token: str,
        *,
        http_client: httpx.Client | None = None,
        gmail_base_url: str = "https://gmail.googleapis.com/gmail/v1",
        calendar_base_url: str = "https://www.googleapis.com/calendar/v3",
        inbox_max_results: int = 25,
        calendar_id: str = "primary",
    ) -> None:
        self._access_token = access_token
        self._http_client = http_client or httpx.Client(timeout=30)
        self._gmail_base_url = gmail_base_url.rstrip("/")
        self._calendar_base_url = calendar_base_url.rstrip("/")
        self._inbox_max_results = inbox_max_results
        self._calendar_id = calendar_id

    def list_new_inbox_messages(self, since_cursor: str | None) -> list[EmailMessage]:
        query = "in:inbox is:unread"
        if since_cursor:
            query = f"{query} after:{since_cursor}"

        payload = self._request_json(
            "GET",
            f"{self._gmail_base_url}/users/me/messages",
            params={"q": query, "maxResults": self._inbox_max_results},
        )

        return [
            self.get_email_message(message["id"])
            for message in payload.get("messages", [])
            if message.get("id")
        ]

    def get_email_message(self, email_id: str) -> EmailMessage:
        payload = self._request_json(
            "GET",
            f"{self._gmail_base_url}/users/me/messages/{email_id}",
            params={"format": "full"},
        )
        return self._map_email_message(payload)

    def send_thread_reply(self, request: SendEmailReplyRequest) -> str:
        raw_message = self._build_reply_raw_message(request)
        payload = self._request_json(
            "POST",
            f"{self._gmail_base_url}/users/me/messages/send",
            json={"raw": raw_message, "threadId": request.thread_id},
        )
        return payload["id"]

    def mark_email_read(self, email_id: str) -> None:
        self._request_json(
            "POST",
            f"{self._gmail_base_url}/users/me/messages/{email_id}/modify",
            json={"removeLabelIds": ["UNREAD"]},
        )

    def list_calendar_events(
        self, start_at: datetime, end_at: datetime
    ) -> list[CalendarEvent]:
        payload = self._request_json(
            "GET",
            f"{self._calendar_base_url}/calendars/{self._calendar_id}/events",
            params={
                "timeMin": start_at.isoformat(),
                "timeMax": end_at.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        return [self._map_calendar_event(item) for item in payload.get("items", [])]

    @staticmethod
    def decode_gmail_raw_message(raw: str) -> str:
        padded = raw + ("=" * (-len(raw) % 4))
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http_client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _map_email_message(self, payload: dict[str, Any]) -> EmailMessage:
        headers = self._headers_by_name(payload.get("payload", {}).get("headers", []))
        sent_at = self._parse_sent_at(headers.get("date"), payload.get("internalDate"))

        return EmailMessage(
            id=payload["id"],
            thread_id=payload["threadId"],
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            to=self._parse_address_header(headers.get("to", "")),
            cc=self._parse_address_header(headers.get("cc", "")),
            sent_at=sent_at,
            snippet=payload.get("snippet", ""),
            body_text=self._extract_plain_text(payload.get("payload", {})),
            is_unread="UNREAD" in payload.get("labelIds", []),
            message_id=headers.get("message-id"),
            references=tuple(headers.get("references", "").split()),
        )

    @staticmethod
    def _headers_by_name(headers: list[dict[str, str]]) -> dict[str, str]:
        return {
            header["name"].lower(): header.get("value", "")
            for header in headers
            if "name" in header
        }

    @staticmethod
    def _parse_address_header(value: str) -> tuple[str, ...]:
        if not value:
            return ()
        addresses = []
        for name, address in getaddresses([value]):
            if name and address:
                addresses.append(formataddr((name, address)))
            elif address:
                addresses.append(address)
        return tuple(addresses)

    @staticmethod
    def _parse_sent_at(date_header: str | None, internal_date: str | None) -> datetime:
        if date_header:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed

        if internal_date:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)

        return datetime.now(tz=UTC)

    def _extract_plain_text(self, payload: dict[str, Any]) -> str:
        parts = list(self._walk_message_parts(payload))
        plain_parts = [
            self._decode_message_part(part)
            for part in parts
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data")
        ]
        return "\n".join(part for part in plain_parts if part)

    def _walk_message_parts(self, part: dict[str, Any]):
        yield part
        for child in part.get("parts", []) or []:
            yield from self._walk_message_parts(child)

    @staticmethod
    def _decode_message_part(part: dict[str, Any]) -> str:
        data = part.get("body", {}).get("data", "")
        padded = data + ("=" * (-len(data) % 4))
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")

    def _build_reply_raw_message(self, request: SendEmailReplyRequest) -> str:
        message = MimeEmailMessage()
        message["To"] = ", ".join(request.to)
        if request.cc:
            message["Cc"] = ", ".join(request.cc)
        if request.bcc:
            message["Bcc"] = ", ".join(request.bcc)
        message["Subject"] = self._reply_subject(request.subject)
        message["In-Reply-To"] = request.in_reply_to
        if request.references:
            message["References"] = " ".join(request.references)
        message.set_content(request.body_text)

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return encoded.rstrip("=")

    @staticmethod
    def _reply_subject(subject: str) -> str:
        if subject.lower().startswith("re:"):
            return subject
        return f"Re: {subject}"

    def _map_calendar_event(self, payload: dict[str, Any]) -> CalendarEvent:
        start_at, start_all_day, start_timezone = self._parse_calendar_time(
            payload.get("start", {})
        )
        end_at, _end_all_day, end_timezone = self._parse_calendar_time(
            payload.get("end", {})
        )

        attendees = tuple(
            (
                attendee.get("displayName"),
                attendee.get("email"),
                attendee.get("responseStatus"),
            )
            for attendee in payload.get("attendees", [])
        )

        return CalendarEvent(
            id=payload["id"],
            title=payload.get("summary", ""),
            start_at=start_at,
            end_at=end_at,
            all_day=start_all_day,
            timezone=start_timezone or end_timezone,
            location=payload.get("location"),
            description=payload.get("description"),
            html_link=payload.get("htmlLink"),
            attendees=attendees,
        )

    @staticmethod
    def _parse_calendar_time(value: dict[str, str]) -> tuple[datetime, bool, str | None]:
        if "dateTime" in value:
            return datetime.fromisoformat(value["dateTime"]), False, value.get("timeZone")

        if "date" in value:
            parsed_date = datetime.fromisoformat(value["date"])
            return parsed_date.replace(tzinfo=UTC), True, value.get("timeZone")

        return datetime.now(tz=UTC), False, value.get("timeZone")
