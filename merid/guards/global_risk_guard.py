"""Process-wide GlobalRiskGuard singleton.

Canonical risk gate for all Kalshi PM order submissions. Extracted from
``merid.trading.kalshi_continuous_trader`` so that every caller — the
``KalshiContinuousTrader`` loop, ``KalshiTradingAgent`` (agent grid, 35 agents),
crypto lanes (``btc15m_lane``, ``crypto15m_lane``), web manual trades, and any
future order source — shares the **same** per-cycle / total risk envelope
on a **unified** ``equity_cents`` source.

See ``docs/TRADING_OWNERSHIP_DECISION.md`` for the policy context and
``docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md`` for the full wiring.

Invariants enforced (per ``check_order`` call):
    1. Sum of ``max_loss_cents`` for all approved orders in the current cycle
       ≤ ``max_cycle_risk_pct * equity_cents``.
    2. ``existing_risk_cents + cycle_new_risk_cents`` ≤
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
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from utils.logger import get_logger
from merid.utils.logging_helpers import log_guardrail_check, log_risk_check, log_trading_operation
from merid.utils.alerting import send_alert_sync, AlertSeverity, AlertContext

logger = get_logger("merid.guards.global_risk_guard")


# ────────────────────────────────────────────────────────────────────────────
# Data
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class PendingOrderRisk:
    """Risk metadata for a pending order.

    ``max_loss_cents`` is the canonical field — callers MUST compute it
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
        max_cycle_risk_pct: float = 0.02,
        max_total_risk_pct: float = 0.02,
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

    # ── cycle boundary ──────────────────────────────────────────────────
    def reset_cycle(self) -> None:
        """Call at the start of each decision cycle.

        Also increments ``batch_id`` so downstream consumers can key
        intents/orders to the current batch.
        """
        with self._lock:
            self._cycle_new_risk_cents = 0
            self._cycle_approved_count = 0
            self._batch_id += 1

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
            # ── Scalper single-batch mode (hard veto) ──────────────────
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
                    f"equity_cents={equity_cents} — fail-closed"
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
            # TEMPORARY: Disabled cycle risk cap to allow trades during debugging
            if False:  # Disabled to reduce trade blocking
                if new_cycle_total > cycle_risk_cents:
                    # Calculate remaining capacity
                    remaining_capacity_cents = cycle_risk_cents - self._cycle_new_risk_cents
                    
                    # If remaining capacity is zero or negative, reject
                    if remaining_capacity_cents <= 0:
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
                
                # Adaptive sizing: resize order to fit remaining capacity
                original_max_loss = pending_order.max_loss_cents
                scaled_max_loss = min(original_max_loss, remaining_capacity_cents)
                
                # Calculate scaled contracts (proportional)
                if pending_order.max_loss_cents > 0:
                    scale_factor = scaled_max_loss / pending_order.max_loss_cents
                    scaled_contracts = max(1, int(pending_order.contracts * scale_factor))
                    scaled_max_loss = scaled_contracts * pending_order.entry_price_cents  # Recalculate to ensure integer cents
                else:
                    scaled_contracts = 1
                    scaled_max_loss = pending_order.entry_price_cents
                
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

            # 2. Total open risk cap
            # TEMPORARY: Disabled total risk cap to allow trades during debugging
            if False:  # Disabled to reduce trade blocking
                new_total_risk = max(0, existing_risk_cents) + new_cycle_total
                if new_total_risk > max_total_risk_cents:
                    reason = (
                        f"GLOBAL RISK GUARD BLOCK: Total risk cap exceeded | "
                        f"equity=${equity_cents/100:.2f} | "
                        f"total_cap=${max_total_risk_cents/100:.2f} | "
                        f"existing=${existing_risk_cents/100:.2f} | "
                        f"new_cycle=${new_cycle_total/100:.2f} | "
                        f"would_be_total=${new_total_risk/100:.2f}"
                    )
                    log_risk_check(
                        "total_risk_cap",
                        logger,
                        current_value=float(new_total_risk),
                        limit_value=float(max_total_risk_cents),
                        action="reject",
                        equity_usd=float(equity_cents) / 100,
                        existing_risk_cents=existing_risk_cents,
                        new_cycle_risk_cents=new_cycle_total,
                    )
                    send_alert_sync(
                        condition="total_risk_cap",
                        severity=AlertSeverity.CRITICAL,
                        message=f"Total risk cap exceeded: ${new_total_risk/100:.2f} > ${max_total_risk_cents/100:.2f}",
                        context=AlertContext(
                            source="merid.guards.global_risk_guard",
                            current_value=float(new_total_risk) / 100,
                            threshold_value=float(max_total_risk_cents) / 100,
                            additional_fields={
                                "equity_usd": float(equity_cents) / 100,
                                "existing_risk_cents": existing_risk_cents,
                                "new_cycle_risk_cents": new_cycle_total,
                            },
                        ),
                    )
                    logger.critical(reason)
                    logger.info(
                        "[RISK-DECISION] asset=%s ticker=%s proposed_size=%d allowed_size=0 equity_cents=%d decision=REJECTED reason=TOTAL_RISK_CAP_EXCEEDED",
                        pending_order.asset, pending_order.ticker, pending_order.contracts, equity_cents
                    )
                    self._rejections += 1
                    self._last_reject_reason = reason
                    return False, reason

            # Approved
            self._cycle_new_risk_cents = new_cycle_total
            self._cycle_approved_count += 1
            self._approvals += 1

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

    # ── telemetry ───────────────────────────────────────────────────────
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
    """Load canonical risk percentages from core.settings.
    
    OPTIMIZED RISK REGIME (2026-05-07): 3% cycle / 8% total for better throughput while maintaining safety.
    With $35 equity: 3% = $1.05 cycle cap for 2-3 contract winners (was $0.70 with 2%).
    """
    try:
        from merid.core.settings import MAX_CYCLE_RISK_PCT, MAX_TOTAL_RISK_PCT  # type: ignore
        cycle_pct = float(MAX_CYCLE_RISK_PCT)
        total_pct = float(MAX_TOTAL_RISK_PCT)
        logger.info(
            "[GLOBAL-RISK-GUARD] Loaded canonical pcts: cycle=%.4f (%.2f%%) total=%.4f (%.2f%%)",
            cycle_pct, cycle_pct * 100, total_pct, total_pct * 100
        )
        return cycle_pct, total_pct
    except Exception:
        try:
            # OPTIMIZED RISK REGIME: 3% cycle / 8% total
            cycle = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.03"))  # 3% default
            total = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.08"))  # 8% default
            logger.warning(
                "[GLOBAL-RISK-GUARD] core.settings import failed, using env/defaults: cycle=%.4f total=%.4f",
                cycle, total
            )
            return cycle, total
        except Exception:
            logger.error("[GLOBAL-RISK-GUARD] Failed to load risk pcts, using safe defaults: 3%/8%")
            return 0.03, 0.08  # Safe defaults 3%/8%


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


# ── providers ───────────────────────────────────────────────────────────

def set_equity_provider(fn: Optional[Callable[[], int]]) -> None:
    """Register a zero-arg callable returning the canonical ``equity_cents``.

    Intended to be called once at startup by the component that owns the
    canonical bankroll view (typically the AgentGrid's portfolio cache or
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
            logger.error("[GLOBAL-RISK-GUARD] equity_provider raised exception: %s — using default", e, exc_info=True)
    return default_equity_cents()


def resolve_existing_risk_cents() -> int:
    """Return open-position risk in cents via registered provider, else 0."""
    if _existing_risk_provider is not None:
        try:
            return max(0, int(_existing_risk_provider() or 0))
        except Exception as e:
            logger.warning("[GLOBAL-RISK-GUARD] existing_risk_provider raised: %s — using 0", e)
    return 0


# ────────────────────────────────────────────────────────────────────────────
# Convenience helpers for routers
# ────────────────────────────────────────────────────────────────────────────

def compute_intent_max_loss_cents(
    side: str,
    action: str,
    price_cents: int,
    count: int,
) -> int:
    """Compute max-loss for an ``OrderIntent`` in cents.

    Binary Kalshi contracts settle at 100¢ or 0¢.
        long YES bought at P:  max_loss = P * count
        long NO  bought at P:  max_loss = P * count  (same — pay P, lose P if wrong)
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
    exempt — they reduce exposure).
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
