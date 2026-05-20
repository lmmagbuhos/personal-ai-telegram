import pytest

from personal_hermes.llm.intents import LLMIntent, LLMIntentResult, parse_intent_payload
from personal_hermes.llm.minimax import MiniMaxIntentClient


def test_parse_intent_payload_accepts_known_intent_and_normalized_text():
    result = parse_intent_payload(
        '{"intent":"calendar_create","normalized_text":"schedule meeting tomorrow at 2pm review"}'
    )

    assert result == LLMIntentResult(
        intent=LLMIntent.CALENDAR_CREATE,
        normalized_text="schedule meeting tomorrow at 2pm review",
    )


def test_parse_intent_payload_defaults_unknown_for_invalid_json():
    result = parse_intent_payload("not json")

    assert result.intent == LLMIntent.UNKNOWN
    assert result.normalized_text == ""


def test_parse_intent_payload_accepts_minimax_reasoning_prefix():
    result = parse_intent_payload(
        '<think>calendar schedule request</think>\n\n'
        '{"intent":"calendar_read","normalized_text":"Do I have anything later today?"}'
    )

    assert result == LLMIntentResult(
        intent=LLMIntent.CALENDAR_READ,
        normalized_text="Do I have anything later today?",
    )


def test_parse_intent_payload_rejects_unknown_intent_value():
    result = parse_intent_payload('{"intent":"delete_everything","normalized_text":"x"}')

    assert result.intent == LLMIntent.UNKNOWN
    assert result.normalized_text == ""


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error is not None:
            raise self.status_error

    def json(self):
        return self.payload


def test_minimax_client_posts_openai_compatible_chat_request(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"intent":"gmail_search","normalized_text":"search emails from alex"}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("personal_hermes.llm.minimax.httpx.post", fake_post)
    client = MiniMaxIntentClient(
        api_key="secret",
        model="MiniMax-M2.7",
        base_url="https://api.minimax.io/v1",
        timeout_seconds=7,
    )

    result = client.classify("show me emails from Alex")

    assert result.intent == LLMIntent.GMAIL_SEARCH
    assert result.normalized_text == "search emails from alex"
    assert calls[0]["url"] == "https://api.minimax.io/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["json"]["model"] == "MiniMax-M2.7"
    assert calls[0]["timeout"] == 7


def test_minimax_client_returns_unknown_on_malformed_response(monkeypatch):
    monkeypatch.setattr(
        "personal_hermes.llm.minimax.httpx.post",
        lambda *args, **kwargs: FakeResponse({"choices": []}),
    )
    client = MiniMaxIntentClient(
        api_key="secret",
        model="MiniMax-M2.7",
        base_url="https://api.minimax.io/v1",
        timeout_seconds=7,
    )

    result = client.classify("hello")

    assert result.intent == LLMIntent.UNKNOWN
