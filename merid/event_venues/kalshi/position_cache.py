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
        
        # CRITICAL FIX: Register exit intent callback for PositionMonitor
        # This ensures extreme profit exits (99c YES / 1c NO) actually place orders
        self._register_exit_intent_callback()
        
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

    def _register_exit_intent_callback(self) -> None:
        """Register exit intent callback with PositionMonitor.
        
        CRITICAL FIX: This callback is triggered when PositionMonitor detects
        extreme profit exits (99c YES / 1c NO) or other exit conditions.
        It creates an OrderIntent and routes it through the order router to
        actually place the exit order.
        
        Without this callback, the PositionMonitor would detect the exit condition
        but no order would be placed, leaving the position open.
        """
        try:
            from merid.position_management.position_monitor import get_position_monitor
            from merid.position_management.exit_policy import ExitReason
            
            monitor = get_position_monitor()
            
            def exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close=None):
                """Callback to place exit order when PositionMonitor triggers exit.
                
                Args:
                    position: Position object from PositionMonitor
                    exit_reason: ExitReason enum (EXTREME_PROFIT, STOP_LOSS, TAKE_PROFIT, etc.)
                    exit_price_cents: Exit price in cents
                    contracts_to_close: Optional number of contracts for partial exits (scale-out)
                """
                try:
                    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
                    from merid.position_management.position import PositionSide
                    
                    # Determine exit side and action
                    # For YES positions: exit by selling YES
                    # For NO positions: exit by buying YES (to close the NO)
                    if position.side == PositionSide.YES:
                        exit_action = "sell"
                        exit_side = "yes"
                    else:  # NO position
                        exit_action = "buy"
                        exit_side = "yes"
                    
                    # Determine order size (full position or partial scale-out)
                    exit_size = contracts_to_close if contracts_to_close else position.size
                    
                    # Determine order type based on exit reason
                    # Extreme profit exits use market orders for immediate execution
                    # Other exits use limit orders for better fill prices
                    if exit_reason == ExitReason.EXTREME_PROFIT:
                        order_type = "market"
                        time_in_force = "ioc"  # Immediate or cancel
                        logger.info(
                            "[EXIT-CALLBACK] EXTREME-PROFIT exit: market order for immediate execution "
                            "position=%s side=%s size=%d price=%dc",
                            position.position_id[:8], position.side.value, exit_size, exit_price_cents
                        )
                    else:
                        order_type = "limit"
                        time_in_force = "gtc"  # Good till cancelled
                        logger.info(
                            "[EXIT-CALLBACK] %s exit: limit order for better fill "
                            "position=%s side=%s size=%d price=%dc",
                            exit_reason.value, position.position_id[:8], position.side.value, exit_size, exit_price_cents
                        )
                    
                    # Create exit intent
                    exit_intent = OrderIntent(
                        ticker=position.market_id,
                        side=exit_side,
                        action=exit_action,
                        price_cents=exit_price_cents,
                        count=exit_size,
                        order_type=order_type,
                        time_in_force=time_in_force,
                        source="position_monitor",
                        agent_id="position_monitor",
                        rationale=f"Exit triggered: {exit_reason.value}",
                    )
                    
                    # Submit order asynchronously
                    async def submit_exit():
                        try:
                            result = await route_order_async(exit_intent)
                            logger.info(
                                "[EXIT-CALLBACK] Exit order submitted: position=%s status=%s reason=%s",
                                position.position_id[:8], result.status, result.reason
                            )
                            
                            # Record exit in RoundTripMonitor if entry intent ID is available
                            if hasattr(position, 'exit_policy_id') and position.exit_policy_id:
                                try:
                                    from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
                                    rt_monitor = get_round_trip_monitor()
                                    rt_monitor.record_exit(
                                        exit_intent_id=exit_intent.intent_id,
                                        entry_intent_id=position.exit_policy_id,
                                        exit_price_cents=exit_price_cents,
                                        exit_reason=exit_reason.value,
                                    )
                                    logger.info(
                                        "[EXIT-CALLBACK] Recorded exit in RoundTripMonitor: position=%s",
                                        position.position_id[:8]
                                    )
                                except Exception as rt_err:
                                    logger.debug("[EXIT-CALLBACK] Failed to record exit in RoundTripMonitor: %s", rt_err)
                        except Exception as submit_err:
                            logger.error(
                                "[EXIT-CALLBACK] Failed to submit exit order: position=%s error=%s",
                                position.position_id[:8], submit_err, exc_info=True
                            )
                    
                    # Schedule async submission
                    import asyncio
                    loop = asyncio.get_event_loop()
                    loop.create_task(submit_exit())
                    
                except Exception as callback_err:
                    logger.error(
                        "[EXIT-CALLBACK] Exit intent callback failed: position=%s error=%s",
                        position.position_id[:8], callback_err, exc_info=True
                    )
            
            # Register the callback
            monitor.register_exit_intent_callback(exit_intent_callback)
            logger.info("[POSITION-CACHE] Registered exit intent callback with PositionMonitor")
            
        except Exception as init_err:
            logger.error("[POSITION-CACHE] Failed to register exit intent callback: %s", init_err, exc_info=True)

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
                    
                    tp_r = tp_targets.get("tp_r", 1.0)
                    sl_price = tp_targets.get("sl_price", price_cents - 5)
                    risk_cents = abs(price_cents - sl_price) if sl_price else 5
                    
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
                    
                    monitor_position = Position(
                        position_id=market_id,  # Use market_id as position_id
                        market_id=market_id,
                        side=side_enum,
                        size=contracts,
                        avg_entry_price_cents=price_cents,
                        take_profit_price_cents=tp_targets.get("tp_price"),
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
                    
                    # PRODUCTION FIX (2026-05-10): Filter out test positions
                    if _is_test_ticker(market_id):
                        logger.debug(f"Skipping test ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    # PRODUCTION FIX (2026-07-03): Filter out expired positions
                    # Expired markets should not be in the cache as they can't be traded
                    if _is_expired_ticker(market_id):
                        logger.debug(f"Skipping expired ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    contracts = int(pos.get("contracts", 0))
                    
                    # PRODUCTION FIX (2026-05-11): Only cache open positions (contracts > 0)
                    # Closed positions (contracts=0) should not be in the cache
                    if contracts == 0:
                        logger.debug(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
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

    # ── Trailing Stop Monitoring (TUNED 2026-05-25) ─────────────────────────────

    def start_monitoring(self) -> None:
        """Start the trailing stop monitoring loop.

        This should be called during application startup if trailing is enabled.
        The loop runs every 5 seconds and checks positions for trailing activation.
        """
        logger.info("[TRAIL-MONITOR] start_monitoring called, enabled=%s, interval=%s", self._monitoring_enabled, self._monitoring_interval_seconds)
        if self._monitoring_enabled:
            logger.warning("[TRAIL-MONITOR] Already running, ignoring start request")
            return

        self._monitoring_enabled = True
        self._monitoring_task = asyncio.create_task(self._monitor_positions_loop())
        logger.info("[TRAIL-MONITOR] Started trailing stop monitoring loop (interval=%.1fs)", self._monitoring_interval_seconds)

    def stop_monitoring(self) -> None:
        """Stop the trailing stop monitoring loop.

        This should be called during application shutdown.
        """
        if not self._monitoring_enabled:
            return

        self._monitoring_enabled = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            self._monitoring_task = None
        logger.info("[TRAIL-MONITOR] Stopped trailing stop monitoring loop")

    async def _monitor_positions_loop(self) -> None:
        """Background loop that monitors positions for trailing stop activation and time-based forced exit.

        For each open position with TP/SL targets:
        1. Fetch current market price from market state
        2. Check time to expiry and force exit at cutoff (P0 FIX)
        3. Compute current PnL in R-multiples
        4. Check if trailing should activate (based on trailing_activation_r_multiple from config)
        5. If activated, compute new trailing stop and submit order to update SL
        """
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.prediction.dynamic_takeprofit import get_dtp_engine

        dtp_engine = get_dtp_engine()
        market_state_store = get_kalshi_market_state_store()

        # P3-FIX9: Get cutoff from profile (default 2 minutes)
        cutoff_minutes = 2  # Default fallback
        try:
            from pathlib import Path
            import yaml
            profile_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_yaml_path.exists():
                with open(profile_yaml_path, 'r', encoding='utf-8') as f:
                    profile_config = yaml.safe_load(f)
                cutoff_minutes = profile_config.get("exit_policy", {}).get("time_exit", {}).get("cutoff_minutes_before_expiry", 2)
                logger.info("[TRAIL-CONFIG] Loaded cutoff_minutes=%d from profile", cutoff_minutes)
        except Exception as exc:
            logger.warning("[TRAIL-CONFIG] Failed to load cutoff from profile, using default 2: %s", exc)

        logger.info("[TRAIL-MONITOR] Loop started, interval=%s, cutoff_minutes=%d", self._monitoring_interval_seconds, cutoff_minutes)

        while self._monitoring_enabled:
            try:
                async with self._ensure_mutex():
                    positions_snapshot = list(self._positions.values())

                logger.info("[TRAIL-MONITOR] Loop tick, positions=%d", len(positions_snapshot))

                for position in positions_snapshot:
                    # Skip positions without TP/SL targets or zero contracts
                    if position.contracts <= 0:
                        continue
                    if position.take_profit_price_cents is None or position.stop_loss_price_cents is None:
                        logger.error(
                            "[TRAIL-ERROR] market=%s side=%s has missing TP/SL metadata (tp=%s sl=%s) - position cannot be monitored for trailing",
                            position.market_id, position.side, position.take_profit_price_cents, position.stop_loss_price_cents
                        )
                        continue

                    # Get current market price
                    state = market_state_store.get_unified(position.market_id)
                    if not state or state.mid_cents <= 0:
                        continue

                    current_price_cents = state.mid_cents
                    entry_price_cents = position.avg_price_cents
                    sl_price_cents = position.stop_loss_price_cents

                    # P0 FIX: Staged time-based exits for volatile markets
                    # Load staged exit configuration from profile
                    staged_exit_enabled = False
                    staged_exit_stages = []
                    try:
                        from pathlib import Path
                        import yaml
                        profile_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
                        if profile_yaml_path.exists():
                            with open(profile_yaml_path, 'r', encoding='utf-8') as f:
                                profile_config = yaml.safe_load(f)
                            staged_exit_config = profile_config.get("staged_time_exit", {})
                            staged_exit_enabled = staged_exit_config.get("enabled", False)
                            staged_exit_stages = staged_exit_config.get("stages", [])
                    except Exception as exc:
                        logger.warning("[STAGED-EXIT] Failed to load staged exit config: %s", exc)
                    
                    if state.seconds_to_expiry is not None:
                        time_to_expiry_minutes = state.seconds_to_expiry / 60.0
                        time_since_entry_minutes = (state.seconds_to_expiry / 60.0) - 15.0  # Approximate time since entry (15m window)
                        if time_since_entry_minutes < 0:
                            time_since_entry_minutes = 0
                        
                        # Check staged exits if enabled
                        if staged_exit_enabled and staged_exit_stages:
                            for stage_idx, stage in enumerate(staged_exit_stages):
                                stage_minutes = stage.get("minutes", 0)
                                stage_percent = stage.get("percent", 0)
                                
                                # Check if we've reached this stage time
                                if time_since_entry_minutes >= stage_minutes:
                                    # Check if this stage has already been executed
                                    stage_key = f"stage_{stage_idx}"
                                    if not getattr(position, stage_key + "_executed", False):
                                        # Calculate contracts to close for this stage
                                        contracts_to_close = int(position.contracts * (stage_percent / 100.0))
                                        
                                        if contracts_to_close >= 1:
                                            logger.info(
                                                "[STAGED-EXIT] market=%s side=%s stage=%d minutes=%d percent=%d%% time_since=%.1fmin closing %d contracts",
                                                position.market_id, position.side, stage_idx, stage_minutes, stage_percent, time_since_entry_minutes, contracts_to_close
                                            )
                                            
                                            # Submit partial exit order
                                            try:
                                                from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
                                                
                                                # Determine exit side
                                                if position.side == "yes":
                                                    exit_action = "sell"
                                                    exit_side = "yes"
                                                else:  # "no"
                                                    exit_action = "buy"
                                                    exit_side = "yes"
                                                
                                                # Create staged exit intent (limit order for better fill)
                                                staged_exit_intent = OrderIntent(
                                                    ticker=position.market_id,
                                                    side=exit_side,
                                                    action=exit_action,
                                                    price_cents=current_price_cents,
                                                    count=contracts_to_close,
                                                    order_type="limit",
                                                    time_in_force="gtc",
                                                    source="staged_time_exit",
                                                    agent_id="position_cache",
                                                    rationale=f"Staged exit stage {stage_idx}: {stage_percent}% at {stage_minutes}min",
                                                )
                                                
                                                # Submit order asynchronously
                                                result = await route_order_async(staged_exit_intent)
                                                logger.info(
                                                    "[STAGED-EXIT] market=%s submitted staged exit order: status=%s reason=%s",
                                                    position.market_id, result.status, result.reason
                                                )
                                                
                                                # Mark stage as executed
                                                setattr(position, stage_key + "_executed", True)
                                                setattr(position, stage_key + "_timestamp", datetime.utcnow())
                                                
                                                # Update position contracts count
                                                position.contracts -= contracts_to_close
                                                
                                                # Mark exit reason in RoundTripMonitor for partial exit
                                                from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
                                                rt_monitor = get_round_trip_monitor()
                                                if position.entry_intent_id:
                                                    rt_monitor.record_exit(
                                                        exit_intent_id=staged_exit_intent.intent_id,
                                                        entry_intent_id=position.entry_intent_id,
                                                        exit_price_cents=current_price_cents,
                                                        exit_reason=f"staged_exit_stage_{stage_idx}",
                                                    )
                                                
                                            except Exception as exc:
                                                logger.error(
                                                    "[STAGED-EXIT] market=%s failed to submit staged exit order: %s",
                                                    position.market_id, exc, exc_info=True
                                                )
                        
                        # Fallback: single cutoff at 2 min (original logic)
                        if time_to_expiry_minutes <= cutoff_minutes:
                            logger.info(
                                "[TIME-EXIT] market=%s side=%s time_to_expiry=%.1fmin <= cutoff=%dmin forcing exit",
                                position.market_id, position.side, time_to_expiry_minutes, cutoff_minutes
                            )
                            # Submit market exit order via order router
                            try:
                                from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

                                # Determine exit side: closing YES long = sell YES, closing NO long = buy YES
                                # For YES positions: action="sell", side="yes"
                                # For NO positions: action="buy", side="yes" (to close the NO)
                                if position.side == "yes":
                                    exit_action = "sell"
                                    exit_side = "yes"
                                else:  # "no"
                                    exit_action = "buy"
                                    exit_side = "yes"

                                # Create exit intent
                                exit_intent = OrderIntent(
                                    ticker=position.market_id,
                                    side=exit_side,
                                    action=exit_action,
                                    price_cents=current_price_cents,  # Market price
                                    count=position.contracts,
                                    order_type="market",  # Market order for quick exit
                                    time_in_force="ioc",  # Immediate or cancel
                                    source="time_exit_monitor",
                                    agent_id="position_cache",
                                    rationale=f"Time-based forced exit at {time_to_expiry_minutes:.1f}min to expiry",
                                )

                                # Submit order asynchronously
                                result = await route_order_async(exit_intent)
                                logger.info(
                                    "[TIME-EXIT] market=%s submitted exit order: status=%s reason=%s",
                                    position.market_id, result.status, result.reason
                                )

                                # Mark exit reason in RoundTripMonitor
                                from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
                                rt_monitor = get_round_trip_monitor()
                                if position.entry_intent_id:
                                    rt_monitor.record_exit(
                                        exit_intent_id=exit_intent.intent_id,
                                        entry_intent_id=position.entry_intent_id,
                                        exit_price_cents=current_price_cents,
                                        exit_reason="time_exit",
                                    )
                                    logger.info(
                                        "[TIME-EXIT] market=%s recorded exit in RoundTripMonitor with reason=time_exit",
                                        position.market_id
                                    )
                                else:
                                    logger.warning(
                                        "[TIME-EXIT] market=%s exit submitted but RoundTripMonitor tracking incomplete (missing entry_intent_id)",
                                        position.market_id
                                    )

                            except Exception as exc:
                                logger.error(
                                    "[TIME-EXIT] market=%s failed to submit exit order: %s",
                                    position.market_id, exc, exc_info=True
                                )
                            continue

                    # P1 FIX: Partial profit taking (scale-out) at trigger threshold
                    # Load scale-out parameters from profile config
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        risk_envelope = get_kalshi_crypto_15m_risk_envelope()
                        scale_out_config = risk_envelope.profile.get('scale_out', {})
                        scale_out_trigger_r = scale_out_config.get('scale_out_trigger_r', 0.7)
                        scale_out_fraction = scale_out_config.get('scale_out_fraction', 0.5)
                    except Exception as config_err:
                        logger.warning("[SCALE-OUT] Failed to load scale-out config, using defaults: %s", config_err)
                        scale_out_trigger_r = 0.7
                        scale_out_fraction = 0.5
                    if not position.scale_out_complete and current_r >= scale_out_trigger_r:
                        size_to_sell = int(position.contracts * scale_out_fraction)
                        if size_to_sell >= 1:
                            logger.info(
                                "[SCALE-OUT] market=%s side=%s fraction=%.2f size=%d at %.2fR",
                                position.market_id, position.side, scale_out_fraction, size_to_sell, current_r
                            )
                            # Submit partial exit order via order router
                            try:
                                from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

                                # Determine exit side
                                if position.side == "yes":
                                    exit_action = "sell"
                                    exit_side = "yes"
                                else:  # "no"
                                    exit_action = "buy"
                                    exit_side = "yes"

                                # Create scale-out intent (limit order near current price)
                                scale_out_intent = OrderIntent(
                                    ticker=position.market_id,
                                    side=exit_side,
                                    action=exit_action,
                                    price_cents=current_price_cents,  # Limit at current price
                                    count=size_to_sell,
                                    order_type="limit",
                                    time_in_force="gtc",
                                    source="scale_out_monitor",
                                    agent_id="position_cache",
                                    rationale=f"Scale-out at {current_r:.2f}R (sell {scale_out_fraction:.0%} of position)",
                                )

                                # Submit order asynchronously
                                result = await route_order_async(scale_out_intent)
                                logger.info(
                                    "[SCALE-OUT] market=%s submitted scale-out order: status=%s reason=%s",
                                    position.market_id, result.status, result.reason
                                )

                                # Move stop loss to breakeven for remaining position
                                # Breakeven = entry price (no loss if stopped out)
                                new_sl_cents = entry_price_cents
                                logger.info(
                                    "[SCALE-OUT] market=%s moving SL to breakeven: old_sl=%dc new_sl=%dc",
                                    position.market_id, sl_price_cents, new_sl_cents
                                )
                                # Cancel existing SL bracket and submit new one at breakeven
                                if position.sl_bracket_client_tag:
                                    try:
                                        # Cancel only the SL bracket (preserve TP bracket)
                                        from merid.event_venues.kalshi.client_v2 import get_kalshi_client
                                        client = get_kalshi_client()
                                        sl_tag = position.sl_bracket_client_tag
                                        
                                        # Cancel the SL order
                                        try:
                                            await client.cancel_order_by_client_order_id(sl_tag)
                                            logger.info(
                                                "[SCALE-OUT] market=%s canceled old SL bracket: tag=%s",
                                                position.market_id, sl_tag
                                            )
                                        except Exception as cancel_exc:
                                            logger.warning(
                                                "[SCALE-OUT] market=%s failed to cancel SL bracket (non-fatal): %s",
                                                position.market_id, cancel_exc
                                            )
                                        
                                        # Submit new SL bracket at breakeven
                                        new_sl_tag = self._bracket_client_tag(position.market_id, "sl", new_sl_cents)
                                        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

                                        # Remaining contracts after scale-out
                                        # position.contracts already reflects the updated count after the partial fill
                                        remaining_contracts = position.contracts
                                        
                                        sl_intent = OrderIntent(
                                            ticker=position.market_id,
                                            side=position.side,
                                            action="sell",
                                            price_cents=int(new_sl_cents),
                                            count=int(remaining_contracts),
                                            source="scale_out_breakeven_sl",
                                            agent_id="position_cache_bracket",
                                            client_tag=new_sl_tag,
                                            group_id="bracket",
                                            rationale=f"breakeven_sl_after_scaleout:{position.market_id}:{new_sl_cents}c",
                                        )
                                        
                                        res = await route_order_async(sl_intent)
                                        ok = bool(getattr(res, "success", False))
                                        self._record_bracket_metric("sl", ok)
                                        
                                        # Update position with new SL tag and price
                                        position.sl_bracket_client_tag = new_sl_tag
                                        position.stop_loss_price_cents = new_sl_cents
                                        
                                        logger.info(
                                            "[SCALE-OUT] market=%s submitted new SL at breakeven: price=%dc contracts=%d tag=%s ok=%s",
                                            position.market_id, new_sl_cents, remaining_contracts, new_sl_tag, ok
                                        )
                                        
                                    except Exception as sl_exc:
                                        logger.error(
                                            "[SCALE-OUT] market=%s failed to update SL to breakeven: %s",
                                            position.market_id, sl_exc, exc_info=True
                                        )

                                # Mark scale-out as complete
                                position.scale_out_complete = True
                                logger.info(
                                    "[SCALE-OUT] market=%s scale-out complete, remaining contracts=%d",
                                    position.market_id, position.contracts - size_to_sell
                                )

                            except Exception as exc:
                                logger.error(
                                    "[SCALE-OUT] market=%s failed to submit scale-out order: %s",
                                    position.market_id, exc, exc_info=True
                                )

                    # Compute risk per contract (R)
                    risk_cents = abs(entry_price_cents - sl_price_cents)
                    if risk_cents == 0:
                        continue

                    # Compute current PnL in R-multiples
                    if position.side == "yes":
                        pnl_cents = current_price_cents - entry_price_cents
                    else:  # "no"
                        pnl_cents = entry_price_cents - current_price_cents
                    current_r = pnl_cents / risk_cents if risk_cents > 0 else 0.0

                    # RATCHET PROFIT FLOOR: Research-backed profit locking mechanism
                    # Activates when price reaches high threshold (e.g., 85¢) and sets a hard floor
                    # Prevents giving back significant gains when 99¢ TP is not guaranteed
                    # NOTE: Ratchet operates independently of trailing stop and takes precedence at high prices
                    # - Trailing stop: activates at 12¢ profit, trails 5¢ behind (low-mid range)
                    # - Ratchet: activates at 85¢ price, sets floor 5¢ below (high range)
                    # - When ratchet activates, it cancels existing TP/SL brackets to prevent conflicts
                    try:
                        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                        from merid.prediction.dynamic_takeprofit import get_dtp_engine
                        
                        if is_profile_active():
                            profile_adapter = get_active_profile()
                            profile = profile_adapter.profile
                            
                            if profile.ratchet_profit_floor_enabled:
                                dtp_engine = get_dtp_engine()
                                
                                # Check if ratchet should activate
                                if not position.ratchet_activated:
                                    # Create a temporary TakeProfitPlan with ratchet parameters
                                    from merid.prediction.dynamic_takeprofit import TakeProfitPlan
                                    ratchet_plan = TakeProfitPlan(
                                        tp_price=position.take_profit_price_cents or 99,
                                        tp_r_multiple=position.take_profit_r_multiple or 2.0,
                                        tp_level=type('obj', (object,), {'value': 'base'})(),
                                        ratchet_enabled=True,
                                        ratchet_activation_threshold_cents=profile.ratchet_activation_threshold_cents,
                                        ratchet_floor_offset_cents=profile.ratchet_floor_offset_cents,
                                        ratchet_force_exit_on_breach=profile.ratchet_force_exit_on_floor_breach,
                                        ratchet_min_hold_after_activation_sec=profile.ratchet_min_hold_after_activation_sec,
                                    )
                                    
                                    should_activate = dtp_engine.should_activate_ratchet(
                                        current_price_cents=current_price_cents,
                                        direction="LONG" if position.side == "yes" else "SHORT",
                                        plan=ratchet_plan
                                    )
                                    
                                    if should_activate:
                                        # Activate ratchet and set floor
                                        floor_price = dtp_engine.compute_ratchet_floor(
                                            activation_price_cents=current_price_cents,
                                            plan=ratchet_plan,
                                            direction="LONG" if position.side == "yes" else "SHORT"
                                        )
                                        
                                        position.ratchet_activated = True
                                        position.ratchet_floor_price_cents = floor_price
                                        position.ratchet_activation_timestamp = datetime.now(timezone.utc)
                                        
                                        logger.info(
                                            "[RATCHET-ACTIVATED] market=%s side=%s activation_price=%dc floor_price=%dc",
                                            position.market_id, position.side, current_price_cents, floor_price
                                        )
                                
                                # Check if ratchet floor is breached (mandatory exit)
                                elif position.ratchet_activated and position.ratchet_floor_price_cents is not None:
                                    activation_ts = position.ratchet_activation_timestamp.timestamp() if position.ratchet_activation_timestamp else None
                                    
                                    should_exit = dtp_engine.should_exit_on_ratchet_floor(
                                        current_price_cents=current_price_cents,
                                        floor_price_cents=position.ratchet_floor_price_cents,
                                        direction="LONG" if position.side == "yes" else "SHORT",
                                        activation_timestamp=activation_ts,
                                        min_hold_seconds=profile.ratchet_min_hold_after_activation_sec,
                                    )
                                    
                                    if should_exit and profile.ratchet_force_exit_on_floor_breach:
                                        logger.warning(
                                            "[RATCHET-FLOOR-BREACH] market=%s side=%s current=%dc floor=%dc - forcing exit",
                                            position.market_id, position.side, current_price_cents, position.ratchet_floor_price_cents
                                        )
                                        
                                        # Cancel existing TP/SL brackets before submitting ratchet exit
                                        # This prevents duplicate orders and ensures clean exit
                                        if position.tp_bracket_client_tag or position.sl_bracket_client_tag:
                                            try:
                                                await self._cancel_brackets(position)
                                                logger.info(
                                                    "[RATCHET-EXIT] market=%s canceled existing TP/SL brackets before ratchet exit",
                                                    position.market_id
                                                )
                                            except Exception as cancel_exc:
                                                logger.warning(
                                                    "[RATCHET-EXIT] market=%s failed to cancel brackets (non-fatal): %s",
                                                    position.market_id, cancel_exc
                                                )
                                        
                                        # Submit emergency exit order
                                        try:
                                            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
                                            
                                            # Determine exit side
                                            if position.side == "yes":
                                                exit_action = "sell"
                                                exit_side = "yes"
                                            else:  # "no"
                                                exit_action = "buy"
                                                exit_side = "yes"
                                            
                                            # Use aggressive market order for floor breach (fast exit)
                                            ratchet_exit_intent = OrderIntent(
                                                ticker=position.market_id,
                                                side=exit_side,
                                                action=exit_action,
                                                price_cents=current_price_cents - 1 if position.side == "yes" else current_price_cents + 1,  # Aggressive pricing
                                                count=position.contracts,
                                                order_type="market",
                                                source="ratchet_floor_breach",
                                                agent_id="position_cache",
                                                rationale=f"Ratchet floor breach: current={current_price_cents}c floor={position.ratchet_floor_price_cents}c",
                                            )
                                            
                                            result = await route_order_async(ratchet_exit_intent)
                                            logger.info(
                                                "[RATCHET-EXIT] market=%s submitted exit order: status=%s reason=%s",
                                                position.market_id, result.status, result.reason
                                            )
                                            
                                        except Exception as ratchet_exc:
                                            logger.error(
                                                "[RATCHET-EXIT] market=%s failed to submit exit order: %s",
                                                position.market_id, ratchet_exc, exc_info=True
                                            )
                    
                    except Exception as ratchet_exc:
                        logger.error(
                            "[RATCHET-ERROR] market=%s ratchet logic failed: %s",
                            position.market_id, ratchet_exc, exc_info=True
                        )

                    # P3-FIX8: Get trailing activation threshold from profile (min_profit_cents for 15m binary options)
                    # NOTE: PositionMonitor handles trailing activation using min_profit_cents (12¢ per 2026 research)
                    # This loop only handles time-based forced exit, not trailing activation
                    # Trailing activation is delegated to PositionMonitor to avoid duplicate logic

            except Exception as exc:
                logger.error("[TRAIL-MONITOR] Error in monitoring loop: %s", exc, exc_info=True)

            # Wait for next check interval
            await asyncio.sleep(self._monitoring_interval_seconds)

        logger.info("[TRAIL-MONITOR] Monitoring loop exited")


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
