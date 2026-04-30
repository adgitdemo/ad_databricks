"""
Entry point for the Multi-Genie Slack Bot.

Runs two servers concurrently:
  1. Flask  – handles OAuth callback & health check (HTTP on PORT)
  2. Slack  – socket-mode handler for real-time Slack events
"""
import logging
import sys
from threading import Thread

from config import Config
from oauth_server import create_flask_app
from slack_bot import SlackGenieBot
from token_store import TokenStore


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, "INFO"),
        format="%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("app.log"),
        ],
    )


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        Config.validate()
        logger.info("Configuration validated")
    except ValueError as exc:
        logger.error("Config error: %s", exc)
        sys.exit(1)

    # --- shared token store ---
    token_store = TokenStore(
        path=Config.TOKEN_STORE_PATH,
        encryption_key=Config.TOKEN_ENCRYPTION_KEY,
    )

    # --- Slack bot ---
    bot = SlackGenieBot(token_store)

    # --- Flask (OAuth + health) — passes bot callback for post-auth question replay ---
    flask_app = create_flask_app(token_store, on_auth_complete=bot.on_auth_complete)

    def run_flask():
        logger.info("Flask server starting on port %d", Config.PORT)
        flask_app.run(host="0.0.0.0", port=Config.PORT, debug=False)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # --- Start socket-mode handler (blocks main thread) ---
    logger.info("Starting Slack bot...")
    logger.info(
        "Genie spaces: %s", ", ".join(Config.get_space_aliases()) or "(none)"
    )
    logger.info("Auth mode: %s", Config.AUTH_MODE)

    bot.start()


if __name__ == "__main__":
    main()
