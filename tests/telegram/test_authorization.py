from personal_hermes.telegram.adapter import TelegramAdapter
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


def test_authorized_message_is_accepted():
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
    )
    message = TelegramMessage(
        chat_id=123,
        user_id=456,
        message_id=1,
        text="What is my availability today?",
    )

    assert adapter.is_authorized(message) is True


def test_message_from_wrong_chat_or_user_is_rejected():
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
    )

    assert adapter.is_authorized(
        TelegramMessage(chat_id=999, user_id=456, message_id=1, text="hello")
    ) is False
    assert adapter.is_authorized(
        TelegramMessage(chat_id=123, user_id=999, message_id=1, text="hello")
    ) is False


def test_authorized_callback_is_accepted():
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
    )
    callback = TelegramCallback(
        chat_id=123,
        user_id=456,
        message_id=1,
        callback_query_id="query-1",
        data="send_reply:9",
    )

    assert adapter.is_authorized(callback) is True


def test_callback_from_wrong_chat_or_user_is_rejected():
    adapter = TelegramAdapter(
        bot_token="token",
        authorized_chat_id=123,
        authorized_user_id=456,
    )

    assert adapter.is_authorized(
        TelegramCallback(
            chat_id=999,
            user_id=456,
            message_id=1,
            callback_query_id="query-1",
            data="send_reply:9",
        )
    ) is False
    assert adapter.is_authorized(
        TelegramCallback(
            chat_id=123,
            user_id=999,
            message_id=1,
            callback_query_id="query-1",
            data="send_reply:9",
        )
    ) is False

