"""B2: Kalshi venue-side responsible-trading wrapper.

Reads the venue's own balance, account limits, and any self-exclusion state
from the Kalshi REST API and exposes a normalised summary for display in
KalshiGridView.  All calls are fail-open — if the API is unavailable a
degraded-but-safe stub is returned.

Responsible-trading endpoints used:
  GET /portfolio/balance       → current_balance, portfolio_value, available_funds
  GET /account/settings        → (vendor-specific limits if exposed)

The MERID-side daily loss limit from settings is surfaced alongside the
venue data so operators see both caps in one place.
"""
from __future__ import annotations

import asyncio
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from merid.data.ingress_replay import replay_time
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.responsible_trading")

_CACHE_TTL = 60.0   # seconds between API refreshes


@dataclass
class ResponsibleTradingSnapshot:
    """Normalised view of venue-side and MERID-side trading limits."""

    # Venue balance (cents)
    balance_cents: int = 0
    portfolio_value_cents: int = 0
    available_funds_cents: int = 0

    # MERID-side caps (loaded from settings / kill-switch)
    merid_daily_loss_limit_usd: float = 0.0
    merid_max_position_usd: float = 0.0
    merid_kill_switch_active: bool = False
    merid_current_daily_pnl_usd: float = 0.0

    # Venue self-exclusion / cool-off state (Kalshi does not expose this via
    # the public REST API as of 2026 — reserved for future use)
    venue_loss_limit_set: bool = False
    venue_deposit_limit_set: bool = False
    venue_cool_off_active: bool = False

    # Metadata
    fetched_at: float = field(default_factory=_time.time)
    source: str = "live"    # "live" | "stub"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "balance_usd": round(self.balance_cents / 100, 2),
            "portfolio_value_usd": round(self.portfolio_value_cents / 100, 2),
            "available_funds_usd": round(self.available_funds_cents / 100, 2),
            "merid_daily_loss_limit_usd": self.merid_daily_loss_limit_usd,
            "merid_max_position_usd": self.merid_max_position_usd,
            "merid_kill_switch_active": self.merid_kill_switch_active,
            "merid_current_daily_pnl_usd": round(self.merid_current_daily_pnl_usd, 2),
            "venue_loss_limit_set": self.venue_loss_limit_set,
            "venue_deposit_limit_set": self.venue_deposit_limit_set,
            "venue_cool_off_active": self.venue_cool_off_active,
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


class KalshiResponsibleTradingClient:
    """Thin wrapper that merges venue API data with MERID risk controller state."""

    def __init__(self) -> None:
        self._cache: Optional[ResponsibleTradingSnapshot] = None
        self._cache_ts: float = 0.0

    async def get_snapshot(self, force: bool = False) -> ResponsibleTradingSnapshot:
        """Return a fresh (or cached) ResponsibleTradingSnapshot."""
        now = replay_time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        snapshot = await self._fetch()
        self._cache = snapshot
        self._cache_ts = now
        return snapshot

    async def _fetch(self) -> ResponsibleTradingSnapshot:
        snap = ResponsibleTradingSnapshot()

        # ── Venue balance ──────────────────────────────────────────────
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            await asyncio.wait_for(client.connect(), timeout=10.0)
            balance_result = await client.get_balance()
            if balance_result.success and balance_result.value is not None:
                bal = balance_result.value
                snap.balance_cents = int(getattr(bal, "balance", 0) or 0)
                
                # FIX: Kalshi API doesn't return portfolio_value field
                # Calculate portfolio value from position cache instead
                portfolio_value_cents = 0
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()
                    positions = cache.get_all_positions(validate_freshness=False)
                    
                    total_portfolio_cents = 0
                    for pos in positions.values():
                        if pos.contracts > 0:
                            cost_basis = pos.contracts * pos.avg_price_cents
                            unrealized_cents = int(float(pos.unrealized_pnl_usd) * 100)
                            total_portfolio_cents += cost_basis + unrealized_cents
                    
                    if total_portfolio_cents > 0:
                        portfolio_value_cents = total_portfolio_cents
                except Exception as exc:
                    logger.warning("[responsible_trading] Failed to fetch portfolio value from cache: %s", exc)
                    portfolio_value_cents = snap.balance_cents
                
                snap.portfolio_value_cents = portfolio_value_cents
                snap.available_funds_cents = int(getattr(bal, "available_balance", snap.balance_cents) or snap.balance_cents)
                snap.source = "live"
        except Exception as exc:
            logger.debug("responsible_trading: venue balance fetch failed: %s", exc)
            snap.source = "stub"

        # ── MERID-side risk state ──────────────────────────────────────
        try:
            from merid.risk.kill_switches import risk_controller
            snap.merid_kill_switch_active = not risk_controller.can_trade()
            snap.merid_current_daily_pnl_usd = getattr(risk_controller, "_daily_pnl", 0.0)
            snap.merid_daily_loss_limit_usd = getattr(risk_controller, "daily_loss_limit", 0.0)
            snap.merid_max_position_usd = getattr(risk_controller, "max_position_value", 0.0)
        except Exception as exc:
            logger.debug("responsible_trading: risk controller read failed: %s", exc)

        snap.fetched_at = replay_time()
        return snap


_client: Optional[KalshiResponsibleTradingClient] = None
_client_lock = threading.Lock()


def get_responsible_trading_client() -> KalshiResponsibleTradingClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = KalshiResponsibleTradingClient()
    return _client
