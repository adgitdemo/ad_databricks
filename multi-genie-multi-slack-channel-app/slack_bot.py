"""
Slack bot that routes messages to multiple Databricks Genie spaces
with per-user OBO authentication, semantic caching, and audit logging.
"""
import json
import logging
import re
import time
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from audit import write_audit
from cache import search_cache, write_cache, sync_cache_index
from config import Config
from genie_client import get_genie_client, get_workspace_client, get_user_name
from genie_router import GenieRouter, RouteResult, build_space_picker_blocks
from oauth_server import refresh_user_token
from token_store import TokenStore

logger = logging.getLogger(__name__)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
MAP_TTL = 3600


class SlackGenieBot:
    def __init__(self, token_store: TokenStore):
        self.app = App(
            token=Config.SLACK_BOT_TOKEN,
            signing_secret=Config.SLACK_SIGNING_SECRET,
        )
        self.client = WebClient(token=Config.SLACK_BOT_TOKEN)
        self.token_store = token_store
        self.router = GenieRouter()

        # thread_ts → (genie conversation_id, created_at)
        self.conv_map: dict[str, tuple[str, float]] = {}
        # feedback message ts → (conv_id, msg_id, space_id, created_at)
        self.feedback_map: dict[str, tuple[str, str, str, float]] = {}
        # pending questions: thread_ts → (user, question, created_at)
        self._pending_questions: dict[str, tuple[str, str, float]] = {}
        # pending auth: slack_user_id → (question, channel, thread_ts, created_at)
        self._pending_auth: dict[str, tuple[str, str, str, float]] = {}
        # rate limiter: user_id → list of timestamps
        self._rate_limits: dict[str, list[float]] = {}

        self._register_handlers()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self):
        @self.app.event("app_mention")
        def on_mention(event, say, client):
            self._handle_message(event, say, client)

        @self.app.event("message")
        def on_message(event, say, client):
            if event.get("channel_type") == "im" or event.get("thread_ts"):
                self._handle_message(event, say, client)

        @self.app.action("select_genie_space")
        def on_space_selected(ack, body, client):
            ack()
            self._handle_space_selection(body, client)

        @self.app.action("feedback_positive")
        def on_positive(ack, body, client):
            ack()
            self._handle_feedback(body, "positive", client)

        @self.app.action("feedback_negative")
        def on_negative(ack, body, client):
            ack()
            self._handle_feedback(body, "negative", client)

        @self.app.action("auth_link")
        def on_auth_click(ack, body, client):
            ack()

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    def _handle_message(self, event: dict, say, client):
        if event.get("bot_id"):
            return

        text = self._clean(event.get("text", ""))
        user = event.get("user", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not text.strip():
            say("Please ask me a question about your data!", thread_ts=thread_ts)
            return

        self._cleanup_stale_maps()

        if not self._check_rate_limit(user):
            say(
                ":hourglass: You're sending messages too fast. Please wait a moment and try again.",
                thread_ts=thread_ts,
            )
            return

        # --- OBO auth gate ---
        user_token = self._resolve_user_token(user)
        if user_token is None and Config.AUTH_MODE == "obo":
            self._pending_auth[user] = (text, channel, thread_ts, time.time())
            self._send_auth_prompt(channel, thread_ts, user, say)
            return

        # --- Route to Genie space ---
        route = self.router.route(text, channel, thread_ts, user_token=user_token or "")
        if not route:
            self._pending_questions[thread_ts] = (user, text, time.time())
            say(
                blocks=build_space_picker_blocks(),
                text="Which data domain are you asking about?",
                thread_ts=thread_ts,
            )
            return

        self._ask_genie(route, user, user_token, channel, thread_ts, say, client)

    # ------------------------------------------------------------------
    # Space selection callback
    # ------------------------------------------------------------------

    def _handle_space_selection(self, body: dict, client):
        action = body.get("actions", [{}])[0]
        alias = action.get("selected_option", {}).get("value", "")
        channel = body.get("channel", {}).get("id", "")
        message = body.get("message", {})
        thread_ts = message.get("thread_ts") or message.get("ts")
        user = body.get("user", {}).get("id", "")

        space_id = Config.get_space_id(alias)
        if not space_id:
            return

        self.router.set_thread_alias(thread_ts, alias)

        client.chat_update(
            channel=channel,
            ts=message.get("ts"),
            text=f"Using *{alias}* data domain.",
            blocks=[],
        )

        pending = self._pending_questions.pop(thread_ts, None)
        if not pending:
            return
        pending_user, question = pending[0], pending[1]

        user_token = self._resolve_user_token(pending_user)
        route = RouteResult(alias, space_id, question, "picker")

        def say(text="", blocks=None, thread_ts=thread_ts):
            kwargs: dict[str, Any] = {"channel": channel, "thread_ts": thread_ts}
            if blocks:
                kwargs["blocks"] = blocks
                kwargs["text"] = text or ""
            else:
                kwargs["text"] = text
            client.chat_postMessage(**kwargs)

        self._ask_genie(route, pending_user, user_token, channel, thread_ts, say, client)

    # ------------------------------------------------------------------
    # Genie interaction with cache + audit + SP fallback
    # ------------------------------------------------------------------

    def _ask_genie(
        self,
        route: RouteResult,
        slack_user_id: str,
        user_token: str | None,
        channel: str,
        thread_ts: str,
        say,
        client,
    ):
        start_time = time.time()
        auth_mode = "OBO" if user_token else "SP"
        sp_client = get_workspace_client()

        user_name = "unknown"
        try:
            uc = get_workspace_client(user_token) if user_token else sp_client
            user_name = get_user_name(uc)
        except Exception:
            pass

        cache_score = 0.0
        best_cache_score = 0.0
        cache_status = "SKIPPED"
        response_source = "GENIE"

        # --- Cache check (new conversations only) ---
        cached_conv = self.conv_map.get(thread_ts)
        is_followup = cached_conv is not None

        if not is_followup and Config.CACHE_ENABLED:
            cached, best_cache_score, cache_status = search_cache(route.question, sp_client, route.space_id)
            if cached:
                cache_score = best_cache_score
                response_source = "CACHE"
                latency_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "RESPONSE source=CACHE score=%.3f cache_status=%s query='%s'",
                    cache_score, cache_status, route.question[:80],
                )
                say(cached.get("answer", ""), thread_ts=thread_ts)
                say(":zap: _Served from cache_", thread_ts=thread_ts)

                write_audit(
                    sp_client, user_name, slack_user_id, auth_mode, route.question,
                    route.alias, response_source, cache_score, best_cache_score,
                    cache_status, cached.get("conversation_id"),
                    cached.get("message_id"), latency_ms,
                )
                return

        # --- Thinking indicator ---
        client.chat_postMessage(
            channel=channel,
            text=f":thinking_face: Asking *{route.alias}* Genie...",
            thread_ts=thread_ts,
        )

        # --- Try OBO first, optionally fall back to SP ---
        tokens_to_try: list[tuple[str, str | None]] = []
        if user_token:
            tokens_to_try.append(("OBO", user_token))
        if Config.SP_FALLBACK_ENABLED:
            tokens_to_try.append(("SP", None))

        conv_id = cached_conv[0] if cached_conv else None
        result = None
        actual_mode = auth_mode

        for mode, token in tokens_to_try:
            try:
                genie = get_genie_client(
                    space_id=route.space_id,
                    host=Config.DATABRICKS_HOST,
                    user_token=token or "",
                )
                result = genie.ask_with_retry(route.question, conv_id)
                if result.get("success"):
                    actual_mode = mode
                    if mode != auth_mode:
                        response_source = "GENIE_SP_FALLBACK"
                    break
                logger.warning("Genie returned error with auth=%s: %s", mode, result.get("error"))
            except Exception as e:
                logger.error("Failed with auth_mode=%s: %s", mode, e)

        latency_ms = int((time.time() - start_time) * 1000)

        if not result or not result.get("success"):
            err = (result or {}).get("error", "Unknown error")
            say(f":x: {err}", thread_ts=thread_ts)
            write_audit(
                sp_client, user_name, slack_user_id, auth_mode, route.question,
                route.alias, "ERROR", cache_score, best_cache_score,
                cache_status, None, None, latency_ms, str(err)[:500],
            )
            return

        result_conv_id = result.get("conversation_id")
        result_msg_id = result.get("message_id")

        if result_conv_id:
            self.conv_map[thread_ts] = (result_conv_id, time.time())

        # --- Main response ---
        response_text = result.get("response", "")
        say(response_text or ":white_check_mark: Query executed successfully", thread_ts=thread_ts)

        # --- Query result table ---
        columns = result.get("columns", [])
        rows = result.get("data", [])
        if columns and rows:
            self._send_table(channel, thread_ts, columns, rows, client)

        # --- Suggested follow-ups ---
        suggestions = result.get("suggested_questions", [])
        if suggestions:
            text_lines = "*:bulb: Suggested follow-up questions:*\n"
            for i, q in enumerate(suggestions, 1):
                text_lines += f"{i}. {q}\n"
            client.chat_postMessage(channel=channel, text=text_lines, thread_ts=thread_ts)

        # --- Feedback buttons ---
        if result_conv_id and result_msg_id:
            fb = self._send_feedback_buttons(channel, thread_ts, client)
            if fb:
                self.feedback_map[fb["ts"]] = (result_conv_id, result_msg_id, route.space_id, time.time())

        logger.info(
            "RESPONSE source=%s auth=%s rows=%d latency=%dms",
            response_source, actual_mode, len(rows), latency_ms,
        )

        # --- Write to cache (new conversations only) ---
        if not is_followup and Config.CACHE_ENABLED:
            answer = response_text or json.dumps(rows)
            write_cache(
                route.question, answer, result.get("sql_query"),
                result_conv_id, result_msg_id, sp_client, route.space_id,
            )
            sync_cache_index(sp_client)

        # --- Audit ---
        write_audit(
            sp_client, user_name, slack_user_id, auth_mode, route.question,
            route.alias, response_source, cache_score, best_cache_score,
            cache_status, result_conv_id, result_msg_id, latency_ms,
        )

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def _handle_feedback(self, body: dict, rating: str, client):
        msg = body.get("message", {})
        msg_ts = msg.get("ts")
        channel = body.get("channel", {}).get("id")

        info = self.feedback_map.get(msg_ts)
        if not info:
            client.chat_update(
                channel=channel,
                ts=msg_ts,
                text=":warning: _Unable to submit feedback._",
                blocks=[],
            )
            return

        conv_id, message_id, space_id = info[0], info[1], info[2]
        user = body.get("user", {}).get("id", "")
        user_token = self._resolve_user_token(user)

        genie = get_genie_client(
            space_id=space_id,
            host=Config.DATABRICKS_HOST,
            user_token=user_token or "",
        )
        success = genie.send_feedback(conv_id, message_id, rating)

        emoji = ":+1:" if rating == "positive" else ":-1:"
        if success:
            client.chat_update(
                channel=channel, ts=msg_ts,
                text=f"{emoji} _Thanks for your feedback!_", blocks=[],
            )
        else:
            client.chat_update(
                channel=channel, ts=msg_ts,
                text=":x: _Failed to submit feedback._", blocks=[],
            )

    # ------------------------------------------------------------------
    # Auth prompt
    # ------------------------------------------------------------------

    def _send_auth_prompt(self, channel, thread_ts, user, say):
        base = Config.OAUTH_REDIRECT_URI.rsplit("/", 1)[0]
        auth_url = f"{base}/auth/link?slack_user={user}"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":lock: *Connect your Databricks account* to get started.\n"
                        "Your queries will run with your own permissions."
                    ),
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Connect Databricks"},
                    "url": auth_url,
                    "action_id": "auth_link",
                },
            },
        ]
        say(
            blocks=blocks,
            text="Please connect your Databricks account.",
            thread_ts=thread_ts,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def on_auth_complete(self, slack_user_id: str):
        """Called by oauth_server after a user successfully links their Databricks account."""
        logger.info("on_auth_complete called for user %s, pending_auth keys: %s",
                     slack_user_id, list(self._pending_auth.keys()))
        pending = self._pending_auth.pop(slack_user_id, None)
        if not pending:
            logger.info("No pending question for user %s", slack_user_id)
            return
        question, channel, thread_ts, created_at = pending

        age = time.time() - created_at
        if age > MAP_TTL:
            logger.info("Pending question expired (%.0fs old) for user %s", age, slack_user_id)
            return

        user_token = self._resolve_user_token(slack_user_id)
        if not user_token:
            logger.warning("Could not resolve token for user %s after auth", slack_user_id)
            return

        logger.info("Replaying pending question for user %s: '%s'", slack_user_id, question[:80])

        self.client.chat_postMessage(
            channel=channel,
            text=":white_check_mark: Connected! Processing your question...",
            thread_ts=thread_ts,
        )

        route = self.router.route(question, channel, thread_ts, user_token=user_token)
        if not route:
            route = RouteResult(
                Config.DEFAULT_GENIE_ALIAS,
                Config.get_space_id(Config.DEFAULT_GENIE_ALIAS) or "",
                question,
                "default",
            )

        def say(text="", blocks=None, thread_ts=thread_ts):
            kwargs: dict[str, Any] = {"channel": channel, "thread_ts": thread_ts}
            if blocks:
                kwargs["blocks"] = blocks
                kwargs["text"] = text or ""
            else:
                kwargs["text"] = text
            self.client.chat_postMessage(**kwargs)

        self._ask_genie(route, slack_user_id, user_token, channel, thread_ts, say, self.client)

    def _check_rate_limit(self, user_id: str) -> bool:
        now = time.time()
        timestamps = self._rate_limits.get(user_id, [])
        timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        if len(timestamps) >= RATE_LIMIT_MAX:
            self._rate_limits[user_id] = timestamps
            return False
        timestamps.append(now)
        self._rate_limits[user_id] = timestamps
        return True

    def _cleanup_stale_maps(self):
        now = time.time()
        for key in [k for k, v in self.conv_map.items() if now - v[1] > MAP_TTL]:
            self.conv_map.pop(key, None)
        for key in [k for k, v in self.feedback_map.items() if now - v[3] > MAP_TTL]:
            self.feedback_map.pop(key, None)
        for key in [k for k, v in self._pending_questions.items() if now - v[2] > MAP_TTL]:
            self._pending_questions.pop(key, None)
        for key in [k for k, v in self._pending_auth.items() if now - v[3] > MAP_TTL]:
            self._pending_auth.pop(key, None)

    def _resolve_user_token(self, slack_user_id: str) -> str | None:
        if Config.AUTH_MODE != "obo":
            return None
        return refresh_user_token(self.token_store, slack_user_id)

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    def _send_feedback_buttons(self, channel, thread_ts, client) -> dict | None:
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Was this response helpful?*"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":+1: Helpful", "emoji": True},
                        "action_id": "feedback_positive",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":-1: Not Helpful", "emoji": True},
                        "action_id": "feedback_negative",
                    },
                ],
            },
        ]
        try:
            return client.chat_postMessage(
                channel=channel, blocks=blocks,
                text="Was this response helpful?", thread_ts=thread_ts,
            )
        except Exception:
            logger.error("Failed to send feedback buttons", exc_info=True)
            return None

    def _send_table(self, channel, thread_ts, columns, rows, client):
        if not rows:
            return

        max_rows = 10
        col_widths = []
        for i, col in enumerate(columns):
            w = len(col)
            for row in rows[:max_rows]:
                if i < len(row):
                    w = max(w, len(str(row[i] if row[i] is not None else "")))
            col_widths.append(min(w + 2, 30))

        lines = []
        lines.append("│".join(col.center(w) for col, w in zip(columns, col_widths)))
        lines.append("┼".join("─" * w for w in col_widths))
        for row in rows[:max_rows]:
            parts = []
            for val, w in zip(row, col_widths):
                s = str(val) if val is not None else ""
                parts.append(s[:w].ljust(w))
            lines.append("│".join(parts))

        table = "\n".join(lines)
        msg = f"*Query Results:*\n```\n{table}\n```"
        if len(rows) > max_rows:
            msg += f"\n_Showing {max_rows} of {len(rows)} rows_"

        client.chat_postMessage(channel=channel, text=msg, thread_ts=thread_ts)

    def start(self):
        handler = SocketModeHandler(self.app, Config.SLACK_APP_TOKEN)
        logger.info("Slack bot starting in socket mode...")
        handler.start()
