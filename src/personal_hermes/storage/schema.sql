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
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
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
    user_id INTEGER NOT NULL,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    telegram_message_id INTEGER,
    PRIMARY KEY (user_id, email_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pending_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'sent', 'failed', 'ignored', 'expired')
    ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    telegram_message_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reply_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    telegram_action_id TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calendar_agenda_notifications (
    user_id INTEGER NOT NULL,
    agenda_date TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, agenda_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calendar_reminders (
    user_id INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_start_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, event_id, event_start_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_state (
    user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, telegram_chat_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
