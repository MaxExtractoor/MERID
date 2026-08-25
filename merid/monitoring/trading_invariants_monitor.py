"""
Trading Invariants Monitor - 2026-08-01

Monitors critical invariants that broke in the 9 original bugs to prevent silent regressions.

Invariants Monitored:
1. Maker vs taker opportunity counts
2. Rejection reasons by category
3. Fallback spread usage frequency
4. Zero-depth / stale-book incidents
5. Fees vs expected fees at low prices
6. Trades rejected because adjusted price breached allocator bounds
7. Execution mode distribution (maker vs taker)
8. Price range violations (canonical range breaches)
9. Missing tick_id in lifecycle events (CRITICAL: 2026-08-02)
10. Candidate lifecycle imbalance per tick (CRITICAL: 2026-08-02)
11. Economics-mode disagreement between policy and router (CRITICAL: 2026-08-02)
"""

import time
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class TradingInvariantsMonitor:
    """Monitors trading invariants to detect regressions."""

    def __init__(self):
        self.start_time = datetime.now()

        # Invariant counters
        self.maker_opportunities = 0
        self.taker_opportunities = 0
        self.rejection_reasons = Counter()
        self.fallback_spread_usage = 0
        self.zero_depth_incidents = 0
        self.stale_book_incidents = 0
        self.allocator_bound_rejections = 0
        self.canonical_range_violations = 0

        # Fee tracking
        self.fee_discrepancies = []  # List of (expected_fee, actual_fee, price_cents)
        self.low_price_trades = []  # List of (price_cents, fee_cents, expected_fee_cents)

        # Execution mode tracking
        self.execution_mode_distribution = Counter()

        # Price range tracking
        self.price_range_violations = []  # List of (price_cents, side, reason)

        # CRITICAL: 2026-08-02 - Lifecycle reconciliation invariants
        self.missing_tick_id_events = 0  # Lifecycle events without tick_id
        self.lifecycle_imbalance_ticks = 0  # Ticks with candidate != terminal events
        self.economics_mode_mismatches = 0  # Policy vs router economics mode disagreements

        # Alert thresholds
        self.alert_thresholds = {
            "fallback_spread_rate": 0.05,  # Alert if >5% of trades use fallback
            "zero_depth_rate": 0.02,  # Alert if >2% of trades have zero depth
            "allocator_bound_rejection_rate": 0.01,  # Alert if >1% of trades rejected due to allocator bounds
            "fee_discrepancy_rate": 0.01,  # Alert if >1% of trades have fee discrepancies
            "missing_tick_id_rate": 0.0,  # Alert if ANY lifecycle event missing tick_id (zero tolerance)
            "lifecycle_imbalance_rate": 0.01,  # Alert if >1% of ticks have lifecycle imbalance
            "economics_mode_mismatch_rate": 0.01,  # Alert if >1% of trades have economics mode mismatch
        }

    def record_maker_opportunity(self, ticker: str, edge_pct: float, regime: str):
        """Record a maker execution opportunity."""
        self.maker_opportunities += 1
        self.execution_mode_distribution["maker"] += 1
        logger.debug(
            "[INVARIANTS-MONITOR] Maker opportunity: ticker=%s edge=%.2f%% regime=%s",
            ticker, edge_pct, regime
        )

    def record_taker_opportunity(self, ticker: str, edge_pct: float, regime: str):
        """Record a taker execution opportunity."""
        self.taker_opportunities += 1
        self.execution_mode_distribution["taker"] += 1
        logger.debug(
            "[INVARIANTS-MONITOR] Taker opportunity: ticker=%s edge=%.2f%% regime=%s",
            ticker, edge_pct, regime
        )

    def record_rejection(self, reason: str, ticker: str, details: str = ""):
        """Record a trade rejection."""
        self.rejection_reasons[reason] += 1
        logger.info(
            "[INVARIANTS-MONITOR] Rejection: reason=%s ticker=%s details=%s",
            reason, ticker, details
        )

    def record_fallback_spread_usage(self, ticker: str, original_spread: float):
        """Record fallback spread usage."""
        self.fallback_spread_usage += 1
        logger.warning(
            "[INVARIANTS-MONITOR] Fallback spread used: ticker=%s original_spread=%.2fc",
            ticker, original_spread
        )

    def record_zero_depth_incident(self, ticker: str, side: str):
        """Record a zero-depth incident."""
        self.zero_depth_incidents += 1
        logger.warning(
            "[INVARIANTS-MONITOR] Zero depth incident: ticker=%s side=%s",
            ticker, side
        )

    def record_stale_book_incident(self, ticker: str, age_seconds: float):
        """Record a stale book incident."""
        self.stale_book_incidents += 1
        logger.warning(
            "[INVARIANTS-MONITOR] Stale book incident: ticker=%s age=%.1fs",
            ticker, age_seconds
        )

    def record_allocator_bound_rejection(self, ticker: str, price_cents: int, bound: str):
        """Record a trade rejected due to allocator bounds."""
        self.allocator_bound_rejections += 1
        logger.warning(
            "[INVARIANTS-MONITOR] Allocator bound rejection: ticker=%s price=%dc bound=%s",
            ticker, price_cents, bound
        )

    def record_canonical_range_violation(self, ticker: str, price_cents: int, side: str, reason: str):
        """Record a canonical range violation."""
        self.canonical_range_violations += 1
        self.price_range_violations.append((price_cents, side, reason))
        logger.warning(
            "[INVARIANTS-MONITOR] Canonical range violation: ticker=%s price=%dc side=%s reason=%s",
            ticker, price_cents, side, reason
        )

    def record_fee_discrepancy(self, expected_fee: float, actual_fee: float, price_cents: int, ticker: str):
        """Record a fee discrepancy."""
        discrepancy_pct = abs(expected_fee - actual_fee) / expected_fee if expected_fee > 0 else 0
        self.fee_discrepancies.append((expected_fee, actual_fee, price_cents, ticker, discrepancy_pct))
        logger.warning(
            "[INVARIANTS-MONITOR] Fee discrepancy: ticker=%s price=%dc expected=%.2fc actual=%.2fc discrepancy=%.2f%%",
            ticker, price_cents, expected_fee, actual_fee, discrepancy_pct * 100
        )

    def record_low_price_trade(self, price_cents: int, fee_cents: float, expected_fee_cents: float, ticker: str):
        """Record a low-price trade (<= 15c) for fee analysis."""
        if price_cents <= 15:
            self.low_price_trades.append((price_cents, fee_cents, expected_fee_cents, ticker))
            logger.debug(
                "[INVARIANTS-MONITOR] Low price trade: ticker=%s price=%dc fee=%.2fc expected=%.2fc",
                ticker, price_cents, fee_cents, expected_fee_cents
            )

    # CRITICAL: 2026-08-02 - Lifecycle reconciliation invariant methods

    def record_missing_tick_id(self, candidate_id: str, event_type: str):
        """Record a lifecycle event missing tick_id (CRITICAL: zero tolerance)."""
        self.missing_tick_id_events += 1
        logger.error(
            "[INVARIANTS-MONITOR] CRITICAL: Lifecycle event missing tick_id: candidate_id=%s event_type=%s",
            candidate_id, event_type
        )

    def record_lifecycle_imbalance(self, tick_id: int, candidates: int, terminal_events: int, breakdown: Dict[str, int]):
        """Record a tick with lifecycle imbalance (candidates != terminal events)."""
        self.lifecycle_imbalance_ticks += 1
        logger.error(
            "[INVARIANTS-MONITOR] CRITICAL: Lifecycle imbalance: tick=%d candidates=%d terminal=%d breakdown=%s",
            tick_id, candidates, terminal_events, breakdown
        )

    def record_economics_mode_mismatch(self, candidate_id: str, policy_role: str, router_mode: str, ticker: str):
        """Record economics mode disagreement between policy and router."""
        self.economics_mode_mismatches += 1
        logger.error(
            "[INVARIANTS-MONITOR] CRITICAL: Economics mode mismatch: candidate_id=%s policy=%s router=%s ticker=%s",
            candidate_id, policy_role, router_mode, ticker
        )

    def get_summary(self) -> Dict:
        """Get a summary of invariant violations."""
        total_opportunities = self.maker_opportunities + self.taker_opportunities
        total_trades = total_opportunities  # Approximation

        summary = {
            "start_time": self.start_time.isoformat(),
            "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
            "maker_opportunities": self.maker_opportunities,
            "taker_opportunities": self.taker_opportunities,
            "total_opportunities": total_opportunities,
            "execution_mode_distribution": dict(self.execution_mode_distribution),
            "rejection_reasons": dict(self.rejection_reasons),
            "fallback_spread_usage": self.fallback_spread_usage,
            "zero_depth_incidents": self.zero_depth_incidents,
            "stale_book_incidents": self.stale_book_incidents,
            "allocator_bound_rejections": self.allocator_bound_rejections,
            "canonical_range_violations": self.canonical_range_violations,
            "fee_discrepancies_count": len(self.fee_discrepancies),
            "low_price_trades_count": len(self.low_price_trades),
            # CRITICAL: 2026-08-02 - Lifecycle reconciliation metrics
            "missing_tick_id_events": self.missing_tick_id_events,
            "lifecycle_imbalance_ticks": self.lifecycle_imbalance_ticks,
            "economics_mode_mismatches": self.economics_mode_mismatches,
        }

        # Calculate rates
        if total_trades > 0:
            summary["fallback_spread_rate"] = self.fallback_spread_usage / total_trades
            summary["zero_depth_rate"] = self.zero_depth_incidents / total_trades
            summary["allocator_bound_rejection_rate"] = self.allocator_bound_rejections / total_trades
            summary["fee_discrepancy_rate"] = len(self.fee_discrepancies) / total_trades
            summary["economics_mode_mismatch_rate"] = self.economics_mode_mismatches / total_trades
        else:
            summary["fallback_spread_rate"] = 0.0
            summary["zero_depth_rate"] = 0.0
            summary["allocator_bound_rejection_rate"] = 0.0
            summary["fee_discrepancy_rate"] = 0.0
            summary["economics_mode_mismatch_rate"] = 0.0

        # Lifecycle imbalance rate is per tick, not per trade
        # We'll track this separately with a tick counter if needed
        summary["lifecycle_imbalance_rate"] = 0.0  # Placeholder for tick-based rate

        return summary

    def check_alerts(self) -> List[str]:
        """Check if any invariant thresholds are breached and return alert messages."""
        summary = self.get_summary()
        alerts = []

        if summary["fallback_spread_rate"] > self.alert_thresholds["fallback_spread_rate"]:
            alerts.append(
                f"ALERT: Fallback spread rate {summary['fallback_spread_rate']:.2%} exceeds threshold {self.alert_thresholds['fallback_spread_rate']:.2%}"
            )

        if summary["zero_depth_rate"] > self.alert_thresholds["zero_depth_rate"]:
            alerts.append(
                f"ALERT: Zero depth rate {summary['zero_depth_rate']:.2%} exceeds threshold {self.alert_thresholds['zero_depth_rate']:.2%}"
            )

        if summary["allocator_bound_rejection_rate"] > self.alert_thresholds["allocator_bound_rejection_rate"]:
            alerts.append(
                f"ALERT: Allocator bound rejection rate {summary['allocator_bound_rejection_rate']:.2%} exceeds threshold {self.alert_thresholds['allocator_bound_rejection_rate']:.2%}"
            )

        if summary["fee_discrepancy_rate"] > self.alert_thresholds["fee_discrepancy_rate"]:
            alerts.append(
                f"ALERT: Fee discrepancy rate {summary['fee_discrepancy_rate']:.2%} exceeds threshold {self.alert_thresholds['fee_discrepancy_rate']:.2%}"
            )

        # Check for canonical range violations (any is bad)
        if summary["canonical_range_violations"] > 0:
            alerts.append(
                f"ALERT: {summary['canonical_range_violations']} canonical range violations detected"
            )

        # CRITICAL: 2026-08-02 - Lifecycle reconciliation alerts (zero tolerance for missing tick_id)
        if summary["missing_tick_id_events"] > 0:
            alerts.append(
                f"CRITICAL ALERT: {summary['missing_tick_id_events']} lifecycle events missing tick_id (zero tolerance)"
            )

        if summary["lifecycle_imbalance_ticks"] > 0:
            alerts.append(
                f"CRITICAL ALERT: {summary['lifecycle_imbalance_ticks']} ticks with lifecycle imbalance (candidates != terminal events)"
            )

        if summary["economics_mode_mismatch_rate"] > self.alert_thresholds["economics_mode_mismatch_rate"]:
            alerts.append(
                f"CRITICAL ALERT: Economics mode mismatch rate {summary['economics_mode_mismatch_rate']:.2%} exceeds threshold {self.alert_thresholds['economics_mode_mismatch_rate']:.2%}"
            )

        return alerts

    def log_summary(self):
        """Log the invariant summary."""
        summary = self.get_summary()
        alerts = self.check_alerts()

        logger.info(
            "[INVARIANTS-MONITOR] Summary: "
            "maker=%d taker=%d total=%d "
            "fallback_spread=%d (%.2f%%) "
            "zero_depth=%d (%.2f%%) "
            "allocator_reject=%d (%.2f%%) "
            "canonical_violations=%d "
            "fee_discrepancies=%d (%.2f%%) "
            "missing_tick_id=%d "
            "lifecycle_imbalance=%d "
            "economics_mismatch=%d (%.2f%%)",
            summary["maker_opportunities"],
            summary["taker_opportunities"],
            summary["total_opportunities"],
            summary["fallback_spread_usage"],
            summary["fallback_spread_rate"] * 100,
            summary["zero_depth_incidents"],
            summary["zero_depth_rate"] * 100,
            summary["allocator_bound_rejections"],
            summary["allocator_bound_rejection_rate"] * 100,
            summary["canonical_range_violations"],
            summary["fee_discrepancies_count"],
            summary["fee_discrepancy_rate"] * 100,
            summary["missing_tick_id_events"],
            summary["lifecycle_imbalance_ticks"],
            summary["economics_mode_mismatches"],
            summary["economics_mode_mismatch_rate"] * 100,
        )

        if alerts:
            for alert in alerts:
                logger.error("[INVARIANTS-MONITOR] %s", alert)


# Global singleton instance
_invariants_monitor: Optional[TradingInvariantsMonitor] = None


def get_invariants_monitor() -> TradingInvariantsMonitor:
    """Get the global invariants monitor instance."""
    global _invariants_monitor
    if _invariants_monitor is None:
        _invariants_monitor = TradingInvariantsMonitor()
    return _invariants_monitor


def reset_invariants_monitor():
    """Reset the global invariants monitor (for testing)."""
    global _invariants_monitor
    _invariants_monitor = None
