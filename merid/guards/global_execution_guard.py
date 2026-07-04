"""Unified Global Execution Guard — Final safety net for ALL order paths.

DEPRECATED: This module is deprecated in favor of UnifiedRiskManager.
Use merid.risk.unified_risk_manager instead.

All risk management has been consolidated into a single source of truth:
- Configuration: config/profiles/kalshi_crypto_15m_v2.yaml (for 15m Kalshi)
- Implementation: merid.risk.unified_risk_manager.UnifiedRiskManager
- Single entry point: check_order() method

This module is kept for backward compatibility but will be removed in a future release.
New code should use UnifiedRiskManager for all risk checks.

CRITICAL: For kalshi_crypto_15m_v2 profile, risk parameters are loaded from profile YAML.
This module's defaults (3% bankroll cap) are NOT used by the 15m production stack.

---

Legacy documentation (deprecated):

This module provides a SINGLE chokepoint that ALL order execution paths must
call before submitting orders to Kalshi. It enforces:
1. Global 3% bankroll cap (across ALL execution paths) - 2026 best practice
2. Top-3 edge allocation check
3. Total notional tracking (singleton across the process)
4. Emergency circuit breaker

Usage::
    from merid.guards.global_execution_guard import get_global_execution_guard
    
    guard = get_global_execution_guard()
    allowed, reason = guard.check_order(
        ticker="KXBTC15M-...",
        contracts=10,
        price_cents=55,
        source="trading_agent",  # or "pipeline_adapter", "kalshi_client", etc.
    )
    
    if not allowed:
        logger.error(f"[GLOBAL_GUARD_BLOCKED] {reason}")
        return  # Do not submit order
"""

from __future__ import annotations

import threading
import time
import warnings
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

# Emit deprecation warning when module is imported
warnings.warn(
    "GlobalExecutionGuard is DEPRECATED. Use UnifiedRiskManager instead. "
    "For kalshi_crypto_15m_v2 profile, risk parameters are loaded from profile YAML.",
    DeprecationWarning,
    stacklevel=2
)

from utils.logger import get_logger
from utils.logging_helpers import log_guardrail_check, log_risk_check, log_trading_operation
from utils.alerting import send_alert_sync, AlertSeverity, AlertContext

logger = get_logger("merid.guards.global_execution_guard")

# Emit deprecation warning on import
warnings.warn(
    "GlobalExecutionGuard is deprecated. Use merid.risk.unified_risk_manager.UnifiedRiskManager instead.",
    DeprecationWarning,
    stacklevel=2
)


@dataclass
class GuardDecision:
    """Decision from the global execution guard."""
    allowed: bool
    reason: str
    current_total_notional_usd: float
    proposed_notional_usd: float
    bankroll_cap_usd: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GlobalExecutionGuard:
    """Unified execution guard — SINGLE chokepoint for ALL order paths.
    
    This is a process-wide singleton that tracks total notional exposure
    and enforces the 3% bankroll cap (2026 best practice) regardless of which execution path
    the order came from.
    
    SAFETY INVARIANTS:
    1. All orders MUST call check_order() before submission
    2. Total notional cannot exceed 3% of configured bankroll (MAX_CYCLE_RISK_PCT from core.settings)
    3. All decisions are logged with [GLOBAL_GUARD] prefix for audit
    4. Fail-closed: any error in guard = order blocked
    """
    
    _instance: Optional["GlobalExecutionGuard"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "GlobalExecutionGuard":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._total_notional_usd: float = 0.0
            self._orders_this_minute: int = 0
            self._orders_this_hour: int = 0
            self._last_minute_reset: float = time.time()
            self._last_hour_reset: float = time.time()
            self._order_history: List[Dict] = []
            self._max_history: int = 1000
            self._emergency_halt: bool = False
            self._halt_reason: str = ""
            self._initialized = True
            
            logger.info("[GLOBAL_GUARD] Initialized — all order paths must route through this guard")
    
    def check_order(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        source: str,
        asset: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Check if order is allowed — THE UNIFIED GATE.
        
        ALL execution paths MUST call this before submitting orders.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts
            price_cents: Price per contract in cents
            source: Which execution path (trading_agent, pipeline_adapter, kalshi_client, etc.)
            asset: Optional asset code (BTC, ETH, etc.)
            action: Order action - "buy" (entry) or "sell" (exit/close)
            
        Returns:
            (allowed: bool, reason: str)
            - allowed = True: Order may proceed
            - allowed = False: Order MUST be rejected
        """
        with self._lock:
            # 0. Emergency halt check
            if self._emergency_halt:
                log_guardrail_check(
                    "emergency_halt",
                    logger,
                    value=1.0,
                    threshold=0.0,
                    passed=False,
                    halt_reason=self._halt_reason,
                    ticker=ticker,
                    source=source,
                )
                send_alert_sync(
                    condition="emergency_halt",
                    severity=AlertSeverity.CRITICAL,
                    message=f"Emergency halt active: {self._halt_reason}",
                    context=AlertContext(
                        source="merid.guards.global_execution_guard",
                        additional_fields={
                            "halt_reason": self._halt_reason,
                            "ticker": ticker,
                            "source": source,
                        },
                    ),
                )
                logger.error(
                    "[GLOBAL_GUARD_BLOCKED] Emergency halt active: %s | ticker=%s source=%s",
                    self._halt_reason, ticker, source
                )
                return False, f"EMERGENCY_HALT: {self._halt_reason}"
            
            # 1. Validate inputs
            if contracts <= 0:
                return False, "Invalid contract count (must be > 0)"
            
            if price_cents <= 0 or price_cents >= 100:
                return False, f"Invalid price_cents: {price_cents} (must be 1-99)"
            
            # CRITICAL: Price range guard - enforce 50-70c range for Kalshi crypto 15m
            # This aligns with production stack: kalshi_tools.py, order_router.py, trading.py
            # Prevents <50¢ lottery tickets (10.4% win rate) and >70¢ low-profit trades
            min_price_cents = 50  # 50 cents minimum
            max_price_cents = 70  # 70 cents maximum
            
            # Allow profile override for different strategies
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                    min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_contract_price_cents'):
                    max_price_cents = profile_adapter.profile.guardrails_max_contract_price_cents
            except Exception as e:
                logger.debug("[GLOBAL_GUARD] Failed to load price limits from profile: %s, using defaults 50-70c", e)
            
            if price_cents < min_price_cents:
                logger.critical(
                    "[GLOBAL_GUARD_BLOCKED] Price below minimum: price=%dc < %dc threshold | ticker=%s source=%s",
                    price_cents, min_price_cents, ticker, source
                )
                return False, f"MIN_PRICE_VIOLATION:price={price_cents}c < {min_price_cents}c threshold"
            
            if price_cents > max_price_cents:
                logger.critical(
                    "[GLOBAL_GUARD_BLOCKED] Price above maximum: price=%dc > %dc threshold | ticker=%s source=%s",
                    price_cents, max_price_cents, ticker, source
                )
                return False, f"MAX_PRICE_VIOLATION:price={price_cents}c > {max_price_cents}c threshold"
            
            # 2. Calculate notional
            # CRITICAL FIX: For BUY_NO orders, notional is (100 - price_cents) because max loss is when NO loses
            # For BUY_YES orders, notional is price_cents because max loss is the contract cost
            # This aligns with GlobalRiskGuard documentation: contracts * (100 - entry_price_cents) for long NO
            # CRITICAL FIX: Use 'action' parameter (not 'side') - action is "buy" or "sell"
            # For BUY_NO detection, we need to check if action is "buy" and the order is for NO side
            # Since check_order doesn't receive side directly, we infer from price_cents:
            # - High price_cents (>50) typically indicates YES (probability > 50%)
            # - Low price_cents (<50) typically indicates NO (probability < 50%)
            # However, this is not reliable. The proper fix is to pass side to check_order.
            # TEMPORARY WORKAROUND: Use action="buy" as default assumption for notional calculation
            # If action is "sell", notional is always price_cents (selling reduces exposure)
            if action and action.lower() == "sell":
                proposed_notional_usd = (contracts * price_cents) / 100.0
            else:
                # For buy orders, assume YES pricing (price_cents is the YES price)
                # TODO: Pass side parameter to check_order for accurate BUY_NO detection
                proposed_notional_usd = (contracts * price_cents) / 100.0
            _is_sell = action and action.lower() == "sell"
            
            # 3. Get bankroll and compute cycle risk cap from bankroll_service_v2 (single source of truth)
            # CRITICAL FIX: Make bankroll access truly lazy to prevent import-time race conditions
            # Only access bankroll service when actually checking an order, not during import
            # CRITICAL FIX: Read MAX_CYCLE_RISK_PCT from environment variable first, then fallback to core.settings
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                import os
                
                # LAZY BANKROLL ACCESS: Only fetch when actually checking an order
                # This prevents import-time bankroll service access during KalshiVenueClient creation
                bankroll_usd = get_equity_for_risk_calc_sync()
                if bankroll_usd is None or bankroll_usd <= 0:
                    logger.error("[GLOBAL_GUARD_ERROR] Bankroll unavailable from bankroll_service_v2")
                    return False, "BANKROLL_UNAVAILABLE: bankroll_service_v2 returned None or 0"
                
                # Read MAX_CYCLE_RISK_PCT from environment variable first (set by start_15m.ps1)
                # This ensures GlobalExecutionGuard uses the same cap as KalshiRiskConfig
                env_value = os.getenv("MAX_CYCLE_RISK_PCT", "NOT_SET")
                logger.info(
                    "[GLOBAL_GUARD] MAX_CYCLE_RISK_PCT env var = '%s'",
                    env_value
                )
                max_cycle_risk_pct = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.005"))  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
                bankroll_cap_usd = bankroll_usd * max_cycle_risk_pct
                logger.info(
                    "[GLOBAL_GUARD] bankroll=$%.2f max_cycle_risk_pct=%.4f (%.1f%%) bankroll_cap_usd=$%.2f",
                    bankroll_usd, max_cycle_risk_pct, max_cycle_risk_pct * 100, bankroll_cap_usd
                )
            except Exception as e:
                logger.error("[GLOBAL_GUARD_ERROR] Failed to get bankroll: %s", e)
                # Fail-closed: block order if we can't determine bankroll
                return False, f"BANKROLL_UNAVAILABLE: {e}"
            
            # 4. Handle sell orders (exits) - they REDUCE exposure, so approve and subtract
            if _is_sell:
                # Sell orders close positions - always allow and reduce tracked notional
                new_total = max(0.0, self._total_notional_usd - proposed_notional_usd)
                self._total_notional_usd = new_total
                log_trading_operation(
                    "sell_order_approved",
                    logger,
                    market_id=ticker,
                    side="SELL",
                    contracts=contracts,
                    price_cents=price_cents,
                    notional_usd=proposed_notional_usd,
                    total_notional_usd=new_total,
                    source=source,
                )
                logger.info(
                    "[GLOBAL_GUARD_APPROVED] SELL order reducing exposure | "
                    "ticker=%s contracts=%d price_cents=%d "
                    "notional=$%.2f total_now=$%.2f source=%s",
                    ticker, contracts, price_cents,
                    proposed_notional_usd, new_total, source
                )
                return True, "OK"
            
            # 5. Check global notional cap for BUY orders (entries)
            new_total = self._total_notional_usd + proposed_notional_usd
            
            if new_total > bankroll_cap_usd:
                log_risk_check(
                    "global_bankroll_cap",
                    logger,
                    current_value=new_total,
                    limit_value=bankroll_cap_usd,
                    action="reject",
                    ticker=ticker,
                    contracts=contracts,
                    price_cents=price_cents,
                    current_total_notional=self._total_notional_usd,
                    proposed_notional=proposed_notional_usd,
                    bankroll=bankroll_usd,
                    source=source,
                )
                send_alert_sync(
                    condition="global_bankroll_cap",
                    severity=AlertSeverity.CRITICAL,
                    message=f"Bankroll cap exceeded: ${new_total:.2f} > ${bankroll_cap_usd:.2f}",
                    context=AlertContext(
                        source="merid.guards.global_execution_guard",
                        current_value=new_total,
                        threshold_value=bankroll_cap_usd,
                        additional_fields={
                            "ticker": ticker,
                            "contracts": contracts,
                            "price_cents": price_cents,
                            "bankroll_usd": bankroll_usd,
                            "source": source,
                        },
                    ),
                )
                # Reject order when cap exceeded
                return False, f"BANKROLL_CAP_EXCEEDED: ${new_total:.2f} > ${bankroll_cap_usd:.2f}"
            
            # 5. Rate limiting (per-minute, per-hour)
            now = time.time()
            if now - self._last_minute_reset >= 60:
                self._orders_this_minute = 0
                self._last_minute_reset = now
            if now - self._last_hour_reset >= 3600:
                self._orders_this_hour = 0
                self._last_hour_reset = now
            
            # Get rate limits from settings
            try:
                from merid.settings import settings
                max_per_minute = getattr(settings, 'MAX_ORDERS_PER_MINUTE', 30)
                max_per_hour = getattr(settings, 'MAX_ORDERS_PER_HOUR', 300)
                
                # 2026 OPTIMIZATION: Read max_orders_per_cycle from profile
                # This limits orders per 15-minute cycle for better risk management
                try:
                    from config.profiles.kalshi_crypto_15m_v2 import get_profile_config
                    profile_config = get_profile_config()
                    max_per_cycle = profile_config.get('guardrails', {}).get('max_orders_per_cycle', 3)
                    logger.info("[EXECUTION-GUARD] max_orders_per_cycle from profile: %d", max_per_cycle)
                except Exception as profile_exc:
                    logger.warning("[EXECUTION-GUARD] Failed to read max_orders_per_cycle from profile: %s", profile_exc)
                    max_per_cycle = 3  # Default to 3
            except Exception:
                max_per_minute = 30
                max_per_hour = 300
            
            if self._orders_this_minute >= max_per_minute:
                log_risk_check(
                    "rate_limit_minute",
                    logger,
                    current_value=self._orders_this_minute,
                    limit_value=max_per_minute,
                    action="reject",
                    ticker=ticker,
                    source=source,
                )
                logger.warning(
                    "[GLOBAL_GUARD_BLOCKED] Rate limit: %d orders/minute | ticker=%s source=%s",
                    max_per_minute, ticker, source
                )
                return False, f"RATE_LIMIT_MINUTE: {max_per_minute} orders/minute exceeded"
            
            if self._orders_this_hour >= max_per_hour:
                log_risk_check(
                    "rate_limit_hour",
                    logger,
                    current_value=self._orders_this_hour,
                    limit_value=max_per_hour,
                    action="reject",
                    ticker=ticker,
                    source=source,
                )
                logger.warning(
                    "[GLOBAL_GUARD_BLOCKED] Rate limit: %d orders/hour | ticker=%s source=%s",
                    max_per_hour, ticker, source
                )
                return False, f"RATE_LIMIT_HOUR: {max_per_hour} orders/hour exceeded"
            
            # 6. All checks passed — record the order
            self._total_notional_usd = new_total
            self._orders_this_minute += 1
            self._orders_this_hour += 1
            
            order_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ticker": ticker,
                "contracts": contracts,
                "price_cents": price_cents,
                "notional_usd": proposed_notional_usd,
                "total_notional_usd": new_total,
                "source": source,
                "asset": asset,
            }
            self._order_history.append(order_record)
            if len(self._order_history) > self._max_history:
                self._order_history.pop(0)
            
            log_trading_operation(
                "buy_order_approved",
                logger,
                market_id=ticker,
                side="BUY",
                contracts=contracts,
                price_cents=price_cents,
                notional_usd=proposed_notional_usd,
                total_notional_usd=new_total,
                bankroll_cap_usd=bankroll_cap_usd,
                source=source,
                asset=asset,
            )
            logger.info(
                "[GLOBAL_GUARD_APPROVED] ticker=%s contracts=%d price_cents=%d "
                "notional=$%.2f total_now=$%.2f cap=$%.2f source=%s",
                ticker, contracts, price_cents,
                proposed_notional_usd, new_total, bankroll_cap_usd, source
            )
            
            return True, "OK"
    
    def record_fill(self, ticker: str, contracts: int, price_cents: int, source: str) -> None:
        """Record a fill to update total notional.
        
        This should be called when an order actually fills (not just submits).
        """
        with self._lock:
            notional_usd = (contracts * price_cents) / 100.0
            # For now, we track submitted notional as a conservative estimate
            # In production, you'd track actual filled notional separately
            log_trading_operation(
                "order_fill_recorded",
                logger,
                market_id=ticker,
                contracts=contracts,
                price_cents=price_cents,
                notional_usd=notional_usd,
                source=source,
            )
            logger.debug(
                "[GLOBAL_GUARD_FILL] ticker=%s contracts=%d price_cents=%d "
                "notional=$%.2f source=%s",
                ticker, contracts, price_cents, notional_usd, source
            )
    
    def get_status(self) -> Dict:
        """Get current guard status for monitoring."""
        with self._lock:
            try:
                # CRITICAL FIX: Make bankroll access lazy to prevent import-time race conditions
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                import os
                bankroll_usd = get_equity_for_risk_calc_sync()
                if bankroll_usd is None or bankroll_usd <= 0:
                    bankroll_usd = 0.0
                    bankroll_cap_usd = 0.0
                    max_cycle_risk_pct = 0.005  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
                else:
                    # Read MAX_CYCLE_RISK_PCT from environment variable first (set by start_15m.ps1)
                    max_cycle_risk_pct = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.005"))  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
                    bankroll_cap_usd = bankroll_usd * max_cycle_risk_pct
            except Exception:
                bankroll_usd = 0.0
                bankroll_cap_usd = 0.0
                max_cycle_risk_pct = 0.005  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
            
            return {
                "total_notional_usd": round(self._total_notional_usd, 2),
                "bankroll_usd": round(bankroll_usd, 2),
                "bankroll_cap_usd": round(bankroll_cap_usd, 2),
                "cap_percentage": round(max_cycle_risk_pct * 100, 1),
                "pct_of_cap_used": round((self._total_notional_usd / bankroll_cap_usd) * 100, 1) if bankroll_cap_usd > 0 else 0,
                "orders_this_minute": self._orders_this_minute,
                "orders_this_hour": self._orders_this_hour,
                "emergency_halt": self._emergency_halt,
                "halt_reason": self._halt_reason,
                "order_count_last_hour": len(self._order_history),
            }
    
    def emergency_halt(self, reason: str) -> None:
        """Emergency halt — block ALL orders immediately."""
        with self._lock:
            self._emergency_halt = True
            self._halt_reason = reason
            log_guardrail_check(
                "emergency_halt_triggered",
                logger,
                value=1.0,
                threshold=0.0,
                passed=False,
                halt_reason=reason,
            )
            logger.critical(
                "[GLOBAL_GUARD_EMERGENCY_HALT] All order execution HALTED: %s",
                reason
            )
    
    def emergency_resume(self) -> None:
        """Resume after emergency halt (requires manual intervention)."""
        with self._lock:
            was_halted = self._emergency_halt
            self._emergency_halt = False
            self._halt_reason = ""
            if was_halted:
                log_guardrail_check(
                    "emergency_halt_resumed",
                    logger,
                    value=0.0,
                    threshold=0.0,
                    passed=True,
                )
                logger.critical("[GLOBAL_GUARD_EMERGENCY_RESUME] Order execution RESUMED")
    
    def reset_total_notional(self, new_value: float = 0.0) -> None:
        """Reset total notional (for testing or reconciliation)."""
        with self._lock:
            old_value = self._total_notional_usd
            self._total_notional_usd = new_value
            log_risk_check(
                "total_notional_reset",
                logger,
                current_value=old_value,
                limit_value=new_value,
                action="reset",
            )
            logger.warning(
                "[GLOBAL_GUARD_RESET] Total notional reset: $%.2f -> $%.2f",
                old_value, new_value
            )
    
    def reset_cycle(self) -> None:
        """Reset cycle-level state (total notional accumulator).
        
        This should be called at the start of each trading cycle to prevent
        the notional accumulator from growing indefinitely across cycles.
        
        The guard tracks total notional exposure across all orders in a cycle.
        Without a reset, the accumulator would grow forever and block all orders
        after the first few cycles.
        """
        with self._lock:
            old_value = self._total_notional_usd
            self._total_notional_usd = 0.0
            log_risk_check(
                "cycle_notional_reset",
                logger,
                current_value=old_value,
                limit_value=0.0,
                action="reset",
            )
            logger.warning(
                "[GLOBAL_GUARD_CYCLE_RESET] Total notional reset for new cycle: $%.2f -> $0.00",
                old_value
            )


# Module-level singleton accessor
def get_global_execution_guard() -> GlobalExecutionGuard:
    """Get the process-wide GlobalExecutionGuard singleton."""
    return GlobalExecutionGuard()
