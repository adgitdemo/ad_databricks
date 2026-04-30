"""
Databricks Genie API client with:
  - Rate-limit-aware retry with exponential backoff + jitter
  - OBO → Service Principal fallback
  - Client caching per (space_id, token_hash)
"""
import hashlib
import logging
import os
import random
import time
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceExhausted, TooManyRequests

from config import Config

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}
RATE_LIMIT_ERRORS = (ResourceExhausted, TooManyRequests)
RATE_LIMIT_MESSAGES = ["rate limit", "too many requests", "429", "quota", "throttl"]

# Client cache: key → (timestamp, GenieClient)
_client_cache: dict[str, tuple[float, "GenieClient"]] = {}
CLIENT_CACHE_TTL = 300


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, RATE_LIMIT_ERRORS):
        return True
    msg = str(exc).lower()
    return any(phrase in msg for phrase in RATE_LIMIT_MESSAGES)


def _retry_delay(attempt: int) -> float:
    delay = min(Config.RETRY_BASE_DELAY * (2 ** attempt), Config.RETRY_MAX_DELAY)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def get_workspace_client(user_token: str = "") -> WorkspaceClient:
    from databricks.sdk.config import Config as SdkConfig
    if user_token:
        cfg = SdkConfig(host=Config.DATABRICKS_HOST, token=user_token, auth_type="pat")
        return WorkspaceClient(config=cfg)
    host = Config.DATABRICKS_HOST
    token = os.environ.get("DATABRICKS_TOKEN", "")
    if token:
        cfg = SdkConfig(host=host, token=token, auth_type="pat")
        return WorkspaceClient(config=cfg)
    return WorkspaceClient()


def get_user_name(client: WorkspaceClient) -> str:
    try:
        me = client.current_user.me()
        return me.user_name or me.display_name or "unknown"
    except Exception:
        return "unknown"


def get_genie_client(space_id: str, *, host: str = "", user_token: str = "") -> "GenieClient":
    """Return a GenieClient, reusing cached instances within the TTL window."""
    token_hash = hashlib.sha256(user_token.encode()).hexdigest()[:12] if user_token else "sp"
    key = f"{space_id}:{token_hash}"
    now = time.time()
    cached = _client_cache.get(key)
    if cached and (now - cached[0]) < CLIENT_CACHE_TTL:
        return cached[1]
    client = GenieClient(space_id, host=host, user_token=user_token)
    _client_cache[key] = (now, client)
    if len(_client_cache) > 100:
        stale = [k for k, (ts, _) in _client_cache.items() if now - ts > CLIENT_CACHE_TTL]
        for k in stale:
            _client_cache.pop(k, None)
    return client


class GenieClient:
    """
    Thin wrapper around the Genie conversational API.

    Supports two auth modes:
      - OBO:  pass ``user_token`` — API calls run as that Databricks user.
      - SP:   omit ``user_token`` — SDK auto-detects the service principal.
    """

    def __init__(self, space_id: str, *, host: str = "", user_token: str = ""):
        self.space_id = space_id
        self._ws = get_workspace_client(user_token)
        self._api = self._ws.api_client
        self._host = self._ws.config.host.rstrip("/")

    def _genie_api(self, method: str, path: str, body: dict | None = None):
        return self._api.do(method, path, body=body)

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------

    def send_message(
        self, content: str, conversation_id: str | None = None
    ) -> dict | None:
        if conversation_id:
            path = (
                f"/api/2.0/genie/spaces/{self.space_id}"
                f"/conversations/{conversation_id}/messages"
            )
        else:
            path = f"/api/2.0/genie/spaces/{self.space_id}/start-conversation"

        result = self._genie_api("POST", path, {"content": content})
        if not result:
            return None

        msg = result.get("message", result)
        return {
            "message_id": msg.get("id") or result.get("message_id"),
            "conversation_id": msg.get("conversation_id") or result.get("conversation_id") or conversation_id,
            "status": msg.get("status") or result.get("status"),
        }

    def poll_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        timeout: float = 0,
    ) -> dict | None:
        if timeout <= 0:
            timeout = Config.POLL_TIMEOUT
        path = (
            f"/api/2.0/genie/spaces/{self.space_id}"
            f"/conversations/{conversation_id}/messages/{message_id}"
        )
        start = time.time()
        interval = Config.POLL_INTERVAL
        while True:
            result = self._genie_api("GET", path)
            if not result:
                return None
            msg = result.get("message", result)
            status = msg.get("status")
            logger.info("Poll: conversation=%s message=%s status=%s", conversation_id, message_id, status)

            if status in TERMINAL_STATUSES:
                return msg
            elapsed = time.time() - start
            if elapsed > timeout:
                logger.error("Polling timed out after %.1fs", elapsed)
                return None
            time.sleep(min(interval, max(0, timeout - elapsed)))
            interval = min(interval * 1.3, 5.0)
        return None

    def get_query_result(
        self, conversation_id: str, message_id: str, attachment_id: str
    ) -> dict | None:
        """Fetch query result via the attachment-based query-result endpoint."""
        try:
            return self._genie_api(
                "GET",
                f"/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}"
                f"/messages/{message_id}/attachments/{attachment_id}/query-result",
            )
        except Exception:
            logger.error("Failed to fetch query result", exc_info=True)
            return None

    def get_statement_result(self, statement_id: str) -> dict | None:
        try:
            return self._genie_api("GET", f"/api/2.0/sql/statements/{statement_id}")
        except Exception:
            logger.error("Failed to fetch statement result", exc_info=True)
            return None

    def send_feedback(
        self,
        conversation_id: str,
        message_id: str,
        rating: str,
        text: str = "",
    ) -> bool:
        path = (
            f"/api/2.0/genie/spaces/{self.space_id}"
            f"/conversations/{conversation_id}/messages/{message_id}/feedback"
        )
        payload: dict = {"rating": rating.upper()}
        if text:
            payload["feedback_text"] = text
        try:
            self._genie_api("POST", path, payload)
            return True
        except Exception:
            logger.error("Feedback submission failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # High-level ask with retry + rate-limit handling
    # ------------------------------------------------------------------

    def ask_with_retry(
        self, question: str, conversation_id: str | None = None
    ) -> dict:
        """Send a question with exponential backoff on rate limits."""
        last_exc = None
        for attempt in range(Config.MAX_RETRIES + 1):
            try:
                sent = self.send_message(question, conversation_id)
                if not sent:
                    return {"success": False, "error": "Failed to send message"}

                conv_id = sent["conversation_id"]
                msg_id = sent["message_id"]

                completed = self.poll_message(conv_id, msg_id)
                if not completed:
                    return {
                        "success": False,
                        "conversation_id": conv_id,
                        "error": "Timeout or poll failure",
                    }

                status = completed.get("status")
                if status != "COMPLETED":
                    err = completed.get("error", {}).get("message", status)
                    return {"success": False, "conversation_id": conv_id, "error": err}

                response_text, sql_query, columns, rows, suggested_questions = self._format_response(completed, conv_id)

                return {
                    "success": True,
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "response": response_text,
                    "sql_query": sql_query,
                    "columns": columns,
                    "data": rows,
                    "suggested_questions": suggested_questions,
                    "attachments": completed.get("attachments", []),
                }

            except Exception as e:
                last_exc = e
                if _is_rate_limit_error(e) and attempt < Config.MAX_RETRIES:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "Rate limited (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, Config.MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Genie ask failed after %d attempts", attempt + 1, exc_info=True)
                    return {"success": False, "error": str(last_exc)}

        return {"success": False, "error": str(last_exc)}

    def _format_response(
        self, message: dict, conversation_id: str
    ) -> tuple[str, Optional[str], list[str], list[list], list[str]]:
        """Extract description, SQL, columns, rows, and suggested questions from a completed message."""
        message_id = message.get("id", "")
        attachments = message.get("attachments") or []
        description_parts: list[str] = []
        sql_query: str | None = None
        columns: list[str] = []
        rows: list[list] = []
        suggested_questions: list[str] = []

        for att in attachments:
            attachment_id = att.get("attachment_id") or att.get("id", "")

            if att.get("text"):
                content = att["text"].get("content", "")
                if content:
                    description_parts.append(content)

            if att.get("suggested_questions"):
                suggested_questions = att["suggested_questions"].get("questions", [])

            if att.get("query"):
                query_info = att["query"]
                sql_query = query_info.get("query", "")

                if attachment_id:
                    result = self.get_query_result(conversation_id, message_id, attachment_id)
                    if result:
                        stmt_response = result.get("statement_response", {})
                        result_data = stmt_response.get("result", {})
                        manifest = stmt_response.get("manifest", {})
                        columns = [
                            col.get("name", f"col_{i}")
                            for i, col in enumerate(manifest.get("schema", {}).get("columns", []))
                        ]
                        rows = result_data.get("data_array", [])

                if not columns and not rows:
                    statement_id = query_info.get("statement_id")
                    if statement_id:
                        stmt = self.get_statement_result(statement_id)
                        if stmt:
                            columns = [
                                col.get("name", f"col_{i}")
                                for i, col in enumerate(
                                    stmt.get("manifest", {}).get("schema", {}).get("columns", [])
                                )
                            ]
                            rows = stmt.get("result", {}).get("data_array", [])
                            desc = query_info.get("description", "")
                            if desc and desc not in description_parts:
                                description_parts.append(desc)

        text = "\n\n".join(description_parts) or message.get("content", "No response generated")
        return text, sql_query, columns, rows, suggested_questions
