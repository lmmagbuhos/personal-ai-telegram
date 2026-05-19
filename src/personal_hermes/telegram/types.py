from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramMessage:
    chat_id: int
    user_id: int
    message_id: int
    text: str


@dataclass(frozen=True)
class TelegramCallback:
    chat_id: int
    user_id: int
    message_id: int
    callback_query_id: str
    data: str
