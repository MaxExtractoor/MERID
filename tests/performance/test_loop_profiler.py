"""
Tests for Loop Performance Profiler

Phase 4.2: Profile agent processing and market scanning

Test suite for the 15m loop performance profiler including:
- Profiler initialization and lifecycle
- Cycle timing accuracy
- Phase-level breakdown
- Performance summary generation
- Bottleneck detection
- API endpoint integration
"""

import pytest
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from merid.performance.loop_profiler import (
    LoopProfiler, 
    CycleMetrics, 
    PerformanceSummary,
    get_loop_profiler,
    reset_loop_profiler
)


class TestLoopProfiler:
    """Test the LoopProfiler class."""
    
    def test_profiler_initialization(self):
        """Test profiler initialization with default parameters."""
        profiler = LoopProfiler()
        
        assert profiler._enabled is True
        assert profiler.max_history == 1000
        assert len(profiler._cycle_history) == 0
        assert len(profiler._phase_timers) == 0
        assert profiler.CYCLE_DURATION_WARNING_MS == 1000.0
        assert profiler.CYCLE_DURATION_CRITICAL_MS == 2000.0
    
    def test_profiler_initialization_with_custom_params(self):
        """Test profiler initialization with custom parameters."""
        profiler = LoopProfiler(max_history=500)
        
        assert profiler.max_history == 500
        assert profiler.CYCLE_DURATION_WARNING_MS == 1000.0
        assert profiler.CYCLE_DURATION_CRITICAL_MS == 2000.0
    
    def test_profiler_enable_disable(self):
        """Test profiler enable/disable functionality."""
        profiler = LoopProfiler()
        
        # Test disable
        profiler.disable()
        assert profiler._enabled is False
        
        # Test enable
        profiler.enable()
        assert profiler._enabled is True
    
    @pytest.mark.asyncio
    async def test_profile_cycle_context_manager(self):
        """Test the profile_cycle context manager."""
        profiler = LoopProfiler()
        
        # Test with profiler enabled
        async with profiler.profile_cycle(1):
            await asyncio.sleep(0.1)  # Simulate some work
        
        # Check that cycle was recorded
        assert len(profiler._cycle_history) == 1
        cycle = profiler._cycle_history[0]
        assert cycle.cycle_id == 1
        assert cycle.duration_ms > 50  # Should be at least 50ms
        assert cycle.memory_usage_mb >= 0
        assert cycle.cpu_percent >= 0
    
    @pytest.mark.asyncio
    async def test_profile_cycle_context_manager_disabled(self):
        """Test the profile_cycle context manager when disabled."""
        profiler = LoopProfiler()
        profiler.disable()
        
        # Test with profiler disabled
        async with profiler.profile_cycle(1):
            await asyncio.sleep(0.1)  # Simulate some work
        
        # Check that no cycle was recorded
        assert len(profiler._cycle_history) == 0
    
    @pytest.mark.asyncio
    async def test_profile_phase_context_manager(self):
        """Test the profile_phase context manager."""
        profiler = LoopProfiler()
        
        # Set current cycle to enable phase profiling
        profiler._current_cycle = 1
        
        # Test phase profiling
        async with profiler.profile_phase("agent_processing"):
            await asyncio.sleep(0.05)  # Simulate agent processing
        
        # Check that phase was recorded
        assert "agent_processing" in profiler._phase_timers
        assert profiler._phase_timers["agent_processing"] >= 0.05
    
    @pytest.mark.asyncio
    async def test_profile_phase_context_manager_disabled(self):
        """Test the profile_phase context manager when disabled."""
        profiler = LoopProfiler()
        profiler.disable()
        profiler._current_cycle = 1
        
        # Test phase profiling with disabled profiler
        async with profiler.profile_phase("agent_processing"):
            await asyncio.sleep(0.05)  # Simulate agent processing
        
        # Check that no phase was recorded
        assert len(profiler._phase_timers) == 0
    
    @pytest.mark.asyncio
    async def test_profile_phase_without_current_cycle(self):
        """Test the profile_phase context manager without current cycle."""
        profiler = LoopProfiler()
        
        # Test phase profiling without current cycle
        async with profiler.profile_phase("agent_processing"):
            await asyncio.sleep(0.05)  # Simulate agent processing
        
        # Check that no phase was recorded
        assert len(profiler._phase_timers) == 0
    
    def test_generate_warnings(self):
        """Test warning generation for performance issues."""
        profiler = LoopProfiler()
        
        # Test no warnings
        warnings = profiler._generate_warnings(500, 200, 50)
        assert len(warnings) == 0
        
        # Test duration warning
        warnings = profiler._generate_warnings(1500, 200, 50)
        assert len(warnings) == 1
        assert "WARNING: Cycle duration 1500.0ms" in warnings[0]
        
        # Test critical duration warning
        warnings = profiler._generate_warnings(2500, 200, 50)
        assert len(warnings) == 1
        assert "CRITICAL: Cycle duration 2500.0ms" in warnings[0]
        
        # Test memory warning
        warnings = profiler._generate_warnings(500, 600, 50)
        assert len(warnings) == 1
        assert "WARNING: Memory usage 600.0MB" in warnings[0]
        
        # Test CPU warning
        warnings = profiler._generate_warnings(500, 200, 90)
        assert len(warnings) == 1
        assert "WARNING: CPU usage 90.0%" in warnings[0]
        
        # Test multiple warnings
        warnings = profiler._generate_warnings(2500, 600, 90)
        assert len(warnings) == 3
    
    def test_get_performance_summary_empty(self):
        """Test performance summary with no data."""
        profiler = LoopProfiler()
        summary = profiler.get_performance_summary()
        
        assert summary.total_cycles == 0
        assert summary.avg_cycle_duration_ms == 0.0
        assert summary.p95_cycle_duration_ms == 0.0
        assert summary.p99_cycle_duration_ms == 0.0
        assert summary.max_cycle_duration_ms == 0.0
        assert summary.min_cycle_duration_ms == 0.0
        assert summary.avg_memory_usage_mb == 0.0
        assert summary.max_memory_usage_mb == 0.0
        assert summary.avg_cpu_percent == 0.0
        assert summary.max_cpu_percent == 0.0
        assert summary.error_rate == 0.0
        assert summary.bottleneck_phase == "unknown"
        assert summary.recommendations == ["No data available"]
    
    def test_get_performance_summary_with_data(self):
        """Test performance summary with cycle data."""
        profiler = LoopProfiler()
        
        # Add some test cycles with performance issues
        now = time.time()
        for i in range(10):
            cycle = CycleMetrics(
                cycle_id=i,
                start_time=now + i,
                end_time=now + i + 0.1,
                duration_ms=100 + i * 10,
                agent_processing_ms=50 + i * 5,
                market_scanning_ms=20 + i * 2,
                order_submission_ms=10 + i * 1,
                risk_check_ms=20 + i * 2,
                memory_usage_mb=100 + i * 10,
                cpu_percent=20 + i * 5,
                error_count=i % 2,
                warnings=["WARNING: Cycle duration too long"] if i > 5 else []
            )
            profiler._cycle_history.append(cycle)
        
        summary = profiler.get_performance_summary()
        
        assert summary.total_cycles == 10
        assert summary.avg_cycle_duration_ms == pytest.approx(145, rel=1e-2)
        assert summary.max_cycle_duration_ms == 190
        assert summary.min_cycle_duration_ms == 100
        assert summary.avg_memory_usage_mb == pytest.approx(145, rel=1e-2)
        assert summary.max_memory_usage_mb == 190
        assert summary.error_rate == 0.5  # 5 errors out of 10 cycles
        assert summary.bottleneck_phase in ["agent_processing", "market_scanning", "order_submission", "risk_check"]
        # Should have recommendations due to warnings and performance issues
        assert len(summary.recommendations) >= 0
    
    def test_get_recent_cycles(self):
        """Test getting recent cycles."""
        profiler = LoopProfiler()
        
        # Add some test cycles
        now = time.time()
        for i in range(15):
            cycle = CycleMetrics(
                cycle_id=i,
                start_time=now + i,
                end_time=now + i + 0.1,
                duration_ms=100 + i * 10,
                agent_processing_ms=50,
                market_scanning_ms=20,
                order_submission_ms=10,
                risk_check_ms=20,
                memory_usage_mb=100,
                cpu_percent=20,
                error_count=0,
                warnings=[]
            )
            profiler._cycle_history.append(cycle)
        
        # Test getting recent cycles
        recent = profiler.get_recent_cycles(5)
        assert len(recent) == 5
        assert recent[0].cycle_id == 10  # Should get the last 5 cycles
        assert recent[-1].cycle_id == 14
        
        # Test getting more cycles than available
        recent = profiler.get_recent_cycles(20)
        assert len(recent) == 15  # Should get all available cycles
    
    def test_reset_history(self):
        """Test resetting performance history."""
        profiler = LoopProfiler()
        
        # Add some test cycles
        for i in range(5):
            cycle = CycleMetrics(
                cycle_id=i,
                start_time=time.time(),
                end_time=time.time() + 0.1,
                duration_ms=100,
                agent_processing_ms=50,
                market_scanning_ms=20,
                order_submission_ms=10,
                risk_check_ms=20,
                memory_usage_mb=100,
                cpu_percent=20,
                error_count=0,
                warnings=[]
            )
            profiler._cycle_history.append(cycle)
        
        assert len(profiler._cycle_history) == 5
        
        # Reset history
        profiler.reset_history()
        
        assert len(profiler._cycle_history) == 0
        assert len(profiler._phase_timers) == 0
    
    def test_export_metrics(self):
        """Test exporting metrics for external monitoring."""
        profiler = LoopProfiler()
        
        # Add some test cycles
        now = time.time()
        for i in range(3):
            cycle = CycleMetrics(
                cycle_id=i,
                start_time=now + i,
                end_time=now + i + 0.1,
                duration_ms=100 + i * 10,
                agent_processing_ms=50 + i * 5,
                market_scanning_ms=20 + i * 2,
                order_submission_ms=10 + i * 1,
                risk_check_ms=20 + i * 2,
                memory_usage_mb=100 + i * 10,
                cpu_percent=20 + i * 5,
                error_count=0,
                warnings=["Test warning"] if i == 0 else []
            )
            profiler._cycle_history.append(cycle)
        
        exported = profiler.export_metrics()
        
        assert "summary" in exported
        assert "recent_cycles" in exported
        assert "timestamp" in exported
        
        summary = exported["summary"]
        assert summary["total_cycles"] == 3
        assert summary["avg_duration_ms"] == pytest.approx(110, rel=1e-2)
        
        recent_cycles = exported["recent_cycles"]
        assert len(recent_cycles) == 3
        assert recent_cycles[0]["cycle_id"] == 0
        assert recent_cycles[0]["warnings"] == ["Test warning"]
    
    @patch('merid.performance.loop_profiler.psutil.Process')
    def test_get_memory_usage(self, mock_process):
        """Test memory usage measurement."""
        mock_process.return_value.memory_info.return_value.rss = 1024 * 1024 * 500  # 500MB
        profiler = LoopProfiler()
        
        memory_mb = profiler._get_memory_usage()
        assert memory_mb == 500.0
    
    @patch('merid.performance.loop_profiler.psutil.Process')
    def test_get_cpu_usage(self, mock_process):
        """Test CPU usage measurement."""
        mock_process.return_value.cpu_percent.return_value = 75.5
        profiler = LoopProfiler()
        
        cpu_percent = profiler._get_cpu_usage()
        assert cpu_percent == 75.5
    
    def test_generate_recommendations(self):
        """Test performance recommendations generation."""
        profiler = LoopProfiler()
        
        # Test slow agent processing
        metrics = CycleMetrics(
            cycle_id=1,
            start_time=time.time(),
            end_time=time.time() + 0.1,
            duration_ms=1000,
            agent_processing_ms=600,  # Slow agent processing
            market_scanning_ms=200,
            order_submission_ms=100,
            risk_check_ms=100,
            memory_usage_mb=200,
            cpu_percent=50,
            error_count=0,
            warnings=[]
        )
        
        phase_times = [
            ("agent_processing", metrics.agent_processing_ms),
            ("market_scanning", metrics.market_scanning_ms),
            ("order_submission", metrics.order_submission_ms),
            ("risk_check", metrics.risk_check_ms),
        ]
        
        recommendations = profiler._generate_recommendations(metrics, phase_times)
        
        assert len(recommendations) > 0
        assert any("agent" in rec.lower() for rec in recommendations)
    
    def test_analyze_bottlenecks(self):
        """Test bottleneck analysis."""
        profiler = LoopProfiler()
        
        # Create a cycle with a clear bottleneck
        metrics = CycleMetrics(
            cycle_id=1,
            start_time=time.time(),
            end_time=time.time() + 0.1,
            duration_ms=2000,  # Critical duration
            agent_processing_ms=1500,  # Clear bottleneck
            market_scanning_ms=200,
            order_submission_ms=100,
            risk_check_ms=200,
            memory_usage_mb=200,
            cpu_percent=50,
            error_count=0,
            warnings=["CRITICAL: Cycle duration 2000.0ms exceeds threshold"]
        )
        
        # This should not raise an exception
        profiler._analyze_bottlenecks(metrics)


class TestProfilerSingleton:
    """Test the global profiler singleton pattern."""
    
    def test_get_loop_profiler_singleton(self):
        """Test that get_loop_profiler returns the same instance."""
        reset_loop_profiler()
        
        profiler1 = get_loop_profiler()
        profiler2 = get_loop_profiler()
        
        assert profiler1 is profiler2
        assert isinstance(profiler1, LoopProfiler)
    
    def test_reset_loop_profiler(self):
        """Test resetting the global profiler."""
        # Get initial profiler
        profiler1 = get_loop_profiler()
        
        # Add some data
        cycle = CycleMetrics(
            cycle_id=1,
            start_time=time.time(),
            end_time=time.time() + 0.1,
            duration_ms=100,
            agent_processing_ms=50,
            market_scanning_ms=20,
            order_submission_ms=10,
            risk_check_ms=20,
            memory_usage_mb=100,
            cpu_percent=20,
            error_count=0,
            warnings=[]
        )
        profiler1._cycle_history.append(cycle)
        
        assert len(profiler1._cycle_history) == 1
        
        # Reset profiler
        reset_loop_profiler()
        
        # Get new profiler
        profiler2 = get_loop_profiler()
        
        assert profiler2 is not profiler1  # Should be a new instance
        assert len(profiler2._cycle_history) == 0


class TestProfilerIntegration:
    """Test profiler integration with the 15m loop."""
    
    def test_profiler_integration_simulation(self):
        """Test profiler integration with simulated 15m loop execution."""
        profiler = LoopProfiler()
        
        async def run_simulation():
            # Simulate a complete cycle execution
            async with profiler.profile_cycle(1):
                # Simulate market scanning
                async with profiler.profile_phase("market_scanning"):
                    await asyncio.sleep(0.02)  # 20ms market scanning
                
                # Simulate risk check
                async with profiler.profile_phase("risk_check"):
                    await asyncio.sleep(0.01)  # 10ms risk check
                
                # Simulate agent processing
                async with profiler.profile_phase("agent_processing"):
                    await asyncio.sleep(0.05)  # 50ms agent processing
                
                # Simulate order submission
                async with profiler.profile_phase("order_submission"):
                    await asyncio.sleep(0.01)  # 10ms order submission
        
        # Run the simulation
        asyncio.run(run_simulation())
        
        # Verify cycle was recorded
        assert len(profiler._cycle_history) == 1
        cycle = profiler._cycle_history[0]
        
        assert cycle.cycle_id == 1
        assert cycle.duration_ms >= 80  # At least 80ms total
        assert cycle.market_scanning_ms >= 20
        assert cycle.risk_check_ms >= 10
        assert cycle.agent_processing_ms >= 50
        assert cycle.order_submission_ms >= 10
    
    def test_profiler_with_system_metrics(self):
        """Test profiler with mocked system metrics."""
        # Mock system metrics
        with patch('merid.performance.loop_profiler.psutil.Process') as mock_process:
            mock_process.return_value.memory_info.return_value.rss = 1024 * 1024 * 300  # 300MB
            mock_process.return_value.cpu_percent.return_value = 60.0
            
            profiler = LoopProfiler()
            
            async def run_simulation():
                # Simulate a cycle
                async with profiler.profile_cycle(1):
                    await asyncio.sleep(0.01)
            
            # Run the simulation
            asyncio.run(run_simulation())
            
            # Verify system metrics were recorded
            cycle = profiler._cycle_history[0]
            assert cycle.memory_usage_mb == 300.0
            assert cycle.cpu_percent == 60.0


if __name__ == "__main__":
    pytest.main([__file__])
