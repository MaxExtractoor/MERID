"""Live Sanity Harness — Log and validate realized fees, roles, and policy decisions.

This module provides real-time validation of parabolic fees and policy decisions
against the regression table. It logs:
- actual_role vs expected_role (role misclassification detection)
- fee_cents vs regression table (fee calculation validation)
- policy_mode mix (usage distribution across modes)
- edge vs fees (edge capture efficiency)

Usage::

    from merid.event_venues.kalshi.policy_sanity_harness import PolicySanityHarness

    harness = PolicySanityHarness()

    # In order router after fill:
    harness.record_fill(
        ticker="KXBTC-250324",
        price_cents=55,
        contracts=10,
        fee_cents=result.fee_cents,
        expected_role=result.expected_role,
        actual_role=result.actual_role,
        policy_mode=result.policy_mode,
        edge_pct=intent.edge_pct,
    )

    # Get daily summary:
    summary = harness.get_daily_summary()
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.policy_sanity_harness")


# Regression table for fee validation (from canonical spec)
REGRESSION_TABLE: Dict[Tuple[float, int], Tuple[int, int]] = {
    # (price_dollars, contracts) -> (expected_taker_fee, expected_maker_fee)
    (0.01, 1): (1, 1),
    (0.05, 10): (4, 1),
    (0.50, 1): (2, 1),
    (0.50, 10): (18, 5),
    (0.50, 100): (175, 44),
    (0.95, 10): (4, 1),
    (0.99, 1): (1, 1),
}


@dataclass
class FillRecord:
    """Record of a single fill for validation."""

    timestamp: str
    ticker: str
    price_cents: int
    contracts: int
    fee_cents: Optional[int]
    expected_role: Optional[str]
    actual_role: Optional[str]
    policy_mode: Optional[str]
    edge_pct: Optional[float]

    # Validation results
    fee_valid: Optional[bool] = None
    fee_deviation_cents: Optional[int] = None
    role_mismatch: Optional[bool] = None
    edge_net_of_fees: Optional[float] = None


@dataclass
class DailyStats:
    """Aggregated daily statistics."""

    date: str
    total_fills: int = 0
    total_contracts: int = 0
    total_fees_cents: int = 0

    # Policy mode distribution
    policy_mode_counts: Dict[str, int] = field(default_factory=dict)

    # Role tracking
    expected_maker_count: int = 0
    expected_taker_count: int = 0
    actual_maker_count: int = 0
    actual_taker_count: int = 0
    role_mismatches: int = 0

    # Fee validation
    fee_validation_passed: int = 0
    fee_validation_failed: int = 0
    total_fee_deviation_cents: int = 0

    # Edge metrics
    total_edge_pct: float = 0.0
    avg_edge_pct: float = 0.0
    total_net_edge_pct: float = 0.0  # Edge minus fees as pct


class PolicySanityHarness:
    """Live sanity harness for policy and fee validation.

    Records fills, validates against regression table, and aggregates metrics.
    """

    def __init__(self, max_records: int = 10000):
        self._max_records = max_records
        self._records: List[FillRecord] = []
        self._lock = threading.Lock()
        self._daily_stats: Dict[str, DailyStats] = {}

    def record_fill(
        self,
        ticker: str,
        price_cents: int,
        contracts: int,
        fee_cents: Optional[int],
        expected_role: Optional[str],
        actual_role: Optional[str],
        policy_mode: Optional[str],
        edge_pct: Optional[float] = None,
    ) -> FillRecord:
        """Record a fill and validate against regression table.

        Args:
            ticker: Market ticker
            price_cents: Fill price in cents
            contracts: Number of contracts
            fee_cents: Actual fee charged
            expected_role: Expected liquidity role
            actual_role: Actual liquidity role
            policy_mode: Policy mode used
            edge_pct: Estimated edge (optional)

        Returns:
            FillRecord with validation results
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        date = timestamp[:10]  # YYYY-MM-DD

        # Validate fee against regression table
        fee_valid, fee_deviation = self._validate_fee(
            price_cents, contracts, actual_role, fee_cents
        )

        # Check for role mismatch
        role_mismatch = (
            expected_role is not None
            and actual_role is not None
            and expected_role != actual_role
        )

        # Calculate net edge (edge minus fees as percentage)
        edge_net_of_fees = None
        if edge_pct is not None and fee_cents is not None and contracts > 0:
            notional_cents = price_cents * contracts
            fee_pct = (fee_cents / notional_cents) * 100 if notional_cents > 0 else 0
            # Stabilize float representation for exact-equality tests (e.g., 1.4).
            edge_net_of_fees = round(edge_pct - fee_pct, 10)

        record = FillRecord(
            timestamp=timestamp,
            ticker=ticker,
            price_cents=price_cents,
            contracts=contracts,
            fee_cents=fee_cents,
            expected_role=expected_role,
            actual_role=actual_role,
            policy_mode=policy_mode,
            edge_pct=edge_pct,
            fee_valid=fee_valid,
            fee_deviation_cents=fee_deviation,
            role_mismatch=role_mismatch,
            edge_net_of_fees=edge_net_of_fees,
        )

        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]

            # Update daily stats
            stats = self._daily_stats.get(date)
            if stats is None:
                stats = DailyStats(date=date)
                self._daily_stats[date] = stats

            stats.total_fills += 1
            stats.total_contracts += contracts
            if fee_cents:
                stats.total_fees_cents += fee_cents

            # Policy mode counts
            mode = policy_mode or "unknown"
            stats.policy_mode_counts[mode] = stats.policy_mode_counts.get(mode, 0) + 1

            # Role counts
            if expected_role == "maker":
                stats.expected_maker_count += 1
            elif expected_role == "taker":
                stats.expected_taker_count += 1

            if actual_role == "maker":
                stats.actual_maker_count += 1
            elif actual_role == "taker":
                stats.actual_taker_count += 1

            if role_mismatch:
                stats.role_mismatches += 1

            # Fee validation
            if fee_valid is not None:
                if fee_valid:
                    stats.fee_validation_passed += 1
                else:
                    stats.fee_validation_failed += 1
                    if fee_deviation:
                        stats.total_fee_deviation_cents += abs(fee_deviation)

            # Edge metrics
            if edge_pct:
                stats.total_edge_pct += edge_pct
                stats.avg_edge_pct = stats.total_edge_pct / stats.total_fills
            if edge_net_of_fees:
                stats.total_net_edge_pct += edge_net_of_fees

        # Log anomalies
        if role_mismatch:
            logger.warning(
                "[POLICY_SANITY] Role mismatch: %s expected=%s actual=%s",
                ticker, expected_role, actual_role
            )
        if fee_valid is False:
            logger.warning(
                "[POLICY_SANITY] Fee deviation: %s fee=%d expected~=%d deviation=%d",
                ticker, fee_cents or 0,
                (fee_cents or 0) - (fee_deviation or 0),
                fee_deviation or 0
            )

        return record

    def _validate_fee(
        self,
        price_cents: int,
        contracts: int,
        actual_role: Optional[str],
        fee_cents: Optional[int],
    ) -> Tuple[Optional[bool], Optional[int]]:
        """Validate fee against regression table.

        Returns:
            (is_valid, deviation_cents) - None if no matching entry
        """
        if fee_cents is None:
            return None, None

        price_dollars = price_cents / 100.0

        # Look up in regression table (exact match only for now)
        key = (round(price_dollars, 2), contracts)
        if key not in REGRESSION_TABLE:
            return None, None

        expected_taker, expected_maker = REGRESSION_TABLE[key]
        expected_fee = expected_maker if actual_role == "maker" else expected_taker

        deviation = fee_cents - expected_fee
        is_valid = abs(deviation) <= 1  # Allow 1 cent tolerance for ceiling

        return is_valid, deviation

    def get_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get summary for a specific date (today if not specified)."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            stats = self._daily_stats.get(date)
            if stats is None:
                # Always return a stable schema for dashboards/tests.
                return {
                    "date": date,
                    "total_fills": 0,
                    "total_contracts": 0,
                    "total_fees_cents": 0,
                    "total_fees_usd": 0.0,
                    "policy_mode_distribution": {},
                    "role_stats": {
                        "expected_maker": 0,
                        "expected_taker": 0,
                        "actual_maker": 0,
                        "actual_taker": 0,
                        "mismatches": 0,
                        "mismatch_rate": 0,
                    },
                    "fee_validation": {
                        "passed": 0,
                        "failed": 0,
                        "failure_rate": 0,
                        "total_deviation_cents": 0,
                    },
                    "edge_metrics": {
                        "avg_edge_pct": 0,
                        "total_net_edge_pct": 0,
                    },
                }

            return {
                "date": stats.date,
                "total_fills": stats.total_fills,
                "total_contracts": stats.total_contracts,
                "total_fees_cents": stats.total_fees_cents,
                "total_fees_usd": round(stats.total_fees_cents / 100, 2),
                "policy_mode_distribution": stats.policy_mode_counts,
                "role_stats": {
                    "expected_maker": stats.expected_maker_count,
                    "expected_taker": stats.expected_taker_count,
                    "actual_maker": stats.actual_maker_count,
                    "actual_taker": stats.actual_taker_count,
                    "mismatches": stats.role_mismatches,
                    "mismatch_rate": (
                        round(stats.role_mismatches / stats.total_fills, 4)
                        if stats.total_fills > 0 else 0
                    ),
                },
                "fee_validation": {
                    "passed": stats.fee_validation_passed,
                    "failed": stats.fee_validation_failed,
                    "failure_rate": (
                        round(stats.fee_validation_failed / stats.total_fills, 4)
                        if stats.total_fills > 0 else 0
                    ),
                    "total_deviation_cents": stats.total_fee_deviation_cents,
                },
                "edge_metrics": {
                    "avg_edge_pct": round(stats.avg_edge_pct, 4),
                    "total_net_edge_pct": round(stats.total_net_edge_pct, 4),
                },
            }

    def get_recent_anomalies(
        self,
        since_hours: float = 24,
        include_role_mismatches: bool = True,
        include_fee_deviations: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get recent anomalies (role mismatches, fee deviations)."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        cutoff_str = cutoff.isoformat()

        anomalies = []
        with self._lock:
            for record in self._records:
                if record.timestamp < cutoff_str:
                    continue

                if include_role_mismatches and record.role_mismatch:
                    anomalies.append({
                        "type": "role_mismatch",
                        "timestamp": record.timestamp,
                        "ticker": record.ticker,
                        "expected": record.expected_role,
                        "actual": record.actual_role,
                        "policy_mode": record.policy_mode,
                    })

                if include_fee_deviations and record.fee_valid is False:
                    anomalies.append({
                        "type": "fee_deviation",
                        "timestamp": record.timestamp,
                        "ticker": record.ticker,
                        "price_cents": record.price_cents,
                        "contracts": record.contracts,
                        "fee_cents": record.fee_cents,
                        "deviation_cents": record.fee_deviation_cents,
                        "role": record.actual_role,
                    })

        return anomalies

    def get_metrics_for_dashboard(self) -> Dict[str, Any]:
        """Get metrics formatted for dashboard integration."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary = self.get_daily_summary(today)

        # Calculate policy mix percentages
        mode_counts = summary.get("policy_mode_distribution", {})
        total = sum(mode_counts.values()) if mode_counts else 0
        mode_pct = {
            mode: round(count / total, 4) if total > 0 else 0
            for mode, count in mode_counts.items()
        }

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "today": summary,
            "policy_mix_pct": mode_pct,
            "edge_vs_fees": {
                "avg_edge_pct": summary.get("edge_metrics", {}).get("avg_edge_pct", 0),
                "total_net_edge_pct": summary.get("edge_metrics", {}).get("total_net_edge_pct", 0),
            },
            "health": {
                "role_mismatch_rate": summary.get("role_stats", {}).get("mismatch_rate", 0),
                "fee_validation_failure_rate": summary.get("fee_validation", {}).get("failure_rate", 0),
            },
        }

    def export_to_json(self, filepath: str, date: Optional[str] = None) -> None:
        """Export daily records to JSON file."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            records = [
                {
                    "timestamp": r.timestamp,
                    "ticker": r.ticker,
                    "price_cents": r.price_cents,
                    "contracts": r.contracts,
                    "fee_cents": r.fee_cents,
                    "expected_role": r.expected_role,
                    "actual_role": r.actual_role,
                    "policy_mode": r.policy_mode,
                    "edge_pct": r.edge_pct,
                    "fee_valid": r.fee_valid,
                    "fee_deviation_cents": r.fee_deviation_cents,
                    "role_mismatch": r.role_mismatch,
                    "edge_net_of_fees": r.edge_net_of_fees,
                }
                for r in self._records
                if r.timestamp.startswith(date)
            ]

        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)

        logger.info("[POLICY_SANITY] Exported %d records to %s", len(records), filepath)


# Singleton instance
_harness: Optional[PolicySanityHarness] = None
_harness_lock = threading.Lock()


def get_policy_sanity_harness() -> PolicySanityHarness:
    """Get or create the singleton PolicySanityHarness."""
    global _harness
    if _harness is None:
        with _harness_lock:
            if _harness is None:
                _harness = PolicySanityHarness()
    return _harness
