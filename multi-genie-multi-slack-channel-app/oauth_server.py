"""
Flask server that handles the Databricks OAuth U2M (PKCE) flow
for linking Slack users to their Databricks identity.
"""
import base64
import hashlib
import logging
import secrets
import time
from threading import Thread
from urllib.parse import urlencode

import requests as http_requests
from flask import Flask, request, redirect, jsonify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config
from token_store import TokenInfo, TokenStore

logger = logging.getLogger(__name__)


def _http_session() -> http_requests.Session:
    """Build an HTTP session with automatic retries on transient failures."""
    session = http_requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _http_session()


def create_flask_app(token_store: TokenStore, on_auth_complete=None) -> Flask:
    app = Flask(__name__)

    pending: dict[str, dict] = {}

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/")
    def index():
        return jsonify({"app": "multi-genie-slack", "status": "running"})

    @app.route("/auth/link")
    def auth_link():
        """Slack bot sends users here with ?slack_user=U12345."""
        slack_user_id = request.args.get("slack_user")
        if not slack_user_id:
            return "Missing slack_user parameter", 400

        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        state = secrets.token_urlsafe(32)
        pending[state] = {
            "slack_user_id": slack_user_id,
            "code_verifier": code_verifier,
            "created": time.time(),
        }

        params = urlencode({
            "client_id": Config.OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": Config.OAUTH_REDIRECT_URI,
            "scope": Config.OAUTH_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })

        authorize_url = f"{Config.DATABRICKS_HOST}/oidc/v1/authorize?{params}"
        logger.info("Redirecting Slack user %s to Databricks OAuth", slack_user_id)
        return redirect(authorize_url)

    @app.route("/callback")
    def oauth_callback():
        """Databricks redirects here after user consents."""
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            desc = request.args.get("error_description", "")
            logger.error("OAuth error: %s - %s", error, desc)
            return f"Authorization failed: {error} — {desc}", 400

        if not code or not state:
            return "Missing code or state", 400

        auth_info = pending.pop(state, None)
        if not auth_info:
            return "Invalid or expired state. Please try linking again from Slack.", 400

        _expire_stale(pending)

        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Config.OAUTH_REDIRECT_URI,
            "client_id": Config.OAUTH_CLIENT_ID,
            "client_secret": Config.OAUTH_CLIENT_SECRET,
            "code_verifier": auth_info["code_verifier"],
        }

        token_resp = _session.post(
            f"{Config.DATABRICKS_HOST}/oidc/v1/token",
            data=token_data,
            timeout=30,
        )

        if token_resp.status_code != 200:
            logger.error("Token exchange failed: %s", token_resp.text)
            return f"Token exchange failed: {token_resp.text}", 500

        tokens = token_resp.json()
        slack_user_id = auth_info["slack_user_id"]
        db_email = _fetch_user_email(tokens["access_token"])

        token_info = TokenInfo(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            expires_at=time.time() + tokens.get("expires_in", 3600),
            db_email=db_email,
        )
        token_store.put(slack_user_id, token_info)

        logger.info("Linked Slack user %s → Databricks user %s", slack_user_id, db_email or "(unknown)")

        if on_auth_complete:
            def _run_callback():
                try:
                    on_auth_complete(slack_user_id)
                except Exception:
                    logger.exception("on_auth_complete callback failed for %s", slack_user_id)
            Thread(target=_run_callback, daemon=True).start()

        return (
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h2>Connected to Databricks!</h2>"
            f"<p>Linked as <b>{db_email or 'your Databricks account'}</b>.</p>"
            "<p>You can close this tab and return to Slack.</p>"
            "</body></html>"
        )

    return app


def _expire_stale(pending: dict):
    cutoff = time.time() - 600
    for s in [k for k, v in pending.items() if v["created"] < cutoff]:
        pending.pop(s, None)


def _fetch_user_email(access_token: str) -> str:
    try:
        resp = _session.get(
            f"{Config.DATABRICKS_HOST}/oidc/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("email", "")
    except Exception:
        logger.warning("Could not fetch user email", exc_info=True)
    return ""


def refresh_user_token(token_store: TokenStore, slack_user_id: str) -> str | None:
    """Return a valid access token, refreshing if needed. None triggers re-auth."""
    info = token_store.get(slack_user_id)
    if not info:
        return None

    if not info.is_access_expired:
        return info.access_token

    if not info.refresh_token:
        logger.info("No refresh token for %s — needs re-auth", slack_user_id)
        token_store.remove(slack_user_id)
        return None

    try:
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": info.refresh_token,
            "client_id": Config.OAUTH_CLIENT_ID,
            "client_secret": Config.OAUTH_CLIENT_SECRET,
        }

        resp = _session.post(
            f"{Config.DATABRICKS_HOST}/oidc/v1/token",
            data=refresh_data,
            timeout=30,
        )

        if resp.status_code != 200:
            logger.error("Token refresh failed for %s: %s", slack_user_id, resp.text)
            token_store.remove(slack_user_id)
            return None

        tokens = resp.json()
        info.access_token = tokens["access_token"]
        info.expires_at = time.time() + tokens.get("expires_in", 3600)
        if "refresh_token" in tokens:
            info.refresh_token = tokens["refresh_token"]
        token_store.put(slack_user_id, info)
        return info.access_token

    except Exception:
        logger.error("Token refresh error for %s", slack_user_id, exc_info=True)
        return None
