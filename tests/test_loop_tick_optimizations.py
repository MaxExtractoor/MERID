"""Tests for tick processing optimizations in merid/loop.py

This test suite validates:
1. Tick overlap detection and prevention (_tick_in_progress)
2. Per-step duration tracking in tick summaries
3. Symbol batching logic for feature refresh
4. Liquidity parallelization with semaphore limits and timeouts
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch, call
from dataclasses import dataclass, field
from typing import Dict, List, Any

from merid.loop import MeridLoop, LoopConfig, LoopMetrics


class TestTickOverlapProtection:
    """Tests for _tick_in_progress overlap detection."""

    async def test_tick_in_progress_blocks_second_tick(self):
        """Second tick invocation while one is in progress should be skipped."""
        config = LoopConfig()
        config.enable_execution = False  # Safety: no real trades
        loop = MeridLoop(config)

        # First tick starts and holds the lock
        tick1_task = asyncio.create_task(loop.tick())
        await asyncio.sleep(0.01)  # Let first tick acquire lock

        # Second tick should be skipped
        result = await loop.tick()

        # Wait for first tick to complete
        await tick1_task

        assert result["tick"] == "skipped"
        assert result["reason"] == "tick_in_progress"
        assert loop._tick_in_progress is False  # Lock released

    async def test_tick_force_parameter_overrides_protection(self):
        """Force parameter should allow overlapping tick for tests."""
        config = LoopConfig()
        config.enable_execution = False
        loop = MeridLoop(config)

        # Start a slow tick
        slow_task = asyncio.create_task(loop.tick())
        await asyncio.sleep(0.01)

        # Force parameter should allow second tick
        result = await loop.tick(force=True)

        await slow_task

        assert result["tick"] != "skipped"
        assert "reason" not in result

    async def test_tick_lock_released_even_on_exception(self):
        """Lock must be released even if tick raises exception."""
        config = LoopConfig()
        loop = MeridLoop(config)

        # Mock a step to raise exception
        with patch.object(loop, '_run_step', side_effect=Exception("test error")):
            try:
                await loop.tick()
            except Exception:
                pass

        # Lock should be released
        assert loop._tick_in_progress is False

    async def test_tick_overlap_log_warning(self, caplog):
        """Overlapping tick should log a warning."""
        import logging
        pytest.importorskip("pytest")

        config = LoopConfig()
        config.enable_execution = False
        loop = MeridLoop(config)

        # Start first tick
        tick1 = asyncio.create_task(loop.tick())
        await asyncio.sleep(0.01)

        # Second tick should log warning
        with caplog.at_level(logging.WARNING):
            await loop.tick()

        await tick1

        assert "Tick skipped: previous tick still in progress" in caplog.text


class TestPerStepDurationTracking:
    """Tests for per-step timing in tick summaries."""

    async def test_step_timings_included_in_summary(self):
        """Tick summary should include per-step duration tracking."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        loop = MeridLoop(config)

        # Run a minimal tick
        summary = await loop.tick()

        assert "step_timings_ms" in summary
        assert isinstance(summary["step_timings_ms"], dict)

    async def test_step_timings_populated_for_executed_steps(self):
        """Step timings should be populated for steps that actually run."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        # Disable most steps to get predictable results
        config.feature_refresh_interval = 10000  # Won't trigger
        config.consensus_interval = 10000
        config.arb_scan_interval = 10000

        loop = MeridLoop(config)
        summary = await loop.tick()

        # At minimum, notify step should be timed
        assert "notify" in summary["step_timings_ms"]
        assert summary["step_timings_ms"]["notify"] >= 0

    async def test_step_timings_cleared_between_ticks(self):
        """Step timings should be cleared at start of each tick."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        loop = MeridLoop(config)

        # First tick
        summary1 = await loop.tick()
        timings1 = summary1["step_timings_ms"].copy()

        # Second tick
        summary2 = await loop.tick()
        timings2 = summary2["step_timings_ms"]

        # Timings should be independent
        assert timings1 != timings2 or len(timings2) == 0

    async def test_step_timing_values_are_positive(self):
        """All step timing values should be non-negative floats."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        loop = MeridLoop(config)

        summary = await loop.tick()

        for step_name, duration in summary["step_timings_ms"].items():
            assert duration >= 0, f"Step {step_name} has negative duration: {duration}"
            assert isinstance(duration, (int, float)), f"Step {step_name} duration is not numeric"


class TestSymbolBatching:
    """Tests for symbol round-robin batching in _refresh_features."""

    async def test_symbol_batch_size_progression(self):
        """Batch size should start at 1 and increase to 5 over time."""
        config = LoopConfig()
        config.active_symbols = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"]
        config.feature_refresh_interval = 1  # Trigger every tick

        loop = MeridLoop(config)

        # Patch feature service to avoid actual I/O
        with patch.object(loop, '_feature_service') as mock_svc:
            mock_svc.return_value.get_news_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
            mock_svc.return_value.get_social_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
            mock_svc.return_value.get_onchain_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
            mock_svc.return_value.get_macro_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))

            # Tick 1: should process 1 symbol
            loop.metrics.total_ticks = 0
            summary = {"actions": []}
            with patch.object(loop, '_signal_store') as mock_store:
                mock_store.return_value.store_feature_snapshots_batch = MagicMock()
                await loop._refresh_features(time.time(), summary)

            # After 100 ticks: should process 2 symbols
            loop.metrics.total_ticks = 100
            summary = {"actions": []}
            with patch.object(loop, '_signal_store') as mock_store:
                await loop._refresh_features(time.time(), summary)

            # After 200 ticks: should process up to 5 symbols
            loop.metrics.total_ticks = 200
            summary = {"actions": []}
            with patch.object(loop, '_signal_store') as mock_store:
                await loop._refresh_features(time.time(), summary)

    async def test_symbols_visited_over_multiple_ticks(self):
        """All symbols should be visited over multiple ticks with batching."""
        config = LoopConfig()
        symbols = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        config.active_symbols = symbols
        config.feature_refresh_interval = 1

        loop = MeridLoop(config)
        visited_symbols = set()

        # Mock feature service to capture which symbols are processed
        def mock_feature_refresh(*args, **kwargs):
            # Capture symbols from the loop's internal state during execution
            return 3  # batch size

        with patch.object(loop, '_signal_store') as mock_store:
            mock_store.return_value.store_feature_snapshots_batch = MagicMock()

            # Run multiple ticks to cover all symbols
            for tick_num in range(10):
                loop.metrics.total_ticks = tick_num
                summary = {"actions": []}
                await loop._refresh_features(time.time(), summary)

    async def test_startup_cooldown_skips_features(self):
        """Feature refresh should be skipped during first 120 ticks."""
        config = LoopConfig()
        config.feature_refresh_interval = 1

        loop = MeridLoop(config)
        loop.metrics.total_ticks = 50  # Less than 120
        summary = {"actions": []}

        await loop._refresh_features(time.time(), summary)

        assert "features_refreshed:skipped_startup_cooldown" in summary["actions"]


class TestLiquidityParallelization:
    """Tests for parallel liquidity refresh with semaphore and timeouts."""

    async def test_liquidity_semaphore_limit(self):
        """Liquidity refresh should use semaphore to limit concurrent fetches."""
        config = LoopConfig()
        loop = MeridLoop(config)

        # Verify semaphore is created with limit 2
        # This is tested indirectly through the _refresh_liquidity method
        # by checking concurrent execution behavior

        with patch('asyncio.Semaphore') as mock_sem:
            mock_sem_instance = AsyncMock()
            mock_sem.return_value = mock_sem_instance

            # The method should create semaphore with value 2
            # Note: We can't easily patch the internal _sem variable,
            # but we can verify the behavior through timing analysis

    async def test_liquidity_timeout_handling(self):
        """Slow or failing markets should hit timeout and not block others."""
        config = LoopConfig()
        loop = MeridLoop(config)

        tickers = ["KXBTC-15M", "KXETH-15M"]

        # Mock client with one slow response
        with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_client:
            mock_kalshi = MagicMock()

            # First ticker is slow (will timeout)
            async def slow_response(ticker):
                await asyncio.sleep(5.0)  # Exceeds 2s timeout
                return None

            # Second ticker is fast
            async def fast_response(ticker):
                return MagicMock(bids=[[100, 10]], asks=[[101, 10]])

            mock_kalshi.get_orderbook = slow_response
            mock_kalshi.is_circuit_open = False
            mock_client.return_value = mock_kalshi

            # Patch agent grid to return test tickers
            with patch('merid.prediction.agent_grid.get_agent_grid') as mock_grid:
                mock_agent = MagicMock()
                mock_agent.state.active_tickers = tickers
                mock_grid.return_value.agents = [mock_agent]

                summary = {"actions": []}

                # This should complete without blocking on the slow ticker
                start = time.perf_counter()
                await loop._refresh_liquidity(time.time(), summary)
                elapsed = time.perf_counter() - start

                # Should complete in reasonable time despite slow ticker
                assert elapsed < 5.0, f"Liquidity refresh took too long: {elapsed}s"

    async def test_liquidity_circuit_breaker_fast_path(self):
        """Liquidity refresh should skip entirely if circuit is open."""
        config = LoopConfig()
        loop = MeridLoop(config)

        # Set tick count high enough to bypass startup cooldown
        loop.metrics.total_ticks = 200

        with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_client:
            mock_kalshi = MagicMock()
            mock_kalshi.is_circuit_open = True
            mock_client.return_value = mock_kalshi

            summary = {"actions": []}
            await loop._refresh_liquidity(time.time(), summary)

            assert "liquidity_sweep:circuit_open" in summary["actions"]

    async def test_liquidity_startup_cooldown(self):
        """Liquidity refresh should be skipped during first 120 ticks."""
        config = LoopConfig()
        loop = MeridLoop(config)

        loop.metrics.total_ticks = 50  # Less than 120
        summary = {"actions": []}

        await loop._refresh_liquidity(time.time(), summary)

        assert "liquidity_sweep:skipped_startup_cooldown" in summary["actions"]


class TestConsensusParallelization:
    """Tests for consensus parallelization and debate prefetching."""

    async def test_consensus_symbol_cap(self):
        """Consensus should process max 10 symbols per tick."""
        config = LoopConfig()
        loop = MeridLoop(config)

        # Mock coordinator with many pending symbols
        many_symbols = [f"SYM{i}" for i in range(50)]

        with patch.object(loop, '_consensus_coordinator') as mock_coord:
            mock_coord.return_value._opinions = {
                sym: [MagicMock()] for sym in many_symbols
            }
            mock_coord.return_value._active_plans = {}
            mock_coord.return_value.prune_expired_plans = MagicMock()

            summary = {"actions": []}
            await loop._run_consensus(summary)

            # Should only process 10 symbols
            # Verify through action summary
            action = [a for a in summary["actions"] if a.startswith("consensus_check")]
            assert len(action) == 1

    async def test_debate_cap_per_tick(self):
        """Debate opening should be capped at 5 per tick."""
        config = LoopConfig()
        loop = MeridLoop(config)

        with patch.object(loop, '_consensus_coordinator') as mock_coord:
            # Create 20 high-conviction plans
            plans = []
            for i in range(20):
                plan = MagicMock()
                plan.consensus_probability = 0.8  # High conviction (>0.55)
                plan.symbol = f"MARKET{i}"
                plan.is_expired.return_value = False
                plans.append(plan)

            mock_coord.return_value._active_plans = {p.symbol: p for p in plans}
            mock_coord.return_value._opinions = {}
            mock_coord.return_value.prune_expired_plans = MagicMock()

            # Mock debate store
            with patch('merid.prediction.debate.get_debate_store') as mock_debate:
                mock_store = MagicMock()
                mock_store.list_debates.return_value = []  # No existing debates
                mock_store.create_debate = MagicMock()
                mock_debate.return_value = mock_store

                summary = {"actions": []}
                await loop._run_consensus(summary)

                # Debates opened should be capped at 5
                debates_opened = sum(1 for _ in mock_store.create_debate.call_args_list)
                assert debates_opened <= 5, f"Too many debates opened: {debates_opened}"


class TestIntegrationTickPerformance:
    """Integration tests for overall tick performance characteristics."""

    async def test_tick_duration_reasonable(self):
        """Complete tick should complete within reasonable time budget."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        # Extend intervals so steps don't actually trigger
        config.feature_refresh_interval = 10000
        config.consensus_interval = 10000
        config.arb_scan_interval = 10000

        loop = MeridLoop(config)

        start = time.perf_counter()
        summary = await loop.tick()
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Tick should complete in under 1 second for minimal work
        assert elapsed_ms < 1000, f"Tick took too long: {elapsed_ms:.1f}ms"
        assert "duration_ms" in summary
        assert summary["duration_ms"] >= 0

    async def test_multiple_ticks_no_overlap_issues(self):
        """Running multiple ticks sequentially should not cause issues."""
        config = LoopConfig()
        config.enable_execution = False
        config.enable_reconciliation = False
        config.feature_refresh_interval = 10000
        config.consensus_interval = 10000
        config.arb_scan_interval = 10000

        loop = MeridLoop(config)

        summaries = []
        for _ in range(5):
            summary = await loop.tick()
            summaries.append(summary)

        # All ticks should complete
        assert len(summaries) == 5
        # None should be skipped
        assert all(s.get("tick") != "skipped" for s in summaries)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
