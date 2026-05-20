# Personal Hermes

Personal Hermes is a multi-user Python assistant that uses Telegram as the chat surface, Google OAuth for per-user Gmail and Google Calendar access, and OpenClaw `gog` for Google API commands.

## Setup

Use Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` with the Telegram, OpenClaw, and local database settings for the service.

## Test

```bash
python -m pytest
```

## Run

Check local configuration:

```bash
python -m personal_hermes --check-config
```

Start the polling runtime:

```bash
python -m personal_hermes --run
```

For live Telegram, Gmail, and Google Calendar validation, follow:

- `docs/operations/smoke-test.md`
