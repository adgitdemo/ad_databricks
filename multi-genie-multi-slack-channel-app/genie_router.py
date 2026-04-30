"""
Multi-Genie space routing.

Resolution order:
  1. Slack channel → alias mapping           (from CHANNEL_GENIE_MAP)
  2. Thread continuity                        (reuse same space within a thread)
  3. AI classifier                            (optional, uses Foundation Model API)
  4. Interactive picker sent to Slack          (fallback)
"""
import logging
import re
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


class RouteResult:
    __slots__ = ("alias", "space_id", "question", "method")

    def __init__(self, alias: str, space_id: str, question: str, method: str):
        self.alias = alias
        self.space_id = space_id
        self.question = question
        self.method = method


class GenieRouter:
    def __init__(self):
        # thread_ts → alias (persists space choice within a Slack thread)
        self._thread_alias: dict[str, str] = {}

    def route(
        self,
        text: str,
        channel_id: str,
        thread_ts: str,
        *,
        user_token: str = "",
    ) -> Optional[RouteResult]:
        """
        Try to resolve a Genie space for the message.
        Returns RouteResult if resolved, None if a picker should be shown.
        """
        question = text

        # 1. Channel mapping
        alias = Config.CHANNEL_GENIE_MAP.get(channel_id)
        if alias:
            sid = Config.get_space_id(alias)
            if sid:
                self._thread_alias[thread_ts] = alias
                return RouteResult(alias, sid, question, "channel")

        # 2. Thread continuity
        alias = self._thread_alias.get(thread_ts)
        if alias:
            sid = Config.get_space_id(alias)
            if sid:
                return RouteResult(alias, sid, question, "thread")

        # 3. AI classifier (if enabled and >1 space)
        if Config.AI_ROUTER_ENABLED and len(Config.GENIE_SPACES) > 1:
            alias = self._ai_classify(question, user_token)
            if alias:
                sid = Config.get_space_id(alias)
                if sid:
                    self._thread_alias[thread_ts] = alias
                    return RouteResult(alias, sid, question, "ai")

        # 4. Single-space shortcut — skip picker if there's only one
        if len(Config.GENIE_SPACES) == 1:
            alias = Config.DEFAULT_GENIE_ALIAS
            sid = Config.get_space_id(alias)
            if sid:
                self._thread_alias[thread_ts] = alias
                return RouteResult(alias, sid, question, "default")

        # 5. Default alias fallback (for DMs)
        if Config.DEFAULT_GENIE_ALIAS:
            alias = Config.DEFAULT_GENIE_ALIAS
            sid = Config.get_space_id(alias)
            if sid:
                self._thread_alias[thread_ts] = alias
                return RouteResult(alias, sid, question, "default")

        return None

    def set_thread_alias(self, thread_ts: str, alias: str):
        self._thread_alias[thread_ts] = alias

    def _ai_classify(self, question: str, user_token: str = "") -> Optional[str]:
        try:
            from databricks.sdk import WorkspaceClient

            if user_token:
                ws = WorkspaceClient(host=Config.DATABRICKS_HOST, token=user_token)
            else:
                ws = WorkspaceClient()

            descs = Config.get_space_descriptions()
            space_list = "\n".join(
                f"- {alias}: {desc}" for alias, desc in descs.items()
            )

            prompt = (
                f"You are a routing classifier. Given these data domains:\n"
                f"{space_list}\n\n"
                f"Which domain best matches this question: \"{question}\"\n"
                f"Reply with ONLY the domain alias (one word). "
                f"If unsure, reply \"unknown\"."
            )

            resp = ws.serving_endpoints.query(
                name=Config.AI_ROUTER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )

            alias = resp.choices[0].message.content.strip().lower()
            if alias in Config.GENIE_SPACES:
                logger.info("AI router classified → %s", alias)
                return alias

            logger.info("AI router returned unknown alias: %s", alias)

        except Exception:
            logger.warning("AI router failed, falling back", exc_info=True)

        return None


def build_space_picker_blocks() -> list[dict]:
    """Slack Block Kit blocks for an interactive Genie space picker."""
    options = [
        {
            "text": {"type": "plain_text", "text": desc, "emoji": True},
            "value": alias,
        }
        for alias, desc in Config.get_space_descriptions().items()
    ]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Which data domain are you asking about?",
            },
            "accessory": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "Select a domain"},
                "action_id": "select_genie_space",
                "options": options,
            },
        },
    ]
