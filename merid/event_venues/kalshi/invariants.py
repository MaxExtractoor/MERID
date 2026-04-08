"""Kalshi URL invariants — single source of truth for valid API endpoints.

Validates REST and WebSocket URLs at startup to prevent silent misconfiguration.

Live production endpoints (all markets, including crypto/FX):
    REST : https://api.elections.kalshi.com/trade-api/v2
    WS   : wss://api.elections.kalshi.com/trade-api/ws/v2

Demo/sandbox endpoints:
    REST : https://demo-api.kalshi.co/trade-api/v2
    WS   : wss://demo-ws.kalshi.co/v2

Note: ``api.elections.kalshi.com`` is Kalshi's **production** trade API for all
markets (crypto, FX, elections, etc.).  It is NOT elections-only.  Despite the
hostname, this is the endpoint documented by Kalshi for live real-money trading.

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

#: Live production REST base URL — Kalshi's official trade API for all markets.
#: Despite the hostname containing "elections", this is used for ALL Kalshi
#: markets including crypto and FX.
LIVE_REST_BASE: str = "https://api.elections.kalshi.com/trade-api/v2"

#: Live production WebSocket URL — matches the live REST host.
LIVE_WS_BASE: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"

#: Demo/sandbox REST base URL.
DEMO_REST_BASE: str = "https://demo-api.kalshi.co/trade-api/v2"

#: Demo/sandbox WebSocket URL.
DEMO_WS_BASE: str = "wss://demo-ws.kalshi.co/v2"

# ── Pattern sets for validation ───────────────────────────────────────────

#: URL prefixes accepted as valid Kalshi REST endpoints.
#: Includes api.elections.kalshi.com (Kalshi's production trade API).
VALID_KALSHI_API_PATTERNS: tuple = (
    "https://api.elections.kalshi.com",
    "https://demo-api.kalshi.co",
)

#: URL prefixes accepted as valid Kalshi WebSocket endpoints.
VALID_KALSHI_WS_PATTERNS: tuple = (
    "wss://api.elections.kalshi.com",
    "wss://demo-ws.kalshi.co",
)


# ── Validation helpers ────────────────────────────────────────────────────

def assert_valid_rest_url(url: str) -> None:
    """Raise ValueError if *url* is not a recognised Kalshi REST endpoint.

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

    if not any(url.startswith(p) for p in VALID_KALSHI_API_PATTERNS):
        raise ValueError(
            f"Kalshi REST URL {url!r} does not match any recognised endpoint. "
            f"Valid prefixes: {', '.join(VALID_KALSHI_API_PATTERNS)}. "
            f"For live trading use {LIVE_REST_BASE!r}. "
            f"For demo/sandbox use {DEMO_REST_BASE!r}."
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

    if not any(url.startswith(p) for p in VALID_KALSHI_WS_PATTERNS):
        raise ValueError(
            f"Kalshi WS URL {url!r} does not match any recognised endpoint. "
            f"Valid prefixes: {', '.join(VALID_KALSHI_WS_PATTERNS)}. "
            f"For live trading use {LIVE_WS_BASE!r}. "
            f"For demo/sandbox use {DEMO_WS_BASE!r}."
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
        ValueError: If the REST or WS URL is not a recognised Kalshi endpoint.
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
