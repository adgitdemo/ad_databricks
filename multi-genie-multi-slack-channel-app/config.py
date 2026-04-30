"""
Configuration for Multi-Genie Slack Bot with OBO authentication.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- Slack ---
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

    # --- Databricks ---
    # In Databricks Apps the auto-injected DATABRICKS_HOST is just the hostname
    # (no scheme). Ensure it always has https://.
    _raw_host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
    DATABRICKS_HOST = _raw_host if _raw_host.startswith("http") else f"https://{_raw_host}" if _raw_host else ""
    DATABRICKS_CLIENT_ID = os.getenv("DATABRICKS_CLIENT_ID")
    DATABRICKS_CLIENT_SECRET = os.getenv("DATABRICKS_CLIENT_SECRET")

    # --- OAuth (for OBO user linking) ---
    # OAUTH_CLIENT_ID is the app's OAuth application ID (different from SP client ID).
    # Falls back to DATABRICKS_CLIENT_ID if not set separately.
    OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID") or os.getenv("DATABRICKS_CLIENT_ID")
    OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET") or os.getenv("DATABRICKS_CLIENT_SECRET")
    OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "")
    OAUTH_SCOPES = os.getenv(
        "OAUTH_SCOPES", "dashboards.genie sql offline_access"
    )

    # --- Multi-Genie spaces ---
    # JSON map: {"alias": {"space_id": "...", "description": "..."}}
    GENIE_SPACES: dict = json.loads(os.getenv("GENIE_SPACES", "{}"))
    # JSON map: {"slack_channel_id": "genie_alias"}
    CHANNEL_GENIE_MAP: dict = json.loads(os.getenv("CHANNEL_GENIE_MAP", "{}"))
    DEFAULT_GENIE_ALIAS = os.getenv("DEFAULT_GENIE_ALIAS", "")

    # --- Token storage ---
    TOKEN_STORE_PATH = os.getenv("TOKEN_STORE_PATH", ".tokens.enc")
    TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

    # --- AI router (optional) ---
    AI_ROUTER_ENABLED = os.getenv("AI_ROUTER_ENABLED", "false").lower() == "true"
    AI_ROUTER_MODEL = os.getenv("AI_ROUTER_MODEL", "databricks-meta-llama-3-1-8b-instruct")

    # --- Retry ---
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
    RETRY_BASE_DELAY = float(os.getenv("BASE_DELAY", "2.0"))
    RETRY_MAX_DELAY = float(os.getenv("MAX_DELAY", "60.0"))

    # --- Polling ---
    POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2.0"))
    POLL_TIMEOUT = float(os.getenv("POLL_TIMEOUT", "120.0"))

    # --- Semantic cache (Vector Search + Delta table) ---
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "false").lower() == "true"
    VS_INDEX_NAME = os.getenv("VS_INDEX_NAME", "")
    CACHE_TABLE = os.getenv("CACHE_TABLE", "")
    CACHE_SIMILARITY_THRESHOLD = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.85"))
    CACHE_WAREHOUSE_ID = os.getenv("CACHE_WAREHOUSE_ID", "")

    # --- Audit ---
    AUDIT_TABLE = os.getenv("AUDIT_TABLE", "")

    # --- App ---
    PORT = int(os.getenv("PORT", "3000"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # --- Auth mode ---
    # "obo" = per-user OAuth tokens, "service_principal" = shared SP (fallback)
    AUTH_MODE = os.getenv("AUTH_MODE", "obo")
    SP_FALLBACK_ENABLED = os.getenv("SP_FALLBACK_ENABLED", "true").lower() == "true"

    @classmethod
    def validate(cls):
        missing = []
        for var in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"):
            if not getattr(cls, var):
                missing.append(var)

        if not cls.DATABRICKS_HOST:
            missing.append("DATABRICKS_HOST")

        if cls.AUTH_MODE == "obo":
            for var in ("OAUTH_CLIENT_ID", "OAUTH_REDIRECT_URI"):
                if not getattr(cls, var):
                    missing.append(var)

        if not cls.GENIE_SPACES:
            missing.append("GENIE_SPACES (need at least one Genie space)")

        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

        if not cls.DEFAULT_GENIE_ALIAS and cls.GENIE_SPACES:
            cls.DEFAULT_GENIE_ALIAS = next(iter(cls.GENIE_SPACES))

        return True

    @classmethod
    def get_space_id(cls, alias: str) -> str | None:
        space = cls.GENIE_SPACES.get(alias)
        return space["space_id"] if space else None

    @classmethod
    def get_space_aliases(cls) -> list[str]:
        return list(cls.GENIE_SPACES.keys())

    @classmethod
    def get_space_descriptions(cls) -> dict[str, str]:
        return {
            alias: info.get("description", alias)
            for alias, info in cls.GENIE_SPACES.items()
        }
