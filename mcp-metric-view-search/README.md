# MCP Metric View Search

An MCP (Model Context Protocol) server hosted as a Databricks App that enables AI agents to discover, inspect, and query Unity Catalog metric views via semantic search.

## Overview

This app exposes MCP tools that let AI agents (Genie Code, Claude Code, ChatGPT, etc.) find metric views by natural-language queries, powered by in-memory TF-IDF vectorization — no external embedding model required.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  MCP Clients (Genie Code, Claude Code, ChatGPT)     │
└────────────────────────┬────────────────────────────┘
                         │ HTTP + Bearer Token
                         ▼
┌─────────────────────────────────────────────────────┐
│  Databricks App (FastMCP + Starlette/Uvicorn)       │
│  ┌───────────────┐  ┌────────────────────────────┐  │
│  │ Token Auth    │  │ CORS Middleware            │  │
│  │ Middleware    │  │ (browser-based agents)     │  │
│  └───────────────┘  └────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │ MCP Tools (search, details, SQL gen, refresh) │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │ TF-IDF Index (scikit-learn, in-memory)        │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │ Auto-Refresh Thread (configurable interval)   │  │
│  └───────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────┘
                         │ Databricks SDK
                         ▼
┌─────────────────────────────────────────────────────┐
│  Unity Catalog (Metric Views) + SQL Warehouse       │
└─────────────────────────────────────────────────────┘
```

## MCP Tools

| Tool | Description |
| --- | --- |
| `search_metric_views(query, top_k)` | Semantic search over metric view names, comments, measures, and dimensions |
| `get_metric_view_details(metric_view_fqn)` | Returns full definition: measures, dimensions, types, comments, and YAML |
| `generate_sql_example(metric_view_fqn, measures, dimensions)` | Generates correct `MEASURE()` + `GROUP BY ALL` SQL examples |
| `refresh_metric_views()` | Re-scans catalogs and rebuilds the TF-IDF search index |

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Main application — FastMCP server, auth middleware, discovery, tools |
| `app.yaml` | App launch command and environment variables |
| `config.yaml` | Catalog/schema scope and auto-refresh settings |
| `requirements.txt` | Python dependencies |

## Configuration

Edit `config.yaml` to control which catalogs/schemas are scanned and how often the index refreshes:

```yaml
# Limit scanning to specific catalogs and schemas
scope:
  - catalog: your_catalog_name
    schemas:
      - your_schema_name

# Auto-refresh settings
auto_refresh:
  enabled: true
  interval_minutes: 60
```

**Scope behavior:**
- If `scope` is defined: only the listed catalog/schema combinations are scanned
- If `scope` is empty or omitted: all accessible catalogs are scanned (original behavior)

**Auto-refresh behavior:**
- A background daemon thread runs at the configured interval
- Detects newly created or removed metric views and rebuilds the index
- Logs additions/removals for observability

## Service Principal Permissions

The app runs under its service principal (`xxxxx-mcp-metric-view-search`). Grant the following:

```sql
-- SQL Warehouse access
GRANT CAN USE ON WAREHOUSE `xxxxxxx`
  TO `xxxxx-mcp-metric-view-search`;

-- Catalog access (for SHOW CATALOGS + information_schema)
GRANT USE CATALOG ON CATALOG your_catalog_name
  TO `xxxxx-mcp-metric-view-search`;

-- Schema access (for each schema in config.yaml)
GRANT USE SCHEMA ON SCHEMA your_catalog_name.your_schema_name
  TO `xxxxx-mcp-metric-view-search`;

GRANT SELECT ON SCHEMA your_catalog_name.your_schema_name
  TO `xxxxx-mcp-metric-view-search`;
```

### Permission breakdown

| Operation in code | Permission required |
| --- | --- |
| `SHOW CATALOGS` | `USE CATALOG` |
| `SELECT FROM information_schema.tables` | `USE CATALOG` |
| `DESCRIBE TABLE EXTENDED ... AS JSON` | `USE SCHEMA` + `SELECT` on metric view |
| `statement_execution.execute_statement()` | `CAN USE` on SQL Warehouse |

## Authentication

The `/mcp` endpoint bypasses Databricks app-level auth and validates tokens directly:

1. **Authorization: Bearer \<token\>** — standard MCP OAuth (Claude Code, ChatGPT)
2. **X-Forwarded-Access-Token** — Databricks App proxy (Genie Code)

Tokens are validated against `/api/2.0/preview/scim/v2/Me` on the workspace.

