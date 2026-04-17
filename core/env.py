from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class Capabilities:
    """Environment-backed configuration with memoized lookups."""

    @staticmethod
    @lru_cache(maxsize=None)
    def _get(key: str, default: str | None = None) -> str | None:
        return os.getenv(key, default)

    @property
    def supabase_url(self) -> str | None:
        return self._get("SUPABASE_URL")

    @property
    def supabase_key(self) -> str | None:
        return self._get("SUPABASE_KEY")

    @property
    def neo4j_uri(self) -> str | None:
        return self._get("NEO4J_URI")

    @property
    def neo4j_user(self) -> str | None:
        return self._get("NEO4J_USER")

    @property
    def neo4j_password(self) -> str | None:
        return self._get("NEO4J_PASSWORD")

    @property
    def telegram_token(self) -> str | None:
        return self._get("TELEGRAM_TOKEN")

    @property
    def telegram_chat_id(self) -> str | None:
        return self._get("TELEGRAM_CHAT_ID")

    @property
    def my_email(self) -> str | None:
        return self._get("MY_EMAIL")

    @property
    def app_password(self) -> str | None:
        return self._get("APP_PASSWORD")

    @property
    def receiver_email(self) -> str | None:
        return self._get("RECEIVER_EMAIL")

    @property
    def messari_api_key(self) -> str | None:
        return self._get("MESSARI_API_KEY")

    @property
    def alpha_vantage_api_key(self) -> str | None:
        return self._get("ALPHA_VANTAGE_API_KEY")

    @property
    def x_api_key(self) -> str | None:
        return self._get("X_API_KEY")

    @property
    def x_api_secret(self) -> str | None:
        return self._get("X_API_SECRET")

    @property
    def x_access_token(self) -> str | None:
        return self._get("X_ACCESS_TOKEN")

    @property
    def x_access_token_secret(self) -> str | None:
        return self._get("X_ACCESS_TOKEN_SECRET")

    @property
    def x_bearer_token(self) -> str | None:
        return self._get("X_BEARER_TOKEN")

    @property
    def x_bot_service_token(self) -> str | None:
        return self._get("X_BOT_SERVICE_TOKEN")

    @property
    def moat_service_token(self) -> str | None:
        return self._get("MOAT_SERVICE_TOKEN", self.x_bot_service_token)

    @property
    def telegram_bot_service_token(self) -> str | None:
        return self._get("TELEGRAM_BOT_SERVICE_TOKEN")

    @property
    def merid_api_base_url(self) -> str:
        return self._get("MERID_API_BASE_URL", "http://localhost:8000/api/v1")

    @property
    def x_bot_account_id(self) -> str | None:
        return self._get("X_BOT_ACCOUNT_ID")

    @property
    def searxng_url(self) -> str | None:
        return self._get("SEARXNG_URL", "http://localhost:8080/search")

    @property
    def librex_url(self) -> str | None:
        return self._get("LIBREX_URL", "http://localhost:8081")


capabilities = Capabilities()

