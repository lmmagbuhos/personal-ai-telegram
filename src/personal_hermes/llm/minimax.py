from __future__ import annotations

import httpx

from personal_hermes.llm.intents import LLMIntent, LLMIntentResult, parse_intent_payload


SYSTEM_PROMPT = """You classify Telegram messages for a Gmail and Google Calendar assistant.
Return only compact JSON with this schema:
{"intent":"calendar_read|calendar_create|calendar_edit|calendar_cancel|gmail_search|gmail_compose|unknown","normalized_text":"..."}

Rules:
- Do not perform the action.
- Preserve useful names, dates, times, email addresses, subjects, and body text in normalized_text.
- calendar_read means schedule, agenda, availability, free/busy, or "what is on my calendar".
- calendar_create means adding, booking, scheduling, or creating a calendar event.
- calendar_edit means changing, moving, rescheduling, or editing an existing event.
- calendar_cancel means canceling or deleting an existing event.
- gmail_search means finding, showing, reading, listing, or searching emails.
- gmail_compose means drafting or composing a new email.
- Use unknown when the user is chatting, asking for help, or intent is unclear.
"""


class MiniMaxIntentClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def classify(self, text: str) -> LLMIntentResult:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except Exception:
            return LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")

        return parse_intent_payload(str(content))
