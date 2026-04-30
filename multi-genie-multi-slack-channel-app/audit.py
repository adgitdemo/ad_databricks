"""
Audit logging — writes every query interaction to a Delta table for analytics.

Columns: id, timestamp, user_name, slack_user_id, auth_mode, query, space_alias,
         response_source, cache_score, best_cache_score, cache_status,
         conversation_id, message_id, latency_ms, error
"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from databricks.sdk import WorkspaceClient

from config import Config

logger = logging.getLogger(__name__)


def write_audit(
    client: WorkspaceClient,
    user_name: str,
    slack_user_id: str,
    auth_mode: str,
    query: str,
    space_alias: str,
    response_source: str,
    cache_score: float,
    best_cache_score: float,
    cache_status: str,
    conversation_id: Optional[str],
    message_id: Optional[str],
    latency_ms: int,
    error: Optional[str] = None,
) -> None:
    """Write an audit row. Fails silently — never blocks the main flow."""
    if not Config.AUDIT_TABLE:
        return
    try:
        row_id = hashlib.sha256(f"{query}{time.time()}".encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        safe_query = query.replace("'", "''")[:500]
        safe_error = (error or "").replace("'", "''")[:500]

        client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=(
                f"INSERT INTO {Config.AUDIT_TABLE} "
                f"(id, timestamp, user_name, slack_user_id, auth_mode, query, space_alias, "
                f"response_source, cache_score, best_cache_score, cache_status, "
                f"conversation_id, message_id, latency_ms, error) "
                f"VALUES ('{row_id}', '{now}', '{user_name}', '{slack_user_id}', '{auth_mode}', "
                f"'{safe_query}', '{space_alias}', '{response_source}', {cache_score}, "
                f"{best_cache_score}, '{cache_status}', "
                f"'{conversation_id or ''}', '{message_id or ''}', "
                f"{latency_ms}, '{safe_error}')"
            ),
        )
    except Exception as e:
        logger.error("Audit write failed: %s", e)
