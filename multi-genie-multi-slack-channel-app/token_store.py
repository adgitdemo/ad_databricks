"""
Encrypted token storage for Slack-user → Databricks OAuth credential mapping.

Production note: replace with a Delta table or Databricks Secrets scope.
This local implementation uses Fernet symmetric encryption on a JSON file.
"""
import json
import logging
import os
import time
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class TokenInfo:
    __slots__ = ("access_token", "refresh_token", "expires_at", "db_email")

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        db_email: str = "",
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.db_email = db_email

    @property
    def is_access_expired(self) -> bool:
        return time.time() >= self.expires_at - 60

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "db_email": self.db_email,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TokenInfo":
        return cls(
            access_token=d["access_token"],
            refresh_token=d["refresh_token"],
            expires_at=d["expires_at"],
            db_email=d.get("db_email", ""),
        )


class TokenStore:
    """Fernet-encrypted JSON file store for user OAuth tokens."""

    def __init__(self, path: str, encryption_key: str = ""):
        self._path = path
        self._fernet = self._init_fernet(encryption_key)
        self._cache: dict[str, TokenInfo] = {}
        self._load()

    @staticmethod
    def _init_fernet(encryption_key: str) -> Fernet:
        if encryption_key:
            try:
                return Fernet(encryption_key.encode())
            except Exception:
                logger.warning(
                    "Invalid TOKEN_ENCRYPTION_KEY — generating ephemeral key. "
                    "Tokens will NOT survive restarts."
                )
        else:
            logger.warning(
                "No TOKEN_ENCRYPTION_KEY set — generated ephemeral key. "
                "Tokens will NOT survive restarts."
            )
        return Fernet(Fernet.generate_key())

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "rb") as f:
                data = json.loads(self._fernet.decrypt(f.read()))
            self._cache = {
                uid: TokenInfo.from_dict(tok) for uid, tok in data.items()
            }
            logger.info("Loaded %d linked users from token store", len(self._cache))
        except Exception:
            logger.warning("Could not load token store — starting fresh", exc_info=True)

    def _save(self):
        data = {uid: tok.to_dict() for uid, tok in self._cache.items()}
        with open(self._path, "wb") as f:
            f.write(self._fernet.encrypt(json.dumps(data).encode()))

    def get(self, slack_user_id: str) -> Optional[TokenInfo]:
        return self._cache.get(slack_user_id)

    def put(self, slack_user_id: str, token_info: TokenInfo):
        self._cache[slack_user_id] = token_info
        self._save()

    def remove(self, slack_user_id: str):
        self._cache.pop(slack_user_id, None)
        self._save()

    def is_linked(self, slack_user_id: str) -> bool:
        return slack_user_id in self._cache
