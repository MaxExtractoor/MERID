"""Tests for PolicySanityHarness — Live validation of fees, roles, and policy decisions.

Tests cover:
- Fill recording and validation
- Fee regression table validation
- Role mismatch detection
- Daily stats aggregation
- Anomaly detection
- Dashboard metrics formatting
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from merid.event_venues.kalshi.policy_sanity_harness import (
    PolicySanityHarness,
    FillRecord,
    DailyStats,
    get_policy_sanity_harness,
    REGRESSION_TABLE,
)


class TestPolicySanityHarnessBasics:
    """Test basic harness functionality."""

    def test_record_fill_basic(self):
        """Test recording a basic fill."""
        harness = PolicySanityHarness()

        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="maker",
            policy_mode="NEUTRAL_MM",
            edge_pct=5.0,
        )

        assert record.ticker == "KXBTC-250324"
        assert record.price_cents == 50
        assert record.contracts == 10
        assert record.fee_cents == 18
        assert record.expected_role == "maker"
        assert record.actual_role == "maker"
        assert record.policy_mode == "NEUTRAL_MM"
        assert record.edge_pct == 5.0
        assert record.role_mismatch is False

    def test_role_mismatch_detection(self):
        """Test detection of role mismatches."""
        harness = PolicySanityHarness()

        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="taker",  # Mismatch!
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        assert record.role_mismatch is True

    def test_fee_validation_against_regression_table(self):
        """Test fee validation against known regression values."""
        harness = PolicySanityHarness()

        # P=0.50, C=10, Taker role -> expected 18 cents
        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,  # P=0.50
            contracts=10,
            fee_cents=18,  # Correct taker fee
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        assert record.fee_valid is True
        assert record.fee_deviation_cents == 0

    def test_fee_validation_detects_deviation(self):
        """Test detection of fee deviations."""
        harness = PolicySanityHarness()

        # P=0.50, C=10, Taker role -> expected 18 cents, but we got 20
        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=20,  # Wrong! Should be 18
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        assert record.fee_valid is False
        assert record.fee_deviation_cents == 2

    def test_fee_validation_not_in_table(self):
        """Test that fills not in regression table have fee_valid=None."""
        harness = PolicySanityHarness()

        # Price/contract combo not in regression table
        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=55,  # Not in table
            contracts=7,   # Not in table
            fee_cents=15,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        assert record.fee_valid is None  # Unknown - not in table
        assert record.fee_deviation_cents is None

    def test_edge_net_of_fees_calculation(self):
        """Test calculation of net edge (edge minus fees)."""
        harness = PolicySanityHarness()

        # Edge=5%, price=50 cents, 10 contracts = $5 notional
        # Fee=18 cents = 3.6% of notional
        # Net edge = 5% - 3.6% = 1.4%
        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
            edge_pct=5.0,
        )

        assert record.edge_net_of_fees is not None
        assert record.edge_net_of_fees == 5.0 - 3.6  # ~1.4%


class TestDailyStatsAggregation:
    """Test daily statistics aggregation."""

    def test_daily_stats_aggregation(self):
        """Test that daily stats are properly aggregated."""
        harness = PolicySanityHarness()

        # Record multiple fills
        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="maker",
            policy_mode="NEUTRAL_MM",
            edge_pct=5.0,
        )

        harness.record_fill(
            ticker="KXETH-250324",
            price_cents=55,
            contracts=5,
            fee_cents=10,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
            edge_pct=3.0,
        )

        summary = harness.get_daily_summary()

        assert summary["total_fills"] == 2
        assert summary["total_contracts"] == 15
        assert summary["total_fees_cents"] == 28
        assert summary["policy_mode_distribution"]["NEUTRAL_MM"] == 1
        assert summary["policy_mode_distribution"]["AGGRESSIVE_CONVICTION"] == 1
        assert summary["role_stats"]["expected_maker"] == 1
        assert summary["role_stats"]["expected_taker"] == 1
        assert summary["role_stats"]["actual_maker"] == 1
        assert summary["role_stats"]["actual_taker"] == 1
        assert summary["role_stats"]["mismatches"] == 0

    def test_daily_stats_with_mismatches(self):
        """Test daily stats with role mismatches."""
        harness = PolicySanityHarness()

        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="taker",  # Mismatch
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        summary = harness.get_daily_summary()

        assert summary["role_stats"]["mismatches"] == 1
        assert summary["role_stats"]["mismatch_rate"] == 1.0

    def test_daily_stats_fee_validation(self):
        """Test fee validation stats in daily summary."""
        harness = PolicySanityHarness()

        # Valid fee (P=0.50, C=10, Taker=18)
        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        # Invalid fee (should be 18, got 20)
        harness.record_fill(
            ticker="KXETH-250324",
            price_cents=50,
            contracts=10,
            fee_cents=20,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        summary = harness.get_daily_summary()

        assert summary["fee_validation"]["passed"] == 1
        assert summary["fee_validation"]["failed"] == 1
        assert summary["fee_validation"]["failure_rate"] == 0.5


class TestAnomalyDetection:
    """Test anomaly detection and retrieval."""

    def test_get_recent_anomalies_role_mismatches(self):
        """Test retrieving role mismatch anomalies."""
        harness = PolicySanityHarness()

        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="taker",  # Mismatch
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        anomalies = harness.get_recent_anomalies(
            since_hours=24,
            include_role_mismatches=True,
            include_fee_deviations=False,
        )

        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "role_mismatch"
        assert anomalies[0]["expected"] == "maker"
        assert anomalies[0]["actual"] == "taker"

    def test_get_recent_anomalies_fee_deviations(self):
        """Test retrieving fee deviation anomalies."""
        harness = PolicySanityHarness()

        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=25,  # Deviation
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        anomalies = harness.get_recent_anomalies(
            since_hours=24,
            include_role_mismatches=False,
            include_fee_deviations=True,
        )

        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "fee_deviation"
        assert anomalies[0]["deviation_cents"] == 7  # 25 - 18 = 7

    def test_get_recent_anomalies_both_types(self):
        """Test retrieving both types of anomalies."""
        harness = PolicySanityHarness()

        # Role mismatch
        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        # Fee deviation
        harness.record_fill(
            ticker="KXETH-250324",
            price_cents=50,
            contracts=10,
            fee_cents=25,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
        )

        anomalies = harness.get_recent_anomalies(
            since_hours=24,
            include_role_mismatches=True,
            include_fee_deviations=True,
        )

        assert len(anomalies) == 2
        types = [a["type"] for a in anomalies]
        assert "role_mismatch" in types
        assert "fee_deviation" in types


class TestDashboardMetrics:
    """Test dashboard metrics formatting."""

    def test_get_metrics_for_dashboard(self):
        """Test dashboard metrics formatting."""
        harness = PolicySanityHarness()

        # Record some fills
        harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=18,
            expected_role="maker",
            actual_role="maker",
            policy_mode="NEUTRAL_MM",
            edge_pct=5.0,
        )

        harness.record_fill(
            ticker="KXETH-250324",
            price_cents=55,
            contracts=5,
            fee_cents=10,
            expected_role="taker",
            actual_role="taker",
            policy_mode="AGGRESSIVE_CONVICTION",
            edge_pct=3.0,
        )

        metrics = harness.get_metrics_for_dashboard()

        assert "timestamp" in metrics
        assert "today" in metrics
        assert "policy_mix_pct" in metrics
        assert "edge_vs_fees" in metrics
        assert "health" in metrics

        # Check policy mix percentages
        mix = metrics["policy_mix_pct"]
        assert "NEUTRAL_MM" in mix
        assert "AGGRESSIVE_CONVICTION" in mix
        assert mix["NEUTRAL_MM"] == 0.5
        assert mix["AGGRESSIVE_CONVICTION"] == 0.5

        # Check health metrics
        health = metrics["health"]
        assert "role_mismatch_rate" in health
        assert "fee_validation_failure_rate" in health

    def test_get_metrics_empty_harness(self):
        """Test dashboard metrics with no fills."""
        harness = PolicySanityHarness()

        metrics = harness.get_metrics_for_dashboard()

        assert metrics["today"]["total_fills"] == 0
        assert metrics["health"]["role_mismatch_rate"] == 0


class TestRegressionTable:
    """Test that regression table matches expected values."""

    def test_regression_table_values(self):
        """Verify regression table contains expected values."""
        # Key values from canonical spec
        assert (0.50, 1) in REGRESSION_TABLE
        assert (0.50, 10) in REGRESSION_TABLE
        assert (0.50, 100) in REGRESSION_TABLE

        # Check specific values
        assert REGRESSION_TABLE[(0.50, 1)] == (2, 1)  # Taker=2, Maker=1
        assert REGRESSION_TABLE[(0.50, 10)] == (18, 5)  # Taker=18, Maker=5
        assert REGRESSION_TABLE[(0.50, 100)] == (175, 44)  # Taker=175, Maker=44


class TestSingleton:
    """Test singleton pattern."""

    def test_get_policy_sanity_harness_singleton(self):
        """Test that get_policy_sanity_harness returns the same instance."""
        harness1 = get_policy_sanity_harness()
        harness2 = get_policy_sanity_harness()

        assert harness1 is harness2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_record_fill_with_none_values(self):
        """Test recording fills with None values."""
        harness = PolicySanityHarness()

        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=10,
            fee_cents=None,
            expected_role=None,
            actual_role=None,
            policy_mode=None,
            edge_pct=None,
        )

        assert record.fee_cents is None
        assert record.expected_role is None
        assert record.actual_role is None
        assert record.policy_mode is None
        assert record.edge_pct is None

    def test_zero_contracts(self):
        """Test handling of zero contracts."""
        harness = PolicySanityHarness()

        record = harness.record_fill(
            ticker="KXBTC-250324",
            price_cents=50,
            contracts=0,
            fee_cents=0,
            expected_role="maker",
            actual_role="maker",
            policy_mode="NEUTRAL_MM",
        )

        assert record.edge_net_of_fees is None  # Can't calculate with 0 contracts

    def test_max_records_limit(self):
        """Test that max records limit is enforced."""
        harness = PolicySanityHarness(max_records=5)

        # Record 10 fills
        for i in range(10):
            harness.record_fill(
                ticker=f"KXBTC-25032{i}",
                price_cents=50,
                contracts=10,
                fee_cents=18,
                expected_role="maker",
                actual_role="maker",
                policy_mode="NEUTRAL_MM",
            )

        # Should only keep last 5
        assert len(harness._records) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
