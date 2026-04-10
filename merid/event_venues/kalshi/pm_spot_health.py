"""
PM Spot Health — per-asset Coinbase USD feed health for Kalshi prediction markets.

Operator story
--------------
For each of the five PM assets (BTC, ETH, SOL, XRP, DOGE) MERID maintains a
dedicated Coinbase REST ticker loop (see ``data.live_price_feed`` — the
``_coinbase_ticker_loop`` / ``start_pm_coinbase_streaming`` methods).  This
module sits on top of that infrastructure and translates raw tick timestamps
into actionable health statuses used by the PM hard gate.

Status codes (``PmSpotStatus``)
--------------------------------
``ok``
    Last tick is within ``MERID_PM_MAX_SPOT_AGE_SECONDS`` (default 90 s).
    PM trading is allowed for this asset.
``pm_max_age_exceeded``
    Feed is alive (last tick < ``MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS`` = 120 s)
    but the tick is older than the PM gate threshold.  Trades are blocked; no
    Coinbase outage — likely a transient slow poll or restart.
``live_price_feed_unhealthy``
    No tick has ever been recorded, or the last tick is older than
    ``MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS``.  Probable Coinbase issue or
    misconfiguration; investigate logs for consecutive-failure messages.
``warming_up``
    System just started (within ``MERID_PM_WARMUP_GRACE_SECONDS`` = 30 s) and
    this asset has not yet received its first tick.  Not a fault condition.

PM hard gate
------------
``pm_spot_hard_gate_open()`` returns True only when **all five** PM assets have
status ``ok``.  Call this before entering any PM trade order.

Symbol-key convention
---------------------
All public functions in this module use **bare uppercase** asset keys
("BTC", "ETH", …) matching ``data.live_price_feed.KALSHI_ASSETS``.  Do NOT
pass "/USD", "/USDT", or "BTC-USD" variants here.

How to verify PM spot health
-----------------------------
1. Check the structured log lines tagged ``[PM_SPOT_HEALTH]`` emitted by
   ``log_pm_spot_health()``.
2. Call ``get_pm_spot_health_all()`` programmatically — e.g. from a health
   endpoint or the REPL.
3. Check ``pm_spot_hard_gate_open()`` before submitting any PM order.

Common errors
--------------
``pm_max_age_exceeded``
    Feed is alive but stale.  Usually self-corrects within one poll cycle (5 s).
    If persistent, check ``consecutive_failures`` in the snapshot — a high count
    indicates Coinbase rate-limiting.  Review logs for HTTP 4xx/5xx responses.
``live_price_feed_unhealthy``
    No ticks received.  Check:
      - Is ``start_pm_coinbase_streaming()`` being called at startup?
      - Are the ``_coinbase_ticker_loop`` tasks running?
        (``get_pm_feed_health_snapshot()["assets"][asset]["consecutive_failures"]``)
      - Is there a Coinbase outage?  (https://status.coinbase.com)
      - Are environment variables MERID_PM_MAX_SPOT_AGE_SECONDS /
        MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS set to unusually low values?

Differentiating Coinbase outage vs internal bug
------------------------------------------------
- Outage: all five assets show ``live_price_feed_unhealthy`` simultaneously with
  high ``consecutive_failures`` and HTTP 5xx log messages.
- Internal bug: subset of assets unhealthy; BTC/ETH typically healthier because
  they're at index 0/1 in startup order.  Check staggered startup logs to see
  if some tasks were never scheduled.  Check for CancelledError in task logs.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.pm_spot_health")


class PmSpotStatus(str, enum.Enum):
    """Health status for a single PM asset's Coinbase spot feed."""

    OK = "ok"
    PM_MAX_AGE_EXCEEDED = "pm_max_age_exceeded"
    LIVE_PRICE_FEED_UNHEALTHY = "live_price_feed_unhealthy"
    WARMING_UP = "warming_up"


@dataclass
class PmAssetSpotHealth:
    """Per-asset PM spot health record.

    Attributes:
        asset:                Bare uppercase asset key ("BTC", "ETH", …).
        status:               PmSpotStatus enum value.
        tick_age_s:           Seconds since last successful Coinbase tick,
                              or None if never ticked.
        cache_age_s:          Age of the price_cache entry in seconds,
                              or None if no cache entry exists.
        consecutive_failures: How many Coinbase fetches have failed in a row.
        feed_ok:              True when status is not LIVE_PRICE_FEED_UNHEALTHY.
        price_usd:            Latest cached USD price, or None.
        error:                Optional human-readable error string.
    """

    asset: str
    status: PmSpotStatus
    tick_age_s: Optional[float] = None
    cache_age_s: Optional[float] = None
    consecutive_failures: int = 0
    feed_ok: bool = True
    price_usd: Optional[float] = None
    error: Optional[str] = None

    def blocks_pm_trading(self) -> bool:
        """Return True if this asset's health should block PM trades."""
        return self.status in (
            PmSpotStatus.LIVE_PRICE_FEED_UNHEALTHY,
            PmSpotStatus.PM_MAX_AGE_EXCEEDED,
        )


def get_pm_spot_health_all() -> Dict[str, PmAssetSpotHealth]:
    """Return per-asset PM spot health for all five Kalshi assets.

    Delegates to ``LivePriceFeed.get_pm_feed_health_snapshot()`` and converts
    the raw dict into typed ``PmAssetSpotHealth`` objects.

    Returns:
        Dict keyed by bare asset name ("BTC", "ETH", "SOL", "XRP", "DOGE").
    """
    try:
        from data.live_price_feed import get_live_price_feed
        feed = get_live_price_feed()
        snapshot = feed.get_pm_feed_health_snapshot()
    except Exception as exc:
        logger.error("get_pm_spot_health_all: failed to get snapshot — %s", exc)
        from data.live_price_feed import KALSHI_ASSETS
        return {
            a: PmAssetSpotHealth(
                asset=a,
                status=PmSpotStatus.LIVE_PRICE_FEED_UNHEALTHY,
                feed_ok=False,
                error=f"snapshot_error: {exc}",
            )
            for a in KALSHI_ASSETS
        }

    result: Dict[str, PmAssetSpotHealth] = {}
    for asset, raw in snapshot.get("assets", {}).items():
        status_str = raw.get("status", "live_price_feed_unhealthy")
        try:
            status = PmSpotStatus(status_str)
        except ValueError:
            status = PmSpotStatus.LIVE_PRICE_FEED_UNHEALTHY

        error: Optional[str] = None
        if status == PmSpotStatus.LIVE_PRICE_FEED_UNHEALTHY:
            fails = raw.get("consecutive_failures", 0)
            tick_age = raw.get("tick_age_s")
            if tick_age is None:
                error = "no_tick_recorded"
            else:
                error = f"tick_too_old: {tick_age:.1f}s"
            if fails > 0:
                error = f"{error}; consecutive_failures={fails}"
        elif status == PmSpotStatus.PM_MAX_AGE_EXCEEDED:
            tick_age = raw.get("tick_age_s")
            error = f"tick_age={tick_age:.1f}s exceeds pm_max_age" if tick_age else None

        result[asset] = PmAssetSpotHealth(
            asset=asset,
            status=status,
            tick_age_s=raw.get("tick_age_s"),
            cache_age_s=raw.get("cache_age_s"),
            consecutive_failures=raw.get("consecutive_failures", 0),
            feed_ok=raw.get("feed_ok", False),
            price_usd=raw.get("price_usd"),
            error=error,
        )
    return result


def pm_spot_hard_gate_open() -> bool:
    """Return True only when no PM asset is blocking trades.

    Assets with status ``ok`` or ``warming_up`` do not block.
    Assets with status ``pm_max_age_exceeded`` or ``live_price_feed_unhealthy``
    block PM trading.

    This is the primary PM hard gate check.  Call before submitting any PM
    order.  When False, PM trading should be fully blocked regardless of
    signal strength.
    """
    health = get_pm_spot_health_all()
    return not any(h.blocks_pm_trading() for h in health.values())


def pm_spot_hard_gate_open_with_detail() -> tuple[bool, Dict[str, PmAssetSpotHealth]]:
    """Same as ``pm_spot_hard_gate_open`` but also returns the full health dict.

    Returns:
        (gate_open, health_dict) — gate_open is True when no asset is blocking.
    """
    health = get_pm_spot_health_all()
    gate_open = not any(h.blocks_pm_trading() for h in health.values())
    return gate_open, health


def pm_spot_hard_gate_open_for_asset(asset: str) -> tuple[bool, Optional[PmAssetSpotHealth]]:
    """Check the PM hard gate for a single asset only.

    Unlike ``pm_spot_hard_gate_open`` (which requires **all** five assets to be
    healthy), this function only checks the asset that the calling agent is
    actually trading.  A stale DOGE feed therefore no longer blocks a BTC agent.

    Args:
        asset: Bare uppercase asset key ("BTC", "ETH", "SOL", "XRP", "DOGE").

    Returns:
        ``(gate_open, health)`` where *gate_open* is True when the specific
        asset is not blocking trades and *health* is the per-asset health
        record (or None when the asset is not in the health snapshot).

    Example::

        gate_open, h = pm_spot_hard_gate_open_for_asset("BTC")
        if not gate_open:
            logger.warning("BTC spot feed unhealthy: %s", h)
            return
    """
    health = get_pm_spot_health_all()
    h = health.get(asset)
    if h is None:
        # Asset not tracked — treat as unhealthy to be safe.
        logger.warning("[PM_SPOT_HEALTH] per_asset_gate: unknown asset=%s — treating as blocked", asset)
        return False, None
    gate_open = not h.blocks_pm_trading()
    if not gate_open:
        logger.warning(
            "[PM_SPOT_HEALTH] per_asset_gate: asset=%s status=%s — blocking trade",
            asset, h.status.value,
        )
    return gate_open, h


def log_pm_spot_health() -> None:
    """Emit a structured [PM_SPOT_HEALTH] log line for every PM asset.

    Intended to be called periodically (e.g. every minute) from a monitoring
    loop to provide an operator-visible health record.
    """
    health = get_pm_spot_health_all()
    gate_open = not any(h.blocks_pm_trading() for h in health.values())
    for asset, h in sorted(health.items()):
        level = logger.info if h.status == PmSpotStatus.OK else logger.warning
        level(
            "[PM_SPOT_HEALTH] asset=%s status=%s tick_age_s=%s cache_age_s=%s "
            "fails=%d feed_ok=%s price_usd=%s error=%s",
            asset,
            h.status.value,
            f"{h.tick_age_s:.1f}" if h.tick_age_s is not None else "None",
            f"{h.cache_age_s:.1f}" if h.cache_age_s is not None else "None",
            h.consecutive_failures,
            h.feed_ok,
            f"{h.price_usd:.4f}" if h.price_usd else "None",
            h.error or "none",
        )
    if not gate_open:
        logger.warning("[PM_SPOT_HEALTH] hard_gate=BLOCKED — one or more assets not ok")
    else:
        logger.info("[PM_SPOT_HEALTH] hard_gate=OPEN — all assets ok")
