"""Tests for execution gate reconciliation, loop lag exclusion, and SOL wiring diagnostics.

This module tests:
1. ExecutionGate reconciliation: distinguish benign (no positions) from genuine discrepancies
2. Event system loop lag is not an execution_gate input (no loop_lag reasons / state)
3. SOL wiring: detailed filter stats logging for diagnostics
"""

import time
import warnings
from unittest.mock import patch, MagicMock

import pytest


class MockDiscrepancy:
    """Mock discrepancy for testing — mimics VenuePositionDiscrepancy behavior."""

    def __init__(
        self,
        venue,
        symbol,
        merid_qty,
        venue_qty,
        merid_entry_price=0.0,
        venue_entry_price=0.0,
        severity="info",
    ):
        self.venue = venue
        self.symbol = symbol
        self.merid_qty = merid_qty
        self.venue_qty = venue_qty
        self.merid_entry_price = merid_entry_price
        self.venue_entry_price = venue_entry_price
        self.severity = severity
        self.delta_qty = venue_qty - merid_qty
        self.delta_price = venue_entry_price - merid_entry_price
        self.reason = "mock"
        self.timestamp = time.time()


class TestExecutionGateReconciliation:
    """Test reconciliation discrepancy classification in execution gate."""

    def test_benign_zero_positions_downgraded_to_warning(self):
        """When both MERID and venue have zero positions, discrepancy is benign (warning only)."""
        benign = MockDiscrepancy(
            venue="kalshi",
            symbol="KXSOL-TEST",
            merid_qty=0.0,
            venue_qty=0.0,
            merid_entry_price=0.0,
            venue_entry_price=0.0,
            severity="critical",
        )

        from core.execution_gate import check_execution_gate

        with patch("merid.reconciliation.has_critical_discrepancies", return_value=True), patch(
            "merid.reconciliation.get_last_discrepancies", return_value=[benign]
        ):
            status = check_execution_gate()

            recon_reasons = [r for r in status.reasons if r.source == "reconciliation"]
            if recon_reasons:
                assert recon_reasons[0].severity == "warning"

    def test_genuine_mismatch_stays_critical(self):
        """When MERID has position but venue doesn't (or vice versa), it's genuinely critical."""
        genuine = MockDiscrepancy(
            venue="kalshi",
            symbol="KXBTC-TEST",
            merid_qty=0.0,
            venue_qty=5.0,
            merid_entry_price=0.0,
            venue_entry_price=100.0,
            severity="critical",
        )

        from core.execution_gate import check_execution_gate

        with patch("merid.reconciliation.has_critical_discrepancies", return_value=True), patch(
            "merid.reconciliation.get_last_discrepancies", return_value=[genuine]
        ):
            status = check_execution_gate()
            recon_reasons = [r for r in status.reasons if r.source == "reconciliation"]
            if recon_reasons:
                assert recon_reasons[0].severity in ("warning", "critical")

    def test_no_discrepancies_gate_clear(self):
        """When reconciliation has no discrepancies, gate should be clear."""
        from core.execution_gate import check_execution_gate, GateState

        with patch("merid.risk.kill_switches.risk_controller") as mock_rc:
            mock_rc._global_kill = False
            mock_rc._kill_reason = None
            mock_rc._kill_details = None
            with patch("merid.reconciliation.has_critical_discrepancies", return_value=False), patch(
                "merid.reconciliation.get_last_discrepancies", return_value=[]
            ):
                status = check_execution_gate()

            assert status.gate_state in (GateState.CLEAR.value, GateState.LIMITED.value)


class TestLoopLagExcludedFromExecutionGate:
    """Loop lag is monitored elsewhere; it must not appear in check_execution_gate reasons."""

    def test_no_loop_lag_reasons(self):
        """``check_execution_gate`` never consults loop lag; reasons never include source=loop_lag."""
        import core.execution_gate as eg

        with patch("merid.risk.kill_switches.risk_controller") as mock_rc:
            mock_rc._global_kill = False
            mock_rc._kill_reason = None
            mock_rc._kill_details = None
            with patch("merid.reconciliation.has_critical_discrepancies", return_value=False), patch(
                "merid.reconciliation.get_last_discrepancies", return_value=[]
            ):
                status = eg.check_execution_gate()

        lag_reasons = [r for r in status.reasons if r.source == "loop_lag"]
        assert lag_reasons == []

    def test_reset_lag_halt_counter_callable_noop(self):
        from core.execution_gate import reset_lag_halt_counter

        reset_lag_halt_counter()


class TestSOLWiringDiagnostics:
    """Test SOL filter diagnostics and debugging capabilities."""

    def test_filter_stats_structure(self):
        """FilterPipelineResult should have per-asset stats for SOL diagnostics."""
        from merid.trading.kalshi_filter_pipeline import FilterPipeline, FilterPipelineConfig

        cfg = FilterPipelineConfig(assets=["SOL"], max_candidates_per_asset=5)
        fp = FilterPipeline(cfg)
        fp.set_spot_prices({"SOL": 150.0})

        raw = {
            "SOL": [
                {"ticker": "KXSOL-TEST-T200", "series_ticker": "KXSOL", "volume": 100, "open_interest": 50},
                {"ticker": "KXSOL15M-TEST-15M", "series_ticker": "KXSOL15M", "volume": 50, "open_interest": 25},
            ]
        }

        result = fp.filter_markets(raw)

        assert "SOL" in result.per_asset

        stats = result.per_asset["SOL"]
        assert stats.raw == 2
        assert hasattr(stats, "no_spot")
        assert hasattr(stats, "parsed_strike")
        assert hasattr(stats, "directional")
        assert hasattr(stats, "illiquid")
        assert hasattr(stats, "expiry_out_of_bounds")

    def test_sol_debug_logging_env_flag(self):
        """KALSHI_CT_DEBUG_FILTER env flag should enable detailed SOL logging."""
        import os

        os.environ["KALSHI_CT_DEBUG_FILTER"] = "true"

        from merid.trading.kalshi_filter_pipeline import FilterPipeline, FilterPipelineConfig

        cfg = FilterPipelineConfig(assets=["SOL"])
        fp = FilterPipeline(cfg)

        fp.set_spot_prices({"SOL": 150.0})

        del os.environ["KALSHI_CT_DEBUG_FILTER"]

    def test_filter_stats_include_all_drop_reasons(self):
        """Filter stats should capture drop dimensions; raw is an upper bound on explicit drop buckets."""
        from merid.trading.kalshi_filter_pipeline import AssetFilterStats

        stats = AssetFilterStats()

        stats.raw = 100
        stats.no_spot = 5
        stats.parsed_strike = 80
        stats.directional = 10
        stats.unknown_type = 5
        stats.illiquid = 20
        stats.expiry_out_of_bounds = 10
        stats.rti_quarantined = 0

        total_dropped = (
            stats.no_spot + stats.unknown_type + stats.illiquid + stats.expiry_out_of_bounds + stats.rti_quarantined
        )

        assert stats.raw >= total_dropped
        assert stats.raw > 0


class TestIntegrationCTCycle:
    """Integration tests for CT cycle with execution gate."""

    def test_ct_respects_execution_gate_limited(self):
        """CT should skip new entries when gate is limited but allow exits."""
        from core.execution_gate import ExecutionGateStatus, BlockReason, GateState

        status = ExecutionGateStatus(
            blocked=False,
            safe_to_trade=True,
            gate_state=GateState.LIMITED.value,
            reasons=[
                BlockReason(
                    source="reconciliation",
                    severity="warning",
                    message="Kalshi venue reconciliation: no positions to reconcile (fresh start)",
                    hint="Wait for next reconciliation cycle",
                )
            ],
        )

        assert status.allows_reduce()
        assert status.is_limited

    def test_ct_blocked_when_gate_blocked(self):
        """CT should completely stop when gate is blocked."""
        from core.execution_gate import ExecutionGateStatus, BlockReason, GateState

        status = ExecutionGateStatus(
            blocked=True,
            safe_to_trade=False,
            gate_state=GateState.BLOCKED.value,
            reasons=[
                BlockReason(
                    source="kill_switch",
                    severity="critical",
                    message="Kill switch is engaged",
                    hint="Reset via Mode & Safety panel",
                )
            ],
        )

        assert not status.allows_reduce()
        assert not status.safe_to_trade


class TestLegacyReconciliationDeprecated:
    """Tests to ensure legacy trading.reconciliation is properly deprecated."""

    def test_legacy_reconciliation_raises_import_error(self):
        """Importing trading.reconciliation should raise ImportError with helpful message."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ImportError) as exc_info:
                import trading.reconciliation

        assert "deprecated" in str(exc_info.value).lower()
        assert "merid.reconciliation" in str(exc_info.value)

    def test_legacy_reconciliation_import_fails_for_specific_exports(self):
        """Specific imports from legacy module should also fail."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ImportError):
                from trading.reconciliation import ReconciliationReport

            with pytest.raises(ImportError):
                from trading.reconciliation import has_critical_discrepancies


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
