"""CryptoHedgeEngine — Deterministic rule-based hedging for Kalshi crypto.

Given an ExposureSnapshot + HedgeConfig + market catalog, produces a list
of OrderIntent objects that neutralise or reduce net directional exposure
per (asset, timeframe) cell.

Invariant: same snapshot + same config + same catalog → same hedge orders.

Hedge orders carry:
  - ``source = "HEDGE_ENGINE"``
  - ``client_tag`` prefixed with ``HEDGE_`` for trivial dedup
  - ``agent_id = "hedge_engine"``
  - Dedicated strategy group ``"hedge"`` so lease/gate never collides with alpha

Integration point: called from order_router and CT cycle between SIZE and
EXECUTE stages.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.hedging.engine")

# Strategy group constant — prevents lease collisions with alpha agents
HEDGE_STRATEGY_GROUP = "hedge"
HEDGE_AGENT_ID = "hedge_engine"
HEDGE_SOURCE = "HEDGE_ENGINE"
HEDGE_CLIENT_TAG_PREFIX = "HEDGE_"

# Canonical timeframe ordering for adjacent-horizon lookup
_TF_ORDER: List[str] = ["15m", "1h", "daily", "weekly", "monthly"]


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class HedgeOrder:
    """A single hedge order recommendation."""

    asset: str
    timeframe: str
    side: str  # "yes" or "no"
    action: str  # "buy"
    price_cents: int
    count: int
    hedge_reason: str  # "same_asset_same_horizon" | "same_asset_nearby_horizon"
    target_ticker: Optional[str] = None
    client_tag: Optional[str] = None


@dataclass
class HedgeResult:
    """Output of one hedge computation pass."""

    orders: List[HedgeOrder] = field(default_factory=list)
    skipped_cells: List[Dict[str, Any]] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    @property
    def total_hedge_orders(self) -> int:
        return len(self.orders)


# ── Engine ────────────────────────────────────────────────────────────────


class CryptoHedgeEngine:
    """Deterministic hedge engine.

    Thread-safe; all state is in the arguments, not on the instance.
    """

    def __init__(self) -> None:
        self._total_calls: int = 0
        self._total_orders_generated: int = 0
        self._total_skipped: int = 0
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────

    def compute_hedge_orders(
        self,
        exposure: Any,  # ExposureSnapshot
        config: Any,  # HedgeConfig
        bankroll_cents: int = 0,
        market_catalog: Optional[Any] = None,
    ) -> HedgeResult:
        """Compute hedge orders for all (asset, timeframe) cells.

        Args:
            exposure: ExposureSnapshot with per-cell directional deltas.
            config: HedgeConfig loaded from YAML.
            bankroll_cents: Current total bankroll in cents.
            market_catalog: Optional KalshiMarketCatalog for ticker resolution.

        Returns:
            HedgeResult with a list of HedgeOrder objects.
        """
        from merid.hedging.config import HedgeConfig
        from merid.hedging.exposure import ExposureSnapshot

        with self._lock:
            self._total_calls += 1

        if not config.enabled:
            return HedgeResult()

        if bankroll_cents <= 0:
            logger.debug("[hedge-engine] bankroll_cents=%d — no hedging", bankroll_cents)
            return HedgeResult()

        result = HedgeResult()
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

        all_assets = list(ACTIVE_CRYPTO_ASSETS)
        all_tfs = list(config.timeframes.keys())

        for asset in all_assets:
            for tf in all_tfs:
                orders = self._compute_cell(
                    asset, tf, exposure, config, bankroll_cents, market_catalog,
                )
                result.orders.extend(orders)

        with self._lock:
            self._total_orders_generated += len(result.orders)

        if result.orders:
            logger.info(
                "[hedge-engine] Generated %d hedge orders across %d cells",
                len(result.orders),
                len(all_assets) * len(all_tfs),
            )
        return result

    def metrics(self) -> Dict[str, Any]:
        """Return hedge engine metrics for observability."""
        with self._lock:
            return {
                "total_calls": self._total_calls,
                "total_orders_generated": self._total_orders_generated,
                "total_skipped": self._total_skipped,
            }

    # ── Cell-level computation ────────────────────────────────────────

    def _compute_cell(
        self,
        asset: str,
        tf: str,
        exposure: Any,
        config: Any,
        bankroll_cents: int,
        market_catalog: Optional[Any],
    ) -> List[HedgeOrder]:
        """Compute hedge orders for a single (asset, tf) cell."""
        rule = config.get_timeframe_rule(tf)
        max_net = config.max_net_exposure_cents(asset, tf, bankroll_cents)
        net_delta = exposure.net_delta_cents(asset, tf)

        # Step 1: Check if exposure is within bounds
        if abs(net_delta) <= max_net and rule.target_hedge_ratio == 0:
            return []

        if abs(net_delta) <= max_net:
            # Within cap but ratio > 0 means we still partially hedge
            pass

        # Step 2: Compute desired hedge delta
        hedge_delta_cents = int(-rule.target_hedge_ratio * net_delta)

        if abs(hedge_delta_cents) < 1:
            return []

        # Step 3: Determine hedge side
        # If net_delta > 0 (net long / YES), hedge_delta is negative → buy NO
        # If net_delta < 0 (net short / NO), hedge_delta is positive → buy YES
        if hedge_delta_cents < 0:
            hedge_side = "no"
            hedge_count_cents = abs(hedge_delta_cents)
        else:
            hedge_side = "yes"
            hedge_count_cents = hedge_delta_cents

        # Step 4: Convert from cents-of-exposure to contract count
        # Use mid-price heuristic (50¢) unless catalog provides better data
        mid_price_cents = self._resolve_mid_price(asset, tf, market_catalog)
        if mid_price_cents <= 0:
            mid_price_cents = 50  # safe fallback

        count = max(1, hedge_count_cents // mid_price_cents)

        # Step 5: Cap hedge size so it doesn't push us over slice cap
        slice_cents = config.slice_value_cents(asset, bankroll_cents)
        max_hedge_notional = slice_cents * rule.max_net_exposure_pct_of_slice / 100.0
        max_count = max(1, int(max_hedge_notional / mid_price_cents))
        count = min(count, max_count)

        # Step 6: Resolve target ticker
        ticker = self._resolve_ticker(asset, tf, hedge_side, market_catalog)

        # Step 7: Build deterministic client_tag
        tag = self._deterministic_tag(asset, tf, hedge_side, count, mid_price_cents)

        orders = [
            HedgeOrder(
                asset=asset,
                timeframe=tf,
                side=hedge_side,
                action="buy",
                price_cents=mid_price_cents,
                count=count,
                hedge_reason="same_asset_same_horizon",
                target_ticker=ticker,
                client_tag=tag,
            )
        ]

        # Step 8: Adjacent-horizon hedging if same-timeframe doesn't fully cover
        remaining_delta = abs(net_delta) - abs(hedge_delta_cents)
        if remaining_delta > max_net and rule.allow_adjacent_horizons:
            for adj_tf in rule.allow_adjacent_horizons:
                adj_rule = config.get_timeframe_rule(adj_tf)
                adj_max = config.max_net_exposure_cents(asset, adj_tf, bankroll_cents)
                adj_net = exposure.net_delta_cents(asset, adj_tf)
                # Only hedge into adjacent if it has headroom
                if abs(adj_net) < adj_max * 0.8:
                    adj_count = max(1, min(count // 2, max_count // 2))
                    adj_ticker = self._resolve_ticker(asset, adj_tf, hedge_side, market_catalog)
                    adj_tag = self._deterministic_tag(asset, adj_tf, hedge_side, adj_count, mid_price_cents)
                    orders.append(
                        HedgeOrder(
                            asset=asset,
                            timeframe=adj_tf,
                            side=hedge_side,
                            action="buy",
                            price_cents=mid_price_cents,
                            count=adj_count,
                            hedge_reason="same_asset_nearby_horizon",
                            target_ticker=adj_ticker,
                            client_tag=adj_tag,
                        )
                    )
                    break  # one adjacent horizon per cell

        return orders

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_mid_price(
        asset: str, tf: str, market_catalog: Optional[Any]
    ) -> int:
        """Resolve a mid-price for the (asset, tf) cell.

        Uses market catalog if available, otherwise falls back to 50¢.
        """
        if market_catalog is not None:
            try:
                markets = market_catalog.get_markets_by_asset(asset, timeframe=tf)
                if markets:
                    best = markets[0]
                    mid = getattr(best, "mid_price_cents", 0) or 0
                    if 1 <= mid <= 99:
                        return int(mid)
            except Exception as e:
                logger.debug(f"Market catalog price lookup failed: {e}")
        return 50

    @staticmethod
    def _resolve_ticker(
        asset: str, tf: str, side: str, market_catalog: Optional[Any]
    ) -> Optional[str]:
        """Resolve a concrete Kalshi ticker for the hedge."""
        if market_catalog is not None:
            try:
                markets = market_catalog.get_markets_by_asset(asset, timeframe=tf)
                if markets:
                    return markets[0].ticker
            except Exception as e:
                logger.debug(f"Market catalog ticker lookup failed: {e}")
        # Fallback: construct a synthetic series ticker for paper/mock
        try:
            from merid.event_venues.kalshi.market_selector import resolve_series_ticker
            return resolve_series_ticker(asset, tf)
        except Exception as e:
            logger.debug(f"Series ticker resolution failed: {e}")
            return None

    @staticmethod
    def _deterministic_tag(
        asset: str, tf: str, side: str, count: int, price: int,
    ) -> str:
        """Build a deterministic HEDGE_ prefixed client_order_id."""
        # Bucket to 60s so same exposure within a minute → same tag → dedup
        bucket = int(time.time()) // 60
        preimage = f"{asset}:{tf}:{side}:{count}:{price}:{bucket}"
        digest = hashlib.sha256(preimage.encode()).hexdigest()[:12]
        return f"{HEDGE_CLIENT_TAG_PREFIX}{asset}_{tf}_{digest}"

    def to_order_intents(self, result: HedgeResult) -> list:
        """Convert HedgeResult into OrderIntent objects ready for routing.

        Deferred import of OrderIntent to avoid circular dependency.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent

        intents: list = []
        for ho in result.orders:
            intent = OrderIntent(
                ticker=ho.target_ticker or "",
                side=ho.side,
                action=ho.action,
                price_cents=ho.price_cents,
                count=ho.count,
                source=HEDGE_SOURCE,
                agent_id=HEDGE_AGENT_ID,
                client_tag=ho.client_tag,
                group_id=HEDGE_STRATEGY_GROUP,
                rationale=f"hedge:{ho.hedge_reason}:{ho.asset}:{ho.timeframe}",
            )
            intents.append(intent)
        return intents


# ── Singleton ─────────────────────────────────────────────────────────────

_hedge_engine: Optional[CryptoHedgeEngine] = None
_hedge_engine_lock = threading.Lock()


def get_hedge_engine() -> CryptoHedgeEngine:
    """Thread-safe singleton accessor."""
    global _hedge_engine
    if _hedge_engine is None:
        with _hedge_engine_lock:
            if _hedge_engine is None:
                _hedge_engine = CryptoHedgeEngine()
    return _hedge_engine
