# MiniMax Priority LLM Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a MiniMax-backed natural-language intent layer that runs before the existing rule-based router, while keeping the current deterministic parser as fallback.

**Architecture:** Add a small `personal_hermes.llm` package with provider-neutral intent types, a MiniMax HTTP client, and routing helpers. `AssistantRouter` will ask the LLM for a structured intent for normal user messages after commands/stateful flows and before rule-based checks. The LLM may classify and normalize text, but existing Gmail/Calendar services remain responsible for all Google mutations and confirmation flows.

**Tech Stack:** Python 3.12, `httpx`, Pydantic settings, MiniMax OpenAI-compatible Chat Completions API (`POST https://api.minimax.io/v1/chat/completions`, default model `MiniMax-M2.7`), pytest.

---

## File Map

- Create `src/personal_hermes/llm/__init__.py`: package exports.
- Create `src/personal_hermes/llm/intents.py`: structured intent enums/dataclasses and parser.
- Create `src/personal_hermes/llm/minimax.py`: MiniMax HTTP client and prompt construction.
- Modify `src/personal_hermes/config.py`: MiniMax settings.
- Modify `src/personal_hermes/app.py`: instantiate MiniMax client when configured and pass it to router.
- Modify `src/personal_hermes/router.py`: add LLM-first routing, then existing rule fallback.
- Create `tests/llm/test_minimax.py`: MiniMax client tests using mocked `httpx.post`.
- Create or extend `tests/test_router.py`: LLM priority/fallback routing tests.
- Modify `.env.example`, `ENV_SETUP.md`, and `docs/operations/smoke-test.md`: document MiniMax settings and fallback behavior.

---

### Task 1: Add LLM Intent Types

**Files:**
- Create: `src/personal_hermes/llm/__init__.py`
- Create: `src/personal_hermes/llm/intents.py`
- Test: `tests/llm/test_minimax.py`

- [x] **Step 1: Write failing tests for intent parsing**

Add `tests/llm/test_minimax.py`:

```python
import pytest

from personal_hermes.llm.intents import LLMIntent, LLMIntentResult, parse_intent_payload


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


def test_parse_intent_payload_rejects_unknown_intent_value():
    result = parse_intent_payload('{"intent":"delete_everything","normalized_text":"x"}')

    assert result.intent == LLMIntent.UNKNOWN
    assert result.normalized_text == ""
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/llm/test_minimax.py -q
```

Expected: FAIL because `personal_hermes.llm` does not exist.

- [x] **Step 3: Implement intent types**

Create `src/personal_hermes/llm/__init__.py`:

```python
from personal_hermes.llm.intents import LLMIntent, LLMIntentResult

__all__ = ["LLMIntent", "LLMIntentResult"]
```

Create `src/personal_hermes/llm/intents.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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
    try:
        payload = json.loads(text)
    except ValueError:
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
```

- [x] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/llm/test_minimax.py -q
```

Expected: PASS.

---

### Task 2: Add MiniMax Client

**Files:**
- Modify: `tests/llm/test_minimax.py`
- Create: `src/personal_hermes/llm/minimax.py`

- [x] **Step 1: Write failing tests for MiniMax request/response handling**

Append to `tests/llm/test_minimax.py`:

```python
from personal_hermes.llm.intents import LLMIntent
from personal_hermes.llm.minimax import MiniMaxIntentClient


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
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/llm/test_minimax.py -q
```

Expected: FAIL because `personal_hermes.llm.minimax` does not exist.

- [x] **Step 3: Implement MiniMax client**

Create `src/personal_hermes/llm/minimax.py`:

```python
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
```

- [x] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/llm/test_minimax.py -q
```

Expected: PASS.

---

### Task 3: Add MiniMax Settings

**Files:**
- Modify: `src/personal_hermes/config.py`
- Modify: `tests/test_config.py`

- [x] **Step 1: Write failing config tests**

Add `MINIMAX_API_KEY`, `MINIMAX_MODEL`, `MINIMAX_BASE_URL`, and `LLM_TIMEOUT_SECONDS` to `OPTIONAL_ENV_KEYS` in `tests/test_config.py`.

Add:

```python
def test_minimax_settings_are_optional_and_default_to_disabled(monkeypatch):
    clear_optional_env(monkeypatch)
    set_required_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.minimax_api_key is None
    assert settings.minimax_model == "MiniMax-M2.7"
    assert settings.minimax_base_url == "https://api.minimax.io/v1"
    assert settings.llm_timeout_seconds == 10
    assert settings.llm_configured is False


def test_minimax_api_key_enables_llm(monkeypatch):
    clear_optional_env(monkeypatch)
    set_required_env(monkeypatch)
    monkeypatch.setenv("MINIMAX_API_KEY", "secret")

    settings = Settings(_env_file=None)

    assert settings.llm_configured is True
```

- [x] **Step 2: Run targeted tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: FAIL because settings do not exist.

- [x] **Step 3: Implement config fields**

In `src/personal_hermes/config.py`, add fields:

```python
    minimax_api_key: str | None = None
    minimax_model: str = "MiniMax-M2.7"
    minimax_base_url: str = "https://api.minimax.io/v1"
    llm_timeout_seconds: PositiveInt = 10
```

Add property:

```python
    @property
    def llm_configured(self) -> bool:
        return bool(self.minimax_api_key)
```

Add validator:

```python
    @field_validator("minimax_base_url")
    @classmethod
    def validate_minimax_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("minimax_base_url must be an absolute http(s) URL")
        return value.rstrip("/")
```

- [x] **Step 4: Run config tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: PASS.

---

### Task 4: Wire MiniMax Into App Components

**Files:**
- Modify: `src/personal_hermes/app.py`
- Modify: `tests/test_app.py`

- [x] **Step 1: Write failing app wiring tests**

In `tests/test_app.py`, add:

```python
def test_build_components_wires_minimax_when_api_key_configured(tmp_path):
    settings = make_settings(tmp_path / "assistant.sqlite3")
    settings = settings.model_copy(update={"minimax_api_key": "secret"})

    components = build_components(
        settings,
        telegram_gateway=FakeTelegramGateway(),
        command_runner=lambda _args, input_text=None: {"messages": []},
    )

    assert components.router.llm_intent_service is not None


def test_build_components_leaves_llm_unconfigured_without_api_key(tmp_path):
    settings = make_settings(tmp_path / "assistant.sqlite3")

    components = build_components(
        settings,
        telegram_gateway=FakeTelegramGateway(),
        command_runner=lambda _args, input_text=None: {"messages": []},
    )

    assert components.router.llm_intent_service is None
```

- [x] **Step 2: Run targeted tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_app.py -q
```

Expected: FAIL because router has no `llm_intent_service` attribute/constructor arg.

- [x] **Step 3: Implement app wiring**

In `src/personal_hermes/app.py`:

Add import:

```python
from personal_hermes.llm.minimax import MiniMaxIntentClient
```

Add `llm_intent_service = None` near OAuth initialization.

After OpenClaw/Telegram setup:

```python
    if settings.llm_configured:
        assert settings.minimax_api_key is not None
        llm_intent_service = MiniMaxIntentClient(
            api_key=settings.minimax_api_key,
            model=settings.minimax_model,
            base_url=settings.minimax_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
```

Pass `llm_intent_service=llm_intent_service` into `AssistantRouter(...)`.

In `src/personal_hermes/router.py`, add constructor parameter:

```python
        llm_intent_service=None,
```

and assignment:

```python
        self.llm_intent_service = llm_intent_service
```

- [x] **Step 4: Run app tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_app.py -q
```

Expected: PASS.

---

### Task 5: Route Normal Messages Through LLM First

**Files:**
- Modify: `src/personal_hermes/router.py`
- Modify: `tests/test_router.py`

- [x] **Step 1: Add router fakes and failing LLM-priority tests**

In `tests/test_router.py`, add:

```python
from personal_hermes.llm.intents import LLMIntent, LLMIntentResult


class FakeLLMIntentService:
    def __init__(self, result: LLMIntentResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.messages = []

    def classify(self, text: str) -> LLMIntentResult:
        self.messages.append(text)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result
```

Add tests:

```python
def test_llm_calendar_read_routes_before_rule_fallback():
    telegram = FakeTelegram()
    calendar_service = FakeCalendarService()
    llm = FakeLLMIntentService(
        LLMIntentResult(
            intent=LLMIntent.CALENDAR_READ,
            normalized_text="what is on my calendar today",
        )
    )
    router = AssistantRouter(
        telegram=telegram,
        calendar_service=calendar_service,
        mail_action_service=FakeMailActionService(),
        store=None,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(message("do I have anything later?"), now=now)

    assert llm.messages == ["do I have anything later?"]
    assert calendar_service.calls == [("what is on my calendar today", date(2026, 5, 19))]
    assert "free" in telegram.sent[0]["text"]


def test_llm_gmail_search_routes_to_gmail_read_service():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(
        LLMIntentResult(
            intent=LLMIntent.GMAIL_SEARCH,
            normalized_text="search emails from alex",
        )
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    router.handle_event(message("did Alex email me?"), now=now)

    handled_message, user_id, handled_now = gmail_read.messages[0]
    assert handled_message.text == "search emails from alex"
    assert user_id is None
    assert handled_now == now


def test_llm_unknown_falls_back_to_rule_based_routing():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(
        LLMIntentResult(intent=LLMIntent.UNKNOWN, normalized_text="")
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("show unread emails")

    router.handle_event(event, now=now)

    assert gmail_read.messages == [(event, None, now)]


def test_llm_error_falls_back_to_rule_based_routing():
    gmail_read = FakeGmailReadService()
    llm = FakeLLMIntentService(error=RuntimeError("llm unavailable"))
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=None,
        gmail_read_service=gmail_read,
        llm_intent_service=llm,
    )
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    event = message("show unread emails")

    router.handle_event(event, now=now)

    assert gmail_read.messages == [(event, None, now)]
```

- [x] **Step 2: Run router tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_router.py -q
```

Expected: FAIL because router does not use LLM.

- [x] **Step 3: Add LLM routing helper in router**

In `src/personal_hermes/router.py`, import:

```python
from dataclasses import replace

from personal_hermes.llm.intents import LLMIntent, LLMIntentResult
```

Add protocol:

```python
class RouterLLMIntentService(Protocol):
    def classify(self, text: str) -> LLMIntentResult:
        ...
```

Add helper:

```python
    def _handle_llm_intent(self, event: TelegramMessage, *, user_id=None, now: datetime) -> bool:
        if self.llm_intent_service is None:
            return False
        try:
            result = self.llm_intent_service.classify(event.text)
        except Exception:
            return False
        if result.intent == LLMIntent.UNKNOWN:
            return False

        normalized_text = result.normalized_text or event.text
        normalized_event = replace(event, text=normalized_text)

        if result.intent == LLMIntent.CALENDAR_READ:
            schedules = self.calendar_service.schedule_for(
                normalized_text,
                today=now.date(),
                user_id=user_id,
            )
            self.telegram.send_message(
                chat_id=event.chat_id,
                text=format_schedule(schedules, timezone=self.calendar_service.timezone),
            )
            return True
        if result.intent == LLMIntent.CALENDAR_CREATE:
            return self._handle_create_event(normalized_event, user_id=user_id, now=now)
        if result.intent == LLMIntent.CALENDAR_EDIT:
            if self.calendar_edit_service is None:
                return False
            return self.calendar_edit_service.start(
                normalized_event,
                operation="edit",
                user_id=user_id,
                now=now,
            )
        if result.intent == LLMIntent.CALENDAR_CANCEL:
            if self.calendar_edit_service is None:
                return False
            return self.calendar_edit_service.start(
                normalized_event,
                operation="cancel",
                user_id=user_id,
                now=now,
            )
        if result.intent == LLMIntent.GMAIL_SEARCH:
            return self._handle_gmail_search(normalized_event, user_id=user_id, now=now)
        if result.intent == LLMIntent.GMAIL_COMPOSE:
            return self._handle_gmail_compose(normalized_event, user_id=user_id, now=now)
        return False
```

Call this helper in both single-user compatibility branch and multi-user branch after stateful handlers and before `_handle_cancel_event`:

```python
            if self._handle_llm_intent(event, user_id=None, now=now):
                return
```

and:

```python
        if self._handle_llm_intent(event, user_id=user.id, now=now):
            return
```

- [x] **Step 4: Run router tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_router.py -q
```

Expected: PASS.

---

### Task 6: Preserve Stateful Flow Determinism

**Files:**
- Modify: `tests/test_router.py`
- Modify if needed: `src/personal_hermes/router.py`

- [x] **Step 1: Add tests ensuring LLM is skipped for stateful flows**

Add:

```python
def test_edit_reply_state_skips_llm(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    pending_id = store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Original",
        created_at=now,
        expires_at=now + timedelta(days=7),
        telegram_message_id=77,
    )
    store.set_conversation_state(
        telegram_chat_id=123,
        state="editing_reply",
        payload={"pending_reply_id": pending_id, "message_id": 77},
        updated_at=now,
    )
    llm = FakeLLMIntentService(
        LLMIntentResult(intent=LLMIntent.GMAIL_SEARCH, normalized_text="search emails")
    )
    router = AssistantRouter(
        telegram=FakeTelegram(),
        calendar_service=FakeCalendarService(),
        mail_action_service=FakeMailActionService(),
        store=store,
        llm_intent_service=llm,
    )

    router.handle_event(message("This is my edited reply."), now=now)

    assert llm.messages == []
```

- [x] **Step 2: Run router tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_router.py -q
```

Expected: PASS. If it fails, move the `_handle_llm_intent` call later so it only runs after all state-specific handlers.

---

### Task 7: Update Docs And Sample Env

**Files:**
- Modify: `.env.example`
- Modify: `ENV_SETUP.md`
- Modify: `docs/operations/smoke-test.md`

- [x] **Step 1: Add env sample**

In `.env.example`, add:

```bash
MINIMAX_API_KEY=
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimax.io/v1
LLM_TIMEOUT_SECONDS=10
```

- [x] **Step 2: Add setup docs**

In `ENV_SETUP.md`, add a section:

```markdown
## MiniMax LLM Routing

MiniMax is the priority natural-language parser. When `MINIMAX_API_KEY` is set,
normal Telegram messages are classified by MiniMax first. If MiniMax fails,
returns invalid JSON, or returns `unknown`, the existing rule-based parser is
used as fallback.

```bash
MINIMAX_API_KEY=your-minimax-api-key
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimax.io/v1
LLM_TIMEOUT_SECONDS=10
```
```

- [x] **Step 3: Update smoke test**

In `docs/operations/smoke-test.md`, add a natural language test after `/status`:

```markdown
Send:

```text
Can you check whether I have anything later today?
```

Expected:

- The bot returns a calendar schedule/availability response.
- If MiniMax is unavailable, the fallback parser should still handle direct phrases like `what's on my calendar today?`.
```

---

### Task 8: Verification

**Files:**
- No code changes.

- [x] **Run focused tests**

```bash
.venv/bin/python -m pytest tests/llm/test_minimax.py tests/test_router.py tests/test_app.py tests/test_config.py -q
```

Expected: all pass.

- [x] **Run full suite**

```bash
.venv/bin/python -m pytest
```

Expected: all pass.

- [x] **Run config check**

```bash
.venv/bin/python -m personal_hermes --check-config
```

Expected:

```text
Configuration OK
```

- [x] **Optional live MiniMax smoke**

Only if `MINIMAX_API_KEY` is present in `.env`, run a one-off Python check:

```bash
.venv/bin/python - <<'PY'
from personal_hermes.config import Settings
from personal_hermes.llm.minimax import MiniMaxIntentClient

settings = Settings()
assert settings.minimax_api_key
client = MiniMaxIntentClient(
    api_key=settings.minimax_api_key,
    model=settings.minimax_model,
    base_url=settings.minimax_base_url,
    timeout_seconds=settings.llm_timeout_seconds,
)
print(client.classify("Do I have anything later today?"))
PY
```

Expected: an `LLMIntentResult` with `calendar_read` or a valid fallback-safe `unknown`.

