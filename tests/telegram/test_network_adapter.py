from personal_hermes.telegram.adapter import TelegramAdapter
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class FakeTelegramGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []

    def request(self, method: str, payload: dict) -> dict:
        self.calls.append((method, payload))
        if method == "getUpdates":
            return {"ok": True, "result": self.updates}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 77}}
        return {"ok": True, "result": True}


def test_poll_updates_converts_messages_and_callbacks_and_tracks_offset():
    gateway = FakeTelegramGateway()
    gateway.updates = [
        {
            "update_id": 10,
            "message": {
                "message_id": 1,
                "chat": {"id": 123},
                "from": {"id": 456},
                "text": "Am I free today?",
            },
        },
        {
            "update_id": 11,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 456},
                "message": {"message_id": 2, "chat": {"id": 123}},
                "data": "send_reply:9",
            },
        },
    ]
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
        gateway=gateway,
    )

    events = adapter.poll_updates(timeout_seconds=5)
    next_events = adapter.poll_updates(timeout_seconds=5)

    assert events == [
        TelegramMessage(
            chat_id=123,
            user_id=456,
            message_id=1,
            text="Am I free today?",
        ),
        TelegramCallback(
            chat_id=123,
            user_id=456,
            message_id=2,
            callback_query_id="callback-1",
            data="send_reply:9",
        ),
    ]
    assert gateway.calls[0] == (
        "getUpdates",
        {"timeout": 5, "allowed_updates": ["message", "callback_query"]},
    )
    assert gateway.calls[1] == (
        "getUpdates",
        {"timeout": 5, "allowed_updates": ["message", "callback_query"], "offset": 12},
    )
    assert next_events == events


def test_send_message_passes_inline_buttons_and_returns_message_id():
    gateway = FakeTelegramGateway()
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
        gateway=gateway,
    )

    message_id = adapter.send_message(
        chat_id=123,
        text="New email",
        buttons=[[("Send reply", "send_reply:9")]],
    )

    assert message_id == 77
    assert gateway.calls == [
        (
            "sendMessage",
            {
                "chat_id": 123,
                "text": "New email",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "Send reply", "callback_data": "send_reply:9"}
                        ]
                    ]
                },
            },
        )
    ]


def test_edit_message_and_answer_callback_call_gateway():
    gateway = FakeTelegramGateway()
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
        gateway=gateway,
    )

    adapter.edit_message(chat_id=123, message_id=77, text="Sent")
    adapter.answer_callback(callback_query_id="callback-1", text="Done")

    assert gateway.calls == [
        (
            "editMessageText",
            {"chat_id": 123, "message_id": 77, "text": "Sent"},
        ),
        (
            "answerCallbackQuery",
            {"callback_query_id": "callback-1", "text": "Done"},
        ),
    ]

