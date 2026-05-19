import sqlite3
from datetime import UTC, datetime, timedelta

from personal_hermes.storage.store import StateStore


def test_user_upsert_and_lookup_by_telegram_identity_creates_pending_user(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    user = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="Ada Lovelace",
        username="ada",
        now=now,
    )

    assert user.id > 0
    assert user.telegram_user_id == 123
    assert user.telegram_chat_id == 456
    assert user.display_name == "Ada Lovelace"
    assert user.username == "ada"
    assert user.status == "pending"
    assert user.created_at == now
    assert user.updated_at == now
    assert store.get_user_by_telegram(telegram_user_id=123, telegram_chat_id=456) == user
    assert store.get_user_by_telegram(telegram_user_id=123, telegram_chat_id=999) is None


def test_existing_user_upsert_preserves_status_while_updating_display_metadata(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    store = StateStore(database_path)
    store.initialize()
    created_at = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    updated_at = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)

    user = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="Ada",
        username=None,
        now=created_at,
    )
    assert store.activate_user(user.id, updated_at) is True

    active_user = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="Ada Lovelace",
        username="ada",
        now=updated_at,
    )

    assert active_user.id == user.id
    assert active_user.status == "active"
    assert active_user.display_name == "Ada Lovelace"
    assert active_user.username == "ada"
    assert active_user.created_at == created_at
    assert active_user.updated_at == updated_at

    revoked_at = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE users SET status = 'revoked', updated_at = ? WHERE id = ?",
            (revoked_at.isoformat(), user.id),
        )

    refreshed = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="A. Lovelace",
        username="analytical_engine",
        now=revoked_at + timedelta(minutes=1),
    )

    assert refreshed.status == "revoked"
    assert refreshed.display_name == "A. Lovelace"
    assert refreshed.username == "analytical_engine"


def test_oauth_session_single_use_and_expiry(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    created_at = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    expires_at = created_at + timedelta(minutes=10)

    store.create_oauth_session(
        state="state-1",
        telegram_user_id=123,
        telegram_chat_id=456,
        expires_at=expires_at,
        created_at=created_at,
    )

    consumed = store.consume_oauth_session("state-1", created_at + timedelta(minutes=1))
    assert consumed is not None
    assert consumed.state == "state-1"
    assert consumed.telegram_user_id == 123
    assert consumed.telegram_chat_id == 456
    assert consumed.expires_at == expires_at
    assert consumed.created_at == created_at
    assert consumed.used_at == created_at + timedelta(minutes=1)
    assert store.consume_oauth_session("state-1", created_at + timedelta(minutes=2)) is None

    store.create_oauth_session(
        state="state-2",
        telegram_user_id=123,
        telegram_chat_id=456,
        expires_at=created_at + timedelta(minutes=5),
        created_at=created_at,
    )
    assert store.consume_oauth_session("state-2", created_at + timedelta(minutes=5)) is None
    assert store.consume_oauth_session("missing", created_at) is None


def test_save_and_get_google_account_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    user = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="Ada",
        username="ada",
        now=now,
    )

    store.save_google_account(
        user_id=user.id,
        google_subject="google-subject",
        google_email="ada@example.com",
        encrypted_access_token="access-token",
        encrypted_refresh_token="refresh-token",
        granted_scopes=("email", "profile"),
        token_expires_at=None,
        now=now,
    )

    account = store.get_google_account(user.id)
    assert account is not None
    assert account.user_id == user.id
    assert account.google_subject == "google-subject"
    assert account.google_email == "ada@example.com"
    assert account.encrypted_access_token == "access-token"
    assert account.encrypted_refresh_token == "refresh-token"
    assert account.granted_scopes == ("email", "profile")
    assert account.token_expires_at is None
    assert account.status == "active"
    assert account.created_at == now
    assert account.updated_at == now


def test_mark_google_account_status_updates_status(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    user = store.upsert_user_from_telegram(
        telegram_user_id=123,
        telegram_chat_id=456,
        display_name="Ada",
        username="ada",
        now=now,
    )
    store.save_google_account(
        user_id=user.id,
        google_subject="google-subject",
        google_email="ada@example.com",
        encrypted_access_token="access-token",
        encrypted_refresh_token="refresh-token",
        granted_scopes=("email",),
        token_expires_at=now + timedelta(hours=1),
        now=now,
    )

    updated_at = now + timedelta(minutes=30)
    assert store.mark_google_account_status(user.id, "reauth_required", updated_at) is True
    account = store.get_google_account(user.id)
    assert account is not None
    assert account.status == "reauth_required"
    assert account.updated_at == updated_at


def test_list_active_google_users_returns_only_active_users_with_active_google_accounts(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    active_with_active_google = store.upsert_user_from_telegram(
        telegram_user_id=1,
        telegram_chat_id=101,
        display_name="Active",
        username="active",
        now=now,
    )
    active_with_inactive_google = store.upsert_user_from_telegram(
        telegram_user_id=2,
        telegram_chat_id=102,
        display_name="Reauth",
        username="reauth",
        now=now,
    )
    pending_with_active_google = store.upsert_user_from_telegram(
        telegram_user_id=3,
        telegram_chat_id=103,
        display_name="Pending",
        username="pending",
        now=now,
    )

    for user in (active_with_active_google, active_with_inactive_google):
        assert store.activate_user(user.id, now) is True

    for user in (
        active_with_active_google,
        active_with_inactive_google,
        pending_with_active_google,
    ):
        store.save_google_account(
            user_id=user.id,
            google_subject=f"subject-{user.id}",
            google_email=f"user-{user.id}@example.com",
            encrypted_access_token="access-token",
            encrypted_refresh_token="refresh-token",
            granted_scopes=("email",),
            token_expires_at=now + timedelta(hours=1),
            now=now,
        )

    assert (
        store.mark_google_account_status(
            active_with_inactive_google.id,
            "reauth_required",
            now + timedelta(minutes=1),
        )
        is True
    )

    active_google_users = store.list_active_google_users()
    assert [user.id for user in active_google_users] == [active_with_active_google.id]
    assert active_google_users[0].status == "active"
