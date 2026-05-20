# Multiuser-Only Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Remove the legacy single-user runtime path while preserving the working multi-user Google OAuth path.

**Architecture:** Keep `OpenClawClient` capable of account/client flags for lower-level tests and manual use, but stop passing process-level Google account settings from app runtime. Make `MULTIUSER_ENABLED=true` mandatory, require OAuth settings unconditionally, and ensure scheduler services receive the store/token resolver for per-user execution.

**Tech Stack:** Python 3.12, Pydantic settings, pytest, OpenClaw `gog`.

---

### Task 1: Enforce Multiuser Runtime Configuration

**Files:**
- Modify: `src/personal_hermes/config.py`
- Test: `tests/test_config.py`

- [x] Write failing tests that default settings require multi-user OAuth config and reject `MULTIUSER_ENABLED=false`.
- [x] Run targeted config tests and confirm failure.
- [x] Update `Settings` so `multiuser_enabled` defaults to `True`, must remain true, and OAuth settings are always required.
- [x] Run targeted config tests and confirm pass.

### Task 2: Stop Wiring Process-Level Google Account Into Runtime

**Files:**
- Modify: `src/personal_hermes/app.py`
- Test: `tests/test_app.py`

- [x] Write failing test proving `build_components` creates `OpenClawClient` without account/client values even if env/settings include them.
- [x] Run targeted app test and confirm failure.
- [x] Remove `account=settings.gog_account` and `client=settings.gog_client` from runtime client construction.
- [x] Ensure scheduler always receives the store in the multi-user-only runtime.
- [x] Run targeted app tests and confirm pass.

### Task 3: Refresh Docs And Sample Env

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `ENV_SETUP.md`
- Modify: `docs/operations/smoke-test.md`
- Modify: `docs/operations/multiuser-oauth-setup.md`

- [x] Remove legacy single-user setup language from active docs.
- [x] Keep any `gog` references scoped to executable use with per-user access tokens, not stored `GOG_ACCOUNT` refresh tokens.
- [x] Run full tests.

