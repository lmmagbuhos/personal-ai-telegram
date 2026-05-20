from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum


class LLMIntent(StrEnum):
    CALENDAR_READ = "calendar_read"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_EDIT = "calendar_edit"
    CALENDAR_CANCEL = "calendar_cancel"
    GMAIL_SEARCH = "gmail_search"
    GMAIL_COMPOSE = "gmail_compose"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LLMIntentResult:
    intent: LLMIntent
    normalized_text: str


def parse_intent_payload(text: str) -> LLMIntentResult:
    decoder = json.JSONDecoder()
    payload = None
    try:
        payload = decoder.decode(text)
    except ValueError:
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                candidate, _end = decoder.raw_decode(text[index:])
            except ValueError:
                continue
            payload = candidate
            break

    if payload is None:
        return LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")

    if not isinstance(payload, dict):
        return LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")

    raw_intent = payload.get("intent")
    try:
        intent = LLMIntent(str(raw_intent))
    except ValueError:
        return LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")

    normalized_text = payload.get("normalized_text")
    if normalized_text is None:
        normalized_text = ""
    if not isinstance(normalized_text, str):
        return LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")

    return LLMIntentResult(intent=intent, normalized_text=normalized_text.strip())
