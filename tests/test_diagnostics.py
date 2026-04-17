"""Tests for merid.diagnostics module - verifies imports and basic functionality."""

import pytest


class TestDiagnosticsImports:
    """Test that diagnostics modules can be imported without syntax errors."""

    def test_loop_lag_module_imports(self):
        """Test that loop_lag module imports correctly (regression test for syntax error)."""
        from merid.diagnostics.loop_lag import LoopLagMonitor, get_loop_lag_monitor, LoopLagStats
        assert LoopLagMonitor is not None
        assert get_loop_lag_monitor is not None
        assert LoopLagStats is not None

    def test_diagnostics_init_imports(self):
        """Test that diagnostics __init__ imports correctly (regression test for syntax error)."""
        from merid.diagnostics import KalshiPipelineProbe, ProbeResult, ProbeReport
        assert KalshiPipelineProbe is not None
        assert ProbeResult is not None
        assert ProbeReport is not None

    def test_loop_lag_monitor_singleton(self):
        """Test that LoopLagMonitor is a proper singleton."""
        from merid.diagnostics.loop_lag import get_loop_lag_monitor, LoopLagMonitor
        
        monitor1 = get_loop_lag_monitor()
        monitor2 = get_loop_lag_monitor()
        
        assert monitor1 is monitor2
        assert isinstance(monitor1, LoopLagMonitor)

    def test_loop_lag_stats_basic(self):
        """Test LoopLagStats basic functionality."""
        from merid.diagnostics.loop_lag import LoopLagStats, LoopLagSample
        
        stats = LoopLagStats()
        assert stats.current_ms == 0.0
        assert stats.p50_ms == 0.0
        
        # Add a sample
        stats.add(LoopLagSample(timestamp=1.0, lag_ms=10.0))
        assert stats.current_ms == 10.0
        assert len(stats.samples) == 1
        
        # Test to_dict
        d = stats.to_dict()
        assert "current_ms" in d
        assert "p50_ms" in d
        assert "p95_ms" in d

    def test_loop_lag_get_health_threshold_bands(self, monkeypatch):
        """Env-driven bands: ~1.7s → degraded (LIMITED), not halt; halt band >= 2000ms."""
        from merid.diagnostics.loop_lag import (
            LoopLagMonitor,
            LoopLagSample,
            LoopLagStats,
            get_loop_lag_monitor,
            get_loop_lag_thresholds_ms,
        )

        monkeypatch.setenv("KALSHI_LOOP_LAG_HEALTHY_MS", "50")
        monkeypatch.setenv("KALSHI_LOOP_LAG_DEGRADE_MS", "500")
        monkeypatch.setenv("KALSHI_LOOP_LAG_HALT_MS", "2000")

        th = get_loop_lag_thresholds_ms()
        assert th["halt_ms"] == 2000.0
        assert th["degrade_ms"] == 500.0

        m = get_loop_lag_monitor()
        assert isinstance(m, LoopLagMonitor)
        saved = m._stats
        try:
            m._stats = LoopLagStats()
            m._stats.add(LoopLagSample(timestamp=1.0, lag_ms=1704.0))
            h = m.get_health()
            assert h["degraded"] is True
            assert h["critical"] is False
            assert h["healthy"] is False

            m._stats = LoopLagStats()
            m._stats.add(LoopLagSample(timestamp=1.0, lag_ms=2100.0))
            h2 = m.get_health()
            assert h2["critical"] is True
            assert h2["degraded"] is False
        finally:
            m._stats = saved

    def test_kalshi_pipeline_probe_init(self):
        """Test KalshiPipelineProbe can be instantiated."""
        from merid.diagnostics import KalshiPipelineProbe
        
        probe = KalshiPipelineProbe(duration_seconds=10)
        assert probe.duration == 10
        assert probe.report is not None


class TestProbeResult:
    """Test ProbeResult dataclass."""

    def test_probe_result_creation(self):
        """Test ProbeResult can be created with required fields."""
        from merid.diagnostics import ProbeResult
        
        result = ProbeResult(
            probe_name="test_probe",
            timestamp=1.0,
            duration_ms=100.0,
            success=True
        )
        assert result.probe_name == "test_probe"
        assert result.timestamp == 1.0
        assert result.duration_ms == 100.0
        assert result.success is True
        assert result.error is None
        assert result.metadata == {}

    def test_probe_result_with_error(self):
        """Test ProbeResult with error field."""
        from merid.diagnostics import ProbeResult
        
        result = ProbeResult(
            probe_name="test_probe",
            timestamp=1.0,
            duration_ms=100.0,
            success=False,
            error="Something failed"
        )
        assert result.success is False
        assert result.error == "Something failed"
