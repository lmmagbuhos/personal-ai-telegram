from datetime import UTC, datetime

from personal_hermes.mail.gmail import GmailDraftService, GmailMessageActionService, GmailReadService
from personal_hermes.openclaw.types import EmailMessage, GmailDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


NOW = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.answers = []

    def send_message(self, *, chat_id, text, buttons=None):
        self.messages.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        return len(self.messages)

    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})

    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append({"callback_query_id": callback_query_id, "text": text})


class FakeClient:
    def __init__(self):
        self.searches = []
        self.read = []
        self.unread = []
        self.archived = []
        self.trashed = []
        self.modified = []
        self.created_drafts = []
        self.updated_drafts = []
        self.sent_drafts = []
        self.deleted_drafts = []
        self.access_tokens = []
        self.messages = [
            EmailMessage(
                id="msg-1",
                thread_id="thread-1",
                subject="Invoice update",
                sender="Alex <alex@example.com>",
                to=("me@example.com",),
                cc=(),
                sent_at=NOW,
                snippet="Invoice attached",
                body_text="Full invoice body",
                is_unread=True,
                message_id="<msg-1@example.com>",
            )
        ]

    def with_access_token(self, access_token):
        self.access_tokens.append(access_token)
        return self

    def search_email_messages(self, query, *, max_results=10):
        self.searches.append((query, max_results))
        return self.messages

    def get_email_message(self, email_id):
        return self.messages[0]

    def mark_email_read(self, email_id):
        self.read.append(email_id)

    def mark_email_unread(self, email_id):
        self.unread.append(email_id)

    def archive_email(self, email_id):
        self.archived.append(email_id)

    def trash_email(self, email_id):
        self.trashed.append(email_id)

    def modify_email_labels(self, email_id, *, add=(), remove=()):
        self.modified.append((email_id, add, remove))

    def create_email_draft(self, **fields):
        self.created_drafts.append(fields)
        return GmailDraft(
            id="draft-1",
            message_id="msg-draft-1",
            thread_id="thread-draft-1",
            to=fields["to"],
            cc=fields.get("cc", ()),
            bcc=fields.get("bcc", ()),
            subject=fields["subject"],
            body_text=fields["body_text"],
        )

    def update_email_draft(self, draft_id, **fields):
        self.updated_drafts.append((draft_id, fields))
        return GmailDraft(
            id=draft_id,
            message_id="msg-draft-1",
            thread_id="thread-draft-1",
            to=fields.get("to") or ("alex@example.com",),
            cc=fields.get("cc") or (),
            bcc=fields.get("bcc") or (),
            subject=fields.get("subject") or "Subject",
            body_text=fields.get("body_text") or "Body",
        )

    def send_email_draft(self, draft_id):
        self.sent_drafts.append(draft_id)
        return "sent-1"

    def delete_email_draft(self, draft_id):
        self.deleted_drafts.append(draft_id)


def _store(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    return store


def _user_id(store):
    return store.bootstrap_single_user(
        telegram_user_id=1,
        telegram_chat_id=2,
        now=NOW,
    ).id


def _message(text):
    return TelegramMessage(chat_id=2, user_id=1, message_id=10, text=text)


def _callback(data):
    return TelegramCallback(
        chat_id=2,
        user_id=1,
        message_id=20,
        callback_query_id="q",
        data=data,
    )


def test_gmail_read_unread_query_saves_results_before_buttons(tmp_path):
    store = _store(tmp_path)
    user_id = _user_id(store)
    client = FakeClient()
    telegram = FakeTelegram()
    service = GmailReadService(openclaw_client=client, telegram=telegram, store=store)

    assert service.start_search(_message("show unread emails"), user_id=user_id, now=NOW)

    assert client.searches == [("in:inbox is:unread", 10)]
    state = store.get_conversation_state(2, user_id=user_id)
    assert state is not None and state.state == "gmail_search_results"
    assert telegram.messages[0]["buttons"] == [[("Invoice update", "mail_pick:0")]]


def test_pick_result_fetches_full_message_and_shows_action_buttons(tmp_path):
    store = _store(tmp_path)
    user_id = _user_id(store)
    client = FakeClient()
    telegram = FakeTelegram()
    service = GmailReadService(openclaw_client=client, telegram=telegram, store=store)
    service.start_search(_message("find email about invoice"), user_id=user_id, now=NOW)

    service.handle_callback(_callback("mail_pick:0"), user_id=user_id, now=NOW)

    state = store.get_conversation_state(2, user_id=user_id)
    assert state is not None and state.state == "gmail_selected_message"
    callbacks = [cb for row in telegram.messages[-1]["buttons"] for _label, cb in row]
    assert "mail_read" in callbacks
    assert "mail_archive" in callbacks
    assert "mail_trash" in callbacks
    assert "mail_label_add" in callbacks


def test_message_actions_use_selected_message_and_label_value(tmp_path):
    store = _store(tmp_path)
    user_id = _user_id(store)
    client = FakeClient()
    telegram = FakeTelegram()
    read_service = GmailReadService(openclaw_client=client, telegram=telegram, store=store)
    action_service = GmailMessageActionService(openclaw_client=client, telegram=telegram, store=store)
    read_service.start_search(_message("show unread emails"), user_id=user_id, now=NOW)
    read_service.handle_callback(_callback("mail_pick:0"), user_id=user_id, now=NOW)

    action_service.handle_callback(_callback("mail_archive"), user_id=user_id, now=NOW)
    action_service.handle_callback(_callback("mail_star"), user_id=user_id, now=NOW)
    action_service.handle_callback(_callback("mail_label_add"), user_id=user_id, now=NOW)
    action_service.handle_value(_message("Clients"), user_id=user_id, now=NOW)

    assert client.archived == ["msg-1"]
    assert ("msg-1", ("STARRED",), ()) in client.modified
    assert ("msg-1", ("Clients",), ()) in client.modified


def test_draft_compose_creates_preview_then_sends_after_callback(tmp_path):
    store = _store(tmp_path)
    user_id = _user_id(store)
    client = FakeClient()
    telegram = FakeTelegram()
    service = GmailDraftService(openclaw_client=client, telegram=telegram, store=store)

    handled = service.start_compose(
        _message("email alex@example.com subject Hello body See you tomorrow"),
        user_id=user_id,
        now=NOW,
    )
    service.handle_callback(_callback("draft_send"), user_id=user_id, now=NOW)

    assert handled is True
    assert client.created_drafts[0]["to"] == ("alex@example.com",)
    assert client.sent_drafts == ["draft-1"]
    assert store.get_conversation_state(2, user_id=user_id) is None


def test_draft_missing_fields_are_collected_and_edit_updates_draft(tmp_path):
    store = _store(tmp_path)
    user_id = _user_id(store)
    client = FakeClient()
    telegram = FakeTelegram()
    service = GmailDraftService(openclaw_client=client, telegram=telegram, store=store)

    service.start_compose(_message("compose email"), user_id=user_id, now=NOW)
    assert store.get_conversation_state(2, user_id=user_id).state == "gmail_compose_collect_to"
    service.handle_value(_message("alex@example.com"), user_id=user_id, now=NOW)
    service.handle_value(_message("Subject"), user_id=user_id, now=NOW)
    service.handle_value(_message("Body"), user_id=user_id, now=NOW)
    service.handle_callback(_callback("draft_edit"), user_id=user_id, now=NOW)
    service.handle_callback(_callback("draft_edit_subject"), user_id=user_id, now=NOW)
    service.handle_value(_message("Updated subject"), user_id=user_id, now=NOW)

    assert client.created_drafts
    assert client.updated_drafts == [("draft-1", {"subject": "Updated subject"})]
    assert store.get_conversation_state(2, user_id=user_id).state == "gmail_draft_preview"
