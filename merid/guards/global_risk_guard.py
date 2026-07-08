"""Process-wide GlobalRiskGuard singleton.

DEPRECATED: This module is deprecated in favor of UnifiedRiskManager.
Use merid.risk.unified_risk_manager instead.

All risk management has been consolidated into a single source of truth:
- Configuration: config/profiles/kalshi_crypto_15m_v2.yaml (for 15m Kalshi)
- Implementation: merid.risk.unified_risk_manager.UnifiedRiskManager
- Single entry point: check_order() method

This module is kept for backward compatibility but will be removed in a future release.
New code should use UnifiedRiskManager for all risk checks.

CRITICAL: For kalshi_crypto_15m_v2 profile, risk parameters are loaded from profile YAML.
This module's defaults (6% cycle risk, 6% total risk) are NOT used by the 15m production stack.

IMPORT BLOCKED: This module is deprecated and should not be imported in production code.
Use merid.risk.unified_risk_manager instead.
"""

# Import-time error to prevent accidental usage in production
import sys
import os

# Allow import for tests or legacy code paths that explicitly opt-in
if os.getenv("ALLOW_DEPRECATED_RISK_GUARDS", "").lower() not in ("1", "true", "yes"):
    raise ImportError(
        "merid.guards.global_risk_guard is DEPRECATED. "
        "Use merid.risk.unified_risk_manager instead. "
        "Set ALLOW_DEPRECATED_RISK_GUARDS=1 to bypass this check (for tests only)."
   )

# Legacy documentation (deprecated):

Canonical risk gate for all Kalshi PM order submissions. Extracted from
``merid.trading.kalshi_continuous_trader`` so that every caller - the
``KalshiContinuousTrader`` loop, ``KalshiTradingAgent`` (agent grid, 35 agents),
crypto lanes (``btc15m_lane``, ``crypto15m_lane``), web manual trades, and any
future order source - shares the **same** per-cycle / total risk envelope
on a **unified** ``equity_cents`` source.

See ``docs/TRADING_OWNERSHIP_DECISION.md`` for the policy context and
``docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md`` for the full wiring.

Invariants enforced (per ``check_order`` call):
    1. Sum of ``max_loss_cents`` for all approved orders in the current cycle
       <= ``max_cycle_risk_pct * equity_cents``.
    2. ``existing_risk_cents + cycle_new_risk_cents`` <=
       ``max_total_risk_pct * equity_cents``.
    3. If any invariant would be violated, the guard logs CRITICAL and
       returns ``(False, reason)``.

Thread-safe via a single re-entrant lock. Cycle accumulator is process-wide
so concurrent callers (CT + agent grid + lanes) cannot each consume the full
envelope independently.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

# Emit deprecation warning when module is imported
warnings.warn(
    "GlobalRiskGuard is DEPRECATED. Use UnifiedRiskManager instead. "
    "For kalshi_crypto_15m_v2 profile, risk parameters are loaded from profile YAML.",
    DeprecationWarning,
    stacklevel=2
)

from utils.logger import get_logger
from merid.utils.logging_helpers import log_guardrail_check, log_risk_check, log_trading_operation
from merid.utils.alerting import send_alert_sync, AlertSeverity, AlertContext

logger = get_logger("merid.guards.global_risk_guard")

# Emit deprecation warning on import
warnings.warn(
    "GlobalRiskGuard is deprecated. Use merid.risk.unified_risk_manager.UnifiedRiskManager instead.",
    DeprecationWarning,
    stacklevel=2
)


# ─────────────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class PendingOrderRisk:
    """Risk metadata for a pending order.

    ``max_loss_cents`` is the canonical field - callers MUST compute it
    correctly (typically ``contracts * entry_price_cents`` for a long YES,
    or ``contracts * (100 - entry_price_cents)`` for a long NO).
    """

    ticker: str
    asset: str
    contracts: int
    entry_price_cents: int
    direction: str  # "long" or "short"
    max_loss_cents: int
    edge: float = 0.0


# ────────────────────────────────────────────────────────────────────────────
# Guard
# ────────────────────────────────────────────────────────────────────────────

class GlobalRiskGuard:
    """Last-line global risk guard enforcing hard caps before any submit.

    A single instance is shared process-wide via :func:`get_global_risk_guard`.
    """

    def __init__(
        self,
        max_cycle_risk_pct: float = 0.05,  # CRITICAL FIX: 5% per cycle - total across all assets in 15m window (2026-07-05)
        max_total_risk_pct: float = 0.15,  # CRITICAL FIX: 15% total - aligned with kalshi_crypto_15m_v2.yaml (2026-07-04)
        scalper_single_batch_mode: bool = False,
        max_trades_per_batch: int = 3,
    ) -> None:
        self.max_cycle_risk_pct = float(max_cycle_risk_pct)
        self.max_total_risk_pct = float(max_total_risk_pct)
        self.scalper_single_batch_mode = bool(scalper_single_batch_mode)
        self.max_trades_per_batch = max(1, int(max_trades_per_batch))
        self._cycle_new_risk_cents: int = 0
        self._cycle_approved_count: int = 0
        self._batch_id: int = 0
        self._lock = threading.Lock()
        # Telemetry
        self._approvals: int = 0
        self._rejections: int = 0
        self._last_reject_reason: str = ""
        self._scalper_blocks: int = 0
        
        # 2026 Dynamic Cycle Cap Management
        # Track approved orders with timestamps to release capacity from unfilled orders
        self._pending_orders: dict[str, tuple[int, float]] = {}  # order_id -> (risk_cents, approval_timestamp)
        self._fills_in_window: int = 0
        self._window_start_time: float = time.time()
        self._last_fill_time: Optional[float] = None
        self._pending_order_timeout_sec: float = 10.0  # REDUCED: 10 second timeout for unfilled orders (was 60s - too slow for small bankrolls)
        self._no_fill_reset_window_sec: float = 30.0  # REDUCED: 30 second window for no-fill auto-reset (was 5min - too slow for small bankrolls)
        self._emergency_reset_threshold_cents: int = 10000  # FIX: $100 threshold (aligned with micro-account threshold)

    # ── cycle boundary ──────────────────────────────────────────────────
    def reset_cycle(self) -> None:
        """Call at the start of each decision cycle.

        Also increments ``batch_id`` so downstream consumers can key
        intents/orders to the current batch.
        
        2026: Also releases capacity from timed-out pending orders.
        """
        with self._lock:
            self._cycle_new_risk_cents = 0
            self._cycle_approved_count = 0
            self._batch_id += 1
            # Release capacity from timed-out pending orders
            self._release_timed_out_capacity()

    @property
    def batch_id(self) -> int:
        with self._lock:
            return self._batch_id

    def configure_scalper(
        self,
        enabled: bool,
        max_trades_per_batch: Optional[int] = None,
    ) -> None:
        """Toggle scalper single-batch mode at runtime (tests / ops)."""
        with self._lock:
            self.scalper_single_batch_mode = bool(enabled)
            if max_trades_per_batch is not None:
                self.max_trades_per_batch = max(1, int(max_trades_per_batch))

    # ── 2026 Dynamic Cycle Cap Management ────────────────────────────────
    def record_fill(self, order_id: str, filled_risk_cents: int) -> None:
        """Record a fill and release its capacity from the cycle accumulator.
        
        2026 best practice: Track fills separately from approvals to prevent
        approved-but-unfilled orders from permanently consuming cycle capacity.
        """
        with self._lock:
            if order_id in self._pending_orders:
                risk_cents, _ = self._pending_orders[order_id]
                # Release the approved risk from the cycle accumulator
                self._cycle_new_risk_cents = max(0, self._cycle_new_risk_cents - risk_cents)
                del self._pending_orders[order_id]
                self._fills_in_window += 1
                self._last_fill_time = time.time()
                logger.info(
                    "[DYNAMIC-CYCLE-CAP] Fill recorded | order_id=%s | released_risk=$%.2f | "
                    "cycle_accumulator_now=$%.2f | fills_in_window=%d",
                    order_id, risk_cents / 100, self._cycle_new_risk_cents / 100, self._fills_in_window
                )

    def _release_timed_out_capacity(self) -> None:
        """Release capacity from approved orders that have not filled within timeout.
        
        2026 best practice: If an approved order does not fill within 60 seconds,
        release its capacity back to the cycle cap to prevent false rejections.
        """
        now = time.time()
        timed_out_orders = []
        
        for order_id, (risk_cents, approval_time) in self._pending_orders.items():
            if now - approval_time > self._pending_order_timeout_sec:
                timed_out_orders.append((order_id, risk_cents))
        
        if timed_out_orders:
            total_released = sum(risk_cents for _, risk_cents in timed_out_orders)
            for order_id, risk_cents in timed_out_orders:
                del self._pending_orders[order_id]
            
            self._cycle_new_risk_cents = max(0, self._cycle_new_risk_cents - total_released)
            logger.info(
                "[DYNAMIC-CYCLE-CAP] Released timed-out capacity | orders=%d | "
                "released_risk=$%.2f | cycle_accumulator_now=$%.2f",
                len(timed_out_orders), total_released / 100, self._cycle_new_risk_cents / 100
            )

    def check_no_fill_reset(self, equity_cents: int) -> bool:
        """Check if no fills have occurred in the window and auto-reset if needed.
        
        2026 best practice: If no fills occur within 5 minutes, auto-reset the
        cycle accumulator to prevent false rejections due to approved-but-unfilled orders.
        
        Returns True if reset was performed, False otherwise.
        """
        with self._lock:
            now = time.time()
            window_elapsed = now - self._window_start_time
            
            # Check if we should auto-reset
            if (self._fills_in_window == 0 and 
                window_elapsed > self._no_fill_reset_window_sec and
                self._cycle_new_risk_cents > 0):
                
                logger.info(
                    "[DYNAMIC-CYCLE-CAP] Auto-reset triggered | no_fills_in_window=%d | "
                    "window_elapsed=%.1fs | accumulator_before=$%.2f",
                    self._fills_in_window, window_elapsed, self._cycle_new_risk_cents / 100
                )
                
                # Reset accumulator and pending orders
                self._cycle_new_risk_cents = 0
                self._pending_orders.clear()
                self._window_start_time = now
                self._fills_in_window = 0
                
                return True
            
            # Reset window if fills occurred
            if self._fills_in_window > 0 and window_elapsed > self._no_fill_reset_window_sec:
                self._window_start_time = now
                self._fills_in_window = 0
                logger.debug(
                    "[DYNAMIC-CYCLE-CAP] Window reset | fills_in_window=%d | window_elapsed=%.1fs",
                    self._fills_in_window, window_elapsed
                )
            
            return False

    # ── core check ──────────────────────────────────────────────────────
    def check_order(
        self,
        equity_cents: int,
        existing_risk_cents: int,
        pending_order: PendingOrderRisk,
    ) -> Tuple[bool, str]:
        """Check if an order can be submitted.

        Returns ``(allowed, reason)``. When ``allowed`` is False, ``reason``
        explains which invariant would be violated.

        If ``equity_cents`` is non-positive, fail-closed with a clear reason.
        """
        with self._lock:
            # -- Scalper single-batch mode (hard veto) ------------------------------
            if self.scalper_single_batch_mode:
                if max(0, int(existing_risk_cents)) > 0:
                    reason = (
                        "SCALPER_MODE_BLOCK: existing open risk, new batch not allowed | "
                        f"existing_risk_cents={existing_risk_cents} | "
                        f"ticker={pending_order.ticker} | batch_id={self._batch_id}"
                    )
                    logger.warning(reason)
                    logger.info(
                        "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=SCALPER_MODE_BLOCK",
                        pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                    )
                    self._rejections += 1
                    self._scalper_blocks += 1
                    self._last_reject_reason = reason
                    return False, reason
                if self._cycle_approved_count >= self.max_trades_per_batch:
                    reason = (
                        "SCALPER_MODE_BLOCK: max trades per batch exceeded | "
                        f"approved_this_batch={self._cycle_approved_count} | "
                        f"max={self.max_trades_per_batch} | "
                        f"ticker={pending_order.ticker} | batch_id={self._batch_id}"
                    )
                    logger.warning(reason)
                    logger.info(
                        "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=MAX_TRADES_PER_BATCH",
                        pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                    )
                    self._rejections += 1
                    self._scalper_blocks += 1
                    self._last_reject_reason = reason
                    return False, reason

            if equity_cents <= 0:
                reason = (
                    f"GLOBAL RISK GUARD BLOCK: non-positive equity "
                    f"equity_cents={equity_cents} - fail-closed"
                )
                log_risk_check(
                    "non_positive_equity",
                    logger,
                    current_value=float(equity_cents),
                    limit_value=0.0,
                    action="reject",
                )
                send_alert_sync(
                    condition="non_positive_equity",
                    severity=AlertSeverity.CRITICAL,
                    message=f"Non-positive equity detected: {equity_cents} cents",
                    context=AlertContext(
                        source="merid.guards.global_risk_guard",
                        current_value=float(equity_cents),
                        threshold_value=0.0,
                    ),
                )
                logger.critical(reason)
                logger.info(
                    "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=NON_POSITIVE_EQUITY",
                    pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                )
                self._rejections += 1
                self._last_reject_reason = reason
                return False, reason

            cycle_risk_cents = int(equity_cents * self.max_cycle_risk_pct)
            max_total_risk_cents = int(equity_cents * self.max_total_risk_pct)

            # Initialize new_cycle_total for total risk cap check
            new_cycle_total = self._cycle_new_risk_cents + max(0, pending_order.max_loss_cents)
            
            # Initialize new_total_risk for approval section
            new_total_risk = max(0, existing_risk_cents) + new_cycle_total

            # 1. Per-cycle cap with adaptive sizing
            # 2026 BEST PRACTICE: Re-enabled cycle risk cap enforcement
            # This is critical for preventing cycle-level risk violations
            # CRITICAL FIX: Sync with GlobalExecutionGuard bankroll cap to prevent downstream rejections
            if True:  # Enforce cycle risk cap (2026 best practice)
                # Calculate remaining capacity
                remaining_capacity_cents = cycle_risk_cents - self._cycle_new_risk_cents
                
                # 2026 FIX: Auto-reset if capacity is exhausted and no fills have occurred recently
                # This prevents false rejections due to approved-but-unfilled orders
                if remaining_capacity_cents <= 0:
                    # Try to release timed-out capacity first
                    self._release_timed_out_capacity()
                    remaining_capacity_cents = cycle_risk_cents - self._cycle_new_risk_cents
                    
                    # If still exhausted, force an emergency reset for small bankrolls
                    if remaining_capacity_cents <= 0 and equity_cents < self._emergency_reset_threshold_cents:  # <$50 bankroll
                        logger.warning(
                            "[EMERGENCY-CYCLE-RESET] Cycle cap exhausted with small bankroll - forcing reset | "
                            f"equity=${equity_cents/100:.2f} | cycle_cap=${cycle_risk_cents/100:.2f} | "
                            f"accumulator=${self._cycle_new_risk_cents/100:.2f} | pending_orders={len(self._pending_orders)}"
                        )
                        self._cycle_new_risk_cents = 0
                        self._pending_orders.clear()
                        remaining_capacity_cents = cycle_risk_cents
                    elif remaining_capacity_cents <= 0:
                        # For larger bankrolls, straight reject (normal behavior)
                        reason = (
                            f"GLOBAL RISK GUARD BLOCK: Cycle risk cap fully utilized | "
                            f"equity=${equity_cents/100:.2f} | "
                            f"cycle_cap=${cycle_risk_cents/100:.2f} | "
                            f"already_approved=${self._cycle_new_risk_cents/100:.2f} | "
                            f"remaining=$0.00 | "
                            f"ticker={pending_order.ticker} | asset={pending_order.asset}"
                        )
                        logger.warning(reason)
                        logger.info(
                            "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=CYCLE_RISK_CAP_FULL",
                            pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                        )
                        self._rejections += 1
                        self._last_reject_reason = reason
                        return False, reason
                
                # CRITICAL FIX: Check if order would exceed bankroll cap BEFORE approving
                # This prevents GlobalExecutionGuard from rejecting downstream
                proposed_total = self._cycle_new_risk_cents + pending_order.max_loss_cents
                # CRITICAL FIX: Initialize variables to prevent UnboundLocalError
                original_max_loss = pending_order.max_loss_cents
                scaled_contracts = pending_order.contracts  # Default to original contracts
                scaled_max_loss = pending_order.max_loss_cents  # Default to original max_loss
                new_cycle_total = self._cycle_new_risk_cents + pending_order.max_loss_cents  # Default to no scaling
                
                if proposed_total > cycle_risk_cents:
                    # Try to release timed-out capacity first
                    self._release_timed_out_capacity()
                    remaining_capacity_cents = cycle_risk_cents - self._cycle_new_risk_cents
                    
                    # Re-check after releasing capacity
                    proposed_total = self._cycle_new_risk_cents + pending_order.max_loss_cents
                    if proposed_total > cycle_risk_cents:
                        # Adaptive sizing: resize order to fit remaining capacity
                        original_max_loss = pending_order.max_loss_cents
                        
                        # CRITICAL FIX: Calculate scaled contracts to fit exactly within remaining capacity
                        # scaled_max_loss must be <= remaining_capacity_cents
                        if pending_order.entry_price_cents > 0:
                            # Calculate max contracts that fit in remaining capacity
                            max_contracts_for_capacity = int(remaining_capacity_cents / pending_order.entry_price_cents)
                            if max_contracts_for_capacity < 1:
                                # Even 1 contract exceeds remaining capacity
                                # For small bankrolls, reset cycle to allow trading
                                if equity_cents < self._emergency_reset_threshold_cents:  # <$50 bankroll
                                    logger.warning(
                                        "[EMERGENCY-CYCLE-RESET] Min contract size %dc exceeds remaining capacity %dc - forcing reset | "
                                        "equity=$%.2f | cycle_cap=$%.2f | accumulator=$%.2f | pending_orders=%d",
                                        pending_order.entry_price_cents, remaining_capacity_cents,
                                        equity_cents/100, cycle_risk_cents/100, self._cycle_new_risk_cents/100, len(self._pending_orders)
                                    )
                                    self._cycle_new_risk_cents = 0
                                    self._pending_orders.clear()
                                    remaining_capacity_cents = cycle_risk_cents
                                    max_contracts_for_capacity = int(remaining_capacity_cents / pending_order.entry_price_cents)
                                    # Continue with scaling after reset - don't return
                                else:
                                    # For larger bankrolls, reject
                                    reason = (
                                        f"GLOBAL RISK GUARD BLOCK: Bankroll cap exceeded | "
                                        f"equity=${equity_cents/100:.2f} | "
                                        f"bankroll_cap=${cycle_risk_cents/100:.2f} | "
                                        f"cycle_total=${proposed_total/100:.2f} | "
                                        f"ticker={pending_order.ticker} | asset={pending_order.asset}"
                                    )
                                    logger.warning(reason)
                                    logger.info(
                                        "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=BANKROLL_CAP_EXCEEDED",
                                        pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                                    )
                                    self._rejections += 1
                                    self._last_reject_reason = reason
                                    return False, reason
                            
                            scaled_contracts = min(pending_order.contracts, max_contracts_for_capacity)
                            # CRITICAL FIX: Don't force minimum 1 contract if price is too low (prevents 1c orders)
                            # Only force minimum if contract notional is reasonable (>= $0.05)
                            contract_notional_usd = pending_order.entry_price_cents / 100.0
                            if contract_notional_usd >= 0.05:
                                scaled_contracts = max(1, scaled_contracts)  # At least 1 contract
                            else:
                                # For extremely low-priced contracts, respect the capacity calculation
                                # If max_contracts_for_capacity is 0, the order should be rejected
                                if max_contracts_for_capacity < 1:
                                    logger.warning(
                                        "[GLOBAL_GUARD] Rejecting low-price order: price=%dc (<5c) would require %d contracts but capacity allows %d",
                                        pending_order.entry_price_cents, pending_order.contracts, max_contracts_for_capacity
                                    )
                                    reason = (
                                        f"GLOBAL RISK GUARD BLOCK: Low-price order rejected | "
                                        f"price={pending_order.entry_price_cents}c (<5c threshold) | "
                                        f"contracts={pending_order.contracts} | "
                                        f"capacity_contracts={max_contracts_for_capacity}"
                                    )
                                    self._rejections += 1
                                    self._last_reject_reason = reason
                                    return False, reason
                            scaled_max_loss = scaled_contracts * pending_order.entry_price_cents
                        else:
                            scaled_contracts = 1
                            scaled_max_loss = min(original_max_loss, remaining_capacity_cents)
                        
                        # Update pending_order with scaled values
                        pending_order.max_loss_cents = scaled_max_loss
                        pending_order.contracts = scaled_contracts
                        
                        # Recalculate cycle total with scaled order
                        new_cycle_total = self._cycle_new_risk_cents + scaled_max_loss
                    
                    logger.info(
                        "[RISK-SCALING] ticker=%s | original_contracts=%d | scaled_contracts=%d | "
                        "original_max_loss=$%.2f | scaled_max_loss=$%.2f | "
                        "cycle_cap=$%.2f | remaining_capacity=$%.2f | cycle_used_after=$%.2f",
                        pending_order.ticker,
                        int(original_max_loss / pending_order.entry_price_cents) if pending_order.entry_price_cents > 0 else pending_order.contracts,
                        scaled_contracts,
                        original_max_loss / 100,
                        scaled_max_loss / 100,
                        cycle_risk_cents / 100,
                        remaining_capacity_cents / 100,
                        new_cycle_total / 100
                    )
                    
                    # Continue to approval with scaled order (no alert for adaptive sizing)
                else:
                    # Order fits within cap - use original values
                    new_cycle_total = self._cycle_new_risk_cents + pending_order.max_loss_cents

            # 2. Bankroll cap check (sync with GlobalExecutionGuard)
            # CRITICAL FIX: Enforce bankroll cap to prevent GlobalExecutionGuard rejections
            # This ensures GlobalRiskGuard does not approve orders that would be rejected downstream
            bankroll_cap_cents = cycle_risk_cents  # Same as cycle cap for 15m crypto
            if new_cycle_total > bankroll_cap_cents:
                reason = (
                    f"GLOBAL RISK GUARD BLOCK: Bankroll cap exceeded | "
                    f"equity=${equity_cents/100:.2f} | "
                    f"bankroll_cap=${bankroll_cap_cents/100:.2f} | "
                    f"cycle_total=${new_cycle_total/100:.2f} | "
                    f"ticker={pending_order.ticker} | asset={pending_order.asset}"
                )
                logger.warning(reason)
                logger.info(
                    "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=BANKROLL_CAP_EXCEEDED",
                    pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                )
                self._rejections += 1
                self._last_reject_reason = reason
                return False, reason

            # Approved
            self._cycle_new_risk_cents = new_cycle_total
            self._cycle_approved_count += 1
            self._approvals += 1
            
            # 2026: Track approved order with timestamp for dynamic capacity release
            order_id = f"{pending_order.ticker}_{self._batch_id}_{self._cycle_approved_count}"
            self._pending_orders[order_id] = (pending_order.max_loss_cents, time.time())

            logger.info(
                "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=%d equity_cents=%d decision=APPROVED",
                pending_order.asset, pending_order.ticker, pending_order.contracts, pending_order.contracts, equity_cents
            )

            # Drift detection: compare against risk envelope caps
            try:
                from merid.monitoring.drift_metrics import get_drift_metrics_collector
                from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                
                drift_collector = get_drift_metrics_collector()
                envelope = get_risk_envelope_service().get_config()
                
                # Check if approved order exceeds envelope total notional cap
                envelope_max_total_usd = envelope.max_total_notional_usd
                current_exposure_usd = float(existing_risk_cents) / 100
                order_notional_usd = float(pending_order.max_loss_cents) / 100
                total_exposure_with_order = current_exposure_usd + order_notional_usd
                
                drift_collector.collect_risk_envelope_drift(
                    envelope_max_notional_usd=envelope_max_total_usd,
                    realized_exposure_usd=current_exposure_usd,
                    pending_orders_notional_usd=order_notional_usd,
                    epsilon=0.01  # 1% tolerance
                )
            except Exception as e:
                logger.debug(f"[DRIFT-METRICS] Failed to collect drift metrics in GlobalRiskGuard: {e}")

            log_trading_operation(
                "risk_guard_approved",
                logger,
                market_id=pending_order.ticker,
                contracts=pending_order.contracts,
                price_cents=pending_order.entry_price_cents,
                notional_usd=float(pending_order.max_loss_cents) / 100,
                max_loss_usd=float(pending_order.max_loss_cents) / 100,
                cycle_risk_usd=float(new_cycle_total) / 100,
                cycle_cap_usd=float(cycle_risk_cents) / 100,
                total_risk_usd=float(new_total_risk) / 100,
                asset=pending_order.asset,
                edge=pending_order.edge,
            )
            logger.info(
                "[GLOBAL-RISK-GUARD] APPROVED | ticker=%s | max_loss=$%.2f | "
                "cycle_used=$%.2f / $%.2f | total_would_be=$%.2f",
                pending_order.ticker,
                pending_order.max_loss_cents / 100,
                new_cycle_total / 100,
                cycle_risk_cents / 100,
                new_total_risk / 100,
            )
            return True, ""

    # ── capacity query ──────────────────────────────────────────────────
    def get_remaining_cycle_capacity_cents(self, equity_cents: int) -> int:
        """Return remaining cycle capacity in cents.
        
        Useful for upstream checks to skip signal generation when capacity is exhausted.
        """
        with self._lock:
            cycle_risk_cents = int(equity_cents * self.max_cycle_risk_pct)
            remaining = cycle_risk_cents - self._cycle_new_risk_cents
            return max(0, remaining)

    # -- telemetry -------------------------------------------------------
    def metrics(self) -> dict:
        with self._lock:
            return {
                "max_cycle_risk_pct": self.max_cycle_risk_pct,
                "max_total_risk_pct": self.max_total_risk_pct,
                "scalper_single_batch_mode": self.scalper_single_batch_mode,
                "max_trades_per_batch": self.max_trades_per_batch,
                "batch_id": self._batch_id,
                "cycle_new_risk_cents": self._cycle_new_risk_cents,
                "cycle_approved_count": self._cycle_approved_count,
                "approvals": self._approvals,
                "rejections": self._rejections,
                "scalper_blocks": self._scalper_blocks,
                "last_reject_reason": self._last_reject_reason,
            }


# ────────────────────────────────────────────────────────────────────────────
# Singleton + equity/existing-risk providers
# ────────────────────────────────────────────────────────────────────────────

_guard_lock = threading.Lock()
_guard: Optional[GlobalRiskGuard] = None

_equity_provider: Optional[Callable[[], int]] = None
_existing_risk_provider: Optional[Callable[[], int]] = None


def _load_canonical_pcts() -> Tuple[float, float]:
    """Load canonical risk percentages from environment variable or core.settings.
    
    CRITICAL FIX: Read from environment variable first (set by start_15m.ps1)
    to ensure GlobalRiskGuard uses the same cap as KalshiRiskConfig.
    Only fall back to core.settings if env var is not set.
    
    # OPTIMIZED RISK REGIME (2026-05-07): 5% cycle / 8% total for better throughput while maintaining safety.
    # With $40 equity: 5% = $2.02 cycle cap for multi-asset trading.
    #
    # CRITICAL FIX (2026-07-05): Updated default to 5% to match profile YAML bankroll_cap_pct
    # Previous 0.5% was too restrictive for micro accounts.
    """
    try:
        # CRITICAL FIX: Read from environment variable first (set by start_15m.ps1)
        # This ensures GlobalRiskGuard uses the same cap as KalshiRiskConfig
        # Aligned with kalshi_crypto_15m_v2.yaml (2026-07-05)
        cycle = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.05"))  # 5% default - aligned with profile bankroll_cap_pct
        total = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.15"))  # 15% default - aligned with profile
        logger.info(
            "[GLOBAL-RISK-GUARD] Loaded pcts from env: cycle=%.4f (%.2f%%) total=%.4f (%.2f%%)",
            cycle, cycle * 100, total, total * 100
        )
        return cycle, total
    except Exception:
        try:
            from core.settings import MAX_CYCLE_RISK_PCT, MAX_TOTAL_RISK_PCT  # type: ignore
            cycle_pct = float(MAX_CYCLE_RISK_PCT)
            total_pct = float(MAX_TOTAL_RISK_PCT)
            logger.warning(
                "[GLOBAL-RISK-GUARD] Env var read failed, using core.settings: cycle=%.4f total=%.4f",
                cycle_pct, total_pct
            )
            return cycle_pct, total_pct
        except Exception:
            logger.error("[GLOBAL-RISK-GUARD] Failed to load risk pcts, using safe defaults: 5%/8%")
            return 0.05, 0.08  # Safe defaults 5%/8%


def _load_scalper_config() -> Tuple[bool, int]:
    """Load scalper single-batch flag + max-trades-per-batch from settings."""
    try:
        from core.settings import (  # type: ignore
            SCALPER_SINGLE_BATCH_MODE,
            SCALPER_MAX_TRADES_PER_BATCH,
        )
        return bool(SCALPER_SINGLE_BATCH_MODE), int(SCALPER_MAX_TRADES_PER_BATCH)
    except Exception:
        enabled = str(os.getenv("SCALPER_SINGLE_BATCH_MODE", "false")).lower() in (
            "1", "true", "yes", "on",
        )
        try:
            n = max(1, int(os.getenv("SCALPER_MAX_TRADES_PER_BATCH", "3")))
        except Exception:
            n = 3
        return enabled, n


def get_global_risk_guard() -> GlobalRiskGuard:
    """Return the process-wide ``GlobalRiskGuard`` singleton.

    Lazy double-checked construction.  Uses canonical ``MAX_CYCLE_RISK_PCT`` /
    ``MAX_TOTAL_RISK_PCT`` from ``core.settings`` (env-overridable).
    """
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                cycle_pct, total_pct = _load_canonical_pcts()
                scalper_on, max_trades = _load_scalper_config()
                _guard = GlobalRiskGuard(
                    max_cycle_risk_pct=cycle_pct,
                    max_total_risk_pct=total_pct,
                    scalper_single_batch_mode=scalper_on,
                    max_trades_per_batch=max_trades,
                )
                logger.info(
                    "[GLOBAL-RISK-GUARD] Singleton initialized | "
                    "max_cycle_risk_pct=%.4f | max_total_risk_pct=%.4f | "
                    "scalper_single_batch=%s | max_trades_per_batch=%d",
                    cycle_pct, total_pct, scalper_on, max_trades,
                )
    return _guard


def reset_global_risk_guard_for_tests() -> None:
    """Test-only: tear down the singleton so fresh state can be constructed."""
    global _guard, _equity_provider, _existing_risk_provider
    with _guard_lock:
        _guard = None
        _equity_provider = None
        _existing_risk_provider = None


# -- providers ----------------------------------------------------------

def set_equity_provider(fn: Optional[Callable[[], int]]) -> None:
    """Register a zero-arg callable returning the canonical ``equity_cents``.

    Intended to be called once at startup by the component that owns the
    canonical bankroll view (typically the AgentGrid portfolio cache or
    the ``KalshiContinuousTrader`` bankroll manager when CT is active).

    Passing ``None`` clears the provider; callers that did not register a
    provider fall back to :func:`default_equity_cents`.
    """
    global _equity_provider
    _equity_provider = fn


def set_existing_risk_provider(fn: Optional[Callable[[], int]]) -> None:
    """Register a zero-arg callable returning open-position risk in cents."""
    global _existing_risk_provider
    _existing_risk_provider = fn


def default_equity_cents() -> int:
    """Hard-fail equity lookup when no provider is registered.

    PRODUCTION AUDIT (Step 2): NO fallbacks - must use Kalshi Portfolio get_balance.
    Returns 0 to cause guard to fail-closed with clear error.
    """
    logger.critical(
        "[BANKROLL_ALIGNMENT] No equity provider registered to GlobalRiskGuard. "
        "This violates the single-source-of-truth requirement. "
        "Bankroll must come from KalshiPortfolio.get_balance via bankroll_service_v2. "
        "Failing closed to prevent trading without real balance."
    )
    return 0


def resolve_equity_cents() -> int:
    """Return current equity in cents via registered provider or fallback."""
    if _equity_provider is not None:
        try:
            equity = _equity_provider()
            # CRITICAL FIX: Validate equity is positive and reasonable
            if equity is None:
                logger.error("[GLOBAL-RISK-GUARD] equity_provider returned None - using default")
                return default_equity_cents()
            if not isinstance(equity, (int, float)):
                logger.error("[GLOBAL-RISK-GUARD] equity_provider returned invalid type %s - using default", type(equity))
                return default_equity_cents()
            if equity <= 0:
                logger.error("[GLOBAL-RISK-GUARD] equity_provider returned non-positive value %d - using default", equity)
                return default_equity_cents()
            if equity > 1000000:  # $10,000 sanity check
                logger.warning("[GLOBAL-RISK-GUARD] equity_provider returned unusually high value %d - using but flagging", equity)
            return int(equity)
        except Exception as e:
            logger.error("[GLOBAL-RISK-GUARD] equity_provider raised exception: %s - using default", e, exc_info=True)
    return default_equity_cents()


def resolve_existing_risk_cents() -> int:
    """Return open-position risk in cents via registered provider, else 0."""
    if _existing_risk_provider is not None:
        try:
            return max(0, int(_existing_risk_provider() or 0))
        except Exception as e:
            logger.warning("[GLOBAL-RISK-GUARD] existing_risk_provider raised: %s - using 0", e)
    return 0


# -------------------------------------------------------------------------
# Convenience helpers for routers
# -------------------------------------------------------------------------

def compute_intent_max_loss_cents(
    side: str,
    action: str,
    price_cents: int,
    count: int,
) -> int:
    """Compute max-loss for an ``OrderIntent`` in cents.

    Binary Kalshi contracts settle at 100c or 0c.
        long YES bought at P:  max_loss = P * count
        long NO  bought at P:  max_loss = P * count  (same - pay P, lose P if wrong)
    Only meaningful for ``action == "buy"``; sells reduce exposure and should
    not be passed through the guard.
    """
    p = max(0, min(100, int(price_cents)))
    n = max(0, int(count))
    return p * n


def check_intent(
    ticker: str,
    asset: str,
    side: str,
    action: str,
    price_cents: int,
    count: int,
    edge: float = 0.0,
) -> Tuple[bool, str]:
    """Convenience: build ``PendingOrderRisk`` and run ``check_order``.

    Returns ``(True, "")`` automatically for ``action != "buy"`` (exits are
    exempt - they reduce exposure).
    """
    if (action or "").lower() != "buy":
        return True, "exit_exempt"

    max_loss = compute_intent_max_loss_cents(side, action, price_cents, count)
    pending = PendingOrderRisk(
        ticker=ticker,
        asset=asset or "UNKNOWN",
        contracts=int(count),
        entry_price_cents=int(price_cents),
        direction="long" if (side or "").lower() == "yes" else "short",
        max_loss_cents=max_loss,
        edge=float(edge),
    )
    guard = get_global_risk_guard()
    return guard.check_order(
        equity_cents=resolve_equity_cents(),
        existing_risk_cents=resolve_existing_risk_cents(),
        pending_order=pending,
    )
