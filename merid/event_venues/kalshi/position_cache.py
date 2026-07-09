"""Real-time position cache updated from WebSocket fill events.

Reduces latency from 5-30s (REST polling) to <1s (WS event-driven).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time as _time
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


def _is_expired_ticker(ticker: str) -> bool:
    """Check if a ticker has expired (market is in the past).
    
    Parses the date from the ticker format (e.g., KXBTC15M-26JUL022230-30)
    and checks if the market expiration time is in the past.
    
    Args:
        ticker: The market ticker to check
        
    Returns:
        True if the ticker has expired, False otherwise
    """
    if not ticker:
        return False
    
    try:
        import re
        from datetime import datetime, timezone, timedelta
        
        # Parse ticker format: KXBTC15M-26JUL022230-30
        # Extract date part: 26JUL022230 (DDMMMHHMMSS format - 11 total chars)
        match = re.search(r'-(\d{2}[A-Z]{3}\d{6})', ticker.upper())
        if not match:
            return False
        
        date_str = match.group(1)  # e.g., "26JUL022230"
        
        # Parse components - format is DDMMMHHMMSS
        day = int(date_str[0:2])
        month_str = date_str[2:5]
        hour = int(date_str[5:7])
        minute = int(date_str[7:9])
        second = int(date_str[9:11])
        
        # Convert month abbreviation to number
        months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                  'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        month = months.get(month_str)
        if month is None:
            return False
        
        # Assume current year (Kalshi tickers are typically current year)
        current_year = datetime.now(timezone.utc).year
        
        # Create expiration datetime in UTC
        try:
            expiry_dt = datetime(current_year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError:
            # Invalid date (e.g., Feb 30), assume expired
            return True
        
        # Check if expired (allow 15 minute buffer for market close processing)
        now = datetime.now(timezone.utc)
        expiry_buffer = timedelta(minutes=15)
        
        return expiry_dt < (now - expiry_buffer)
        
    except Exception as e:
        logger.debug(f"[EXPIRED-TICKER] Exception parsing ticker {ticker}: {e}")
        return False  # On parse error, don't filter out


def _get_market_price_fallback(ticker: str) -> int:
    """Get market price from KalshiMarketStateStore as fallback for avg_price_cents.
    
    Used when REST API doesn't provide avg_price_cents in position data.
    Returns 50 cents as final fallback if market state unavailable.
    """
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        state = get_kalshi_market_state_store().get_unified(ticker)
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
    P1 FIX: Added scale_out_complete flag for partial profit taking tracking.
    P1 FIX: Added entry_intent_id for RoundTripMonitor exit reason tracking.
    FIX: Added notional_usd property for exposure calculation.
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
    # P1 FIX: Scale-out tracking for partial profit taking
    scale_out_complete: bool = False  # True if partial exit already executed
    # P1 FIX: Entry intent ID for RoundTripMonitor exit reason tracking
    entry_intent_id: Optional[str] = None  # Intent ID of the entry order
    # Task 1: Fill source tracking ("alpha" or "hedge")
    fill_source: str = "alpha"  # "alpha" = trading position, "hedge" = hedge position
    client_order_id: Optional[str] = None  # For hedge fill detection
    # Resting bracket order tracking (GTC limit at TP / SL price)
    tp_bracket_client_tag: Optional[str] = None  # client_tag of resting TP order
    sl_bracket_client_tag: Optional[str] = None  # client_tag of resting SL order
    # Ratchet profit floor tracking (research-backed profit locking mechanism)
    ratchet_activated: bool = False  # True when price has crossed activation threshold
    ratchet_floor_price_cents: Optional[int] = None  # Hard floor price (never lowers once set)
    ratchet_activation_timestamp: Optional[datetime] = None  # When ratchet was activated

    @property
    def notional_usd(self) -> Decimal:
        """Compute notional value in USD from contracts and average price."""
        return Decimal(self.contracts * self.avg_price_cents) / Decimal("100")

    @property
    def notional_value(self) -> Decimal:
        """Alias for notional_usd for compatibility with loop_15m.py."""
        return self.notional_usd

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
        # CRITICAL FIX: Track unhealthy positions (missing exit metadata)
        self._unhealthy_positions: set = set()

        # Log bracket order mode on startup
        brackets_enabled = os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
        mode = "RESTING" if brackets_enabled else "MONITOR_ONLY"
        logger.info("[BRACKET-STATE] mode=%s MERID_RESTING_BRACKETS_ENABLED=%s", mode, os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false"))
        # BUG-FIX: Add mutex for thread safety during concurrent WebSocket fill events
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._mutex: Optional[asyncio.Lock] = None
        # PRODUCTION FIX: Pending TP targets keyed by client_order_id for fill-time lookup
        self._pending_tp_targets: Dict[str, Dict[str, Any]] = {}
        # PRODUCTION FIX: Map Kalshi order_id -> client_tag for fill-to-intent linkage
        # This is needed because HTTP fills don't include client_order_id from Kalshi API
        self._order_id_to_client_tag: Dict[str, str] = {}
        # Task 2: Add fills_ledger reference for authoritative fill_source lookup
        # DETOX FIX: Lazy load fills_ledger to prevent import-time initialization cascade
        # BUG-FIX: Actually initialize the ledger reference (was always None)
        self._fills_ledger = None  # Lazy loaded via _get_fills_ledger()
        # TUNED (2026-05-25): Trailing stop monitoring infrastructure
        self._monitoring_enabled: bool = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._monitoring_interval_seconds: float = 5.0  # Check every 5 seconds
        self._initialized = True
        
        # CRITICAL FIX: Reset stale window exposure if position cache is empty
        # This prevents phantom exposure from blocking all trading after restart
        self._reset_stale_window_exposure()
        
        # CRITICAL FIX: DO NOT register exit intent callback here
        # The production callback is registered in loop_15m.py with proper swing mode logic
        # Registering here would overwrite the production callback and break exit handling
        # PositionMonitor callback registration is done in loop_15m._start_position_monitor()
        
        logger.info("KalshiPositionCache initialized")

    def _ensure_mutex(self) -> asyncio.Lock:
        """Lazy-initialize the mutex in the current event loop."""
        if self._mutex is None:
            self._mutex = asyncio.Lock()
        return self._mutex

    def _get_fills_ledger(self):
        """Lazy load fills_ledger to prevent import-time initialization cascade."""
        if self._fills_ledger is None:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            self._fills_ledger = get_fills_ledger()
        return self._fills_ledger

    def _reset_stale_window_exposure(self) -> None:
        """Reset stale window exposure if position cache is empty.
        
        CRITICAL FIX: This prevents phantom exposure from blocking all trading
        after restart. If the position cache shows 0 open positions but window
        exposure is non-zero, it means exposure tracking is stale (positions
        were closed outside the system or before shutdown).
        
        This should be called during position cache initialization.
        """
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                _WINDOW_TRACKING_STATE,
                _WINDOW_TRACKING_LOCK,
            )
            import time
            
            with _WINDOW_TRACKING_LOCK:
                total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
                agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"]
            
            # Only reset if exposure is non-zero but position cache is empty
            if total_exposure > 0.0 and len(self._positions) == 0:
                logger.warning(
                    f"[POSITION-CACHE] Stale window exposure detected: total=${total_exposure:.2f} "
                    f"agents={len(agent_exposure)} but position cache is empty. Resetting exposure."
                )
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
                force_reset_window_exposure()
        except Exception as e:
            logger.warning("[POSITION-CACHE] Failed to reset stale window exposure: %s", e)

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
            "registered_at": _time.time(),
        }
        # Opportunistic GC every 100 registrations to keep the dict bounded.
        if len(self._pending_tp_targets) % 100 == 0:
            self._purge_stale_tp_targets()

    def register_order_id_mapping(self, kalshi_order_id: str, client_tag: str) -> None:
        """Register Kalshi order_id -> client_tag mapping for fill-to-intent linkage.

        Called by order_router after successful order submission.
        This is needed because HTTP fills from Kalshi API don't include client_order_id,
        only the Kalshi order_id. We use this mapping to recover the client_tag for TP lookup.
        """
        self._order_id_to_client_tag[kalshi_order_id] = client_tag

    def _purge_stale_tp_targets(self, max_age_seconds: float = 86400.0) -> int:
        """Remove tp_target entries older than ``max_age_seconds`` (default 24h).

        Returns the number of entries removed. Called opportunistically from
        register_tp_targets and on demand from operators / tests.
        """
        cutoff = _time.time() - max_age_seconds
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
        async with self._ensure_mutex():
            # Task 2: Look up fill_source from fills_ledger if fill_id provided
            fill_source = await self._lookup_fill_source(fill_id, client_order_id)

            # CRITICAL FIX (2026-07-07): Record window exposure on fill confirmation
            # Window exposure is now counted only when fills are confirmed, not at order submission.
            # This prevents phantom exposure accumulation from unfilled orders.
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                # Extract agent_id from fills_ledger if available
                agent_id = None
                if fill_id and self._fills_ledger:
                    try:
                        fill_record = self._fills_ledger.get_fill(fill_id)
                        if fill_record:
                            agent_id = getattr(fill_record, 'agent_id', None)
                    except Exception as ledger_err:
                        logger.debug("[POSITION-CACHE] Could not get fill record for exposure: %s", ledger_err)
                
                # CRITICAL FIX (2026-07-07): Derive agent_id from ticker if missing
                # This ensures window exposure is tracked even when agent_id is not set in fill record
                # (e.g., HTTP fills without agent_id context)
                if not agent_id:
                    try:
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            agent_id = f"{asset.upper()}_15M"
                            logger.debug(
                                "[POSITION-CACHE] Derived agent_id=%s from ticker=%s for window exposure tracking",
                                agent_id, market_id
                            )
                    except Exception as derive_err:
                        logger.debug("[POSITION-CACHE] Could not derive agent_id from ticker: %s", derive_err)
                
                # Record exposure if we have agent_id and this is an entry order (buy)
                if agent_id and action == "buy":
                    try:
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        order_notional_usd = (contracts * price_cents) / 100.0
                        
                        # CRITICAL FIX (2026-07-08): Release resting exposure and record execution exposure
                        # Resting exposure was recorded at placement time (order_gate, top3 gate)
                        # When order fills, we must release resting exposure and record execution exposure
                        # This prevents double-counting and ensures accurate window tracking
                        # CRITICAL FIX 2026-07-08: Extract asset for per-asset exposure tracking
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id) if market_id else None
                        envelope.release_resting_order_exposure(
                            agent_id=agent_id,
                            order_notional_usd=order_notional_usd
                        )
                        envelope.record_order_execution(
                            agent_id=agent_id,
                            order_notional_usd=order_notional_usd,
                            asset=asset
                        )
                    except RuntimeError as e:
                        # Bankroll not ready - log warning but don't crash
                        logger.warning(
                            "[POSITION-CACHE] Failed to record window exposure: %s (bankroll service unavailable)",
                            e
                    )
                    logger.info(
                        "[POSITION-CACHE] Released resting exposure and recorded execution exposure on fill: agent=%s notional=$%.2f market=%s fill_id=%s",
                        agent_id, order_notional_usd, market_id, fill_id or "N/A"
                    )
                
                # SEV-0 FIX: Release window exposure for position-reducing fills (sell-side)
                # This ensures window exposure is released on partial closes and all exit paths
                # Previously, exposure was only released in remove_position(), missing partial closes
                if agent_id and action == "sell":
                    try:
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        # Calculate notional to release based on contracts closed
                        position_notional_usd = (contracts * price_cents) / 100.0
                        # CRITICAL FIX 2026-07-08: Extract asset for per-asset exposure release
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id) if market_id else None
                        envelope.record_position_closure(
                            agent_id=agent_id,
                            position_notional_usd=position_notional_usd,
                            asset=asset
                        )
                        logger.info(
                            "[POSITION-CACHE] Released window exposure on sell fill: agent=%s notional=$%.2f market=%s fill_id=%s",
                            agent_id, position_notional_usd, market_id, fill_id or "N/A"
                        )
                    except RuntimeError as e:
                        # Bankroll not ready - log warning but don't crash
                        logger.warning(
                            "[POSITION-CACHE] Failed to release window exposure on sell fill: %s (bankroll service unavailable)",
                            e
                        )
                    except Exception as e:
                        logger.error(
                            "[POSITION-CACHE] Failed to release window exposure on sell fill: %s",
                            e,
                            exc_info=True
                        )
            except Exception as exposure_err:
                logger.warning("[POSITION-CACHE] Failed to record window exposure on fill: %s", exposure_err)

            # PRODUCTION FIX: Recover client_order_id from order_id if not provided
            # HTTP fills from Kalshi API don't include client_order_id, only order_id
            # We use the order_id -> client_tag mapping registered at order submission time
            if not client_order_id and fill_id:
                # Try to get order_id from fills_ledger
                ledger = self._get_fills_ledger()
                if ledger:
                    fill_record = ledger.get_fill(fill_id)
                    if fill_record and fill_record.order_id:
                        client_order_id = self._order_id_to_client_tag.get(fill_record.order_id)
                        if client_order_id:
                            logger.debug(
                                "[FILL-INTENT-LINK] Recovered client_order_id=%s from order_id=%s for fill_id=%s",
                                client_order_id, fill_record.order_id, fill_id
                            )

            # Look up TP targets from pending registry if client_order_id provided.
            # P1 fix: use .get() not .pop() so partial fills on the same order
            # still see the TP target; the entry is purged either when the
            # position fully closes or by the TTL/explicit-discard paths.
            tp_targets = {}
            if client_order_id:
                tp_targets = self._pending_tp_targets.get(client_order_id, {}) or {}

            position = self._positions.get(market_id)

            # Log fill with linkage to order submission and position
            logger.info(
                "[FILL] fill_id=%s client_order_id=%s market=%s side=%s size=%d price=%dc position_id=%s",
                fill_id or "N/A", client_order_id or "N/A", market_id, side, contracts, price_cents,
                position.market_id if position else "NEW"
            )

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
                    entry_intent_id=client_order_id or fill_id or "unknown",  # For RoundTripMonitor tracking
                    # Ratchet profit floor initialization (defaults to inactive)
                    ratchet_activated=False,
                    ratchet_floor_price_cents=None,
                    ratchet_activation_timestamp=None,
                )
                
                # Phase 5.4: Record entry in RoundTripMonitor with calibration data
                try:
                    from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor, EntryRecord
                    rt_monitor = get_round_trip_monitor()
                    
                    # Extract raw_logit and agent_id from fills_ledger if available
                    raw_logit = None
                    agent_id = None
                    if fill_id and self._fills_ledger:
                        try:
                            fill_record = self._fills_ledger.get_fill(fill_id)
                            if fill_record:
                                raw_logit = getattr(fill_record, 'raw_logit', None)
                                agent_id = getattr(fill_record, 'agent_id', None)
                        except Exception as ledger_err:
                            logger.debug("[POSITION-CACHE] Could not get fill record for calibration: %s", ledger_err)
                    
                    # Record entry for round-trip tracking
                    entry_record = EntryRecord(
                        intent_id=client_order_id or fill_id or "unknown",
                        ticker=market_id,
                        asset=market_id.split("-")[0].replace("KX", "") if "-" in market_id else "UNKNOWN",
                        timestamp=datetime.utcnow(),
                        price_cents=price_cents,
                        count=contracts,
                        action=action,
                        risk_tier="A",  # Default risk tier
                        window_resolution_id="default",
                        exit_policy_id="default",
                        raw_logit=raw_logit,  # Phase 5.4: Raw logit for calibration
                        agent_id=agent_id,  # Phase 5.4: Agent ID for outcome recording
                    )
                    rt_monitor.record_entry(entry_record)
                except Exception as rt_err:
                    logger.warning("[POSITION-CACHE] Failed to record entry in RoundTripMonitor: %s", rt_err)
                self._positions[market_id] = new_position

                # CRITICAL FIX: Add position to PositionMonitor for TP/SL enforcement
                # This wires the position cache into the exit policy system
                # OFFSET HEDGING: Check if hedging is needed for this fill
                # Only hedge alpha positions (fill_source != "hedge")
                if fill_source != "hedge":
                    try:
                        from merid.event_venues.kalshi.offset_hedging import handle_fill_for_hedging
                        from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
                        
                        # Get current bankroll for hedge sizing (async version)
                        bankroll_service = await get_bankroll_service()
                        bankroll_usd = bankroll_service.get_equity() if bankroll_service else 100.0
                        
                        # Get edge from fills_ledger if available
                        edge_pct = 0.0
                        if fill_id and self._fills_ledger:
                            try:
                                fill_record = self._fills_ledger.get_fill(fill_id)
                                if fill_record:
                                    edge_pct = getattr(fill_record, 'edgepct', 0.0) or 0.0
                            except Exception as edge_err:
                                logger.debug("[POSITION-CACHE] Could not get edge for hedging: %s", edge_err)
                        
                        # Trigger hedging check (fire and forget - don't block position update)
                        asyncio.create_task(handle_fill_for_hedging(
                            market_id, side, edge_pct, price_cents, contracts, bankroll_usd
                        ))
                        logger.info(
                            "[OFFSET-HEDGING] Hedging check triggered: ticker=%s side=%s edge=%.4f count=%d",
                            market_id, side, edge_pct, contracts
                        )
                    except Exception as hedge_err:
                        logger.warning("[POSITION-CACHE] Failed to trigger hedging: %s", hedge_err)
                
                # Add position to PositionMonitor for TP/SL enforcement
                try:
                    from merid.position_management.position_monitor import get_position_monitor
                    from merid.position_management.position import Position, PositionSide, TrailingType
                    
                    monitor = get_position_monitor()
                    
                    # Convert CachedPosition to Position for monitoring
                    side_enum = PositionSide.YES if side.lower() == "yes" else PositionSide.NO
                    
                    # CRITICAL: Configure trailing stop based on profile configuration
                    # Read from kalshi_crypto_15m.yaml trailing_stop section
                    trailing_enabled = False
                    trailing_distance_cents = 5
                    min_profit_cents = 12  # Default from profile (align with 2026 research)
                    activation_delay_sec = 30
                    
                    try:
                        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                        if is_profile_active():
                            adapter = get_active_profile()
                            profile = adapter.profile
                            trailing_enabled = profile.trailing_stop_enabled
                            trailing_distance_cents = profile.trailing_stop_trailing_distance_cents
                            min_profit_cents = profile.trailing_stop_min_profit_cents
                            activation_delay_sec = profile.trailing_stop_activation_delay_sec
                    except Exception as ts_err:
                        logger.debug("[POSITION-CACHE] Could not read trailing stop config: %s", ts_err)
                    
                    # CRITICAL: Mandatory profit exit (2026-07-08)
                    # Calculate profit target based on entry price and profile configuration
                    # This ensures quick wins and forces entries in sweet spot (10-75c)
                    mandatory_profit_enabled = False
                    profit_target_pct = 0.25  # Default 25%
                    try:
                        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                        if is_profile_active():
                            adapter = get_active_profile()
                            profile = adapter.profile
                            mandatory_profit_enabled = profile.mandatory_profit_exit_enabled
                            
                            # Determine profit target based on entry price band
                            if price_cents < profile.mandatory_profit_exit_threshold_low_cents:
                                # Entry 10-30c: 30% profit target (quick flips)
                                profit_target_pct = profile.mandatory_profit_exit_target_pct_low
                            elif price_cents < profile.mandatory_profit_exit_threshold_high_cents:
                                # Entry 30-50c: 25% profit target
                                profit_target_pct = profile.mandatory_profit_exit_target_pct_mid
                            else:
                                # Entry 50-75c: 20% profit target
                                profit_target_pct = profile.mandatory_profit_exit_target_pct_high
                    except Exception as mpe_err:
                        logger.debug("[POSITION-CACHE] Could not read mandatory profit exit config: %s", mpe_err)
                    
                    # Calculate mandatory profit target price
                    mandatory_tp_price = None
                    if mandatory_profit_enabled:
                        profit_cents = int(price_cents * profit_target_pct)
                        mandatory_tp_price = price_cents + profit_cents
                        logger.info(
                            "[MANDATORY-PROFIT-EXIT] Set mandatory profit target: entry=%dc target=%dc profit_pct=%.0f%% profit_cents=%d",
                            price_cents, mandatory_tp_price, profit_target_pct * 100, profit_cents
                        )
                    
                    tp_r = tp_targets.get("tp_r", 1.0)
                    sl_price = tp_targets.get("sl_price")
                    
                    # CRITICAL FIX: Reject positions without SL (2026-07-06)
                    # Previously used hardcoded fallback of price_cents - 5
                    # Now requires explicit SL to enforce "no trade without exit" invariant
                    if sl_price is None:
                        logger.error(
                            "[POSITION-CACHE] Missing SL price for order %s - "
                            "cannot monitor position for exits (invariant violation)",
                            client_order_id
                        )
                        # Flag position as unhealthy and skip monitoring
                        self._unhealthy_positions.add(market_id)
                        return
                    
                    risk_cents = abs(price_cents - sl_price)
                    
                    # CRITICAL: Clamp trailing stops to mandatory FIXED_CENTS mode
                    # This ensures all positions have trailing stop protection regardless of profile config
                    # Trailing stops are mandatory for production safety
                    trailing_type = TrailingType.FIXED_CENTS
                    trailing_param = trailing_distance_cents  # e.g., 5 cents
                    
                    # Research: Configure scale-out target at 1.5-2R (Pay Yourself strategy)
                    # Close 50% at 1.5-2R to lock profits while letting "runner" capture larger moves
                    scale_out_r = 1.5  # Scale out at 1.5R
                    scale_out_price = price_cents + int(risk_cents * scale_out_r)
                    if tp_targets.get("tp_price"):
                        # If TP is set, scale out at 75% of TP (between 1.5-2R)
                        scale_out_price = price_cents + int((tp_targets.get("tp_price") - price_cents) * 0.75)
                    
                    # CRITICAL: Use mandatory profit target if enabled (2026-07-08)
                    # This overrides the agent's TP to ensure quick wins
                    final_tp_price = mandatory_tp_price if mandatory_profit_enabled and mandatory_tp_price else tp_targets.get("tp_price")
                    
                    monitor_position = Position(
                        position_id=market_id,  # Use market_id as position_id
                        market_id=market_id,
                        side=side_enum,
                        size=contracts,
                        avg_entry_price_cents=price_cents,
                        take_profit_price_cents=final_tp_price,  # Use mandatory TP if enabled
                        stop_loss_price_cents=tp_targets.get("sl_price"),
                        trailing_type=trailing_type,
                        trailing_param=trailing_param,
                        scale_out_price_cents=scale_out_price,  # Research: Scale-out at 1.5-2R
                        exit_policy_id=client_order_id or fill_id or "unknown",
                    )
                    
                    monitor.add_position(monitor_position)
                    logger.info(
                        "[POSITION-MONITOR-INTEGRATION] Added position to monitor: market=%s side=%s size=%d TP=%dc SL=%dc trail=%sR",
                        market_id, side, contracts,
                        tp_targets.get('tp_price') or 0,
                        tp_targets.get('sl_price') or 0,
                        trailing_param
                    )
                except Exception as monitor_err:
                    logger.warning("[POSITION-MONITOR-INTEGRATION] Failed to add position to monitor: %s", monitor_err)

                # Log entry timing for audit (correlate with [SCHEDULER-CHECK] for full timing metrics)
                asset = market_id.split("-")[0].replace("KX", "") if "-" in market_id else "UNKNOWN"
                logger.info(
                    "[ENTRY-TIMING] position_id=%s asset=%s ticker=%s side=%s size=%d entry_price=%dc "
                    "entry_timestamp=%s best_price_after=N/A early_cost_cents=N/A early_cost_r=N/A",
                    market_id, asset, market_id, side, contracts, price_cents,
                    datetime.utcnow().isoformat()
                )
                # Task 1: Different log message for hedge vs alpha
                if fill_source == "hedge":
                    logger.info(
                        "[POSITION-CACHE-HEDGE] opened {side} position on {market}: {contracts} @ {price}¢ "
                        "source=hedge client_id={client_id}",
                        side=side, market=market_id, contracts=contracts, price=price_cents,
                        client_id=client_order_id
                    )
                else:
                    logger.info(
                        "[TP-SL-ARMED] market=%s side=%s entry=%dc tp=%dc sl=%dc r_multiple=%.2f vol_regime=N/A confidence=N/A",
                        market_id, side, price_cents,
                        tp_targets.get('tp_price') or 0,
                        tp_targets.get('sl_price') or 0,
                        tp_targets.get('tp_r') or 0
                    )
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

                    # CRITICAL FIX: Remove position from PositionMonitor when closed
                    # This ensures the monitor doesn't track closed positions
                    try:
                        from merid.position_management.position_monitor import get_position_monitor
                        monitor = get_position_monitor()
                        monitor.remove_position(market_id)
                        logger.info(
                            "[POSITION-MONITOR-INTEGRATION] Removed position from monitor: market=%s",
                            market_id
                        )
                    except Exception as monitor_err:
                        logger.warning("[POSITION-MONITOR-INTEGRATION] Failed to remove position from monitor: %s", monitor_err)

                    # CRITICAL FIX: Record position close in KalshiRiskManager for asset_notional tracking
                    # This ensures per-asset notional exposure is decremented when positions close
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        risk_mgr = get_kalshi_risk()
                        
                        # Extract asset from ticker
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            # Record close with category="crypto" and asset for notional tracking
                            risk_mgr.record_close(
                                category="crypto",
                                contracts=pre_contracts,  # Use pre-fill contracts (the amount being closed)
                                price_cents=price_cents,
                                asset=asset.upper(),  # CRITICAL: Pass asset for per-asset notional tracking
                            )
                            logger.info(
                                "[POSITION-CACHE] Recorded position close in risk manager: asset=%s category=crypto contracts=%d price=%dc",
                                asset.upper(), pre_contracts, price_cents
                            )
                    except Exception as risk_err:
                        logger.warning("[POSITION-CACHE] Failed to record position close in risk manager: %s", risk_err)
                    
                    # CRITICAL: Record position close in risk envelope for window-based risk tracking (2026-07-06)
                    # This allows agents to re-enter after closing positions via trailing stop, ratchet, or 99c exit
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        if envelope:
                            from config.kalshi_crypto_config import kalshi_ticker_to_asset
                            asset = kalshi_ticker_to_asset(market_id)
                            if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                                # Derive agent_id from asset
                                agent_id = f"{asset.upper()}_15M"
                                position_notional_usd = (pre_contracts * price_cents) / 100.0
                                envelope.record_position_closure(
                                    agent_id=agent_id,
                                    position_notional_usd=position_notional_usd,
                                    asset=asset.upper()
                                )
                                logger.info(
                                    "[POSITION-CACHE] Recorded window exposure reduction: agent=%s notional=$%.2f",
                                    agent_id, position_notional_usd
                                )
                    except Exception as window_err:
                        logger.warning("[POSITION-CACHE] Failed to record window exposure reduction: %s", window_err)

                    # SELL-SIDE FIX: Release contract lease when position is fully closed
                    # This ensures the lease is freed for future orders and prevents
                    # potential lease conflicts if the lease expires before renewal.
                    # Note: Uses "default" strategy_group since CachedPosition doesn't track it.
                    # The lease system allows same-owner renewal, so this is cleanup-only.
                    try:
                        from merid.event_venues.kalshi.contract_lease import (
                            get_contract_lease_registry,
                            LeaseKey,
                        )
                        registry = get_contract_lease_registry()
                        lease_key = LeaseKey(
                            venue="kalshi",
                            contract_id=market_id,
                            side=position.side,
                            strategy_group="default",
                        )
                        released = registry.release(lease_key, owner_agent_id="position_cache")
                        if released:
                            logger.info(
                                "[LEASE-RELEASE] Released lease for closed position: market=%s side=%s",
                                market_id, position.side
                            )
                    except Exception as lease_exc:
                        logger.debug(
                            "[LEASE-RELEASE] Failed to release lease for %s (non-fatal): %s",
                            market_id, lease_exc
                        )

                    # Calculate realized R before closing
                    realized_r = 0.0
                    if position.stop_loss_price_cents and position.stop_loss_price_cents > 0:
                        risk_cents = abs(position.avg_price_cents - position.stop_loss_price_cents)
                        if risk_cents > 0:
                            if position.side == "yes":
                                pnl_cents = price_cents - position.avg_price_cents
                            else:
                                pnl_cents = position.avg_price_cents - price_cents
                            realized_r = pnl_cents / risk_cents

                    logger.info(
                        "[EXIT] market=%s side=%s reason=MANUAL realized_R=%.2f asset=N/A confidence=N/A time_in_trade=N/A",
                        market_id, position.side, realized_r
                    )

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

            # 2026 Research-Based Risk Management: Update agent grid session tracking
            # This integrates session limit, consecutive loss pause, and session risk cap
            try:
                from merid.prediction.agent_grid_15m import get_agent_grid
                from config.kalshi_crypto_config import kalshi_ticker_to_asset
                
                grid = get_agent_grid()
                if grid and grid._agents:
                    # Extract asset from ticker
                    asset = kalshi_ticker_to_asset(market_id)
                    if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        asset_upper = asset.upper()
                        
                        # Find the agent for this asset
                        for agent in grid._agents:
                            if agent.config.name.startswith(asset_upper):
                                # Calculate PnL and trade risk
                                pnl_usd = 0.0
                                trade_risk_usd = 0.0
                                
                                if position is None:
                                    # New position: calculate trade risk as contracts * price
                                    trade_risk_usd = (contracts * price_cents) / 100.0
                                elif position.contracts == 0:
                                    # Position closed: calculate realized PnL
                                    # For YES: pnl = (exit_price - entry_price) * contracts
                                    # For NO: pnl = (entry_price - exit_price) * contracts
                                    if position.side == "yes":
                                        pnl_cents = price_cents - position.avg_price_cents
                                    else:
                                        pnl_cents = position.avg_price_cents - price_cents
                                    pnl_usd = (pnl_cents * pre_contracts) / 100.0
                                
                                # Call update_cooldown_on_fill with PnL and trade risk
                                agent.update_cooldown_on_fill(
                                    asset=asset_upper,
                                    pnl_usd=pnl_usd,
                                    trade_risk_usd=trade_risk_usd
                                )
                                logger.info(
                                    "[AGENT-GRID-SESSION] Updated session tracking: asset=%s pnl=%.2f trade_risk=%.2f",
                                    asset_upper, pnl_usd, trade_risk_usd
                                )
                                break
            except Exception as agent_err:
                logger.debug("[POSITION-CACHE] Failed to update agent grid session tracking: %s", agent_err)

    async def update_position_price(self, market_id: str, price_cents: int) -> None:
        """Update current price and unrealized PnL when market price changes.
        
        CRITICAL FIX: This updates current_price_cents for micro-scalp PnL calculation.
        Without this, micro-scalp exits with $0 PnL because current_price_cents is stale.
        
        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._ensure_mutex():
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
    
    def get_total_exposure_usd(self) -> float:
        """Get total exposure in USD across all open positions.
        
        This is used for sequential trading checks to ensure $1 max exposure.
        
        Returns:
            Total exposure in USD (sum of contracts * price for all open positions)
        """
        total_exposure = 0.0
        for position in self._positions.values():
            if position.contracts > 0:
                # Exposure = contracts * price_cents / 100
                position_exposure = (position.contracts * position.avg_price_cents) / 100.0
                total_exposure += position_exposure
        return total_exposure
    
    def get_cache_health(self) -> Dict[str, Any]:
        """Get position cache health status for monitoring.
        
        Returns:
            Dict with health metrics including staleness, position count, and sync status.
        """
        from datetime import datetime, timezone
        
        staleness_seconds = 0.0
        if self._last_sync:
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
        
        open_positions = {k: v for k, v in self._positions.items() if v.contracts > 0}
        
        return {
            "last_sync_timestamp": self._last_sync.isoformat() if self._last_sync else None,
            "staleness_seconds": staleness_seconds,
            "is_stale": staleness_seconds > 300,  # 5 minutes
            "total_positions": len(self._positions),
            "open_positions": len(open_positions),
            "closed_positions": len(self._positions) - len(open_positions),
            "monitoring_enabled": self._monitoring_enabled,
        }

    def get_open_positions(self, market_id: str) -> List[CachedPosition]:
        """Get all open positions for a market (returns list for compatibility).
        
        Returns empty list if no position, or list with single position if exists.
        """
        position = self._positions.get(market_id)
        if position and position.contracts > 0:
            return [position]
        return []

    def get_asset_exposure(self, asset: str) -> Dict[str, Any]:
        """Get total exposure for an asset across all markets.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")

        Returns:
            Dict with exposure metrics:
            - total_contracts: Total contracts held
            - total_notional_usd: Total notional value in USD
            - unrealized_pnl_usd: Total unrealized PnL in USD
            - position_count: Number of markets with positions
        """
        total_contracts = 0
        total_notional_usd = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        position_count = 0

        for market_id, position in self._positions.items():
            # Check if this position belongs to the requested asset
            # Market IDs are like KXBTC15M-26MAY241245-45
            if asset.upper() in market_id.upper():
                if position.contracts > 0:
                    total_contracts += position.contracts
                    total_notional_usd += position.notional_usd
                    total_unrealized_pnl += position.unrealized_pnl_usd
                    position_count += 1

        return {
            "total_contracts": total_contracts,
            "total_notional_usd": float(total_notional_usd),
            "unrealized_pnl_usd": float(total_unrealized_pnl),
            "position_count": position_count,
        }

    async def sync_from_rest(self, positions: list, rest_timestamp: Optional[float] = None, force: bool = False) -> None:
        """Sync cache with REST API positions (fallback/reconciliation).
        
        BUG-FIX: Now async with mutex protection for thread safety.
        PRODUCTION FIX (2026-05-10): Filter out test positions to prevent bleeding into production.
        PRODUCTION FIX (2026-05-11): Filter out closed positions (contracts=0) to prevent phantom positions.
        STALENESS GUARD (2026-05-22): Reject REST snapshots older than local cache to prevent stale overwrites.
        FORCE SYNC (2026-07-03): Added force parameter to bypass staleness guard for manual reconciliation.
        
        Args:
            positions: List of position dicts from REST API
            rest_timestamp: Unix timestamp when REST snapshot was fetched. If None, uses current time.
            force: If True, bypass staleness guard and force sync (use for manual reconciliation).
        """
        # Use current time if no timestamp provided
        if rest_timestamp is None:
            rest_timestamp = _time.time()
        
        # Staleness check: reject if REST snapshot is older than local cache (unless force=True)
        if not force and self._last_sync:
            local_sync_time = self._last_sync.timestamp()
            age_seconds = rest_timestamp - local_sync_time
            
            # If REST snapshot is older than local cache by more than 30s, reject it
            if age_seconds < -30.0:
                logger.warning(
                    "[POSITION-CACHE-STALE] Rejecting REST snapshot older than local cache: "
                    f"REST timestamp={rest_timestamp:.0f}, local sync={local_sync_time:.0f}, "
                    f"age={age_seconds:.1f}s (threshold=-30s). Preserving local state."
                )
                return
        
        async with self._ensure_mutex():
            try:
                self._positions.clear()
                positions_processed = 0
                positions_filtered = 0
                
                for pos in positions:
                    market_id = pos.get("market_id") or pos.get("ticker")
                    if not market_id:
                        continue
                    
                    # DEBUG: Log all positions from API before filtering
                    logger.info(
                        f"[POSITION-CACHE-DEBUG] API returned position: market_id={market_id} "
                        f"contracts={pos.get('contracts', 0)} side={pos.get('side', 'yes')} "
                        f"avg_price_cents={pos.get('avg_price_cents', 'N/A')}"
                    )
                    
                    # PRODUCTION FIX (2026-05-10): Filter out test positions
                    if _is_test_ticker(market_id):
                        logger.warning(f"Skipping test ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    # PRODUCTION FIX (2026-07-03): Filter out expired positions
                    # Expired markets should not be in the cache as they can't be traded
                    if _is_expired_ticker(market_id):
                        logger.warning(f"Skipping expired ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    contracts = int(pos.get("contracts", 0))
                    
                    # PRODUCTION FIX (2026-05-11): Only cache open positions (contracts > 0)
                    # Closed positions (contracts=0) should not be in the cache
                    if contracts == 0:
                        logger.warning(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
                        positions_filtered += 1
                        continue
                    
                    # CRITICAL FIX (2026-07-06): Filter out negative contracts
                    # Negative contracts indicate a side inversion or data error from Kalshi API
                    # Example: contracts=-1 side=yes could actually be a NO position
                    if contracts < 0:
                        logger.warning(
                            f"Skipping invalid position in position cache sync: {market_id} "
                            f"(contracts={contracts} side={pos.get('side', 'yes')}) - negative contracts indicate side inversion or API error"
                        )
                        positions_filtered += 1
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
                        # Preserve ratchet state from cache if available (defaults to inactive)
                        ratchet_activated=pos.get("ratchet_activated", False),
                        ratchet_floor_price_cents=pos.get("ratchet_floor_price_cents"),
                        ratchet_activation_timestamp=pos.get("ratchet_activation_timestamp"),
                    )
                    positions_processed += 1

                # CRITICAL FIX: Always update _last_sync even when no positions pass filters
                self._last_sync = datetime.now(timezone.utc)
                logger.info(f"Position cache synced from REST: {positions_processed} open positions, {positions_filtered} filtered (test & closed)")
                # AUDIT #1: Log position cache health after successful sync
                self.log_health()
            except Exception as e:
                logger.error(f"Position cache sync from REST failed: {e}")

    def log_health(self) -> None:
        """Log position cache health metrics for AUDIT #1.
        
        Logs:
        - Last successful sync time
        - Number of open positions
        - Per-asset net exposure
        """
        from datetime import datetime, timezone
        
        # Log last sync time
        if self._last_sync:
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
            logger.info(
                "[POSITION-CACHE-HEALTH] last_sync=%s staleness=%.1fs",
                self._last_sync.isoformat(),
                staleness_seconds
            )
        else:
            logger.warning("[POSITION-CACHE-HEALTH] last_sync=NEVER (cache never synced)")
        
        # Log total open positions
        open_positions = [p for p in self._positions.values() if p.contracts > 0]
        logger.info(
            "[POSITION-CACHE-HEALTH] total_positions=%d open_positions=%d",
            len(self._positions),
            len(open_positions)
        )
        
        # Log per-asset exposure
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            exposure = self.get_asset_exposure(asset)
            logger.info(
                "[POSITION-CACHE-HEALTH] asset=%s contracts=%d notional=%.2f unrealized_pnl=%.2f position_count=%d",
                asset,
                exposure["total_contracts"],
                exposure["total_notional_usd"],
                exposure["unrealized_pnl_usd"],
                exposure["position_count"]
            )

    def is_healthy(self, max_staleness_seconds: float = 60.0) -> bool:
        """Check if position cache is healthy for trading operations.
        
        Health criteria:
        - Cache has been synced at least once (last_sync is not None)
        - Last sync is within max_staleness_seconds (default 60s)
        
        Args:
            max_staleness_seconds: Maximum allowed staleness in seconds
        
        Returns:
            True if cache is healthy, False otherwise
        """
        from datetime import datetime, timezone
        
        if self._last_sync is None:
            logger.warning("[POSITION-CACHE-HEALTH-GUARD] Cache never synced - unhealthy")
            return False
        
        staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
        if staleness_seconds > max_staleness_seconds:
            logger.warning(
                "[POSITION-CACHE-HEALTH-GUARD] Cache too stale: %.1fs > %.1fs - unhealthy",
                staleness_seconds,
                max_staleness_seconds
            )
            return False
        
        return True

    def is_position_healthy(self, market_id: str) -> bool:
        """Check if position has proper exit metadata.
        
        Args:
            market_id: The market ID to check
            
        Returns:
            True if position is healthy (has exit metadata), False otherwise
        """
        return market_id not in self._unhealthy_positions
    
    def get_unhealthy_positions(self) -> List[str]:
        """Get list of unhealthy positions for alerting.
        
        Returns:
            List of market IDs that are unhealthy (missing exit metadata)
        """
        return list(self._unhealthy_positions)
    
    def log_unhealthy_positions(self) -> None:
        """Log unhealthy positions for audit."""
        if self._unhealthy_positions:
            logger.warning(
                "[POSITION-CACHE] Unhealthy positions (missing exit metadata): %s",
                self._unhealthy_positions
            )

    async def clear(self) -> None:
        """Clear all cached positions.
        
        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._ensure_mutex():
            self._positions.clear()
            logger.info("Position cache cleared")
    
    def clear_sync(self) -> None:
        """Synchronous version of clear() for use in non-async contexts.
        
        This bypasses the mutex for simplicity when called from __init__ or other
        synchronous contexts where the event loop is not available.
        """
        self._positions.clear()
        logger.info("Position cache cleared (sync)")
    
    async def clear_expired_positions(self) -> int:
        """Remove positions with expired tickers from the cache.
        
        This should be called periodically (e.g., every 15 minutes at window rollover)
        to ensure the cache doesn't accumulate stale positions from expired markets.
        
        Returns:
            Number of positions removed.
        """
        async with self._ensure_mutex():
            removed_count = 0
            expired_tickers = []
            
            for ticker, position in list(self._positions.items()):
                if _is_expired_ticker(ticker):
                    expired_tickers.append(ticker)
                    del self._positions[ticker]
                    removed_count += 1
            
            if removed_count > 0:
                logger.info(
                    f"[POSITION-CACHE-CLEANUP] Removed {removed_count} expired positions: {expired_tickers}"
                )
                # Log cache health after cleanup
                self.log_health()
            
            return removed_count

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
        async with self._ensure_mutex():
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
        bucket = int(_time.time() // 60)
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

    def _calculate_dynamic_max_hold_seconds(self, market_id: str) -> int:
        """Calculate dynamic max hold time based on remaining time-to-expiry.
        
        CRITICAL FIX: Prevents holding past contract expiry when entering late in the 15m window.
        Research-based approach from Tradewink: Use 80% of remaining TTE to allow execution buffer.
        Source: https://www.tradewink.com/glossary/time-decay-exit
        
        Logic:
        - Parse market ID to extract expiry timestamp (format: KXBTC15M-26JUL191645-45)
        - Calculate remaining seconds to expiry
        - Return 80% of remaining TTE (allows 20% buffer for order execution)
        - Fallback to 300s (5 min) if TTE cannot be determined (conservative)
        
        Example:
        - Enter at 8 min into 15m window → 7 min (420s) remaining
        - Dynamic max_hold = 420 * 0.8 = 336s (5.6 min)
        - This ensures exit before expiry with execution buffer
        """
        try:
            import re
            from datetime import datetime, timezone
            
            # Kalshi market ID format: KX{COIN}15M-{DD}{MON}{HHMM}-{STRIKE}
            # Example: KXBTC15M-26JUL191645-45
            match = re.search(r'KX\w+15M-(\d{2})([A-Z]{3})(\d{4})', market_id)
            if not match:
                logger.warning("[DYNAMIC-HOLD] Could not parse market ID for TTE: %s", market_id)
                return 300  # Conservative 5-minute fallback
            
            day_str, month_str, time_str = match.groups()
            
            # Parse month abbreviation
            month_map = {
                'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
            }
            month = month_map.get(month_str.upper())
            if not month:
                logger.warning("[DYNAMIC-HOLD] Invalid month in market ID: %s", month_str)
                return 300
            
            # Parse time (HHMM format)
            hour = int(time_str[:2])
            minute = int(time_str[2:])
            
            # Calculate expiry timestamp (assume current year, UTC)
            now = datetime.now(timezone.utc)
            year = now.year
            expiry_dt = datetime(year, month, int(day_str), hour, minute, 0, tzinfo=timezone.utc)
            
            # If expiry is in the past, it's next year (unlikely but defensive)
            if expiry_dt < now:
                expiry_dt = expiry_dt.replace(year=year + 1)
            
            # Calculate remaining seconds
            remaining_seconds = (expiry_dt - now).total_seconds()
            
            # Use 80% of remaining TTE (20% buffer for execution)
            dynamic_max_hold = int(remaining_seconds * 0.8)
            
            # Sanity checks
            if dynamic_max_hold < 60:  # Minimum 1 minute
                logger.warning("[DYNAMIC-HOLD] Calculated max_hold too low (%ds), using 60s", dynamic_max_hold)
                dynamic_max_hold = 60
            elif dynamic_max_hold > 600:  # Maximum 10 minutes (safety cap)
                logger.info("[DYNAMIC-HOLD] Capping max_hold at 600s (calculated: %ds)", dynamic_max_hold)
                dynamic_max_hold = 600
            
            logger.info(
                "[DYNAMIC-HOLD] market=%s remaining_tte=%ds dynamic_max_hold=%ds",
                market_id, int(remaining_seconds), dynamic_max_hold
            )
            
            return dynamic_max_hold
            
        except Exception as e:
            logger.warning("[DYNAMIC-HOLD] Failed to calculate dynamic max_hold: %s, using fallback 300s", e)
            return 300  # Conservative 5-minute fallback

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

        # CRITICAL FIX: Calculate dynamic max_hold_seconds based on remaining time-to-expiry
        # This prevents holding past contract expiry when entering late in the 15m window
        # Research-based approach: Use 80% of remaining TTE to allow execution buffer
        # Source: https://www.tradewink.com/glossary/time-decay-exit
        max_hold_seconds = self._calculate_dynamic_max_hold_seconds(position.market_id)

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
            # CRITICAL FIX: Add exit policy metadata to satisfy validation for exit orders
            # Exit orders require exit_policy_id for tracking per _validate_risk_contract_linkage
            exit_policy_id=position.exit_policy_id or "bracket_exit",
            window_resolution_id=position.window_resolution_id or "bracket_window",
            risk_tier="A",  # Default to tier A for bracket exits
            max_hold_seconds=max_hold_seconds,  # Dynamic based on remaining TTE
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
                # CRITICAL FIX: Add exit policy metadata to satisfy validation for exit orders
                # Exit orders require exit_policy_id for tracking per _validate_risk_contract_linkage
                exit_policy_id=position.exit_policy_id or "bracket_exit",
                window_resolution_id=position.window_resolution_id or "bracket_window",
                risk_tier="A",  # Default to tier A for bracket exits
                max_hold_seconds=max_hold_seconds,  # Dynamic based on remaining TTE
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

    # ── Trailing Stop Monitoring (TUNED 2026-05-25) ─────────────────────────────

    def start_monitoring(self) -> None:
        """Start the trailing stop monitoring loop.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor (merid/position_management/position_monitor.py)
        This prevents duplicate monitoring loops and ensures proper callback routing for all exit conditions.
        
        PositionMonitor now handles:
        - Extreme profit exits (99c YES / 1c NO)
        - Dynamic take profit (laddered exits)
        - Ratchet profit floor and trimming
        - Trailing stop activation
        - Stop loss / take profit triggers
        - Staged time-based exits (re-implemented from this class)
        - Exit policy resolution (time stop, edge decay, risk, candle reversal)
        
        This class (KalshiPositionCache) now only handles:
        - Position state management (fills, PnL, metadata)
        - Position cache and exposure tracking
        - Integration with PositionMonitor for position addition
        """
        logger.info("[TRAIL-MONITOR] start_monitoring called - DISABLED (delegated to PositionMonitor)")
        logger.info("[TRAIL-MONITOR] PositionMonitor is now the authoritative exit system")
        # No-op - PositionMonitor handles all exit monitoring

    def stop_monitoring(self) -> None:
        """Stop the trailing stop monitoring loop.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor.
        This is a no-op for backward compatibility.
        """
        logger.info("[TRAIL-MONITOR] stop_monitoring called - DISABLED (delegated to PositionMonitor)")
        # No-op - PositionMonitor handles all exit monitoring

    async def _monitor_positions_loop(self) -> None:
        """Background loop that monitors positions for trailing stop activation and time-based forced exit.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor (merid/position_management/position_monitor.py)
        This method is a no-op for backward compatibility.
        
        All exit monitoring is now handled by PositionMonitor:
        - Extreme profit exits (99c YES / 1c NO)
        - Dynamic take profit (laddered exits)
        - Ratchet profit floor and trimming
        - Trailing stop activation
        - Stop loss / take profit triggers
        - Staged time-based exits
        - Exit policy resolution
        """
        logger.warning("[TRAIL-MONITOR] _monitor_positions_loop called - DISABLED (delegated to PositionMonitor)")
        # No-op - PositionMonitor handles all exit monitoring
        return

    def _emit_health_alert(self, alert_type: str, details: str) -> None:
        """Emit health alert for monitoring.
        
        Args:
            alert_type: Type of alert (e.g., "monitoring_loop_slow", "monitoring_loop_error")
            details: Additional details about the alert
        """
        try:
            from monitoring.metrics import get_metrics_registry
            reg = get_metrics_registry()
            counter = reg.counter(
                "merid_position_monitor_health_alerts_total",
                help_text="Position monitor health alerts",
                label_names=["alert_type"]
            )
            counter.labels(alert_type=alert_type).inc()
        except Exception as e:
            logger.debug("[TRAIL-MONITOR] Failed to emit health alert: %s", e)

    def _trigger_trading_halt(self, reason: str) -> None:
        """Trigger trading halt due to monitoring failure.
        
        Args:
            reason: Reason for the trading halt
        """
        try:
            from merid.governance.adaptive_risk_limits import get_adaptive_risk_limits
            risk_limits = get_adaptive_risk_limits()
            risk_limits.emergency_halt = True
            risk_limits.emergency_halt_reason = f"Position monitoring failure: {reason}"
            logger.critical("[TRAIL-MONITOR] Trading halt triggered: %s", reason)
        except Exception as e:
            logger.critical("[TRAIL-MONITOR] Failed to trigger trading halt: %s", e)


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
