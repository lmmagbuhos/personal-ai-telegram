# Personal Hermes

Personal Hermes is a single-user Python assistant that uses Telegram as the chat surface and OpenClaw for Gmail and Google Calendar access.

## Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` with the Telegram, OpenClaw, and local database settings for the service.

## Test

```bash
python -m pytest
```
