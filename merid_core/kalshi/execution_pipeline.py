"""
Kalshi Execution Pipeline — QUARANTINED (T-001 Zero-Trust Audit)

⚠️  PRODUCTION HARDENING: THIS MODULE IS DISABLED  ⚠️

WARNING: This module is a PARALLEL execution engine that bypasses MeridLoop,
TaCo/Enhanced consensus, the 9-gate execution path, kill switch, VenueGate,
risk manager, and deployment controller.

It bypasses ALL safety guards including:
  - order_router.route_order_async()
  - GlobalRiskGuard (1-2% bankroll cap)
  - Top3BatchManager (top-3 allocation gate)
  - PreTradeGate (lease + deduplication)
  - Execution gate / kill switches

To enable this bypass (NOT RECOMMENDED): set MERID_ALLOW_EXECUTION_PIPELINE_BYPASS=1

If you are looking for the production execution path, see:
  - merid/execution/router.py  (ExecutionRouter)
  - merid/execution/executors/kalshi.py  (KalshiExecutor)
  - merid/event_venues/kalshi/order_router.py (canonical order routing)
"""

from __future__ import annotations

import asyncio
import json
from utils.logger import get_logger
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING — CRITICAL BYPASS DISABLED
# ═══════════════════════════════════════════════════════════════════════════
# This module contains a DIRECT HTTP BYPASS to Kalshi API that circumvents
# the canonical order_router and ALL risk guards (GlobalRiskGuard 1-2% cap,
# Top-3 batch gate, PreTradeGate, execution gate, kill switches).
#
# To enable this bypass (NOT RECOMMENDED): set MERID_ALLOW_EXECUTION_PIPELINE_BYPASS=1
# ═══════════════════════════════════════════════════════════════════════════
if os.getenv("MERID_ALLOW_EXECUTION_PIPELINE_BYPASS", "").lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "[PRODUCTION HARDENING] merid_core.kalshi.execution_pipeline is DISABLED. "
        "This module contains a parallel execution engine that bypasses ALL safety gates "
        "(order_router, GlobalRiskGuard, Top-3 batch, PreTradeGate, kill switches). "
        "Use the canonical path: POST /api/v1/kalshi/orders or KalshiContinuousTrader. "
        "To bypass (NOT RECOMMENDED): MERID_ALLOW_EXECUTION_PIPELINE_BYPASS=1"
    )
# ═══════════════════════════════════════════════════════════════════════════

logger = get_logger(__name__)

_NATS_EXECUTION_ENABLED = os.environ.get("MERID_NATS_EXECUTION_ENABLED", "").lower() == "true"

if not _NATS_EXECUTION_ENABLED:
    logger.warning(
        "merid_core.kalshi.execution_pipeline imported but MERID_NATS_EXECUTION_ENABLED "
        "is not 'true'. All ExecutionPipeline operations are NO-OPs. "
        "This module bypasses ALL safety gates — do NOT enable in production without review."
    )

# Lazy import to avoid import-time crash when NATS is not configured
def _get_nats_imports():
    from merid_core.event_bus.nats_adapter import NATSEventBus, EventEnvelope
    return NATSEventBus, EventEnvelope


class OrderStatus(Enum):
    """Order execution status"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    REJECTED_RISK = "rejected_risk"
    REJECTED_RATE_LIMIT = "rejected_rate_limit"
    ERROR = "error"


@dataclass
class OrderIntent:
    """Order intent from TS agents"""
    session_id: str
    agent_id: str
    market_ticker: str
    side: str  # buy_yes, sell_yes, buy_no, sell_no
    qty: int
    price: float  # 0-1 probability
    client_tag: str  # Idempotency key
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    timestamp: int = 0


@dataclass
class RiskLimits:
    """Risk limits configuration — DYNAMIC from Kalshi balance, not hardcoded."""
    # Position limits (contract counts, these can have defaults)
    max_position_per_market: int = 100
    max_position_per_asset: int = 300
    
    # NOTIONAL LIMITS: 0 or negative means "derive from actual Kalshi balance"
    # These are computed at runtime from /portfolio/balance API
    max_total_notional: float = 0.0  # 0 = derive from bankroll (was $10,000)
    max_daily_loss: float = 0.0    # 0 = derive from bankroll (was $1,000)
    max_venue_exposure: float = 0.0  # 0 = derive from bankroll (was $5,000)


class KalshiPositionLimits:
    """Tracks Kalshi-native per-market position limits and accountability thresholds.

    Kalshi enforces position limits per-market (varies, typically 25k contracts
    for liquid markets, less for illiquid ones).  Accountability thresholds
    (usually ~80% of the limit) trigger additional scrutiny / slower fills.

    This class caches limits fetched from the Kalshi API and provides a
    pre-flight check the execution pipeline calls before placing orders.
    """

    DEFAULT_LIMIT = 25_000  # conservative default when limit unknown
    ACCOUNTABILITY_PCT = 0.80  # warn at 80% of limit

    def __init__(self) -> None:
        self._market_limits: Dict[str, int] = {}  # ticker -> max contracts
        self._last_refresh = 0.0
        self._refresh_interval = 300  # re-fetch every 5 min

    def set_limit(self, ticker: str, limit: int) -> None:
        self._market_limits[ticker] = limit

    def get_limit(self, ticker: str) -> int:
        return self._market_limits.get(ticker, self.DEFAULT_LIMIT)

    def get_accountability_threshold(self, ticker: str) -> int:
        return int(self.get_limit(ticker) * self.ACCOUNTABILITY_PCT)

    def check(
        self, ticker: str, current_position: int, proposed_delta: int
    ) -> Dict[str, Any]:
        """Pre-flight check against Kalshi-native limits.

        Returns:
            Dict with 'ok' bool, plus optional 'warning' or 'reason' strings.
        """
        limit = self.get_limit(ticker)
        threshold = self.get_accountability_threshold(ticker)
        proposed = abs(current_position + proposed_delta)

        if proposed > limit:
            return {
                "ok": False,
                "reason": "kalshi_position_limit",
                "current": current_position,
                "proposed_abs": proposed,
                "limit": limit,
                "detail": f"Would exceed Kalshi position limit ({proposed}/{limit})",
            }

        result: Dict[str, Any] = {"ok": True}
        if proposed > threshold:
            result["warning"] = (
                f"Approaching Kalshi accountability threshold "
                f"({proposed}/{limit}, threshold={threshold})"
            )
            logger.warning(
                "Accountability warning on %s: %d/%d (threshold %d)",
                ticker, proposed, limit, threshold,
            )
        return result

    def refresh_from_api(self) -> None:
        """Fetch per-market limits from the Kalshi REST API (best-effort)."""
        now = time.time()
        if now - self._last_refresh < self._refresh_interval:
            return
        self._last_refresh = now
        try:
            from merid_core.kalshi.rest_client import get_rest_client
            import os
            client = get_rest_client(
                key_id=os.environ.get("KALSHI_API_KEY_ID", ""),
                private_key_path=os.environ.get("KALSHI_PRIVATE_KEY_PATH", ""),
                env=os.environ.get("KALSHI_ENV", "demo"),
            )
            # Kalshi returns position_limit on market detail; cache for known tickers
            for ticker in list(self._market_limits.keys()):
                try:
                    market = client.get_market(ticker)
                    pl = market.get("market", {}).get("position_limit")
                    if pl and isinstance(pl, int):
                        self._market_limits[ticker] = pl
                except Exception as _ml_exc:
                    logger.debug("Position limit fetch failed for %s: %s", ticker, _ml_exc)
            logger.info("Refreshed Kalshi position limits for %d markets", len(self._market_limits))
        except Exception as exc:
            logger.debug("Position limit refresh failed: %s", exc)


class TokenBucket:
    """Token bucket rate limiter"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: Max tokens
            refill_rate: Tokens per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens
        
        Returns:
            True if tokens available, False otherwise
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        
        refill = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + refill)
        self.last_refill = now
    
    def wait_time(self, tokens: int = 1) -> float:
        """
        Calculate wait time for tokens
        
        Returns:
            Seconds to wait
        """
        self._refill()
        
        if self.tokens >= tokens:
            return 0.0
        
        needed = tokens - self.tokens
        return needed / self.refill_rate


class ExecutionPipeline:
    """
    Execution Pipeline
    
    - Consumes OrderIntents from NATS
    - Applies risk checks (position limits, daily loss)
    - Rate limiting (token bucket)
    - Executes orders via Kalshi REST API
    - Publishes execution outcomes
    """
    
    def __init__(
        self,
        event_bus=None,
        risk_limits: Optional[RiskLimits] = None,
        read_rate_limit: int = 20,  # per second
        write_rate_limit: int = 10,  # per second
        enable_live_trading: bool = False
    ):
        if not _NATS_EXECUTION_ENABLED:
            raise RuntimeError(
                "ExecutionPipeline is QUARANTINED. Set MERID_NATS_EXECUTION_ENABLED=true "
                "to enable. This bypasses ALL safety gates — see T-001 audit."
            )
        self.event_bus = event_bus
        self.risk_limits = risk_limits or RiskLimits()
        self.enable_live_trading = enable_live_trading
        
        # Kalshi-native position limits (accountability thresholds)
        self.kalshi_limits = KalshiPositionLimits()
        
        # Rate limiters
        self.read_limiter = TokenBucket(capacity=read_rate_limit, refill_rate=read_rate_limit)
        self.write_limiter = TokenBucket(capacity=write_rate_limit, refill_rate=write_rate_limit)
        
        # State tracking
        self.positions: Dict[str, int] = {}  # market_ticker -> contracts
        self.daily_pnl = 0.0
        # T-042: Use UTC date for daily loss reset instead of epoch time
        from datetime import datetime as _dt, timezone as _tz
        self._last_reset_date = _dt.now(_tz.utc).date()
        # T-041: Persist idempotency tracking to survive restarts
        self._idemp_path = Path("data/processed_intents.json")
        self.processed_intents: set = self._load_idempotency_set()
        
        # Statistics
        self.intents_received = 0
        self.intents_executed = 0
        self.intents_rejected_risk = 0
        self.intents_rejected_rate = 0
        
        logger.info("ExecutionPipeline initialized")
        logger.info(f"  Live trading: {enable_live_trading}")
        logger.info(f"  Read rate limit: {read_rate_limit}/s")
        logger.info(f"  Write rate limit: {write_rate_limit}/s")
    
    def _load_idempotency_set(self) -> set:
        """T-041: Load persisted idempotency set from disk."""
        try:
            if self._idemp_path.exists():
                data = json.loads(self._idemp_path.read_text())
                tags = set(data.get("tags", []))
                logger.info("Loaded %d idempotency tags from disk", len(tags))
                return tags
        except Exception as exc:
            logger.warning("Could not load idempotency set: %s", exc)
        return set()

    def _save_idempotency_set(self) -> None:
        """T-041: Persist idempotency set to disk."""
        try:
            self._idemp_path.parent.mkdir(parents=True, exist_ok=True)
            # Keep last 5000 tags to bound file size
            tags = list(self.processed_intents)
            if len(tags) > 5000:
                tags = tags[-5000:]
                self.processed_intents = set(tags)
            self._idemp_path.write_text(json.dumps({"tags": tags, "updated": time.time()}))
        except Exception as exc:
            logger.warning("Could not save idempotency set: %s", exc)

    async def start(self) -> None:
        """Start consuming OrderIntents"""
        # T-023: Sync positions from Kalshi on startup
        await self._sync_positions_from_kalshi()

        await self.event_bus.subscribe("intents.orders", self.handle_intent)
        logger.info("ExecutionPipeline started, subscribed to intents.orders")

    async def _sync_positions_from_kalshi(self) -> None:
        """T-023: Fetch open positions from Kalshi and populate local tracking."""
        try:
            from merid.execution.executors.kalshi import _get_venue_client
            client = _get_venue_client()
            result = await client._request_with_resilience(
                "GET", "/portfolio/positions", operation_name="sync_positions",
            )
            if result.success:
                remote_positions = {}
                for pos in result.data.get("market_positions", []):
                    ticker = pos.get("ticker", "")
                    count = pos.get("position", 0)
                    if ticker and count != 0:
                        remote_positions[ticker] = count
                # Reconcile
                if self.positions and self.positions != remote_positions:
                    logger.critical(
                        "POSITION MISMATCH: local=%s remote=%s — entering reduce-only",
                        self.positions, remote_positions,
                    )
                self.positions = remote_positions
                logger.info("Synced %d positions from Kalshi", len(remote_positions))
            else:
                logger.warning("Position sync failed: %s — starting with empty positions", result.error)
        except Exception as exc:
            logger.error("Position sync unavailable: %s — starting with empty positions", exc)
    
    async def handle_intent(self, envelope: EventEnvelope) -> None:
        """
        Handle incoming OrderIntent
        
        Pipeline:
        1. Idempotency check
        2. Risk checks
        3. Rate limiting
        4. Execute order (if live trading enabled)
        5. Publish outcome
        """
        self.intents_received += 1
        
        try:
            # Parse intent
            intent = self._parse_intent(envelope.data)
            
            # Idempotency: skip if already processed
            if intent.client_tag in self.processed_intents:
                logger.debug(f"Skipping duplicate intent: {intent.client_tag}")
                return
            
            # Risk checks
            risk_decision = self._check_risk(intent)
            
            if not risk_decision["approved"]:
                await self._publish_rejection(intent, risk_decision)
                self.intents_rejected_risk += 1
                return
            
            # Rate limiting
            if not self.write_limiter.consume():
                wait_time = self.write_limiter.wait_time()
                logger.warning(
                    f"Rate limited: {intent.client_tag}, wait {wait_time:.2f}s"
                )
                
                await self._publish_outcome(
                    intent,
                    OrderStatus.REJECTED_RATE_LIMIT,
                    error=f"Rate limited, retry after {wait_time:.1f}s"
                )
                self.intents_rejected_rate += 1
                return
            
            # Execute order
            if self.enable_live_trading:
                await self._execute_order(intent)
            else:
                logger.info(
                    f"[PAPER] Order: {intent.side} {intent.qty}x {intent.market_ticker} "
                    f"@ {intent.price:.3f} (agent={intent.agent_id})"
                )
                
                await self._publish_outcome(
                    intent,
                    OrderStatus.SUBMITTED,
                    order_id=f"paper-{intent.client_tag}"
                )
            
            # Mark as processed and persist
            self.processed_intents.add(intent.client_tag)
            self.intents_executed += 1
            self._save_idempotency_set()
            
        except Exception as e:
            logger.error(f"Error handling intent: {e}", exc_info=True)
    
    def _parse_intent(self, data: Dict[str, Any]) -> OrderIntent:
        """Parse OrderIntent from event data"""
        return OrderIntent(
            session_id=data["session_id"],
            agent_id=data["agent_id"],
            market_ticker=data["market_ticker"],
            side=data["side"],
            qty=data["qty"],
            price=data["price"],
            client_tag=data["client_tag"],
            confidence=data.get("confidence"),
            rationale=data.get("rationale"),
            timestamp=data.get("timestamp", 0)
        )
    
    def _check_risk(self, intent: OrderIntent) -> Dict[str, Any]:
        """
        Apply risk checks
        
        Returns:
            Risk decision with approved flag and reason
        """
        # Check 0: Category trading permission
        try:
            from merid_core.kalshi.category_config import is_trading_allowed, get_category_mode
            # Extract category from ticker prefix heuristic (e.g., KXBTC → crypto)
            cat = self._infer_category(intent.market_ticker)
            if not is_trading_allowed(cat):
                mode = get_category_mode(cat) if cat else "unknown"
                return {
                    "approved": False,
                    "reason": "category_blocked",
                    "category": cat,
                    "mode": mode,
                    "detail": f"Category '{cat}' is {mode} — trading not permitted",
                }
        except ImportError:
            pass  # category config not available, skip check

        # Check 1: Position limit per market
        current_position = self.positions.get(intent.market_ticker, 0)
        proposed_position = current_position + (intent.qty if "buy" in intent.side else -intent.qty)
        
        if abs(proposed_position) > self.risk_limits.max_position_per_market:
            return {
                "approved": False,
                "reason": "market_position_limit",
                "current": current_position,
                "proposed": proposed_position,
                "limit": self.risk_limits.max_position_per_market
            }
        
        # Check 1b: Kalshi-native position limit + accountability threshold
        delta = intent.qty if "buy" in intent.side else -intent.qty
        kalshi_check = self.kalshi_limits.check(intent.market_ticker, current_position, delta)
        if not kalshi_check["ok"]:
            return {
                "approved": False,
                **kalshi_check,
            }
        
        # Check 2: Daily loss limit
        self._check_daily_reset()
        
        if self.daily_pnl < -self.risk_limits.max_daily_loss:
            return {
                "approved": False,
                "reason": "daily_loss_limit",
                "daily_pnl": self.daily_pnl,
                "limit": -self.risk_limits.max_daily_loss
            }
        
        # Check 3: Total notional limit (simplified)
        total_notional = sum(abs(pos) * 50 for pos in self.positions.values())
        intent_notional = intent.qty * intent.price * 100
        
        if total_notional + intent_notional > self.risk_limits.max_total_notional:
            return {
                "approved": False,
                "reason": "total_notional_limit",
                "current": total_notional,
                "limit": self.risk_limits.max_total_notional
            }
        
        # All checks passed
        return {
            "approved": True,
            "risk_score": 0.0
        }
    
    @staticmethod
    def _infer_category(ticker: str) -> Optional[str]:
        """Infer market category from Kalshi ticker prefix heuristic."""
        t = ticker.upper()
        if any(t.startswith(p) for p in ("KXBTC", "KXETH", "KXSOL", "KXDOGE", "KXADA", "KXAVAX")):
            return "crypto"
        if any(t.startswith(p) for p in ("KXCPI", "KXPCE", "KXPPI")):
            return "inflation"
        if any(t.startswith(p) for p in ("KXFED", "KXFOMC", "KXRATE")):
            return "rates"
        if any(t.startswith(p) for p in ("KXGDP", "KXJOBS", "KXNFP", "KXUNEMPLOY", "KXECON")):
            return "economics"
        if any(t.startswith(p) for p in ("KXSPX", "KXNDX", "KXDJI", "KXSPY", "KXQQQ", "KXTSLA", "KXAAPL")):
            return "financials"
        if any(t.startswith(p) for p in ("KXPRES", "KXSENATE", "KXHOUSE", "KXELEC", "KXTRUMP", "KXBIDEN")):
            return "politics"
        if any(t.startswith(p) for p in ("KXNFL", "KXNBA", "KXMLB", "KXNHL", "KXSOCCER")):
            return "sports"
        if any(t.startswith(p) for p in ("KXTEMP", "KXHURR", "KXWEATHER", "KXCLIMATE")):
            return "climate"
        return None  # unknown — defaults to allowed

    def _check_daily_reset(self) -> None:
        """Reset daily PnL if new UTC day (T-042)."""
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).date()
        
        if today > self._last_reset_date:
            self.daily_pnl = 0.0
            self._last_reset_date = today
            logger.info("Daily PnL reset (new UTC day: %s)", today)
    
    async def _execute_order(self, intent: OrderIntent) -> None:
        """
        Execute order via Kalshi REST API
        
        Uses the Kalshi REST client to place actual orders
        """
        logger.info(
            f"[LIVE] Executing: {intent.side} {intent.qty}x {intent.market_ticker} "
            f"@ {intent.price:.3f} (client_tag={intent.client_tag})"
        )
        
        try:
            # Import REST client (lazy to avoid circular imports)
            from merid_core.kalshi.rest_client import get_rest_client
            import os
            
            # BUG-FIX: Use KALSHI_USE_DEMO (like main executor) instead of KALSHI_ENV
            # Old code defaulted to "demo" which caused mismatches in LIVE mode
            _use_demo = os.environ.get("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes", "on")
            _env = "demo" if _use_demo else "prod"
            
            # Get REST client (will reuse singleton)
            client = get_rest_client(
                key_id=os.environ.get("KALSHI_API_KEY_ID", ""),
                private_key_path=os.environ.get("KALSHI_PRIVATE_KEY_PATH", ""),
                env=_env
            )
            
            # Parse action and side from intent
            # intent.side format: "buy_yes", "sell_yes", "buy_no", "sell_no"
            # Kalshi API: action = "buy"/"sell", side = "yes"/"no"
            parts = intent.side.split("_")
            action = parts[0]    # "buy" or "sell"
            side = parts[1]      # "yes" or "no"
            
            # Convert price from 0-1 to cents (1-99)
            price_cents = int(intent.price * 100)
            price_cents = max(1, min(99, price_cents))
            
            # Create order via REST API (run in thread to avoid blocking the event loop)
            import asyncio as _asyncio
            response = await _asyncio.to_thread(
                client.create_order,
                ticker=intent.market_ticker,
                side=side,
                action=action,
                quantity=intent.qty,
                price=price_cents,
                client_order_id=intent.client_tag,
                order_type="limit",
                time_in_force="gtc",
            )
            
            # Extract order ID from response
            order_id = response.get("order", {}).get("order_id", "unknown")
            
            # Update position tracking only after confirmed submission
            order_status = response.get("order", {}).get("status", "")
            if order_status not in ("canceled", "cancelled"):
                delta = intent.qty if "buy" in intent.side else -intent.qty
                self.positions[intent.market_ticker] = self.positions.get(intent.market_ticker, 0) + delta
            
            await self._publish_outcome(
                intent,
                OrderStatus.SUBMITTED,
                order_id=order_id
            )
            
            logger.info(f"Order submitted successfully: {order_id} (status={order_status})")
            
        except Exception as e:
            logger.error(f"Failed to execute order: {e}", exc_info=True)
            await self._publish_outcome(
                intent,
                OrderStatus.ERROR,
                error=str(e)
            )
    
    async def _publish_rejection(self, intent: OrderIntent, risk_decision: Dict) -> None:
        """Publish risk rejection"""
        await self.event_bus.publish("risk.decisions", {
            "intent_id": intent.client_tag,
            "approved": False,
            "rejection_reason": risk_decision["reason"],
            "risk_score": 1.0,
            "timestamp": int(time.time() * 1000)
        })
        
        logger.info(
            f"Rejected intent {intent.client_tag}: {risk_decision['reason']}"
        )
    
    async def _publish_outcome(
        self,
        intent: OrderIntent,
        status: OrderStatus,
        order_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Publish execution outcome"""
        await self.event_bus.publish("executions", {
            "intent_id": intent.client_tag,
            "order_id": order_id,
            "status": status.value,
            "error_message": error,
            "timestamp": int(time.time() * 1000)
        })
    
    def stats(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        return {
            "intents_received": self.intents_received,
            "intents_executed": self.intents_executed,
            "intents_rejected_risk": self.intents_rejected_risk,
            "intents_rejected_rate": self.intents_rejected_rate,
            "positions": dict(self.positions),
            "daily_pnl": self.daily_pnl,
            "read_tokens": self.read_limiter.tokens,
            "write_tokens": self.write_limiter.tokens
        }
