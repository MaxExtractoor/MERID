"""Canonical Kalshi Fills Ledger — Single source of truth for all executed trades.

This module provides:
- KalshiFill: Data model for a single fill with all Kalshi fields + metadata
- KalshiFillsLedger: Dual-ingestion (HTTP + WebSocket) persistent store
- FillsReconciler: Validates computed positions vs Kalshi-reported positions
- IntentTracker: Tracks order intents and matches them to fills

Design principles:
1. Kalshi is the ONLY source of truth — we never fabricate fills
2. Dual ingestion (HTTP poller + WS) ensures completeness
3. Idempotent upserts prevent duplicates
4. All fills have fill_id from Kalshi — no exceptions
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import numbers
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fills_ledger")

# Test fixture fill ID prefixes — never from real Kalshi API
_TEST_FILL_PREFIXES = (
    "fill_integrity_", "fill_a_", "fill_b_", "fill_ghost_",
    "fill_immutable_", "fill_legit_", "fill_test_", "test_fill_",
    "fill_dup_", "fill_stale_",
)

def _is_test_fixture_fill(fill_id: str) -> bool:
    """Return True if fill_id looks like a test fixture, not a real Kalshi fill."""
    if not fill_id:
        return True
    return any(fill_id.startswith(p) for p in _TEST_FILL_PREFIXES)


class ReconciliationStatus(Enum):
    """Status of fills vs positions reconciliation."""
    OK = "ok"
    DEGRADED = "degraded"  # Minor discrepancies (< 5%)
    BROKEN = "broken"      # Significant divergence
    UNKNOWN = "unknown"    # Haven't run yet


@dataclass
class KalshiFill:
    """Canonical representation of a Kalshi fill/trade.
    
    All fields from Kalshi API preserved, plus MERID metadata.
    Primary key: fill_id (from Kalshi — never null for real fills)
    """
    # Kalshi core fields (from /portfolio/fills or WS)
    fill_id: str  # Kalshi's unique fill ID — THE primary key
    trade_id: Optional[str] = None  # May be same as fill_id or different
    order_id: Optional[str] = None  # Parent order ID
    market_ticker: str = ""  # e.g., "KXBTC-25DEC-ABOVE-100000"
    side: str = ""  # "yes" or "no"
    action: str = ""  # "buy" or "sell"
    count_fp: int = 0  # Number of contracts (fixed-point integer)
    yes_price_dollars: Optional[Decimal] = None  # Price if side=yes
    no_price_dollars: Optional[Decimal] = None  # Price if side=no
    fee_cost: Decimal = Decimal("0")  # Fee paid
    client_order_id: Optional[str] = None  # Our idempotency key
    subaccount_number: Optional[int] = None
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Idempotency and schema metadata (paper fills)
    idempotency_key: Optional[str] = None  # For replay-safety and dedupe
    canonical_hash_version: Optional[str] = None  # Schema version for hash evolution
    hash_preimage: Optional[str] = None  # Forensic debug: hash inputs
    
    # Raw preservation for debugging
    raw_payload: Optional[Dict[str, Any]] = None  # Original JSON from Kalshi
    
    # MERID metadata
    ingestion_source: str = ""  # "http_poller", "websocket", "backfill"
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: Optional[str] = None  # Which MERID agent generated the intent
    intent_id: Optional[str] = None  # Link to our intent record
    decision_trace_id: Optional[str] = None  # End-to-end audit: swarm → sizer → order
    
    # Reconciliation tracking
    reconciled: bool = False  # Has been matched to position ledger
    reconciliation_ts: Optional[datetime] = None
    
    # Strict mode tracking (production safety)
    derived_id: bool = False  # True if fill_id was synthesized (not from Kalshi)
    confirmed_by_rest: bool = False  # True if this fill was later confirmed by HTTP REST API
    
    def resolved_asset(self) -> Optional[str]:
        """Crypto asset code (BTC, ETH, …) from market ticker via canonical prefix map."""
        if not self.market_ticker:
            return None
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            return kalshi_ticker_to_asset(self.market_ticker)
        except Exception:
            return None
    
    def is_incomplete(self) -> bool:
        """True when size or price is missing/zero — UI should show placeholder, not fake zeros."""
        if self.count_fp <= 0:
            return True
        if self.price_cents <= 0:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for API responses."""
        d = asdict(self)
        # Convert Decimal to float for JSON serialization
        for key in ["yes_price_dollars", "no_price_dollars", "fee_cost"]:
            if d.get(key) is not None:
                d[key] = float(d[key])
        # Convert datetime to ISO string
        for key in ["created_time", "ingested_at", "reconciliation_ts"]:
            if d.get(key) is not None:
                d[key] = d[key].isoformat() if isinstance(d[key], datetime) else d[key]
        return d
    
    @property
    def price_cents(self) -> int:
        """Get price in cents (0-100) for unified handling."""
        if self.side == "yes" and self.yes_price_dollars is not None:
            return int(self.yes_price_dollars * 100)
        if self.side == "no" and self.no_price_dollars is not None:
            return int(self.no_price_dollars * 100)
        # Legacy / WS: side missing or mis-set — use whichever leg has a price
        if self.yes_price_dollars is not None:
            return int(self.yes_price_dollars * 100)
        if self.no_price_dollars is not None:
            return int(self.no_price_dollars * 100)
        return 0
    
    @property
    def notional_usd(self) -> Decimal:
        """Calculate notional value (count * price)."""
        price = self.yes_price_dollars if self.side == "yes" else self.no_price_dollars
        if price is None:
            return Decimal("0")
        return Decimal(str(self.count_fp)) * price


@dataclass
class OrderIntent:
    """Record of an order intent before it becomes a fill."""
    intent_id: str  # Our internal ID (client_order_id)
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int
    price_cents: int
    agent_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, submitted, filled, cancelled, rejected
    order_id: Optional[str] = None  # Kalshi order ID once submitted
    fill_ids: List[str] = field(default_factory=list)  # Linked fills
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class KalshiFillsLedger:
    """Canonical ledger for all Kalshi fills — dual ingestion, persistent storage.
    
    Usage:
        ledger = get_fills_ledger()
        
        # From HTTP poller
        await ledger.ingest_http_fills(fills_list)  # returns (count, new_fill_ids)
        
        # From WebSocket
        await ledger.ingest_ws_fill(fill_dict)
        
        # Query
        fills = ledger.get_fills(since=datetime.now() - timedelta(hours=24))
        
        # Reconciliation
        status = await ledger.reconcile_with_kalshi_positions()
    """
    
    _instance: Optional[KalshiFillsLedger] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        
        # In-memory cache: fill_id -> KalshiFill
        self._fills: Dict[str, KalshiFill] = {}
        
        # Order intents: intent_id -> OrderIntent
        self._intents: Dict[str, OrderIntent] = {}
        
        # Index by order_id for quick lookup
        self._fills_by_order: Dict[str, List[str]] = {}  # order_id -> [fill_id, ...]
        
        # Index by market for position reconstruction
        self._fills_by_market: Dict[str, List[str]] = {}  # ticker -> [fill_id, ...]
        
        # Reconciliation state
        self._last_reconciliation: Optional[datetime] = None
        self._reconciliation_status = ReconciliationStatus.UNKNOWN
        self._reconciliation_issues: List[Dict[str, Any]] = []
        
        # Stats
        self._http_ingested = 0
        self._ws_ingested = 0
        self._duplicates_dropped = 0
        
        self._db_path = "data/kalshi_fills.db"
        
        # Async queue for single-writer pattern (prevents DB lock contention)
        self._persist_queue: asyncio.Queue[Optional[KalshiFill]] = asyncio.Queue(maxsize=10000)
        self._writer_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # Lock for thread safety (protects all dict mutations)
        self._mutex = asyncio.Lock()
        
        # Initialize DB with WAL mode on first use
        self._db_initialized = False
        
        # Load persisted fills on startup
        self._loaded_count = 0
        
        logger.info("KalshiFillsLedger initialized")
    
    async def start(self) -> int:
        """Bootstrap ledger by loading persisted fills from SQLite.
        
        Returns:
            Number of fills loaded from database.
        """
        if self._loaded_count == 0:
            self._loaded_count = await self.load_from_db()
        return self._loaded_count
    
    async def ingest_http_fills(self, fills: List[Dict[str, Any]], 
                                agent_map: Optional[Dict[str, str]] = None) -> Tuple[int, List[str]]:
        """Ingest fills from HTTP /portfolio/fills endpoint.
        
        Args:
            fills: List of fill dicts from Kalshi API
            agent_map: Optional mapping of client_order_id -> agent_id
            
        Returns:
            (new_count, new_fill_ids) — IDs are new rows only (for bus/UI hooks)
        """
        new_count = 0
        new_fill_ids: List[str] = []
        merged_duplicate = False
        
        async with self._mutex:
            for raw in fills:
                fill = self._parse_fill(raw, "http_poller")
                if _is_test_fixture_fill(fill.fill_id):
                    continue
                if fill.fill_id in self._fills:
                    # HTTP upsert over prior WS row: enrich without zeroing good data.
                    existing = self._fills[fill.fill_id]
                    if fill.action in ("buy", "sell") and existing.action not in ("buy", "sell"):
                        existing.action = fill.action
                        from merid.event_venues.kalshi.kalshi_ledger_metrics import inc_http_upserts as _incu
                        _incu()
                    if not existing.confirmed_by_rest:
                        existing.confirmed_by_rest = True
                        logger.debug("Fill %s confirmed by REST API", fill.fill_id)
                    # Count: never replace positive with zero
                    if fill.count_fp > 0:
                        existing.count_fp = fill.count_fp
                    elif existing.count_fp <= 0:
                        existing.count_fp = fill.count_fp
                    # Prices: upgrade missing/zero only; do not overwrite positive with zero
                    def _merge_px(cur: Optional[Decimal], inc: Optional[Decimal]) -> Optional[Decimal]:
                        if inc is None:
                            return cur
                        try:
                            if float(inc) <= 0:
                                return cur
                        except Exception:
                            return cur
                        if cur is None or float(cur) <= 0:
                            return inc
                        return cur
                    existing.yes_price_dollars = _merge_px(existing.yes_price_dollars, fill.yes_price_dollars)
                    existing.no_price_dollars = _merge_px(existing.no_price_dollars, fill.no_price_dollars)
                    if fill.order_id and not existing.order_id:
                        existing.order_id = fill.order_id
                    if fill.client_order_id and not existing.client_order_id:
                        existing.client_order_id = fill.client_order_id
                    if fill.side and not existing.side:
                        existing.side = fill.side
                    merged_duplicate = True
                    self._duplicates_dropped += 1
                    continue

                # Link to intent if we have it
                if fill.client_order_id and fill.client_order_id in self._intents:
                    intent = self._intents[fill.client_order_id]
                    intent.fill_ids.append(fill.fill_id)
                    intent.status = "filled"
                    intent.last_update = datetime.now(timezone.utc)
                    fill.intent_id = intent.intent_id
                    fill.agent_id = intent.agent_id
                    # Resolve action from intent when fill has no explicit action.
                    if intent.action in ("buy", "sell") and fill.action not in ("buy", "sell"):
                        fill.action = intent.action
                elif agent_map and fill.client_order_id in agent_map:
                    fill.agent_id = agent_map[fill.client_order_id]
                
                self._fills[fill.fill_id] = fill
                self._index_fill(fill)
                new_count += 1
                new_fill_ids.append(fill.fill_id)
                logger.info(
                    "fills_ledger http_ingest fill_id=%s order_id=%s ticker=%s side=%s action=%s size=%s src=http_poller",
                    fill.fill_id,
                    fill.order_id,
                    fill.market_ticker,
                    fill.side,
                    fill.action,
                    fill.count_fp,
                )
                
            self._http_ingested += new_count
            
        if new_count > 0 or merged_duplicate:
            if new_count > 0:
                logger.info(f"Ingested {new_count} new fills from HTTP (total: {len(self._fills)})")
            await self._persist()
            
        return new_count, new_fill_ids
    
    async def ingest_ws_fill(self, raw: Dict[str, Any], agent_id: Optional[str] = None) -> bool:
        """Ingest a single fill from WebSocket.
        
        Args:
            raw: Fill dict from WebSocket trade event
            agent_id: Agent ID if known from context
            
        Returns:
            True if new fill, False if duplicate
        """
        async with self._mutex:
            fill = self._parse_fill(raw, "websocket")
            
            if fill.fill_id in self._fills:
                self._duplicates_dropped += 1
                return False
            
            # WebSocket may not have all fields - try to enrich
            if not fill.agent_id and agent_id:
                fill.agent_id = agent_id
                
            # Link to intent and resolve action
            if fill.client_order_id and fill.client_order_id in self._intents:
                intent = self._intents[fill.client_order_id]
                intent.fill_ids.append(fill.fill_id)
                intent.status = "filled"
                intent.last_update = datetime.now(timezone.utc)
                fill.intent_id = intent.intent_id
                fill.agent_id = intent.agent_id
                # Resolve action from intent when fill has no explicit action
                if intent.action in ("buy", "sell") and fill.action not in ("buy", "sell"):
                    fill.action = intent.action
            
            # Leave action blank when the wire omits it — HTTP ``/portfolio/fills``
            # upserts canonical buy/sell (see ingest_http_fills duplicate branch).

            if fill.is_incomplete():
                # P2: Incomplete WebSocket fills are expected - WS may not have full data
                # HTTP poller will upsert complete data later. This is normal dual-ingestion behavior.
                logger.debug(
                    "fills_ledger ws_fill_incomplete fill_id=%s order_id=%s ticker=%s "
                    "size=%s price_cents=%s (HTTP will complete via upsert)",
                    fill.fill_id,
                    fill.order_id,
                    fill.market_ticker,
                    fill.count_fp,
                    fill.price_cents,
                )
                return False

            self._fills[fill.fill_id] = fill
            self._index_fill(fill)
            self._ws_ingested += 1
            
        logger.info(
            "fills_ledger ws_ingest fill_id=%s order_id=%s ticker=%s side=%s action=%s size=%s asset=%s src=websocket",
            fill.fill_id,
            fill.order_id,
            fill.market_ticker,
            fill.side,
            fill.action,
            fill.count_fp,
            fill.resolved_asset(),
        )
        await self._persist()
        return True
    
    def record_intent(self, intent: OrderIntent) -> None:
        """Record an order intent before submission."""
        self._intents[intent.intent_id] = intent
        logger.debug(f"Recorded intent: {intent.intent_id} for {intent.market_ticker}")
        # Prune stale intents to prevent unbounded growth (runs every 100 adds)
        if len(self._intents) % 100 == 0:
            self._prune_stale_intents()

    def _prune_stale_intents(self) -> None:
        """Remove intents that are terminal+old or just very old."""
        now = datetime.now(timezone.utc)
        _terminal = {"filled", "cancelled", "rejected", "expired"}
        to_delete = [
            iid for iid, intent in self._intents.items()
            if (
                (intent.status in _terminal and (now - intent.created_at).total_seconds() > 120)
                or (now - intent.created_at).total_seconds() > 600
            )
        ]
        for iid in to_delete:
            del self._intents[iid]
        if to_delete:
            logger.debug("Pruned %d stale intents (remaining=%d)", len(to_delete), len(self._intents))
    
    def update_intent_status(self, intent_id: str, status: str, 
                            order_id: Optional[str] = None) -> None:
        """Update intent status (submitted, rejected, etc.)."""
        if intent_id in self._intents:
            intent = self._intents[intent_id]
            intent.status = status
            if order_id:
                intent.order_id = order_id
            intent.last_update = datetime.now(timezone.utc)
    
    def get_fills(self, 
                  since: Optional[datetime] = None,
                  market_ticker: Optional[str] = None,
                  agent_id: Optional[str] = None,
                  limit: int = 500) -> List[KalshiFill]:
        """Query fills with filters."""
        # Take snapshot to avoid dict mutation during iteration
        fills = list(self._fills.values())
        
        if since:
            fills = [f for f in fills if f.created_time >= since]
        if market_ticker:
            fills = [f for f in fills if f.market_ticker == market_ticker]
        if agent_id:
            fills = [f for f in fills if f.agent_id == agent_id]
            
        # Sort by created_time descending
        fills.sort(key=lambda f: f.created_time, reverse=True)
        return fills[:limit]
    
    def get_fill_by_id(self, fill_id: str) -> Optional[KalshiFill]:
        """Get a single fill by ID."""
        return self._fills.get(fill_id)
    
    def get_intent(self, intent_id: str) -> Optional[OrderIntent]:
        """Get an intent by ID."""
        return self._intents.get(intent_id)
    
    def get_unfilled_intents(self, older_than_seconds: int = 60) -> List[OrderIntent]:
        """Get intents that haven't filled within N seconds."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        return [
            intent for intent in self._intents.values()
            if intent.status in ("submitted", "pending")
            and intent.created_at < cutoff
        ]
    
    def get_orphan_fills(self) -> List[KalshiFill]:
        """Get fills with no linked intent (surprise executions)."""
        # Use list() to avoid dict mutation during iteration
        return [
            fill for fill in list(self._fills.values())
            if fill.intent_id is None and fill.client_order_id is None
        ]
    
    async def compute_position_from_fills_async(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Async wrapper for compute_position_from_fills - runs in thread pool to avoid blocking."""
        import asyncio
        return await asyncio.to_thread(self.compute_position_from_fills, market_ticker)
    
    async def compute_net_positions_async(self) -> Dict[str, Dict[str, Any]]:
        """Async wrapper for compute_net_positions - runs in thread pool to avoid blocking."""
        import asyncio
        return await asyncio.to_thread(self.compute_net_positions)

    def compute_position_from_fills(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Recompute position for a market purely from fills ledger."""
        fill_ids = self._fills_by_market.get(market_ticker, [])
        if not fill_ids:
            return None
            
        yes_contracts = 0
        no_contracts = 0
        yes_cost = Decimal("0")
        no_cost = Decimal("0")
        fees = Decimal("0")
        
        for fill_id in fill_ids:
            fill = self._fills[fill_id]
            fees += fill.fee_cost
            
            if fill.side == "yes":
                if fill.action == "buy":
                    yes_contracts += fill.count_fp
                    yes_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally to maintain correct avg price
                    if yes_contracts > 0:
                        yes_cost -= (yes_cost / yes_contracts) * fill.count_fp
                    yes_contracts -= fill.count_fp
            else:  # side == "no"
                if fill.action == "buy":
                    no_contracts += fill.count_fp
                    no_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally
                    if no_contracts > 0:
                        no_cost -= (no_cost / no_contracts) * fill.count_fp
                    no_contracts -= fill.count_fp
        
        # Net position (positive = long, negative = short)
        net_contracts = yes_contracts - no_contracts
        
        if net_contracts == 0:
            return None
            
        side = "yes" if net_contracts > 0 else "no"
        avg_price = (
            (yes_cost / Decimal(yes_contracts) if yes_contracts > 0 else Decimal("0")) if net_contracts > 0
            else (no_cost / Decimal(no_contracts) if no_contracts > 0 else Decimal("0"))
        )
        
        return {
            "market_ticker": market_ticker,
            "side": side,
            "contracts": abs(net_contracts),
            "avg_price_dollars": float(avg_price),
            "avg_price_cents": int(avg_price * 100),
            "total_fees_usd": float(fees),
            "computed_from_fills": len(fill_ids),
        }

    def compute_net_positions(self) -> Dict[str, Dict[str, Any]]:
        """Compute positions for all markets from fills ledger.
        
        Returns:
            Dict mapping market_ticker -> position dict (same format as compute_position_from_fills)
        """
        positions: Dict[str, Dict[str, Any]] = {}
        # Iterate over all markets that have fills
        for market_ticker in self._fills_by_market.keys():
            pos = self.compute_position_from_fills(market_ticker)
            if pos:  # Only include non-zero positions
                positions[market_ticker] = pos
        return positions
    
    async def reconcile_with_kalshi_positions(self, 
                                              kalshi_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare computed positions from fills vs Kalshi-reported positions.
        
        PURELY DIAGNOSTIC: Reports facts only, never makes risk decisions.
        The risk engine consumes this report and applies its own thresholds
        based on KalshiRiskConfig to determine trading halts or alerts.
        
        Returns reconciliation report with divergences (facts only, no severity).
        """
        divergences = []
        matched = 0
        ghost_trade_candidates = 0
        
        # Track which markets we've checked
        checked_markets: Set[str] = set()
        
        # Debug: Log fills ledger state for reconciliation diagnostics
        logger.debug(f"Reconciliation starting: {len(kalshi_positions)} Kalshi positions, {len(self._fills)} fills in ledger, {len(self._fills_by_market)} markets with fills")

        for kalshi_pos in kalshi_positions:
            ticker = kalshi_pos.get("market_ticker") or kalshi_pos.get("ticker")
            if not ticker:
                continue

            checked_markets.add(ticker)
            computed = await self.compute_position_from_fills_async(ticker)

            # Debug: Log computed vs Kalshi position for diagnostics
            if computed:
                logger.debug(f"Reconciliation compare {ticker}: Kalshi={kalshi_pos.get('contracts', 0)}@{kalshi_pos.get('side', 'yes')}, Ledger={computed['contracts']}@{computed['side']}")
            else:
                logger.debug(f"Reconciliation compare {ticker}: Kalshi={kalshi_pos.get('contracts', 0)}@{kalshi_pos.get('side', 'yes')}, Ledger=None (no fills)")
            
            kalshi_contracts = int(kalshi_pos.get("contracts", 0) or kalshi_pos.get("count", 0))
            kalshi_side = kalshi_pos.get("side", "yes")
            kalshi_avg_price_cents = int(kalshi_pos.get("avg_price_cents", 0) or kalshi_pos.get("avg_price", 0))
            
            if computed is None:
                # Kalshi has position but we have no fills — ghost trade candidate
                if kalshi_contracts > 0:
                    ghost_trade_candidates += 1
                    divergences.append({
                        "type": "position_without_fills",
                        "market": ticker,
                        "kalshi_contracts": kalshi_contracts,
                        "kalshi_side": kalshi_side,
                        "ledger_contracts": 0,
                        "contract_diff": kalshi_contracts,
                        "pct_diff": 100.0,  # 100% divergence
                    })
                continue
            
            our_contracts = computed["contracts"]
            our_side = computed["side"]
            our_avg_price_cents = computed["avg_price_cents"]
            
            # Calculate divergence metrics (facts only, no thresholds)
            contract_diff = abs(kalshi_contracts - our_contracts)
            price_diff_cents = abs(kalshi_avg_price_cents - our_avg_price_cents)
            
            # Percentage diff using Kalshi as reference (avoid div by zero)
            if kalshi_contracts > 0:
                pct_diff = (contract_diff / kalshi_contracts) * 100.0
            else:
                pct_diff = 100.0 if our_contracts > 0 else 0.0
            
            # Side mismatch is always reported
            side_mismatch = kalshi_side != our_side
            
            # Report all divergences > 0 (facts only)
            if contract_diff > 0 or side_mismatch or price_diff_cents > 1:
                divergences.append({
                    "type": "side_mismatch" if side_mismatch else "contract_divergence",
                    "market": ticker,
                    "kalshi_contracts": kalshi_contracts,
                    "kalshi_side": kalshi_side,
                    "kalshi_avg_price_cents": kalshi_avg_price_cents,
                    "ledger_contracts": our_contracts,
                    "ledger_side": our_side,
                    "ledger_avg_price_cents": our_avg_price_cents,
                    "contract_diff": contract_diff,
                    "price_diff_cents": price_diff_cents,
                    "pct_diff": round(pct_diff, 2),
                })
            else:
                matched += 1
                # Mark fills as reconciled (data integrity bookkeeping only)
                for fill_id in self._fills_by_market.get(ticker, []):
                    fill = self._fills[fill_id]
                    fill.reconciled = True
                    fill.reconciliation_ts = datetime.now(timezone.utc)
        
        # Check for fills without positions (unexpected but not necessarily wrong)
        fills_without_positions = 0
        # settled_tickers: markets we hold fills for but Kalshi no longer reports a position.
        # These are candidate settled/closed markets — callers (FillsPoller) use this to
        # fire AgentPerformanceTracker.record_outcome() for wins/losses recording.
        settled_tickers: List[str] = []
        for ticker in self._fills_by_market:
            if ticker not in checked_markets:
                # We have fills for a market Kalshi didn't report in positions
                # (could be closed position, or settlement, or subaccount filtering)
                fills_without_positions += len(self._fills_by_market[ticker])
                # Only include if we actually have a computed open position for this market
                # (i.e., net long/short > 0 in fills) to avoid counting already-closed markets
                net_pos = self.compute_position_from_fills(ticker)
                if net_pos and net_pos.get("contracts", 0) > 0:
                    settled_tickers.append(ticker)
        
        self._last_reconciliation = datetime.now(timezone.utc)
        self._reconciliation_issues = divergences  # Store for API access
        
        # Determine status based ONLY on existence of divergences (not severity)
        # OK = perfect match, DEGRADED = any divergence exists, BROKEN = ghost trades suspected
        if ghost_trade_candidates > 0:
            self._reconciliation_status = ReconciliationStatus.BROKEN
        elif len(divergences) > 0:
            self._reconciliation_status = ReconciliationStatus.DEGRADED
        else:
            self._reconciliation_status = ReconciliationStatus.OK
        
        # Purely diagnostic report - all facts, no judgments
        report = {
            "status": self._reconciliation_status.value,
            "timestamp": self._last_reconciliation.isoformat(),
            "positions_checked": len(kalshi_positions),
            "positions_matched": matched,
            "divergences": divergences,
            "divergence_count": len(divergences),
            "ghost_trade_candidates": ghost_trade_candidates,
            "fills_without_positions": fills_without_positions,
            "settled_tickers": settled_tickers,  # Markets that settled since last reconcile
            # Ledger metadata
            "fills_total": len(self._fills),
            "fills_from_http": self._http_ingested,
            "fills_from_ws": self._ws_ingested,
            "duplicates_dropped": self._duplicates_dropped,
        }
        
        # Log facts at appropriate levels (not risk decisions)
        if ghost_trade_candidates > 0:
            logger.error(f"RECONCILIATION: {ghost_trade_candidates} positions exist without fills (ghost trade risk)")
        if divergences:
            logger.warning(f"RECONCILIATION: {len(divergences)} divergences found")
        else:
            logger.info(f"RECONCILIATION: {matched} positions matched exactly")
            
        return report
    
    def get_reconciliation_status(self) -> Dict[str, Any]:
        """Get current reconciliation status for API/UI.
        
        Returns diagnostic facts only. Risk engine consumes this and applies
        its own thresholds from KalshiRiskConfig to make trading decisions.
        """
        return {
            "status": self._reconciliation_status.value,
            "last_run": self._last_reconciliation.isoformat() if self._last_reconciliation else None,
            "divergence_count": len(self._reconciliation_issues),
            "divergences": self._reconciliation_issues[:10],  # Limit for API
            # Ghost trade detection metric
            "ghost_trade_candidates": sum(
                1 for d in self._reconciliation_issues 
                if d.get("type") == "position_without_fills"
            ),
        }
    
    def summary(self) -> Dict[str, Any]:
        """Get ledger summary for dashboards.

        Returns keys consumed by ``web/api/kalshi_api.py`` risk endpoint:
        - ``daily_realized_pnl_usd``  — realized PnL from today's fills
        - ``total_realized_pnl_usd``  — realized PnL from all fills
        - ``total_fees_usd``          — sum of all fees
        - ``total_fills``             — fill count
        Plus the original metadata fields.
        
        STRICT MODE: In production (MERID_STRICT_FILL_ID=1), derived fills
        (those without canonical Kalshi IDs) are excluded from PnL until
        confirmed by REST API reconciliation.
        """
        import os
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check strict mode
        strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"

        total_realized_pnl = Decimal("0")
        daily_realized_pnl = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        total_fees = Decimal("0")

        # Track derived-only fills for reporting
        derived_fills_excluded = 0
        derived_fills_pending = 0

        # Determine which markets have CLOSED positions (net position == 0 from fills).
        # Only closed markets contribute to REALIZED PnL; open positions are UNREALIZED.
        # This prevents open buy fills from appearing as negative "realized PnL" in the UI.
        closed_markets: set = set()
        open_markets: set = set()
        for ticker in self._fills_by_market:
            net_pos = self.compute_position_from_fills(ticker)
            if net_pos and net_pos.get("contracts", 0) > 0:
                open_markets.add(ticker)
                # Approximate unrealized: cost basis of open position (negative of entry cost)
                avg_p = Decimal(str(net_pos.get("avg_price_cents", 50))) / Decimal("100")
                contracts = Decimal(str(net_pos.get("contracts", 0)))
                total_unrealized_pnl += avg_p * contracts  # cost basis held
            else:
                closed_markets.add(ticker)

        # Take snapshot under lock to avoid dict mutation during iteration
        fills_snapshot = list(self._fills.values())

        for fill in fills_snapshot:
            total_fees += fill.fee_cost

            # STRICT MODE SAFETY: Skip derived fills not confirmed by REST
            if strict_mode and fill.derived_id and not fill.confirmed_by_rest:
                derived_fills_excluded += 1
                continue

            # Count derived fills that are still pending confirmation
            if fill.derived_id and not fill.confirmed_by_rest:
                derived_fills_pending += 1

            # REALIZED PnL: only include fills for CLOSED markets (completed round-trips).
            # Open-position buy fills are excluded — they are UNREALIZED until settlement.
            # This prevents showing the cost basis of open positions as "realized losses".
            if fill.market_ticker and fill.market_ticker not in closed_markets:
                continue

            # Net cash flow for this fill (sell = +notional, buy = -notional)
            sign = Decimal("1") if fill.action == "sell" else Decimal("-1")
            pnl_contribution = sign * fill.notional_usd - fill.fee_cost
            total_realized_pnl += pnl_contribution

            if fill.created_time >= today_start:
                daily_realized_pnl += pnl_contribution

        # Log strict mode exclusions for observability
        if strict_mode and derived_fills_excluded > 0:
            logger.warning(
                f"STRICT MODE: Excluded {derived_fills_excluded} derived fills from PnL "
                f"(pending REST confirmation: {derived_fills_pending})"
            )

        from merid.event_venues.kalshi.kalshi_ledger_metrics import snapshot as _metrics_snap
        return {
            # Keys expected by kalshi_api.py risk endpoint
            "daily_realized_pnl_usd": float(daily_realized_pnl),
            "total_realized_pnl_usd": float(total_realized_pnl),
            "total_unrealized_pnl_usd": float(total_unrealized_pnl),
            "open_markets_count": len(open_markets),
            "closed_markets_count": len(closed_markets),
            "total_fees_usd": float(total_fees),
            "total_fills": len(self._fills),
            # Original metadata
            "fills_total": len(self._fills),
            "fills_from_http": self._http_ingested,
            "fills_from_ws": self._ws_ingested,
            "duplicates_dropped": self._duplicates_dropped,
            "intents_recorded": len(self._intents),
            "unfilled_intents": len(self.get_unfilled_intents()),
            "orphan_fills": len(self.get_orphan_fills()),
            "reconciliation": self.get_reconciliation_status(),
            # Strict mode tracking
            "strict_mode": strict_mode,
            "derived_fills_excluded": derived_fills_excluded,
            "derived_fills_pending": derived_fills_pending,
            # Observability counters from kalshi_ledger_metrics
            **_metrics_snap(),
        }
    
    # ── Private methods ─────────────────────────────────────────────────────
    
    def _parse_fill(self, raw: Dict[str, Any], source: str) -> KalshiFill:
        """Parse raw fill dict from Kalshi into KalshiFill model."""
        # Handle both HTTP and WS formats
        fill_id = raw.get("fill_id") or raw.get("trade_id") or raw.get("id")
        derived_id_flag = False
        if not fill_id:
            # Generate deterministic ID from content for safety
            fill_id = f"derived_{int(hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:8], 16)}"
            derived_id_flag = True
            import os
            strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"
            
            # Log at DEBUG for non-strict, WARNING for strict - and throttle to every 100th
            ticker = raw.get("market_ticker") or raw.get("ticker")
            if not ticker:
                # Critical: fill without market identifier - always log this
                logger.warning(f"Fill missing BOTH ID and ticker from source='{source}' - potential data integrity issue")
            
            # Use periodic logging to avoid spam (log every 100th derived fill)
            self._derived_fill_counter = getattr(self, '_derived_fill_counter', 0) + 1
            if self._derived_fill_counter % 100 == 1:
                log_fn = logger.warning if strict_mode else logger.debug
                log_fn(f"Fill missing ID from source='{source}', derived: {fill_id} (ticker={ticker}, action={raw.get('action')}) [showing 1/100]")
        
        # Parse timestamp
        ts_str = raw.get("created_time") or raw.get("created_at") or raw.get("timestamp")
        created_time = datetime.now(timezone.utc)
        if ts_str:
            try:
                if isinstance(ts_str, numbers.Real) and not isinstance(ts_str, bool):
                    created_time = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
                elif isinstance(ts_str, str):
                    created_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.debug(f"Timestamp parse failed: {e}")
        
        # Parse price - handle both cents and dollars
        yes_price = raw.get("yes_price")
        no_price = raw.get("no_price")
        price = raw.get("price")
        
        def normalize_price(p) -> Optional[Decimal]:
            if p is None:
                return None
            try:
                p = float(p)
                # If > 1, assume cents; else dollars
                return Decimal(str(p / 100.0 if p >= 1.0 else p))
            except Exception:
                return None
        
        yes_price_dollars = normalize_price(yes_price) if yes_price else None
        no_price_dollars = normalize_price(no_price) if no_price else None
        
        # If we only have generic price, assign to side
        if price and not yes_price_dollars and not no_price_dollars:
            side = raw.get("side", "yes")
            if side == "yes":
                yes_price_dollars = normalize_price(price)
            else:
                no_price_dollars = normalize_price(price)
        
        # Parse fee
        fee = raw.get("fee") or raw.get("fee_cost") or raw.get("fee_paid") or 0
        try:
            fee_decimal = Decimal(str(fee))
            if fee_decimal > 1:  # Assume cents
                fee_decimal = fee_decimal / 100
        except Exception:
            fee_decimal = Decimal("0")
        
        # Resolve action: explicit "buy"/"sell" wins; taker_action is fallback.
        # WS fills often arrive with action="" — leave empty (HTTP upsert will upgrade).
        # HTTP fills with no action but positive count default to "buy".
        _raw_act = raw.get("action") or raw.get("taker_action") or ""
        _action = _raw_act if _raw_act in ("buy", "sell") else ""
        _count_fp = int(raw.get("count") or raw.get("contracts") or raw.get("size", 0))
        if not _action:
            from merid.event_venues.kalshi.kalshi_ledger_metrics import inc_fills_missing_action as _inct
            _inct()
            # HTTP source with positive count: default to "buy" rather than storing invalid.
            if source != "websocket" and _count_fp > 0:
                _action = "buy"

        return KalshiFill(
            fill_id=str(fill_id),
            trade_id=raw.get("trade_id"),
            order_id=raw.get("order_id"),
            market_ticker=(raw.get("market_ticker") or raw.get("ticker") or "").upper(),
            side=raw.get("side", ""),
            action=_action,
            count_fp=_count_fp,
            yes_price_dollars=yes_price_dollars,
            no_price_dollars=no_price_dollars,
            fee_cost=fee_decimal,
            client_order_id=raw.get("client_order_id"),
            subaccount_number=raw.get("subaccount_number"),
            created_time=created_time,
            idempotency_key=raw.get("idempotency_key"),
            canonical_hash_version=raw.get("canonical_hash_version"),
            hash_preimage=raw.get("hash_preimage"),
            raw_payload=raw if source != "websocket" else None,  # Don't store full WS payload
            ingestion_source=source,
            ingested_at=datetime.now(timezone.utc),
            derived_id=derived_id_flag,  # Track if ID was synthesized
            confirmed_by_rest=(source == "http_poller"),  # HTTP fills are canonical
            decision_trace_id=raw.get("decision_trace_id"),
        )
    
    def _index_fill(self, fill: KalshiFill) -> None:
        """Add fill to secondary indexes."""
        # Index by order_id
        if fill.order_id:
            if fill.order_id not in self._fills_by_order:
                self._fills_by_order[fill.order_id] = []
            self._fills_by_order[fill.order_id].append(fill.fill_id)
        
        # Index by market
        if fill.market_ticker:
            if fill.market_ticker not in self._fills_by_market:
                self._fills_by_market[fill.market_ticker] = []
            self._fills_by_market[fill.market_ticker].append(fill.fill_id)
    
    async def _init_db(self) -> None:
        """Initialize SQLite with WAL mode and proper settings."""
        if self._db_initialized:
            return
        
        import aiosqlite
        import os
        
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        
        async with aiosqlite.connect(self._db_path) as db:
            # WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute("PRAGMA busy_timeout=30000;")  # 30 second timeout for startup contention
            await db.execute("PRAGMA temp_store=MEMORY;")
            await db.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
            
            # Create tables
            await db.execute("""
                CREATE TABLE IF NOT EXISTS kalshi_fills (
                    fill_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    order_id TEXT,
                    market_ticker TEXT NOT NULL,
                    side TEXT,
                    action TEXT,
                    count_fp INTEGER,
                    yes_price_dollars REAL,
                    no_price_dollars REAL,
                    fee_cost REAL,
                    client_order_id TEXT,
                    subaccount_number INTEGER,
                    created_time TEXT,
                    ingestion_source TEXT,
                    ingested_at TEXT,
                    agent_id TEXT,
                    intent_id TEXT,
                    reconciled INTEGER DEFAULT 0,
                    raw_payload TEXT
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_market ON kalshi_fills(market_ticker)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_order ON kalshi_fills(order_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_time ON kalshi_fills(created_time)
            """)
            # Migrate: decision_trace_id for audit (nullable)
            async with db.execute("PRAGMA table_info(kalshi_fills)") as cur:
                _cols = {r[1] for r in await cur.fetchall()}
            if "decision_trace_id" not in _cols:
                await db.execute("ALTER TABLE kalshi_fills ADD COLUMN decision_trace_id TEXT")
            await db.commit()
        
        self._db_initialized = True
        logger.info("SQLite DB initialized with WAL mode")
    
    async def _execute_with_retry(self, db, sql: str, params: tuple = (), retries: int = 8) -> None:
        """Execute SQL with retry on database locked errors."""
        delay = 0.1
        last_error = None
        
        for i in range(retries):
            try:
                await db.execute(sql, params)
                return
            except sqlite3.OperationalError as e:
                last_error = e
                if "database is locked" not in str(e).lower():
                    raise
                if i < retries - 1:
                    logger.debug(f"DB locked, retrying in {delay}s (attempt {i+1}/{retries})")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 2.0)  # Exponential backoff, cap at 2s
            except Exception:
                raise
        
        # All retries exhausted
        raise last_error if last_error else sqlite3.OperationalError("database is locked after retries")
    
    async def _persist(self) -> None:
        """Queue a fill for persistence (single-writer pattern).
        
        Instead of writing directly to DB (which causes lock contention),
        we queue the fill and let the dedicated writer task handle it.
        """
        # Start writer task if not running
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop(), name="fills_writer")
            def _task_done_cb(task: asyncio.Task) -> None:
                if not task.cancelled() and task.exception():
                    logger.error("FillsLedger writer task crashed: %s", task.exception())
            self._writer_task.add_done_callback(_task_done_cb)
        
        # Signal that there's work to do (writer will read from queue)
        # We don't actually queue fills here - the writer reads from _fills dict
        # This is a signal-only pattern to wake the writer
        try:
            self._persist_queue.put_nowait(None)  # Wake signal
        except asyncio.QueueFull:
            pass  # Writer is already processing
    
    async def _writer_loop(self) -> None:
        """Dedicated writer task that batches and writes to SQLite.
        
        Holds a single persistent connection for the lifetime of the loop
        to avoid lock contention from opening/closing connections per flush.
        """
        logger.info("Fills writer loop started")
        
        import aiosqlite
        
        _writer_db = None
        try:
            _writer_db = await aiosqlite.connect(self._db_path)
            await _writer_db.execute("PRAGMA journal_mode=WAL;")
            await _writer_db.execute("PRAGMA busy_timeout=30000;")  # 30s busy wait for startup contention
            await _writer_db.execute("PRAGMA synchronous=NORMAL;")
            logger.info("Fills writer: persistent DB connection established")
        except ImportError:
            logger.warning("aiosqlite not installed — writer loop running in no-op mode")
        except Exception as e:
            logger.error(f"Fills writer: failed to open DB connection: {e}")
        
        while not self._shutdown_event.is_set():
            try:
                # Wait for work signal with timeout
                try:
                    await asyncio.wait_for(
                        self._persist_queue.get(), 
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Periodic flush even if no signals
                    pass
                
                # Batch collect any additional signals
                batch_signals = 1
                while batch_signals < 100 and not self._persist_queue.empty():
                    try:
                        self._persist_queue.get_nowait()
                        batch_signals += 1
                    except asyncio.QueueEmpty:
                        break
                
                # Perform the actual persistence with the persistent connection
                await self._flush_to_db(_writer_db)
                
            except asyncio.CancelledError:
                logger.info("Fills writer loop cancelled")
                break
            except Exception as e:
                logger.error(f"Writer loop error: {e}")
                await asyncio.sleep(0.1)
        
        # Final flush on shutdown
        try:
            await self._flush_to_db(_writer_db)
        except Exception as e:
            logger.warning(f"Final flush failed: {e}")
        
        # Close persistent connection
        if _writer_db is not None:
            try:
                await _writer_db.close()
                logger.info("Fills writer: persistent DB connection closed")
            except Exception as e:
                logger.debug(f"DB close failed: {e}")
        
        logger.info("Fills writer loop stopped")
    
    async def _flush_to_db(self, db=None) -> None:
        """Flush current fills to SQLite with snapshot iteration.
        
        Args:
            db: Optional persistent aiosqlite connection from _writer_loop.
                If None, opens a one-shot connection (fallback).
        """
        try:
            import aiosqlite
            
            # Ensure DB is initialized
            if not self._db_initialized:
                await self._init_db()
            
            # Take a SNAPSHOT of fills under lock to avoid "dict changed size during iteration"
            fills_snapshot: List[KalshiFill] = []
            async with self._mutex:
                fills_snapshot = list(self._fills.values())
            
            if not fills_snapshot:
                return
            
            async def _do_flush(_db) -> None:
                # Batch upsert using retry logic
                for fill in fills_snapshot:
                    try:
                        await self._execute_with_retry(_db, """
                            INSERT OR REPLACE INTO kalshi_fills (
                                fill_id, trade_id, order_id, market_ticker, side, action,
                                count_fp, yes_price_dollars, no_price_dollars, fee_cost,
                                client_order_id, subaccount_number, created_time,
                                ingestion_source, ingested_at, agent_id, intent_id,
                                reconciled, raw_payload, decision_trace_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            fill.fill_id, fill.trade_id, fill.order_id, fill.market_ticker,
                            fill.side, fill.action, fill.count_fp,
                            float(fill.yes_price_dollars) if fill.yes_price_dollars else None,
                            float(fill.no_price_dollars) if fill.no_price_dollars else None,
                            float(fill.fee_cost),
                            fill.client_order_id, fill.subaccount_number,
                            fill.created_time.isoformat(),
                            fill.ingestion_source,
                            fill.ingested_at.isoformat(),
                            fill.agent_id, fill.intent_id,
                            1 if fill.reconciled else 0,
                            json.dumps(fill.raw_payload) if fill.raw_payload else None,
                            fill.decision_trace_id,
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to persist fill {fill.fill_id}: {e}")
                        # Continue with other fills - don't let one bad fill break the batch
                
                await _db.commit()
            
            if db is not None:
                # Use the persistent writer connection (preferred path)
                await _do_flush(db)
            else:
                # Fallback: open a one-shot connection
                async with aiosqlite.connect(self._db_path) as fallback_db:
                    await fallback_db.execute("PRAGMA journal_mode=WAL;")
                    await fallback_db.execute("PRAGMA busy_timeout=30000;")  # 30s for startup contention
                    await _do_flush(fallback_db)
                
        except ImportError:
            # aiosqlite not installed — fills survive only in RAM; restart loses them.
            # Log once per process so operators notice on first flush, not every flush.
            if not getattr(self, "_aiosqlite_warned", False):
                self._aiosqlite_warned = True
                logger.warning(
                    "aiosqlite not installed — KalshiFillsLedger running in-memory only. "
                    "Fills will be LOST on process restart. Install aiosqlite to enable persistence."
                )
        except Exception as e:
            logger.warning(f"Failed to persist fills batch: {e}")
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the ledger and flush remaining fills."""
        logger.info("Shutting down KalshiFillsLedger...")
        self._shutdown_event.set()
        
        # Signal writer to wake and flush
        try:
            await self._persist_queue.put(None)
        except Exception as e:
            logger.debug(f"Persist queue put failed: {e}")

        # Wait for writer task to complete
        if self._writer_task and not self._writer_task.done():
            try:
                await asyncio.wait_for(self._writer_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Writer task did not complete in time, cancelling")
                self._writer_task.cancel()
                try:
                    await self._writer_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                logger.warning(f"Error waiting for writer task: {e}")
        
        logger.info("KalshiFillsLedger shutdown complete")

    async def load_from_db(self) -> int:
        """Load fills from SQLite on startup."""
        try:
            import aiosqlite
            
            # Ensure DB is initialized first
            if not self._db_initialized:
                await self._init_db()
            
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("PRAGMA busy_timeout=30000;")  # 30s for startup contention
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM kalshi_fills ORDER BY created_time DESC LIMIT 10000"
                ) as cursor:
                    rows = await cursor.fetchall()

                skipped_test = 0
                for row in rows:
                    # Skip test fixture fills that leaked into the DB
                    if _is_test_fixture_fill(row["fill_id"]):
                        skipped_test += 1
                        continue
                    raw_payload = None
                    rp = row["raw_payload"] if "raw_payload" in row.keys() else None
                    if rp:
                        try:
                            raw_payload = json.loads(rp) if isinstance(rp, str) else rp
                        except Exception:
                            raw_payload = None
                    dtid = row["decision_trace_id"] if "decision_trace_id" in row.keys() else None
                    if not dtid and raw_payload:
                        dtid = (raw_payload or {}).get("decision_trace_id")
                    fill = KalshiFill(
                        fill_id=row["fill_id"],
                        trade_id=row["trade_id"],
                        order_id=row["order_id"],
                        market_ticker=row["market_ticker"],
                        side=row["side"],
                        action=row["action"],
                        count_fp=row["count_fp"],
                        yes_price_dollars=Decimal(str(row["yes_price_dollars"])) if row["yes_price_dollars"] else None,
                        no_price_dollars=Decimal(str(row["no_price_dollars"])) if row["no_price_dollars"] else None,
                        fee_cost=Decimal(str(row["fee_cost"])) if row["fee_cost"] else Decimal("0"),
                        client_order_id=row["client_order_id"],
                        subaccount_number=row["subaccount_number"],
                        created_time=datetime.fromisoformat(row["created_time"]) if row["created_time"] else datetime.now(timezone.utc),
                        ingestion_source=row["ingestion_source"] or "db_restore",
                        ingested_at=datetime.fromisoformat(row["ingested_at"]) if row["ingested_at"] else datetime.now(timezone.utc),
                        agent_id=row["agent_id"],
                        intent_id=row["intent_id"],
                        reconciled=bool(row["reconciled"]),
                        raw_payload=raw_payload,
                        decision_trace_id=dtid,
                    )
                    self._fills[fill.fill_id] = fill
                    self._index_fill(fill)
                    
                loaded = len(rows) - skipped_test
                if skipped_test:
                    logger.warning(
                        "Filtered %d test-fixture fills from DB (prefixes: %s)",
                        skipped_test, ", ".join(_TEST_FILL_PREFIXES[:3]) + "..."
                    )
                logger.info(f"Loaded {loaded} fills from database")
                return loaded
        except Exception as e:
            logger.debug(f"No existing fills DB or load error: {e}")
            return 0


# Singleton accessor
_ledger: Optional[KalshiFillsLedger] = None
_ledger_lock = threading.Lock()


def get_fills_ledger() -> KalshiFillsLedger:
    """Get the singleton KalshiFillsLedger instance."""
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = KalshiFillsLedger()
    return _ledger


# Convenience exports
__all__ = [
    "KalshiFill",
    "OrderIntent", 
    "KalshiFillsLedger",
    "get_fills_ledger",
    "ReconciliationStatus",
]
