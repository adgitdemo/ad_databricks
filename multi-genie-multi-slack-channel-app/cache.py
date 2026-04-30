"""
Semantic cache backed by Databricks Vector Search with Delta-aware invalidation.

Flow:
  1. Before calling Genie, search the VS index for a semantically similar question.
  2. If a hit is found (score >= threshold), validate that the underlying Delta tables
     haven't changed since the cache entry was written.
  3. On cache miss or stale data, call Genie normally and write the result to cache.
  4. After writing, trigger a VS index sync so the new entry is searchable.
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from databricks.sdk import WorkspaceClient

from config import Config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Table dependency tracking
# ------------------------------------------------------------------

def extract_table_names(sql_query: str) -> list[str]:
    """Extract fully-qualified table names from a SQL query."""
    if not sql_query:
        return []
    pattern = r'`?(\w+)`?\.`?(\w+)`?\.`?(\w+)`?'
    matches = re.findall(pattern, sql_query)
    tables = list({f"{c}.{s}.{t}" for c, s, t in matches})
    return [t for t in tables if t not in (Config.CACHE_TABLE, Config.AUDIT_TABLE)]


def get_table_version(client: WorkspaceClient, table_name: str) -> Optional[str]:
    """Get the current Delta version of a table."""
    try:
        stmt = client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=f"DESCRIBE HISTORY {table_name} LIMIT 1",
        )
        rows = stmt.result.data_array if stmt.result else []
        if rows and len(rows) > 0:
            return str(rows[0][0])
        return None
    except Exception as e:
        logger.warning("Failed to get version for %s: %s", table_name, e)
        return None


def get_metric_view_refresh_version(client: WorkspaceClient, table_name: str) -> Optional[str]:
    """Get the last refresh timestamp of a metric view as its 'version'."""
    try:
        stmt = client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=f"DESCRIBE DETAIL {table_name}",
        )
        rows = stmt.result.data_array if stmt.result else []
        cols = [c.name for c in stmt.manifest.schema.columns] if stmt.manifest else []
        if rows and cols:
            detail = dict(zip(cols, rows[0]))
            last_modified = detail.get("lastModified") or detail.get("createdAt") or ""
            if last_modified:
                return str(last_modified)
        return None
    except Exception:
        pass
    try:
        parts = table_name.split(".")
        if len(parts) == 3:
            stmt = client.statement_execution.execute_statement(
                warehouse_id=Config.CACHE_WAREHOUSE_ID,
                statement=(
                    f"SELECT last_altered FROM {parts[0]}.information_schema.tables "
                    f"WHERE table_catalog = '{parts[0]}' AND table_schema = '{parts[1]}' "
                    f"AND table_name = '{parts[2]}'"
                ),
            )
            rows = stmt.result.data_array if stmt.result else []
            if rows and rows[0][0]:
                return str(rows[0][0])
    except Exception as e:
        logger.warning("Failed to get metric view refresh state for %s: %s", table_name, e)
    return None


def resolve_view_dependencies(client: WorkspaceClient, table_name: str) -> tuple[list[str], str]:
    """Resolve a table/view/metric-view to its underlying base tables.

    Returns (list_of_tables_to_monitor, object_type).
    """
    try:
        stmt = client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=f"DESCRIBE TABLE EXTENDED {table_name} AS JSON",
        )
        rows = stmt.result.data_array if stmt.result else []
        if not rows or not rows[0][0]:
            return [table_name], "TABLE"

        info = json.loads(rows[0][0])
        obj_type = (info.get("type") or "").upper()
        view_text = info.get("view_text") or ""
        properties = info.get("properties") or {}

        if obj_type in ("MANAGED", "EXTERNAL", "TABLE", ""):
            if "streaming" in obj_type.lower():
                return [table_name], "STREAMING_TABLE"
            return [table_name], "TABLE"

        if obj_type == "METRIC_VIEW":
            source_table = properties.get("metric_view.from.name", "")
            if not source_table:
                match = re.search(r'^source:\s*(\S+)', view_text, re.MULTILINE)
                if match:
                    source_table = match.group(1)
            if source_table:
                logger.info("Metric view %s -> source table: %s", table_name, source_table)
                return [source_table], "METRIC_VIEW"
            return [table_name], "METRIC_VIEW"

        if obj_type == "MATERIALIZED_VIEW":
            base_tables = extract_table_names(view_text) if view_text else []
            all_tables = list(set([table_name] + base_tables))
            return all_tables, "MATERIALIZED_VIEW"

        if "VIEW" in obj_type:
            base_tables = extract_table_names(view_text) if view_text else []
            if base_tables:
                return base_tables, "VIEW"

        return [table_name], "TABLE"
    except Exception as e:
        logger.warning("Failed to resolve %s: %s", table_name, e)
        return [table_name], "TABLE"


def get_table_or_view_version(client: WorkspaceClient, table_name: str, obj_type: str) -> Optional[str]:
    if obj_type == "METRIC_VIEW":
        return get_metric_view_refresh_version(client, table_name)
    return get_table_version(client, table_name)


def get_dependency_versions(client: WorkspaceClient, sql_query: str) -> tuple[list[str], dict[str, str]]:
    """Extract all table dependencies and get their current versions."""
    raw_tables = extract_table_names(sql_query)
    all_tables = []
    metric_views: set[str] = set()
    for t in raw_tables:
        resolved, obj_type = resolve_view_dependencies(client, t)
        all_tables.extend(resolved)
        if obj_type == "METRIC_VIEW":
            metric_views.update(resolved)
    all_tables = list(set(all_tables))

    versions: dict[str, str] = {}
    for table in all_tables:
        obj = "METRIC_VIEW" if table in metric_views else "TABLE"
        version = get_table_or_view_version(client, table, obj)
        if version is not None:
            versions[table] = version
    return all_tables, versions


def validate_cache_entry(client: WorkspaceClient, cached: dict) -> bool:
    """Validate a cache entry by checking if any dependent tables have changed."""
    stored_versions_str = cached.get("table_versions", "")
    stored_deps_str = cached.get("table_dependencies", "")

    if not stored_versions_str or not stored_deps_str:
        return False

    try:
        stored_versions = json.loads(stored_versions_str)
        stored_deps = json.loads(stored_deps_str)
    except (json.JSONDecodeError, TypeError):
        return False

    for table in stored_deps:
        current_version = get_table_version(client, table)
        stored_version = stored_versions.get(table)
        if current_version is None:
            continue
        if stored_version != current_version:
            logger.info(
                "Cache INVALIDATED: table=%s stored=%s current=%s",
                table, stored_version, current_version,
            )
            return False

    logger.info("Cache VALID: all %d dependent tables unchanged", len(stored_deps))
    return True


# ------------------------------------------------------------------
# Cache operations
# ------------------------------------------------------------------

def search_cache(question: str, client: WorkspaceClient, space_id: str = "") -> tuple[Optional[dict], float, str]:
    """Search the VS index for a similar cached question scoped to a Genie space.

    Returns (result_or_None, best_score, cache_status).
    cache_status is one of: DISABLED, NO_MATCH, BELOW_THRESHOLD, INVALIDATED, HIT, ERROR.
    """
    if not Config.CACHE_ENABLED or not Config.VS_INDEX_NAME:
        return None, 0.0, "DISABLED"
    try:
        query_body: dict = {
            "query_text": question,
            "columns": [
                "id", "question", "answer", "conversation_id", "message_id",
                "sql_query", "table_dependencies", "table_versions", "space_id",
            ],
            "num_results": 1,
        }
        if space_id:
            query_body["filters_json"] = json.dumps({"space_id": space_id})

        data = client.api_client.do(
            "POST",
            f"/api/2.0/vector-search/indexes/{Config.VS_INDEX_NAME}/query",
            body=query_body,
        )

        if not data.get("result", {}).get("data_array"):
            return None, 0.0, "NO_MATCH"

        row = data["result"]["data_array"][0]
        columns = [c["name"] for c in data["manifest"]["columns"]]
        result = dict(zip(columns, row))

        score = result.get("score", 0)
        if score < Config.CACHE_SIMILARITY_THRESHOLD:
            logger.info("Cache miss: score=%.3f < threshold=%.2f", score, Config.CACHE_SIMILARITY_THRESHOLD)
            return None, score, "BELOW_THRESHOLD"

        if not validate_cache_entry(client, result):
            logger.info("Cache hit invalidated (stale): score=%.3f", score)
            invalidate_cache_entry(client, result.get("id", ""))
            return None, score, "INVALIDATED"

        logger.info("Cache HIT: score=%.3f question='%s'", score, result.get("question", "")[:50])
        return result, score, "HIT"
    except Exception as e:
        logger.error("Cache search failed: %s | %s", e, type(e).__name__)
        return None, 0.0, "ERROR"


def write_cache(
    question: str, answer: str, sql_query: Optional[str],
    conversation_id: Optional[str], message_id: Optional[str],
    client: WorkspaceClient, space_id: str = "",
) -> None:
    """Write a Q&A pair to the cache table with dependency metadata, scoped to a Genie space."""
    if not Config.CACHE_ENABLED or not Config.CACHE_TABLE:
        return
    try:
        composite_key = f"{space_id}:{question.lower().strip()}"
        row_id = hashlib.sha256(composite_key.encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        all_deps, versions = get_dependency_versions(client, sql_query or "")

        safe_answer = answer.replace("'", "''")
        safe_question = question.replace("'", "''")
        safe_sql = (sql_query or "").replace("'", "''")
        safe_space_id = space_id.replace("'", "''")
        deps_json = json.dumps(all_deps).replace("'", "''")
        versions_json = json.dumps(versions).replace("'", "''")

        client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=(
                f"INSERT INTO {Config.CACHE_TABLE} "
                f"(id, question, answer, conversation_id, message_id, created_at, "
                f"sql_query, table_dependencies, table_versions, space_id) "
                f"VALUES ('{row_id}', '{safe_question}', '{safe_answer}', "
                f"'{conversation_id or ''}', '{message_id or ''}', '{now}', "
                f"'{safe_sql}', '{deps_json}', '{versions_json}', '{safe_space_id}')"
            ),
        )
        logger.info("Cache write: id=%s space=%s deps=%s", row_id, space_id, all_deps)
    except Exception as e:
        logger.error("Cache write failed: %s | %s", e, type(e).__name__)


def invalidate_cache_entry(client: WorkspaceClient, entry_id: str) -> None:
    """Delete a stale cache entry by ID."""
    if not Config.CACHE_TABLE:
        return
    try:
        client.statement_execution.execute_statement(
            warehouse_id=Config.CACHE_WAREHOUSE_ID,
            statement=f"DELETE FROM {Config.CACHE_TABLE} WHERE id = '{entry_id}'",
        )
        logger.info("Cache entry invalidated: id=%s", entry_id)
    except Exception as e:
        logger.error("Cache invalidation failed: %s", e)


def sync_cache_index(client: WorkspaceClient) -> None:
    """Trigger a sync of the vector search index after cache write."""
    if not Config.VS_INDEX_NAME:
        return
    try:
        client.api_client.do(
            "POST",
            f"/api/2.0/vector-search/indexes/{Config.VS_INDEX_NAME}/sync",
            body={},
        )
        logger.info("Cache index sync triggered")
    except Exception as e:
        logger.error("Cache index sync failed: %s | %s", e, type(e).__name__)
