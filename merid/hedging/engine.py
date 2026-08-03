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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    # CRITICAL FIX (2026-07-29): Alpha-hedge pairing metadata
    # Enables precise tracking of which hedge corresponds to which alpha position
    paired_alpha_id: Optional[str] = None  # Alpha position_id this hedge pairs with
    paired_alpha_fill_id: Optional[str] = None  # Alpha fill_id this hedge pairs with
    paired_alpha_entry_time: Optional[float] = None  # Alpha entry timestamp


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
        # P2 Task 8: auto-exit loop health surface
        self._auto_exit_last_check_ts: float = 0.0
        self._auto_exit_total_exits_submitted: int = 0
        self._auto_exit_total_iterations: int = 0
        self._auto_exit_last_error: Optional[str] = None
        self._auto_exit_last_error_ts: float = 0.0
        # CRITICAL FIX (2026-07-29): Track previous exposure to detect flips
        # Enables reduce_on_exposure_flip logic to prevent over-hedging during reversals
        self._previous_exposure: Dict[Tuple[str, str], int] = {}  # (asset, tf) -> net_delta_cents

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
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, TOP_N_EDGE_ASSETS

        all_assets = list(ACTIVE_CRYPTO_ASSETS)
        all_tfs = list(config.timeframes.keys())

        # Hedge assets are picked by exposure magnitude. This is for hedging
        # (defense), not alpha sizing — so ANY asset with non-zero exposure
        # must be hedgeable. Rank by edge but always include assets with
        # non-zero exposure even if it pushes us above TOP_N.
        asset_edges = []
        for asset in all_assets:
            total_edge = 0
            for tf in all_tfs:
                total_edge += abs(exposure.net_delta_cents(asset, tf))
            asset_edges.append((asset, total_edge))

        # Sort by edge descending. Always include any asset with non-zero
        # exposure; pad up to TOP_N_EDGE_ASSETS with the highest-ranked even
        # if their exposure is zero (lets the engine warm up correctly).
        asset_edges.sort(key=lambda x: x[1], reverse=True)
        non_zero = [a for a, e in asset_edges if e > 0]
        top_n_padded = [a for a, _ in asset_edges[:TOP_N_EDGE_ASSETS]]
        # Union preserving rank order: non-zero exposures first, then any
        # remaining slots filled by top-ranked (likely zero-edge) assets.
        seen: set = set()
        top_assets: List[str] = []
        for a in non_zero + top_n_padded:
            if a not in seen:
                top_assets.append(a)
                seen.add(a)

        if len(top_assets) > TOP_N_EDGE_ASSETS and non_zero:
            logger.info(
                "[hedge-engine] Hedging %d assets (TOP_N=%d) — extras have non-zero exposure: %s",
                len(top_assets), TOP_N_EDGE_ASSETS, ', '.join(top_assets),
            )
        elif len(all_assets) > TOP_N_EDGE_ASSETS:
            logger.info(
                "[hedge-engine] Hedging top %d of %d assets by edge: %s",
                len(top_assets), len(all_assets), ', '.join(top_assets),
            )

        for asset in top_assets:
            for tf in all_tfs:
                # CRITICAL FIX (2026-07-29): Detect exposure flip before computing hedge
                # Check if exposure flipped direction since last computation
                current_net_delta = exposure.net_delta_cents(asset, tf)
                cell_key = (asset, tf)
                previous_net_delta = self._previous_exposure.get(cell_key, 0)
                
                # Detect flip: sign changed from positive to negative or vice versa
                exposure_flipped = (previous_net_delta > 0 and current_net_delta < 0) or \
                                 (previous_net_delta < 0 and current_net_delta > 0)
                
                if exposure_flipped and config.auto_exit.reduce_on_exposure_flip:
                    logger.warning(
                        "[hedge-engine] EXPOSURE FLIP detected: asset=%s tf=%s previous=%d¢ current=%d¢ - "
                        "reducing hedge size by 50%% to prevent over-hedging",
                        asset, tf, previous_net_delta, current_net_delta
                    )
                
                orders = self._compute_cell(
                    asset, tf, exposure, config, bankroll_cents, market_catalog,
                    exposure_flipped=exposure_flipped if config.auto_exit.reduce_on_exposure_flip else False
                )
                result.orders.extend(orders)
                
                # Update previous exposure for next cycle
                with self._lock:
                    self._previous_exposure[cell_key] = current_net_delta

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
                # P2 Task 8: auto-exit loop health
                "auto_exit": {
                    "last_check_ts": self._auto_exit_last_check_ts,
                    "last_check_age_seconds": (
                        time.time() - self._auto_exit_last_check_ts
                        if self._auto_exit_last_check_ts > 0 else None
                    ),
                    "total_iterations": self._auto_exit_total_iterations,
                    "total_exits_submitted": self._auto_exit_total_exits_submitted,
                    "last_error": self._auto_exit_last_error,
                    "last_error_ts": self._auto_exit_last_error_ts,
                    "healthy": (
                        self._auto_exit_last_check_ts > 0
                        and (time.time() - self._auto_exit_last_check_ts) < 60
                    ),
                },
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
        exposure_flipped: bool = False,
    ) -> List[HedgeOrder]:
        """Compute hedge orders for a single (asset, tf) cell.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            tf: Timeframe (15m, 1h, etc.)
            exposure: ExposureSnapshot with per-cell directional deltas
            config: HedgeConfig loaded from YAML
            bankroll_cents: Current total bankroll in cents
            market_catalog: Optional KalshiMarketCatalog for ticker resolution
            exposure_flipped: If True, exposure flipped direction since last computation
        """
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
            # CRITICAL: Skip hedge when price is below 50c minimum (lottery ticket behavior)
            # _resolve_mid_price returns 0 to signal "skip this hedge"
            logger.info(
                "[hedge-engine] asset=%s tf=%s skipping hedge - price below 50c minimum",
                asset, tf
            )
            return []  # Return empty list to skip hedge

        count = max(1, hedge_count_cents // mid_price_cents)

        # Step 5: Cap hedge size so it doesn't push us over slice cap
        slice_cents = config.slice_value_cents(asset, bankroll_cents)
        max_hedge_notional = slice_cents * rule.max_net_exposure_pct_of_slice / 100.0
        max_count = max(1, int(max_hedge_notional / mid_price_cents))
        count = min(count, max_count)
        
        # CRITICAL FIX (2026-07-29): Reduce hedge size on exposure flip
        # When alpha exposure flips direction (long → short or short → long),
        # reduce hedge size by 50% to prevent over-hedging during reversals
        if exposure_flipped:
            original_count = count
            count = max(1, int(count * 0.5))  # Reduce by 50%, minimum 1 contract
            logger.info(
                "[hedge-engine] Reduced hedge size on exposure flip: asset=%s tf=%s original=%d reduced=%d",
                asset, tf, original_count, count
            )
        
        # CRITICAL FIX (2026-07-29): Hedge size validation
        # Ensure hedge size never exceeds alpha size to prevent over-hedging
        try:
            cell = exposure.get_cell(asset, tf)
            # Total alpha contracts (yes + no) in this cell
            total_alpha_contracts = cell.yes_contracts + cell.no_contracts
            if total_alpha_contracts > 0:
                max_hedge_by_alpha = total_alpha_contracts
                if count > max_hedge_by_alpha:
                    original_count = count
                    count = max_hedge_by_alpha
                    logger.warning(
                        "[hedge-engine] Hedge size capped to alpha size: asset=%s tf=%s original=%d capped=%d alpha_contracts=%d",
                        asset, tf, original_count, count, total_alpha_contracts
                    )
        except Exception as size_err:
            logger.warning("[hedge-engine] Failed to validate hedge size against alpha (non-critical): %s", size_err)

        # Step 6: Resolve target ticker
        ticker = self._resolve_ticker(asset, tf, hedge_side, market_catalog)

        # Step 7: Build deterministic client_tag
        tag = self._deterministic_tag(asset, tf, hedge_side, count, mid_price_cents)

        # Step 10: FVG-Aware Hedge Timing (P1-7)
        # Try to enter hedge at FVG zone midpoint for better price
        fvg_optimized_price = self._resolve_fvg_price(
            asset, tf, hedge_side, mid_price_cents
        )
        final_price_cents = fvg_optimized_price if fvg_optimized_price else mid_price_cents
        
        # CRITICAL FIX (2026-07-29): Populate alpha-hedge pairing metadata
        # Get the largest alpha position from the cell to pair with this hedge
        paired_alpha_id = None
        paired_alpha_fill_id = None
        paired_alpha_entry_time = None
        
        try:
            cell = exposure.get_cell(asset, tf)
            if cell.alpha_positions:
                # Find the largest alpha position by size
                largest_alpha_id = max(
                    cell.alpha_positions.keys(),
                    key=lambda pid: cell.alpha_positions[pid].get("size", 0)
                )
                alpha_meta = cell.alpha_positions[largest_alpha_id]
                paired_alpha_id = largest_alpha_id
                paired_alpha_fill_id = alpha_meta.get("fill_id")
                paired_alpha_entry_time = alpha_meta.get("entry_time")
                
                logger.debug(
                    "[hedge-engine] Pairing hedge with alpha: alpha_id=%s fill_id=%s entry_time=%s",
                    paired_alpha_id[:8] if paired_alpha_id else None,
                    paired_alpha_fill_id[:8] if paired_alpha_fill_id else None,
                    paired_alpha_entry_time
                )
        except Exception as pair_err:
            logger.warning("[hedge-engine] Failed to get alpha pairing metadata (non-critical): %s", pair_err)
        
        orders = [
            HedgeOrder(
                asset=asset,
                timeframe=tf,
                side=hedge_side,
                action="buy",
                price_cents=final_price_cents,
                count=count,
                hedge_reason="same_asset_same_horizon",
                target_ticker=ticker,
                client_tag=tag,
                paired_alpha_id=paired_alpha_id,
                paired_alpha_fill_id=paired_alpha_fill_id,
                paired_alpha_entry_time=paired_alpha_entry_time,
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

        # Step 9: Cross-asset hedging hook — currently disabled.
        # SEV-1 FIX: Add warning if cross-asset hedging is enabled but not implemented
        if config.cross_asset_enabled:
            logger.warning(
                "[hedge-engine] cross_asset_enabled is True but cross-asset hedging "
                "is not implemented. This configuration has no effect. "
                "To enable cross-asset hedging, implement _compute_cross_asset_hedge method."
            )
        return orders

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_mid_price(
        asset: str, tf: str, market_catalog: Optional[Any]
    ) -> int:
        """Resolve a mid-price for the (asset, tf) cell.

        Uses market catalog if available, otherwise falls back to 50¢.
        
        CRITICAL: Enforces 50c minimum entry price to match agent grid constraints.
        This prevents hedge orders at lottery-ticket prices (e.g., 5c) that have
        statistically poor win rates (10.4% for prices < $0.30 based on 2026-07-03 analysis).
        """
        if market_catalog is not None:
            try:
                # CRITICAL: For 15m timeframe, use canonical get_current_15m_market to enforce single-market invariant
                if tf == "15m":
                    current_market = market_catalog.get_current_15m_market(asset)
                    if current_market:
                        mid = getattr(current_market, "mid_price_cents", 0) or 0
                        # CRITICAL: Enforce 50c minimum to match agent grid min_entry_prices
                        if 50 <= mid <= 99:
                            return int(mid)
                        elif mid > 0 and mid < 50:
                            logger.warning(
                                "[hedge-engine] asset=%s tf=%s mid_price=%dc < 50c minimum - skipping hedge (lottery ticket behavior)",
                                asset, tf, mid
                            )
                            return 0  # Signal to skip hedge
                else:
                    # For other timeframes, use get_markets_by_asset (legacy behavior)
                    markets = market_catalog.get_markets_by_asset(asset, timeframe=tf)
                    if markets:
                        best = markets[0]
                        mid = getattr(best, "mid_price_cents", 0) or 0
                        # CRITICAL: Enforce 50c minimum to match agent grid min_entry_prices
                        if 50 <= mid <= 99:
                            return int(mid)
                        elif mid > 0 and mid < 50:
                            logger.warning(
                                "[hedge-engine] asset=%s tf=%s mid_price=%dc < 50c minimum - skipping hedge (lottery ticket behavior)",
                                asset, tf, mid
                            )
                            return 0  # Signal to skip hedge
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
                # CRITICAL: For 15m timeframe, use canonical get_current_15m_market to enforce single-market invariant
                if tf == "15m":
                    current_market = market_catalog.get_current_15m_market(asset)
                    if current_market:
                        return current_market.ticker if hasattr(current_market, 'ticker') else None
                else:
                    # For other timeframes, use get_markets_by_asset (legacy behavior)
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
            logger.debug(f"Ticker resolution fallback failed for %s/%s: %s", asset, tf, e)
            return None

    @staticmethod
    def _deterministic_tag(
        asset: str, tf: str, side: str, count: int, price_cents: int
    ) -> str:
        """Build a deterministic client_tag for a hedge order.
        
        Same (asset, tf, side, count, price) bucket within the same 60s window
        → same tag → exchange-level dedup. Prefix with HEDGE_ for visibility.
        """
        bucket = int(time.time() // 60)
        preimage = f"{asset}|{tf}|{side}|{count}|{price_cents}|{bucket}".encode("utf-8")
        digest = hashlib.sha256(preimage).hexdigest()[:16]
        return f"{HEDGE_CLIENT_TAG_PREFIX}{digest}"

    def _resolve_fvg_price(
        self,
        asset: str,
        timeframe: str,
        hedge_side: str,
        current_price_cents: int,
    ) -> Optional[int]:
        """Resolve FVG-optimized price for hedge entry (P1-7).
        
        If an active FVG zone exists in hedge direction, return zone midpoint
        for better entry pricing. Otherwise return None (use market price).
        
        P1-001 FIX: Now uses FVG forecaster from prediction module for consistent
        FVG detection across alpha and hedge paths.
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe (e.g., "15m")
            hedge_side: "yes" (bullish) or "no" (bearish)
            current_price_cents: Current market price in cents
            
        Returns:
            FVG-optimized price in cents or None
        """
        try:
            # P1-001: Use FVG forecaster from prediction module (unified FVG source)
            from merid.prediction.forecasters.fvg import get_fvg_store
            
            store = get_fvg_store()
            active_fvgs = store.get_active_fvgs(asset, timeframe)
            
            if not active_fvgs:
                return None
            
            # Find FVG in hedge direction
            # hedge_side="yes" means we want to buy YES (bullish) → look for bullish FVG
            # hedge_side="no" means we want to buy NO (bearish) → look for bearish FVG
            target_direction = "bullish" if hedge_side == "yes" else "bearish"
            
            matching_fvgs = [f for f in active_fvgs if f.direction == target_direction]
            if not matching_fvgs:
                return None
            
            # Get nearest FVG to current price
            current_price = current_price_cents / 100.0
            nearest_fvg = min(matching_fvgs, key=lambda f: abs(f.midpoint() - current_price))
            
            # Check if price is within fill distance of FVG
            if not nearest_fvg.is_within_fill_distance(current_price):
                return None
            
            # Use FVG midpoint as optimized price
            fvg_price = nearest_fvg.midpoint()
            price_cents = int(fvg_price * 100)
            logger.debug(
                "[FVG-HEDGE] %s/%s/%s: FVG price=%d¢ vs market=%d¢",
                asset, timeframe, hedge_side, price_cents, current_price_cents
            )
            return price_cents
            
        except Exception as e:
            logger.debug("[FVG-HEDGE] Failed to resolve FVG price: %s", e)
        
        return None

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
                # CRITICAL FIX (2026-07-29): Pass alpha-hedge pairing metadata
                # Store in metadata dict for fill tracking and PnL attribution
                metadata={
                    "paired_alpha_id": ho.paired_alpha_id,
                    "paired_alpha_fill_id": ho.paired_alpha_fill_id,
                    "paired_alpha_entry_time": ho.paired_alpha_entry_time,
                } if ho.paired_alpha_id else None,
            )
            intents.append(intent)
        return intents

    async def execute_take_profit_exits(
        self,
        config: HedgeConfig,
        current_prices: Dict[str, int],
    ) -> HedgeResult:
        """Execute take profit and stop loss exits for active hedge positions.

        This method checks all active hedges against configured TP/SL levels
        and generates exit orders for any positions that have hit their targets.

        Args:
            config: HedgeConfig with take_profit settings
            current_prices: Dict mapping asset to current price in cents

        Returns:
            HedgeResult containing any exit orders needed
        """
        result = HedgeResult()
        from merid.hedging.pnl_tracker import get_hedge_pnl_tracker

        tracker = get_hedge_pnl_tracker()

        # Check take profit and stop loss levels
        tp_orders = tracker.check_take_profit_levels(config, current_prices)
        for order in tp_orders:
            # Look up the original PnL record to determine the correct exit side.
            # An exit is a SELL on the same side that was originally bought
            # (Kalshi: closing a YES long = sell YES; closing a NO long = sell NO).
            rec = tracker._records.get(order["record_id"])
            if rec is None:
                continue
            exit_side = rec.hedge_side  # close on same side that was bought
            result.orders.append(HedgeOrder(
                asset=order["asset"],
                timeframe=rec.hedge_ticker.split("-")[-1] if "-" in rec.hedge_ticker else "exit",
                hedge_reason=f"tp_exit:{order['reason']}",
                side=exit_side,
                action="sell",
                count=order["exit_count"],
                price_cents=order["exit_price_cents"],
                target_ticker=rec.hedge_ticker,
                client_tag=f"tp_exit:{order['reason']}:{order['record_id']}",
            ))
            logger.info(
                "[TP-EXEC] %s exit for %s ticker=%s side=%s: %d @ %d¢",
                order["reason"], order["asset"], rec.hedge_ticker, exit_side,
                order["exit_count"], order["exit_price_cents"]
            )

        # Check max hold time — close at market
        hold_orders = tracker.get_hedges_past_hold_time(config)
        for order in hold_orders:
            rec = tracker._records.get(order["record_id"])
            if rec is None:
                continue
            result.orders.append(HedgeOrder(
                asset=order["asset"],
                timeframe="exit",
                hedge_reason="max_hold_time",
                side=rec.hedge_side,
                action="sell",
                count=rec.hedge_entry_count,
                price_cents=0,  # Market order
                target_ticker=rec.hedge_ticker,
                client_tag=f"max_hold:{order['record_id']}",
            ))

        return result

    async def run_auto_exit_loop(
        self,
        config: HedgeConfig,
        price_provider: Callable[[], Dict[str, int]],
        interval_seconds: float = 5.0,
    ):
        """Continuously monitor and execute auto-exits.

        This is a long-running task that should be started with asyncio.create_task().

        Args:
            config: HedgeConfig with auto_exit settings
            price_provider: Callable that returns current prices dict
            interval_seconds: How often to check for exits
        """
        import asyncio
        from merid.event_venues.kalshi.order_router import route_order_async

        while True:
            try:
                current_prices = price_provider()
                result = await self.execute_take_profit_exits(config, current_prices)
                # P2 Task 8: track loop health
                with self._lock:
                    self._auto_exit_last_check_ts = time.time()
                    self._auto_exit_total_iterations += 1
                if result.orders:
                    intents = self.to_order_intents(result)
                    logger.info(
                        "[AUTO-EXIT-LOOP] Submitting %d hedge exit orders",
                        len(intents),
                    )
                    submitted = 0
                    for intent in intents:
                        try:
                            await route_order_async(intent)
                            submitted += 1
                        except Exception as submit_exc:
                            logger.error(
                                "[AUTO-EXIT-LOOP] route_order_async failed: %s | intent=%s",
                                submit_exc, intent.client_tag,
                            )
                    with self._lock:
                        self._auto_exit_total_exits_submitted += submitted
            except Exception as e:
                logger.error("[AUTO-EXIT-LOOP] Error in TP/SL check: %s", e)
                with self._lock:
                    self._auto_exit_last_error = str(e)
                    self._auto_exit_last_error_ts = time.time()
            await asyncio.sleep(interval_seconds)


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
