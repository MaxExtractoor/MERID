"""Real-time position cache updated from WebSocket fill events.

Reduces latency from 5-30s (REST polling) to <1s (WS event-driven).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

logger = get_logger("merid.event_venues.kalshi.position_cache")


def _is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test market ticker.
    
    Test tickers are identified by patterns like:
    - Contains "TEST" or "KXTEST"
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"
    
    NOTE: Crypto series tickers (KXBTC-15M, KXETH-D, etc.) are NOT test tickers - they are real trading markets.
    
    Args:
        ticker: The market ticker to check
        
    Returns:
        True if the ticker is a test market, False otherwise
    """
    if not ticker:
        return False
    
    ticker_upper = ticker.upper()
    
    # Explicit test markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True
    
    # Short codes (test development tickers)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True
    
    return False


def _get_market_price_fallback(ticker: str) -> int:
    """Get market price from KalshiMarketStateStore as fallback for avg_price_cents.
    
    Used when REST API doesn't provide avg_price_cents in position data.
    Returns 50 cents as final fallback if market state unavailable.
    """
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        state = get_kalshi_market_state_store().get_state(ticker)
        if state and state.mid_cents > 0:
            return state.mid_cents
    except Exception as _exc:
        logger.debug("position_cache: failed to fetch market state for %s, using 50c fallback: %s", ticker, _exc)
    return 50


@dataclass
class CachedPosition:
    """Cached position state.
    
    Task 1: Added fill_source and client_order_id to distinguish hedge vs alpha positions
    for accurate exposure calculation.
    """
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    realized_pnl_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Take-profit targets from dynamic TP computation (R-multiple based)
    take_profit_price_cents: Optional[int] = None  # TP price level in cents
    take_profit_r_multiple: Optional[float] = None  # R-multiple target (e.g., 1.5R, 2.0R)
    stop_loss_price_cents: Optional[int] = None  # Protective stop in cents
    # Task 1: Fill source tracking ("alpha" or "hedge")
    fill_source: str = "alpha"  # "alpha" = trading position, "hedge" = hedge position
    client_order_id: Optional[str] = None  # For hedge fill detection
    # Resting bracket order tracking (GTC limit at TP / SL price)
    tp_bracket_client_tag: Optional[str] = None  # client_tag of resting TP order
    sl_bracket_client_tag: Optional[str] = None  # client_tag of resting SL order

    def apply_fill(
        self,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        side: str,
        action: str = "buy",
    ) -> None:
        """Update position with a new fill.

        Action-aware (P0 fix): a SELL fill always closes/reduces the position
        regardless of side, because Kalshi sell orders close the same-side
        long. Previously the cache used ``side == self.side`` to detect adds,
        which silently inflated positions whenever a TP/SL bracket filled
        (sell on the same side that was bought).
        """
        action = (action or "buy").lower()
        is_open = action == "buy" and side == self.side
        is_close = action == "sell" or (action == "buy" and side != self.side)

        if is_open:
            # Adding to position (same side, buy action)
            total_cost_old = self.contracts * self.avg_price_cents
            total_cost_new = contracts * price_cents
            self.contracts += contracts
            # P0-2 FIX: Use proper rounding instead of integer division to prevent PnL drift
            self.avg_price_cents = round((total_cost_old + total_cost_new) / self.contracts) if self.contracts > 0 else price_cents
        elif is_close:
            # Closing/reducing position
            # PnL direction depends on the SIDE of the original position.
            # YES long: profit when close price > entry; NO long: profit when close price < entry.
            if self.side == "yes":
                pnl_per = price_cents - self.avg_price_cents
            else:
                pnl_per = self.avg_price_cents - price_cents
            if contracts >= self.contracts:
                # Full close
                pnl_cents = self.contracts * pnl_per
                self.realized_pnl_usd += Decimal(pnl_cents) / Decimal("100") - Decimal(fee_cents) / Decimal("100")
                self.contracts = 0
            else:
                # Partial close
                pnl_cents = contracts * pnl_per
                self.realized_pnl_usd += Decimal(pnl_cents) / Decimal("100") - Decimal(fee_cents) / Decimal("100")
                self.contracts -= contracts

        self.last_updated = datetime.now(timezone.utc)

    def update_unrealized_pnl(self, current_price_cents: int) -> None:
        """Recalculate unrealized PnL based on current market price."""
        if self.contracts > 0:
            if self.side == "yes":
                pnl_cents = self.contracts * (current_price_cents - self.avg_price_cents)
            else:
                pnl_cents = self.contracts * (self.avg_price_cents - current_price_cents)
            self.unrealized_pnl_usd = Decimal(pnl_cents) / Decimal("100")
        else:
            self.unrealized_pnl_usd = Decimal("0")


class KalshiPositionCache:
    """Real-time position cache updated from WebSocket events.

    Usage:
        cache = get_position_cache()
        cache.on_fill(market_id, contracts, price_cents, fee_cents, side)
        position = cache.get_position(market_id)
    """

    _instance: Optional[KalshiPositionCache] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._positions: Dict[str, CachedPosition] = {}
        self._last_sync: Optional[datetime] = None
        # BUG-FIX: Add mutex for thread safety during concurrent WebSocket fill events
        self._mutex = asyncio.Lock()
        # PRODUCTION FIX: Pending TP targets keyed by client_order_id for fill-time lookup
        self._pending_tp_targets: Dict[str, Dict[str, Any]] = {}
        # Task 2: Add fills_ledger reference for authoritative fill_source lookup
        # BUG-FIX: Actually initialize the ledger reference (was always None)
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        self._fills_ledger = get_fills_ledger()
        self._initialized = True
        logger.info("KalshiPositionCache initialized")

    def register_tp_targets(
        self,
        client_order_id: str,
        take_profit_price_cents: Optional[int] = None,
        take_profit_r_multiple: Optional[float] = None,
        stop_loss_price_cents: Optional[int] = None,
    ) -> None:
        """Register TP targets for an order before it fills.

        Called by order_router when placing orders with TP targets.
        Targets are looked up by client_order_id when fills arrive.

        P1 fix: each entry has a registered_at timestamp so stale targets
        from canceled / rejected orders can be reaped (see _purge_stale_tp_targets).
        """
        self._pending_tp_targets[client_order_id] = {
            "tp_price": take_profit_price_cents,
            "tp_r": take_profit_r_multiple,
            "sl_price": stop_loss_price_cents,
            "registered_at": time.time(),
        }
        # Opportunistic GC every 100 registrations to keep the dict bounded.
        if len(self._pending_tp_targets) % 100 == 0:
            self._purge_stale_tp_targets()

    def _purge_stale_tp_targets(self, max_age_seconds: float = 86400.0) -> int:
        """Remove tp_target entries older than ``max_age_seconds`` (default 24h).

        Returns the number of entries removed. Called opportunistically from
        register_tp_targets and on demand from operators / tests.
        """
        cutoff = time.time() - max_age_seconds
        stale_ids = [
            coid
            for coid, target in self._pending_tp_targets.items()
            if float(target.get("registered_at", 0.0)) < cutoff
        ]
        for coid in stale_ids:
            self._pending_tp_targets.pop(coid, None)
        if stale_ids:
            logger.info(
                "[TP-TARGET-GC] purged %d stale TP targets (>%ds old)",
                len(stale_ids), int(max_age_seconds),
            )
        return len(stale_ids)

    def discard_tp_targets(self, client_order_id: str) -> bool:
        """Explicitly drop TP targets for a canceled / rejected order.

        Called by order_router when an order is canceled before any fill so
        the registry doesn't leak the (never-used) targets.
        """
        return self._pending_tp_targets.pop(client_order_id, None) is not None

    async def on_fill(
        self,
        market_id: str,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        side: str,
        client_order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
        action: str = "buy",
    ) -> None:
        """Handle a fill event from WebSocket.

        BUG-FIX: Now async with mutex protection to prevent race conditions
        during concurrent WebSocket fill events.

        PRODUCTION FIX: Looks up TP targets by client_order_id for dynamic R-multiple exits.

        Task 1: Detect hedge fills by client_order_id prefix and log separately
        for exposure calculation accuracy.

        Task 2: Integrates with fills_ledger for authoritative fill_source lookup.
        """
        async with self._mutex:
            # Task 2: Look up fill_source from fills_ledger if fill_id provided
            fill_source = await self._lookup_fill_source(fill_id, client_order_id)

            # Look up TP targets from pending registry if client_order_id provided.
            # P1 fix: use .get() not .pop() so partial fills on the same order
            # still see the TP target; the entry is purged either when the
            # position fully closes or by the TTL/explicit-discard paths.
            tp_targets = {}
            if client_order_id:
                tp_targets = self._pending_tp_targets.get(client_order_id, {}) or {}

            position = self._positions.get(market_id)

            if position is None:
                # New position - capture TP targets from the opening order
                # Task 1: Store fill_source in position for hedge/alpha distinction
                new_position = CachedPosition(
                    market_id=market_id,
                    contracts=contracts,
                    side=side,
                    avg_price_cents=price_cents,
                    take_profit_price_cents=tp_targets.get("tp_price"),
                    take_profit_r_multiple=tp_targets.get("tp_r"),
                    stop_loss_price_cents=tp_targets.get("sl_price"),
                    fill_source=fill_source,  # Task 1: Track fill source
                    client_order_id=client_order_id,  # Task 1: Store for hedge detection
                )
                self._positions[market_id] = new_position
                # Task 1: Different log message for hedge vs alpha
                if fill_source == "hedge":
                    logger.info(
                        "[POSITION-CACHE-HEDGE] opened {side} position on {market}: {contracts} @ {price}¢ "
                        "source=hedge client_id={client_id}",
                        side=side, market=market_id, contracts=contracts, price=price_cents,
                        client_id=client_order_id
                    )
                else:
                    logger.debug(
                        f"Position cache: opened {side} position on {market_id}: {contracts} @ {price_cents}¢ "
                        f"TP={tp_targets.get('tp_price')}¢ ({tp_targets.get('tp_r')}R)"
                    )

                # OPT-IN: Submit resting bracket orders (GTC sell limit at TP price).
                # Gated by MERID_RESTING_BRACKETS_ENABLED to prevent unintended live
                # orders during initial rollout. Skipped for hedge positions (handled
                # by the hedge auto-exit loop).
                if (
                    fill_source != "hedge"
                    and new_position.take_profit_price_cents
                    and os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
                ):
                    try:
                        await self._submit_resting_bracket(new_position)
                    except Exception as bx_exc:
                        logger.warning(
                            "[BRACKET] failed to submit resting bracket for %s: %s",
                            market_id, bx_exc,
                        )
            else:
                # Update existing
                pre_contracts = position.contracts
                position.apply_fill(contracts, price_cents, fee_cents, side, action=action)
                logger.debug(
                    f"Position cache: updated {market_id}: action={action} side={side} "
                    f"{pre_contracts}->{position.contracts} contracts"
                )

                # P0 Task 2: cancel resting brackets when position is fully closed
                # so stale TP/SL orders don't keep sitting on the book and trigger
                # phantom re-entry.
                if position.contracts == 0:
                    if position.tp_bracket_client_tag or position.sl_bracket_client_tag:
                        try:
                            await self._cancel_brackets(position)
                        except Exception as cancel_exc:
                            logger.warning(
                                "[BRACKET-CANCEL] Failed to cancel brackets for %s: %s",
                                market_id, cancel_exc,
                            )
                    # P1 fix: drop the now-unneeded TP target entry so registry
                    # doesn't grow unbounded across long-running sessions.
                    if client_order_id:
                        self._pending_tp_targets.pop(client_order_id, None)
                    if position.client_order_id:
                        self._pending_tp_targets.pop(position.client_order_id, None)
                    del self._positions[market_id]
                    logger.debug(f"Position cache: closed position on {market_id}")
                # P0 Task 3: resize bracket when position grows.
                # If a buy added contracts and we have an existing TP bracket
                # whose count was set when the position was smaller, cancel and
                # re-submit the bracket sized to the new total so the new
                # contracts are also covered.
                elif (
                    action == "buy"
                    and side == position.side
                    and position.contracts > pre_contracts
                    and (position.tp_bracket_client_tag or position.sl_bracket_client_tag)
                    and os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
                ):
                    try:
                        await self._cancel_brackets(position)
                        await self._submit_resting_bracket(position)
                        logger.info(
                            "[BRACKET-RESIZE] %s: resized brackets to %d contracts",
                            market_id, position.contracts,
                        )
                    except Exception as resize_exc:
                        logger.warning(
                            "[BRACKET-RESIZE] Failed to resize brackets for %s: %s",
                            market_id, resize_exc,
                        )
                # P1 fix: drop the now-unneeded TP target entry so registry
                # doesn't grow unbounded across long-running sessions.
                if client_order_id:
                    self._pending_tp_targets.pop(client_order_id, None)
                if position.client_order_id:
                    self._pending_tp_targets.pop(position.client_order_id, None)

    async def update_position_price(self, market_id: str, price_cents: int) -> None:
        """Update current price and unrealized PnL when market price changes.
        
        CRITICAL FIX: This updates current_price_cents for micro-scalp PnL calculation.
        Without this, micro-scalp exits with $0 PnL because current_price_cents is stale.
        
        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._mutex:
            position = self._positions.get(market_id)
            if position:
                position.current_price_cents = price_cents
                position.update_unrealized_pnl(price_cents)

    def get_position(self, market_id: str) -> Optional[CachedPosition]:
        """Get cached position for a market."""
        return self._positions.get(market_id)

    def get_all_positions(self, validate_freshness: bool = True) -> Dict[str, CachedPosition]:
        """Get all cached positions.
        
        Args:
            validate_freshness: If True, checks if cache is stale and logs warning.
            
        Returns:
            Dict of market_id -> CachedPosition
        """
        if validate_freshness and self._last_sync:
            from datetime import datetime, timezone
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
            if staleness_seconds > 300:  # 5 minutes
                logger.warning(
                    f"[POSITION-CACHE-STALE] Cache is {staleness_seconds:.0f}s old. "
                    f"Consider calling sync_from_rest() before get_all_positions()."
                )
        return dict(self._positions)

    def get_open_positions(self, market_id: str) -> List[CachedPosition]:
        """Get all open positions for a market (returns list for compatibility).
        
        Returns empty list if no position, or list with single position if exists.
        """
        position = self._positions.get(market_id)
        if position and position.contracts > 0:
            return [position]
        return []

    async def sync_from_rest(self, positions: list) -> None:
        """Sync cache with REST API positions (fallback/reconciliation).
        
        BUG-FIX: Now async with mutex protection for thread safety.
        PRODUCTION FIX (2026-05-10): Filter out test positions to prevent bleeding into production.
        PRODUCTION FIX (2026-05-11): Filter out closed positions (contracts=0) to prevent phantom positions.
        """
        async with self._mutex:
            try:
                self._positions.clear()
                for pos in positions:
                    market_id = pos.get("market_id") or pos.get("ticker")
                    if not market_id:
                        continue
                    
                    # PRODUCTION FIX (2026-05-10): Filter out test positions
                    if _is_test_ticker(market_id):
                        logger.debug(f"Skipping test ticker in position cache sync: {market_id}")
                        continue

                    contracts = int(pos.get("contracts", 0))
                    
                    # PRODUCTION FIX (2026-05-11): Only cache open positions (contracts > 0)
                    # Closed positions (contracts=0) should not be in the cache
                    if contracts == 0:
                        logger.debug(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
                        continue

                    self._positions[market_id] = CachedPosition(
                        market_id=market_id,
                        contracts=contracts,
                        side=pos.get("side", "yes"),
                        # PRODUCTION-FIX: Try to get avg_price_cents from market state if REST doesn't provide it
                        avg_price_cents=int(pos.get("avg_price_cents", _get_market_price_fallback(market_id))),
                        realized_pnl_usd=Decimal(str(pos.get("realized_pnl", 0))),
                        unrealized_pnl_usd=Decimal(str(pos.get("unrealized_pnl", 0))),
                        # Preserve TP targets from OrderIntent if available
                        take_profit_price_cents=pos.get("take_profit_price_cents"),
                        take_profit_r_multiple=pos.get("take_profit_r_multiple"),
                        stop_loss_price_cents=pos.get("stop_loss_price_cents"),
                    )

                self._last_sync = datetime.now(timezone.utc)
                logger.info(f"Position cache synced from REST: {len(self._positions)} positions (test & closed filtered)")
            except Exception as e:
                logger.error(f"Position cache sync from REST failed: {e}")

    async def clear(self) -> None:
        """Clear all cached positions.
        
        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._mutex:
            self._positions.clear()
            logger.info("Position cache cleared")

    async def _lookup_fill_source(
        self,
        fill_id: Optional[str],
        client_order_id: Optional[str],
    ) -> str:
        """Look up fill_source from fills_ledger for authoritative classification.
        
        Task 2: Integrates with fills_ledger to get proper fill_source.
        Falls back to client_order_id prefix detection if ledger lookup fails.
        
        Args:
            fill_id: The fill ID to look up in fills_ledger
            client_order_id: The client order ID for fallback detection
            
        Returns:
            "hedge" if hedge fill, "alpha" otherwise
        """
        # Try to get fill_source from fills_ledger if fill_id provided
        if fill_id and self._fills_ledger:
            try:
                fill = self._fills_ledger.get_fill_by_id(fill_id)
                if fill and fill.fill_source:
                    return fill.fill_source
            except Exception as e:
                logger.warning(f"Failed to lookup fill {fill_id} in ledger: {e}")
        
        # Fallback: detect by client_order_id prefix
        if client_order_id and client_order_id.startswith('HEDGE_'):
            return "hedge"
        
        return "alpha"
    
    async def reconcile_with_fills_ledger(
        self,
        ledger: Optional[Any] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Reconcile position cache with fills_ledger for consistency.
        
        Task 4: Detects discrepancies between cache and ledger hedge fill tracking.
        
        Args:
            ledger: KalshiFillsLedger instance (uses self._fills_ledger if None)
            dry_run: If True, only reports issues without fixing
            
        Returns:
            Dict with reconciliation results
        """
        if ledger is None:
            ledger = self._fills_ledger
        
        if not ledger:
            return {"error": "No fills_ledger available for reconciliation"}
        
        issues = []
        hedge_fills_in_cache = 0
        hedge_fills_in_ledger = 0
        
        # Get hedge fills from ledger
        ledger_hedge_fills = ledger.get_hedge_fills(limit=10000)
        hedge_fills_in_ledger = len(ledger_hedge_fills)
        
        # Check cache positions for hedge fill_source consistency
        async with self._mutex:
            for ticker, pos in self._positions.items():
                if pos.fill_source == "hedge":
                    hedge_fills_in_cache += 1
                    # Verify this hedge fill exists in ledger
                    matching = [f for f in ledger_hedge_fills if f.market_ticker == ticker]
                    if not matching:
                        issues.append({
                            "type": "cache_hedge_not_in_ledger",
                            "ticker": ticker,
                            "position": pos,
                        })
        
        # Report summary
        result = {
            "dry_run": dry_run,
            "hedge_fills_in_cache": hedge_fills_in_cache,
            "hedge_fills_in_ledger": hedge_fills_in_ledger,
            "discrepancy_count": len(issues),
            "issues": issues[:10],  # Limit to first 10
            "is_consistent": len(issues) == 0 and hedge_fills_in_cache == hedge_fills_in_ledger,
        }
        
        if issues:
            logger.warning(
                "Position cache / fills ledger reconciliation found %d issues",
                len(issues)
            )
        
        return result

    # ── Resting bracket orders ────────────────────────────────────────

    async def _cancel_brackets(self, position: CachedPosition) -> None:
        """Cancel any resting bracket orders attached to *position*.

        Looks up the bracket order by ``client_order_id`` (the stored client_tag)
        via Kalshi's ``get_order_by_client_id_result`` and cancels it. Tolerates
        missing orders (already-filled / never-rested) silently. Clears the
        bracket tags on the position regardless of cancel outcome.
        """
        try:
            from merid.event_venues.kalshi.client_v2 import get_kalshi_client
        except Exception as imp_exc:
            logger.debug("[BRACKET-CANCEL] client unavailable: %s", imp_exc)
            position.tp_bracket_client_tag = None
            position.sl_bracket_client_tag = None
            return

        client = get_kalshi_client()
        for kind, tag in (
            ("tp", position.tp_bracket_client_tag),
            ("sl", position.sl_bracket_client_tag),
        ):
            if not tag:
                continue
            try:
                lookup = await client.get_order_by_client_id_result(
                    tag, market_id=position.market_id,
                )
                order = getattr(lookup, "data", None) if lookup else None
                if order is not None:
                    order_id = getattr(order, "order_id", None) or getattr(order, "id", None)
                    status = (getattr(order, "status", "") or "").lower()
                    if order_id and status not in ("filled", "canceled", "rejected", "executed"):
                        await client.cancel_order(order_id, market_id=position.market_id)
                        logger.info(
                            "[BRACKET-CANCEL] %s: %s order %s canceled (tag=%s)",
                            position.market_id, kind.upper(), order_id, tag,
                        )
                    else:
                        logger.debug(
                            "[BRACKET-CANCEL] %s: %s tag=%s already terminal (status=%s)",
                            position.market_id, kind.upper(), tag, status,
                        )
                else:
                    logger.debug(
                        "[BRACKET-CANCEL] %s: no resting %s order found for tag=%s",
                        position.market_id, kind.upper(), tag,
                    )
            except Exception as exc:
                logger.warning(
                    "[BRACKET-CANCEL] %s: error canceling %s tag=%s: %s",
                    position.market_id, kind.upper(), tag, exc,
                )
        # Clear tags so re-submit (resize path) starts fresh
        position.tp_bracket_client_tag = None
        position.sl_bracket_client_tag = None

    @staticmethod
    def _bracket_client_tag(market_id: str, kind: str, price_cents: int) -> str:
        """Deterministic client_tag for a bracket order so retries dedupe.

        Same (market_id, kind, price) within a 60s window produces the same tag.
        Prefix with BRACKET_ for visibility in logs / DLQ.
        """
        bucket = int(time.time() // 60)
        preimage = f"{market_id}|{kind}|{price_cents}|{bucket}".encode("utf-8")
        digest = hashlib.sha256(preimage).hexdigest()[:16]
        return f"BRACKET_{kind.upper()}_{digest}"

    @staticmethod
    def _record_bracket_metric(kind: str, ok: bool) -> None:
        """Increment bracket submission counter for observability.

        P2 Task 7: gives ops a Prometheus surface to alert on. The counter is
        labeled by kind (tp/sl) and outcome (success/failure). Best-effort —
        any error in metrics fetch is swallowed.
        """
        try:
            from monitoring.metrics import get_metrics_registry
            reg = get_metrics_registry()
            counter = reg.counter(
                "merid_bracket_submission_total",
                help_text="Resting bracket order submissions, labeled by kind/outcome",
                label_names=["kind", "outcome"],
            )
            counter.inc(labels={
                "kind": kind,
                "outcome": "success" if ok else "failure",
            })
        except Exception:
            pass

    async def _submit_resting_bracket(self, position: CachedPosition) -> None:
        """Submit a GTC limit sell at the take-profit price (and optional SL).

        For a Kalshi binary contract:
        - Long YES → exit by selling YES at TP price (closing limit ABOVE entry).
        - Long NO  → exit by selling NO at TP price (closing limit ABOVE entry).
        Either way the action is ``sell`` on the same side that was bought.

        SL bracket only submitted if ``stop_loss_price_cents`` is set. SL is a
        marketable limit (sells at any price ≤ SL) — not a true stop-market;
        Kalshi does not natively support stops.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        tp_price = position.take_profit_price_cents
        sl_price = position.stop_loss_price_cents

        if not tp_price or position.contracts <= 0:
            return

        # TP leg: GTC sell at TP price
        tp_tag = self._bracket_client_tag(position.market_id, "tp", tp_price)
        tp_intent = OrderIntent(
            ticker=position.market_id,
            side=position.side,
            action="sell",
            price_cents=int(tp_price),
            count=int(position.contracts),
            source="resting_bracket_take_profit",
            agent_id="position_cache_bracket",
            client_tag=tp_tag,
            group_id="bracket",
            rationale=f"resting_tp:{position.market_id}:{tp_price}c",
        )

        position.tp_bracket_client_tag = tp_tag
        try:
            res = await route_order_async(tp_intent)
            ok = bool(getattr(res, "success", False))
            self._record_bracket_metric("tp", ok)
            logger.info(
                "[BRACKET] TP submitted market=%s side=%s qty=%d @ %d¢ tag=%s ok=%s",
                position.market_id, position.side, position.contracts,
                tp_price, tp_tag, ok,
            )
        except Exception as exc:
            self._record_bracket_metric("tp", False)
            logger.warning(
                "[BRACKET] TP submission failed market=%s tag=%s err=%s",
                position.market_id, tp_tag, exc,
            )

        # SL leg (optional)
        if sl_price and sl_price > 0:
            sl_tag = self._bracket_client_tag(position.market_id, "sl", sl_price)
            sl_intent = OrderIntent(
                ticker=position.market_id,
                side=position.side,
                action="sell",
                price_cents=int(sl_price),
                count=int(position.contracts),
                source="resting_bracket_stop_loss",
                agent_id="position_cache_bracket",
                client_tag=sl_tag,
                group_id="bracket",
                rationale=f"resting_sl:{position.market_id}:{sl_price}c",
            )
            position.sl_bracket_client_tag = sl_tag
            try:
                res = await route_order_async(sl_intent)
                ok = bool(getattr(res, "success", False))
                self._record_bracket_metric("sl", ok)
                logger.info(
                    "[BRACKET] SL submitted market=%s side=%s qty=%d @ %d¢ tag=%s ok=%s",
                    position.market_id, position.side, position.contracts,
                    sl_price, sl_tag, ok,
                )
            except Exception as exc:
                self._record_bracket_metric("sl", False)
                logger.warning(
                    "[BRACKET] SL submission failed market=%s tag=%s err=%s",
                    position.market_id, sl_tag, exc,
                )


# Singleton accessor
import threading as _threading
_position_cache_instance: "KalshiPositionCache | None" = None
_position_cache_lock = _threading.Lock()


def get_position_cache() -> "KalshiPositionCache":
    """Get the global position cache singleton."""
    global _position_cache_instance
    if _position_cache_instance is None:
        with _position_cache_lock:
            if _position_cache_instance is None:
                _position_cache_instance = KalshiPositionCache()
    return _position_cache_instance
