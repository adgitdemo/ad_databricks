"""
MCP Server – Metric View Semantic Search
=========================================
Hosted as a Databricks App. Exposes MCP tools that let AI agents
discover Unity Catalog metric views, inspect their measures/dimensions,
and generate example SQL — powered by in-memory TF-IDF vectorisation
for fast similarity search (no external model downloads).

Auth: The /mcp route bypasses app-level auth and validates Bearer tokens
itself, so MCP OAuth clients (Claude Code, ChatGPT, Genie Code, etc.)
can authenticate directly.
"""

import os
import json
import logging
import threading
import time
import yaml
import numpy as np
from typing import Optional, List, Dict

import httpx
from fastmcp import FastMCP
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.sql import StatementState
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("metric-view-mcp")

# ── Service-principal config (auto-injected in Databricks Apps) ────
_sp_cfg = Config()

# ── MCP server ─────────────────────────────────────────────────────
mcp = FastMCP("metric-view-search")

# ── Configuration ──────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def _load_config() -> dict:
    """Load config.yaml for scope and auto-refresh settings."""
    if not os.path.exists(_CONFIG_PATH):
        logger.warning(f"Config file not found at {_CONFIG_PATH}; using defaults (scan all catalogs).")
        return {}
    with open(_CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f) or {}
    logger.info(f"Loaded config: scope={cfg.get('scope', 'ALL')}, "
                f"auto_refresh={cfg.get('auto_refresh', {})}")
    return cfg


_config: dict = _load_config()


def _get_scoped_catalogs_schemas() -> Optional[Dict[str, List[str]]]:
    """Return {catalog: [schema, ...]} from config, or None to scan all."""
    scope = _config.get("scope")
    if not scope:
        return None
    result: Dict[str, List[str]] = {}
    for entry in scope:
        cat = entry.get("catalog", "").strip()
        schemas = entry.get("schemas", [])
        if cat:
            result[cat] = [s.strip() for s in schemas if s and s.strip()]
    return result if result else None


# ── Global state ───────────────────────────────────────────────────
_metric_views_cache: dict = {}
_tfidf_matrix = None
_vectorizer: Optional[TfidfVectorizer] = None
_view_names: list = []
_view_texts: list = []
_refresh_thread: Optional[threading.Thread] = None
_refresh_stop_event = threading.Event()


# ── Token-auth ASGI middleware ─────────────────────────────────────

class TokenAuthMiddleware:
    """Pure ASGI middleware that validates bearer tokens on /mcp routes.

    Accepts tokens from (in priority order):
      1. Authorization: Bearer <token>  (MCP OAuth spec – Claude Code, ChatGPT, etc.)
      2. X-Forwarded-Access-Token       (Databricks App proxy – Genie Code)

    Validates by calling /api/2.0/preview/scim/v2/Me on the workspace.
    CORS preflight (OPTIONS) requests are passed through without auth.
    """

    def __init__(self, app):
        self.app = app
        self.host = _sp_cfg.host.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            return await self.app(scope, receive, send)

        method = scope.get("method", "")
        if method == "OPTIONS":
            return await self.app(scope, receive, send)

        token = None
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                auth_val = value.decode()
                if auth_val.lower().startswith("bearer "):
                    token = auth_val[7:]
                    break
            elif key == b"x-forwarded-access-token" and token is None:
                token = value.decode()

        if not token:
            return await self._send_error(
                scope, receive, send,
                status=401,
                body={"error": "Missing authentication token. Provide Authorization: Bearer <token> or X-Forwarded-Access-Token."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.host}/api/2.0/preview/scim/v2/Me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0,
                )
            if resp.status_code != 200:
                logger.warning(f"Token validation failed: HTTP {resp.status_code}")
                return await self._send_error(
                    scope, receive, send,
                    status=401,
                    body={"error": "Invalid or expired token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user_info = resp.json()
            logger.info(f"Authenticated user: {user_info.get('userName', 'unknown')}")
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return await self._send_error(
                scope, receive, send,
                status=503,
                body={"error": "Authentication service unavailable"},
            )

        return await self.app(scope, receive, send)

    @staticmethod
    async def _send_error(scope, receive, send, *, status, body, headers=None):
        from starlette.responses import JSONResponse
        extra = headers or {}
        response = JSONResponse(body, status_code=status, headers=extra)
        await response(scope, receive, send)


# ── Helpers ────────────────────────────────────────────────────────

def _ws() -> WorkspaceClient:
    return WorkspaceClient()


def _sql(statement: str) -> list:
    """Execute SQL using the app's service principal."""
    w = _ws()
    wh = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
    if not wh:
        raise ValueError("Set DATABRICKS_WAREHOUSE_ID in app.yaml env.")
    resp = w.statement_execution.execute_statement(
        warehouse_id=wh, statement=statement, wait_timeout="50s"
    )
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL error: {getattr(resp.status, 'error', resp.status)}")
    return resp.result.data_array if resp.result and resp.result.data_array else []


def _search_text(mv: dict) -> str:
    parts = [f"metric view {mv['name']}", mv.get("comment", "")]
    for m in mv.get("measures", []):
        parts.append(f"measure {m['name']} {m.get('comment', '')}")
    for d in mv.get("dimensions", []):
        parts.append(f"dimension {d['name']} {d.get('comment', '')}")
    return " ".join(filter(None, parts))


# ── Discovery ─────────────────────────────────────────────────────

def discover_metric_views() -> int:
    global _metric_views_cache, _tfidf_matrix, _vectorizer, _view_names, _view_texts
    logger.info("Scanning catalogs for metric views …")
    views: dict = {}

    try:
        cats = [r[0] for r in _sql("SHOW CATALOGS")]
    except Exception as e:
        logger.error(f"Cannot list catalogs: {e}")
        return 0

    for cat in cats:
        if cat in ("system", "__databricks_internal"):
            continue
        try:
            rows = _sql(
                f"SELECT table_catalog, table_schema, table_name, comment "
                f"FROM `{cat}`.information_schema.tables "
                f"WHERE table_type = 'METRIC_VIEW'"
            )
        except Exception:
            continue

        for row in rows:
            c, s, n, cmt = row[0], row[1], row[2], row[3]
            fqn = f"{c}.{s}.{n}"
            try:
                desc = _sql(f"DESCRIBE TABLE EXTENDED `{c}`.`{s}`.`{n}` AS JSON")
                if not desc:
                    continue
                j = json.loads(desc[0][0])
                measures, dims = [], []
                for col in j.get("columns", []):
                    info = {
                        "name": col.get("name"),
                        "type": col.get("type", {}).get("name", "unknown"),
                        "comment": col.get("comment", ""),
                    }
                    (measures if col.get("is_measure") else dims).append(info)

                vt = j.get("view_text", "")
                views[fqn] = {
                    "catalog": c, "schema": s, "name": n, "fqn": fqn,
                    "comment": j.get("comment", cmt or ""),
                    "measures": measures, "dimensions": dims,
                    "yaml_definition": yaml.safe_load(vt) if vt else None,
                    "view_text": vt,
                    "owner": j.get("owner", ""),
                }
                logger.info(f"  ✓ {fqn}")
            except Exception as exc:
                logger.warning(f"  ✗ {fqn}: {exc}")

    _metric_views_cache = views

    if views:
        _view_names = list(views.keys())
        _view_texts = [_search_text(views[f]) for f in _view_names]
        _vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), stop_words="english", sublinear_tf=True
        )
        _tfidf_matrix = _vectorizer.fit_transform(_view_texts)
        logger.info(f"Indexed {len(_view_names)} metric view(s) (TF-IDF, in-memory).")
    else:
        _tfidf_matrix, _vectorizer, _view_names, _view_texts = None, None, [], []
        logger.warning("No metric views found.")

    return len(views)


# ── MCP Tools ─────────────────────────────────────────────────────

@mcp.tool()
def search_metric_views(query: str, top_k: int = 5) -> str:
    """Semantic search over metric views by name, description, measures, or dimensions.

    Args:
        query: Natural-language search string (e.g. "revenue by customer").
        top_k: Maximum number of results to return (default 5).
    """
    if not _metric_views_cache or _tfidf_matrix is None or _vectorizer is None:
        return json.dumps({"error": "Cache empty – call refresh_metric_views first."})

    q_vec = _vectorizer.transform([query])
    scores = cosine_similarity(q_vec, _tfidf_matrix).flatten()
    top = np.argsort(scores)[::-1][:top_k]

    results = []
    for i in top:
        if scores[i] <= 0:
            continue
        mv = _metric_views_cache[_view_names[i]]
        results.append({
            "metric_view": mv["fqn"],
            "similarity_score": round(float(scores[i]), 4),
            "comment": mv.get("comment", ""),
            "measures": [m["name"] for m in mv["measures"]],
            "dimensions": [d["name"] for d in mv["dimensions"]],
            "owner": mv.get("owner", ""),
        })
    return json.dumps({"query": query, "results": results}, indent=2)


@mcp.tool()
def get_metric_view_details(metric_view_fqn: str) -> str:
    """Return full definition of a metric view – measures, dimensions, types, comments, and YAML.

    Args:
        metric_view_fqn: Fully qualified name (catalog.schema.view).
    """
    mv = _metric_views_cache.get(metric_view_fqn)
    if not mv:
        return json.dumps({"error": f"'{metric_view_fqn}' not in cache."})
    return json.dumps({
        "metric_view": mv["fqn"],
        "comment": mv.get("comment", ""),
        "owner": mv.get("owner", ""),
        "measures": mv["measures"],
        "dimensions": mv["dimensions"],
        "yaml_definition": mv.get("view_text", ""),
    }, indent=2)


@mcp.tool()
def generate_sql_example(
    metric_view_fqn: str,
    measures: Optional[List[str]] = None,
    dimensions: Optional[List[str]] = None,
) -> str:
    """Generate correct metric view SQL using MEASURE() and GROUP BY ALL syntax.

    Metric view query rules:
      - Measures MUST be wrapped in MEASURE() e.g. MEASURE(`revenue`) AS `revenue`
      - Always use GROUP BY ALL (never list columns)
      - Never use SELECT *
      - Backtick all column names

    Args:
        metric_view_fqn: Fully qualified name (catalog.schema.view).
        measures: Measure names to SELECT (default: all).
        dimensions: Dimension names to GROUP BY (default: first two).
    """
    mv = _metric_views_cache.get(metric_view_fqn)
    if not mv:
        return json.dumps({"error": f"'{metric_view_fqn}' not in cache."})

    all_m = [m["name"] for m in mv["measures"]]
    all_d = [d["name"] for d in mv["dimensions"]]
    sel_m = [m for m in (measures or all_m) if m in all_m] or all_m
    sel_d = [d for d in (dimensions or all_d[:2]) if d in all_d] or all_d[:2]

    fqn_sql = f"`{mv['catalog']}`.`{mv['schema']}`.`{mv['name']}`"

    # Dimensions are plain columns; measures use MEASURE()
    dim_lines = [f"  `{d}`" for d in sel_d]
    mea_lines = [f"  MEASURE(`{m}`) AS `{m}`" for m in sel_m]

    # Grouped query: dimensions + MEASURE()-wrapped measures + GROUP BY ALL
    select_parts = ",\n".join(dim_lines + mea_lines)
    grouped = (
        f"-- Grouped by {', '.join(sel_d)}\n"
        f"SELECT\n{select_parts}\n"
        f"FROM {fqn_sql}\n"
        f"GROUP BY ALL\n"
        f"ORDER BY {', '.join(f'`{d}`' for d in sel_d)}\n"
        f"LIMIT 100;"
    )

    # Overall aggregates: only MEASURE()-wrapped measures + GROUP BY ALL
    mea_select = ",\n".join(f"  MEASURE(`{m}`) AS `{m}`" for m in sel_m)
    simple = (
        f"-- Overall aggregates (no dimensions)\n"
        f"SELECT\n{mea_select}\n"
        f"FROM {fqn_sql}\n"
        f"GROUP BY ALL;"
    )

    # Filtered example with WHERE clause
    filtered = (
        f"-- With a WHERE filter (edit the condition as needed)\n"
        f"SELECT\n{select_parts}\n"
        f"FROM {fqn_sql}\n"
        f"WHERE `{sel_d[0]}` IS NOT NULL\n"
        f"GROUP BY ALL\n"
        f"ORDER BY {', '.join(f'`{d}`' for d in sel_d)}\n"
        f"LIMIT 100;"
    ) if sel_d else None

    result = {
        "metric_view": metric_view_fqn,
        "selected_measures": sel_m,
        "selected_dimensions": sel_d,
        "grouped_sql": grouped,
        "simple_sql": simple,
        "available_measures": all_m,
        "available_dimensions": all_d,
        "syntax_rules": [
            "Measures MUST be wrapped in MEASURE() – e.g. MEASURE(`revenue`) AS `revenue`",
            "Always use GROUP BY ALL – never list specific columns in GROUP BY",
            "Never use SELECT * on metric views",
            "Backtick all dimension and measure names",
            "Use HAVING with aliases to filter by measure values",
            "For ratios, use MEASURE(`a`) / MEASURE(`b`) – never AVG(MEASURE(...))",
        ],
    }
    if filtered:
        result["filtered_sql"] = filtered

    return json.dumps(result, indent=2)


@mcp.tool()
def refresh_metric_views() -> str:
    """Re-scan catalogs and rebuild the metric-view search index."""
    try:
        n = discover_metric_views()
        return json.dumps({
            "status": "success",
            "metric_views_found": n,
            "metric_views": list(_metric_views_cache.keys()),
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


# ── Auto-Refresh Background Thread ─────────────────────────────────

def _auto_refresh_worker():
    """Background thread that periodically re-scans for new metric views."""
    auto_cfg = _config.get("auto_refresh", {})
    interval_min = auto_cfg.get("interval_minutes", 60)
    interval_sec = interval_min * 60
    logger.info(f"Auto-refresh thread started (interval: every {interval_min} minutes).")

    while not _refresh_stop_event.is_set():
        # Sleep for the configured interval (or until stop is signaled)
        _refresh_stop_event.wait(timeout=interval_sec)
        if _refresh_stop_event.is_set():
            break

        logger.info("Auto-refresh: checking for new metric views …")
        try:
            prev_keys = set(_metric_views_cache.keys())
            discover_metric_views()
            new_keys = set(_metric_views_cache.keys()) - prev_keys
            removed_keys = prev_keys - set(_metric_views_cache.keys())
            if new_keys:
                logger.info(f"Auto-refresh: added {len(new_keys)} new metric view(s): {new_keys}")
            if removed_keys:
                logger.info(f"Auto-refresh: removed {len(removed_keys)} metric view(s): {removed_keys}")
            if not new_keys and not removed_keys:
                logger.info(f"Auto-refresh complete: no changes (total: {len(_metric_views_cache)}).")
        except Exception as e:
            logger.error(f"Auto-refresh failed: {e}")


def _start_auto_refresh():
    """Start the background auto-refresh thread if enabled in config."""
    global _refresh_thread
    auto_cfg = _config.get("auto_refresh", {})
    if not auto_cfg.get("enabled", False):
        logger.info("Auto-refresh is disabled in config.yaml.")
        return
    _refresh_thread = threading.Thread(
        target=_auto_refresh_worker, daemon=True, name="metric-view-auto-refresh"
    )
    _refresh_thread.start()


# ── Startup ───────────────────────────────────────────────────────
try:
    discover_metric_views()
except Exception as e:
    logger.error(f"Initial discovery failed (use refresh_metric_views): {e}")

# Start background auto-refresh
_start_auto_refresh()

if __name__ == "__main__":
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    # Build stateless MCP ASGI app at /mcp
    app = mcp.http_app(path="/mcp", stateless_http=True)

    # CORS – allow browser-based agents (Genie Code, ChatGPT web, etc.)
    workspace_host = os.environ.get("DATABRICKS_HOST", _sp_cfg.host or "")
    allowed_origins = [workspace_host] if workspace_host else []
    allowed_origins.append("*")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Token-auth middleware – validates Bearer tokens on /mcp,
    # bypassing app-level auth so MCP OAuth works for all clients
    app.add_middleware(TokenAuthMiddleware)

    uvicorn.run(app, host="0.0.0.0", port=8000)
