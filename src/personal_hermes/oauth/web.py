from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from personal_hermes.oauth.crypto import TokenCipher
from personal_hermes.oauth.google import GoogleOAuthService
from personal_hermes.storage.store import StateStore


def create_oauth_app(
    *,
    store: StateStore,
    oauth: GoogleOAuthService,
    token_cipher: TokenCipher,
    telegram,
    now_provider: Callable[[], datetime] | None = None,
) -> FastAPI:
    if now_provider is None:
        now_provider = lambda: datetime.now(tz=UTC)

    app = FastAPI()

    @app.get("/oauth/google/callback", response_class=HTMLResponse)
    def google_callback(
        state: str = Query(...),
        code: str = Query(...) ,
    ) -> HTMLResponse:
        now = now_provider()
        session = store.consume_oauth_session(state=state, now=now)
        if session is None:
            return HTMLResponse(
                "<h1>Connection expired</h1><p>Run /connect in Telegram again.</p>",
                status_code=400,
            )

        user = store.upsert_user_from_telegram(
            telegram_user_id=session.telegram_user_id,
            telegram_chat_id=session.telegram_chat_id,
            display_name=None,
            username=None,
            now=now,
        )

        try:
            bundle = oauth.exchange_callback(
                f"/oauth/google/callback?state={state}&code={code}",
                expected_state=state,
            )
        except Exception:
            return HTMLResponse(
                "<h1>Connection failed</h1><p>Return to Telegram and run /connect.</p>",
                status_code=400,
            )

        store.save_google_account(
            user_id=user.id,
            google_subject=bundle.google_subject,
            google_email=bundle.google_email,
            encrypted_access_token=token_cipher.encrypt(bundle.access_token),
            encrypted_refresh_token=token_cipher.encrypt(bundle.refresh_token),
            granted_scopes=bundle.granted_scopes,
            token_expires_at=bundle.token_expires_at,
            now=now,
        )
        store.activate_user(user.id, now=now)
        telegram.send_message(
            chat_id=session.telegram_chat_id,
            text="Google connected.",
        )

        return HTMLResponse(
            "<h1>Google connected</h1><p>You can return to Telegram.</p>"
        )

    return app
