"""Kalshi URL invariants — single source of truth for valid API endpoints.

Validates REST and WebSocket URLs at startup to prevent silent misconfiguration
(e.g. using the elections-only host for crypto/FX trading).

Live production endpoints (crypto/FX):
    REST : https://api.kalshi.com/trade-api/v2
    WS   : wss://api.kalshi.com/trade-api/ws/v2

Demo/sandbox endpoints:
    REST : https://demo-api.kalshi.co/trade-api/v2
    WS   : wss://demo-ws.kalshi.co/v2

PROHIBITED for production crypto/FX:
    https://api.elections.kalshi.com  — elections-only, NOT valid for crypto/FX

Usage::

    from merid.event_venues.kalshi.invariants import (
        assert_valid_rest_url,
        assert_valid_ws_url,
        validate_config_env_match,
    )

    # Raises ValueError with actionable message if invalid
    assert_valid_rest_url(config.rest_api_url)
    assert_valid_ws_url(config.ws_api_url)

    # Checks that KALSHI_ENV=live does not use a demo URL (and vice versa)
    validate_config_env_match(config, kalshi_env="live")
"""

from __future__ import annotations

from typing import Optional
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.invariants")

# ── Canonical endpoints ───────────────────────────────────────────────────

#: Live production REST base URL (crypto/FX trading on api.kalshi.com).
LIVE_REST_BASE: str = "https://api.kalshi.com/trade-api/v2"

#: Live production WebSocket URL.
LIVE_WS_BASE: str = "wss://api.kalshi.com/trade-api/ws/v2"

#: Demo/sandbox REST base URL.
DEMO_REST_BASE: str = "https://demo-api.kalshi.co/trade-api/v2"

#: Demo/sandbox WebSocket URL.
DEMO_WS_BASE: str = "wss://demo-ws.kalshi.co/v2"

# ── Pattern sets for validation ───────────────────────────────────────────

#: URL prefixes accepted as valid Kalshi REST endpoints.
#: The elections host is intentionally absent — it is not valid for crypto/FX.
VALID_KALSHI_API_PATTERNS: tuple = (
    "https://api.kalshi.com",
    "https://demo-api.kalshi.co",
)

#: URL prefixes accepted as valid Kalshi WebSocket endpoints.
VALID_KALSHI_WS_PATTERNS: tuple = (
    "wss://api.kalshi.com",
    "wss://demo-ws.kalshi.co",
)

#: Hosts that are explicitly prohibited for production crypto/FX trading.
_ELECTIONS_HOSTS: tuple = (
    "api.elections.kalshi.com",
    "elections.kalshi.com",
)


# ── Validation helpers ────────────────────────────────────────────────────

def _contains_elections_host(url: str) -> bool:
    """Return True if *url* routes to the elections-only host."""
    url_lower = url.lower()
    return any(host in url_lower for host in _ELECTIONS_HOSTS)


def assert_valid_rest_url(url: str) -> None:
    """Raise ValueError if *url* is not a recognised Kalshi REST endpoint.

    Specifically rejects the elections-only host (``api.elections.kalshi.com``)
    which does not serve crypto/FX markets and causes catalog degradation.

    Args:
        url: The REST base URL to validate.

    Raises:
        ValueError: With an actionable message recommending the correct host.
    """
    if not url:
        raise ValueError(
            "Kalshi REST URL is empty. "
            f"Set KALSHI_API_HOST to {LIVE_REST_BASE!r} for live trading "
            f"or {DEMO_REST_BASE!r} for demo/sandbox."
        )

    if _contains_elections_host(url):
        raise ValueError(
            f"Kalshi REST URL {url!r} uses the elections-only host "
            f"(api.elections.kalshi.com) which does NOT serve crypto/FX markets. "
            f"For live crypto/FX trading use {LIVE_REST_BASE!r}. "
            f"For demo/sandbox use {DEMO_REST_BASE!r}."
        )

    if not any(url.startswith(p) for p in VALID_KALSHI_API_PATTERNS):
        raise ValueError(
            f"Kalshi REST URL {url!r} does not match any recognised endpoint. "
            f"Valid prefixes: {', '.join(VALID_KALSHI_API_PATTERNS)}. "
            f"For live trading use {LIVE_REST_BASE!r}."
        )


def assert_valid_ws_url(url: str) -> None:
    """Raise ValueError if *url* is not a recognised Kalshi WebSocket endpoint.

    Args:
        url: The WebSocket URL to validate.

    Raises:
        ValueError: With an actionable message recommending the correct host.
    """
    if not url:
        raise ValueError(
            "Kalshi WebSocket URL is empty. "
            f"Set the WS URL to {LIVE_WS_BASE!r} for live trading "
            f"or {DEMO_WS_BASE!r} for demo/sandbox."
        )

    if _contains_elections_host(url):
        raise ValueError(
            f"Kalshi WS URL {url!r} uses the elections-only host "
            f"(api.elections.kalshi.com) which does NOT serve crypto/FX markets. "
            f"For live crypto/FX trading use {LIVE_WS_BASE!r}. "
            f"For demo/sandbox use {DEMO_WS_BASE!r}."
        )

    if not any(url.startswith(p) for p in VALID_KALSHI_WS_PATTERNS):
        raise ValueError(
            f"Kalshi WS URL {url!r} does not match any recognised endpoint. "
            f"Valid prefixes: {', '.join(VALID_KALSHI_WS_PATTERNS)}. "
            f"For live trading use {LIVE_WS_BASE!r}."
        )


def validate_config_env_match(config: object, kalshi_env: Optional[str] = None) -> list[str]:
    """Check that *config* URL choices are consistent with *kalshi_env*.

    Does not raise — returns a list of human-readable issue strings so callers
    can decide how loudly to surface them (warning vs. fatal).

    Args:
        config: A ``KalshiConfig``-like object with ``base_url`` and ``ws_url``
                properties, plus a ``use_demo`` bool.
        kalshi_env: Value of the ``KALSHI_ENV`` environment variable
                    (``"live"`` or ``"demo"``/``"paper"``/``"sandbox"``).

    Returns:
        List of issue strings (empty = all OK).
    """
    import os
    env = (kalshi_env or os.getenv("KALSHI_ENV", "")).lower().strip()
    issues: list[str] = []

    base_url = getattr(config, "base_url", None) or getattr(config, "rest_api_url", None) or ""
    ws_url = getattr(config, "ws_url", None) or getattr(config, "ws_api_url", None) or ""
    use_demo = getattr(config, "use_demo", False)

    if env == "live":
        if use_demo:
            issues.append(
                "KALSHI_ENV=live but config.use_demo=True — "
                "live trading requires use_demo=False."
            )
        if base_url and "demo" in base_url.lower():
            issues.append(
                f"KALSHI_ENV=live but REST URL {base_url!r} looks like a demo endpoint. "
                f"Expected {LIVE_REST_BASE!r}."
            )
        if ws_url and "demo" in ws_url.lower():
            issues.append(
                f"KALSHI_ENV=live but WS URL {ws_url!r} looks like a demo endpoint. "
                f"Expected {LIVE_WS_BASE!r}."
            )
        if base_url and _contains_elections_host(base_url):
            issues.append(
                f"KALSHI_ENV=live but REST URL {base_url!r} uses the elections-only host. "
                f"Use {LIVE_REST_BASE!r} for live crypto/FX trading."
            )
        if ws_url and _contains_elections_host(ws_url):
            issues.append(
                f"KALSHI_ENV=live but WS URL {ws_url!r} uses the elections-only host. "
                f"Use {LIVE_WS_BASE!r} for live crypto/FX trading."
            )

    elif env in ("demo", "paper", "sandbox"):
        if not use_demo:
            issues.append(
                f"KALSHI_ENV={env} but config.use_demo=False — "
                "demo/paper mode should use use_demo=True."
            )

    return issues


def validate_config_or_raise(config: object, kalshi_env: Optional[str] = None) -> None:
    """Validate *config* URLs and env consistency; log warnings and raise on hard errors.

    This is the **startup gate** — call it during application boot so that
    misconfiguration fails fast with a clear error rather than silently
    degrading into ``LIMITED (reduce-only)`` mode.

    Args:
        config: A ``KalshiConfig``-like object.
        kalshi_env: Value of ``KALSHI_ENV`` (read from env if not provided).

    Raises:
        ValueError: If the REST or WS URL contains the elections-only host or
                    is otherwise unrecognised.
    """
    base_url = getattr(config, "base_url", None) or getattr(config, "rest_api_url", None) or ""
    ws_url = getattr(config, "ws_url", None) or getattr(config, "ws_api_url", None) or ""

    # Hard checks — raise immediately
    assert_valid_rest_url(base_url)
    assert_valid_ws_url(ws_url)

    # Soft checks — log warnings
    issues = validate_config_env_match(config, kalshi_env)
    for issue in issues:
        logger.warning("Kalshi config/env mismatch: %s", issue)
