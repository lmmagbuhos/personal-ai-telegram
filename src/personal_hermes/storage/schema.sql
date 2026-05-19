CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    display_name TEXT,
    username TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'active', 'revoked', 'disabled')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (telegram_user_id, telegram_chat_id)
);

CREATE TABLE IF NOT EXISTS oauth_sessions (
    state TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    google_subject TEXT NOT NULL,
    google_email TEXT NOT NULL,
    encrypted_access_token TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    granted_scopes TEXT NOT NULL,
    token_expires_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('active', 'reauth_required', 'revoked')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_emails (
    email_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    telegram_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS pending_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'sent', 'failed', 'ignored', 'expired')
    ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    telegram_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS reply_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    telegram_action_id TEXT NOT NULL,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_agenda_notifications (
    agenda_date TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_reminders (
    event_id TEXT NOT NULL,
    event_start_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (event_id, event_start_at)
);

CREATE TABLE IF NOT EXISTS conversation_state (
    telegram_chat_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
