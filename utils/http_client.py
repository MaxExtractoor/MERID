"""MeridHttpClient — Unified async HTTP client for all internal service calls.

Wraps ``httpx.AsyncClient`` with:
- Configurable exponential-backoff retry (3 attempts by default)
- Standard auth header injection from settings
- Consistent error mapping to ``MeridHttpError``
- Per-request timeout enforcement
- Structured logging for every call

Usage::

    from utils.http_client import get_http_client, MeridHttpError

    client = get_http_client()
    try:
        data = await client.get("/api/v1/kalshi/health")
    except MeridHttpError as e:
        logger.error("API call failed: %s (status=%s)", e, e.status_code)

    # Or as a context manager for one-off calls:
    async with MeridHttpClient(base_url="https://trading.kalshi.com") as c:
        resp = await c.get("/trade-api/v2/exchange/status")
"""

from __future__ import annotations

import asyncio
import ssl
import threading
import time
from typing import Any, Dict, Optional

import certifi
import httpx

from utils.logger import get_logger

logger = get_logger("utils.http_client")

# ── Shared SSL Context (BUG-EL4 fix) ─────────────────────────────────────
# Creating SSL contexts is expensive (~3s on Windows). Cache once and reuse.
_ssl_context_lock = threading.Lock()
_ssl_context_cache: Optional[ssl.SSLContext] = None


def get_shared_ssl_context() -> ssl.SSLContext:
    """Return a cached SSL context to avoid repeated CA bundle parsing.

    Creating an SSL context parses the entire CA certificate bundle synchronously,
    which takes ~3 seconds on Windows. This singleton caches the context for reuse
    across all HTTP clients.
    """
    global _ssl_context_cache
    if _ssl_context_cache is None:
        with _ssl_context_lock:
            if _ssl_context_cache is None:
                _ssl_context_cache = ssl.create_default_context(cafile=certifi.where())
    return _ssl_context_cache


# ── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_S: float = 10.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BACKOFF_BASE_S: float = 0.5   # 0.5s, 1.0s, 2.0s
DEFAULT_RETRY_STATUS_CODES: frozenset = frozenset({429, 500, 502, 503, 504})


# ── Exception ─────────────────────────────────────────────────────────────

class MeridHttpError(Exception):
    """Raised when an HTTP call fails after all retries."""

    def __init__(self, message: str, status_code: Optional[int] = None, url: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url

    def __repr__(self) -> str:
        return f"MeridHttpError(status={self.status_code}, url={self.url!r})"


# ── Client ────────────────────────────────────────────────────────────────

class MeridHttpClient:
    """Async HTTP client with retry, auth injection, and structured logging.

    Args:
        base_url: Base URL prepended to all relative paths.
        timeout_s: Per-request timeout in seconds.
        max_retries: Number of retry attempts (0 = no retry).
        backoff_base_s: Base seconds for exponential backoff between retries.
        auth_token: Bearer token to inject into Authorization header.
                    If None, no Authorization header is added.
        extra_headers: Additional headers merged into every request.
    """

    def __init__(
        self,
        base_url: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        auth_token: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_s)
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._auth_token = auth_token
        self._extra_headers = extra_headers or {}
        self._client: Optional[httpx.AsyncClient] = None

    # ── Context manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> "MeridHttpClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=self._build_headers(),
            verify=get_shared_ssl_context(),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public request methods ────────────────────────────────────────────

    async def get(self, path: str, **kwargs: Any) -> Any:
        """GET request — returns parsed JSON body."""
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        """POST request with JSON body — returns parsed JSON response."""
        return await self._request("POST", path, json=json, **kwargs)

    async def put(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return await self._request("PUT", path, json=json, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # ── Core retry loop ───────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}" if self._base_url else path
        attempt = 0
        last_exc: Optional[Exception] = None

        while attempt <= self._max_retries:
            t0 = time.monotonic()
            try:
                client = self._get_or_create_client()
                response = await client.request(
                    method,
                    url,
                    headers=self._build_headers(),
                    **kwargs,
                )
                elapsed_ms = (time.monotonic() - t0) * 1000

                if response.status_code in DEFAULT_RETRY_STATUS_CODES and attempt < self._max_retries:
                    logger.warning(
                        "[http] %s %s → %d (attempt %d/%d, %.0fms) — retrying",
                        method, url, response.status_code, attempt + 1, self._max_retries + 1, elapsed_ms,
                    )
                    await self._backoff(attempt)
                    attempt += 1
                    continue

                if response.is_error:
                    raise MeridHttpError(
                        f"{method} {url} failed with status {response.status_code}",
                        status_code=response.status_code,
                        url=url,
                    )

                logger.debug("[http] %s %s → %d (%.0fms)", method, url, response.status_code, elapsed_ms)
                try:
                    return response.json()
                except Exception:
                    return response.text

            except MeridHttpError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning(
                        "[http] %s %s network error (attempt %d/%d, %.0fms): %s — retrying",
                        method, url, attempt + 1, self._max_retries + 1, elapsed_ms, exc,
                    )
                    await self._backoff(attempt)
                    attempt += 1
                    continue
                break
            except Exception as exc:
                last_exc = exc
                break

        raise MeridHttpError(
            f"{method} {url} failed after {attempt} attempt(s): {last_exc}",
            url=url,
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_or_create_client(self) -> httpx.AsyncClient:
        """Return the shared client, or create a one-shot client if not in context manager."""
        if self._client is not None:
            return self._client
        # One-shot client (not using context manager) - still use shared SSL context
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=self._build_headers(),
            verify=get_shared_ssl_context(),
        )

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
            headers["X-Session-ID"] = self._auth_token
        headers.update(self._extra_headers)
        return headers

    async def _backoff(self, attempt: int) -> None:
        wait = self._backoff_base * (2 ** attempt)
        await asyncio.sleep(wait)

    def set_auth_token(self, token: str) -> None:
        """Update the bearer token used for subsequent requests."""
        self._auth_token = token


# ── Singleton ─────────────────────────────────────────────────────────────

_client_instance: Optional[MeridHttpClient] = None


def get_http_client(
    *,
    base_url: str = "",
    auth_token: Optional[str] = None,
) -> MeridHttpClient:
    """Get or create the singleton MeridHttpClient.

    For service-to-service calls within MERID, use the singleton.
    For calls to external APIs (Kalshi, etc.), use ``MeridHttpClient`` as a
    context manager so the connection pool is properly closed.
    """
    global _client_instance
    if _client_instance is None:
        from config.network import backend_url
        _client_instance = MeridHttpClient(
            base_url=base_url or backend_url(),
            auth_token=auth_token,
        )
    return _client_instance
