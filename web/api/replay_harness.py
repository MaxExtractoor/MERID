"""Historical Replay Harness — Compare baseline vs incentive-tuned behavior.

Runs historical Kalshi market data through MERID agents and consensus,
comparing performance with incentives disabled vs enabled.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from utils.logger import get_logger

logger = get_logger("replay.harness")


class ReplayMode(Enum):
    """Replay comparison mode."""
    BASELINE = "baseline"           # Incentives disabled
    INCENTIVE_TUNED = "incentive_tuned"  # Incentives enabled


@dataclass
class ReplayScenario:
    """Configuration for a replay scenario."""
    start_time: float  # Unix timestamp
    end_time: float
    market_filters: Dict[str, Any] = field(default_factory=dict)  # category, symbols, etc.
    description: str = ""


@dataclass
class ReplayRunResult:
    """Results from a single replay run."""
    run_id: str
    mode: ReplayMode
    scenario: ReplayScenario
    
    # PnL metrics
    total_pnl: float = 0.0
    per_market_pnl: Dict[str, float] = field(default_factory=dict)
    per_category_pnl: Dict[str, float] = field(default_factory=dict)
    
    # Performance metrics
    hit_rate: float = 0.0  # Accuracy on resolved markets
    total_markets: int = 0
    resolved_markets: int = 0
    
    # Risk metrics
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # Agent leaderboard snapshot
    agent_leaderboard: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timing
    start_time: float = 0.0
    end_time: float = 0.0
    
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time


@dataclass
class ReplayComparison:
    """Comparison between baseline and incentive-tuned runs."""
    comparison_id: str
    baseline: ReplayRunResult
    tuned: ReplayRunResult
    
    # Computed differences
    pnl_diff: float = 0.0
    pnl_diff_pct: float = 0.0
    hit_rate_diff: float = 0.0
    drawdown_diff: float = 0.0
    
    def __post_init__(self):
        if self.baseline.total_pnl != 0:
            self.pnl_diff = self.tuned.total_pnl - self.baseline.total_pnl
            self.pnl_diff_pct = (self.pnl_diff / abs(self.baseline.total_pnl)) * 100
        self.hit_rate_diff = self.tuned.hit_rate - self.baseline.hit_rate
        self.drawdown_diff = self.tuned.max_drawdown - self.baseline.max_drawdown


class HistoricalReplayHarness:
    """Runs historical scenarios through MERID for A/B comparison.
    
    Isolated "sim" mode ensures no live orders can be sent.
    """
    
    def __init__(self):
        self._isolated = True  # Always True for safety
        self._active_run: Optional[str] = None
        self._results: Dict[str, ReplayRunResult] = {}
        self._event_handlers: List[Callable] = []
        
    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit replay event to handlers."""
        for handler in self._event_handlers:
            try:
                handler(event_type, data)
            except Exception as exc:
                logger.debug("Replay event handler error: %s", exc)
    
    async def run_scenario(
        self,
        scenario: ReplayScenario,
        mode: ReplayMode,
        progress_callback: Optional[Callable[[int, int], None]] = None) -> ReplayRunResult:
        """Run a single replay scenario.
        
        Args:
            scenario: Time window and market filters
            mode: BASELINE or INCENTIVE_TUNED
            progress_callback: Called with (completed, total)
            
        Returns:
            ReplayRunResult with all metrics
        """
        run_id = str(uuid.uuid4())[:8]
        self._active_run = run_id
        
        logger.info(
            "Starting replay run %s: mode=%s, window=%.0f-%.0f",
            run_id, mode.value, scenario.start_time, scenario.end_time
        )
        
        self._emit_event("replay.started", {
            "run_id": run_id,
            "mode": mode.value,
            "scenario": {
                "start": scenario.start_time,
                "end": scenario.end_time,
                "filters": scenario.market_filters,
            },
        })
        
        result = ReplayRunResult(
            run_id=run_id,
            mode=mode,
            scenario=scenario,
            start_time=time.time())
        
        try:
            # Configure coordinator for this mode
            await self._configure_for_mode(mode)
            
            # Load historical events
            events = await self._load_historical_events(scenario)
            
            # Replay events through event bus
            total = len(events)
            for i, event in enumerate(events):
                if self._active_run != run_id:
                    raise RuntimeError("Run cancelled")
                
                await self._replay_event(event)
                
                if progress_callback and i % 10 == 0:
                    progress_callback(i + 1, total)
            
            # Collect metrics
            result = await self._collect_results(result)
            
        except Exception as exc:
            logger.error("Replay run %s failed: %s", run_id, exc)
            self._emit_event("replay.error", {"run_id": run_id, "error": str(exc)})
            raise
        finally:
            result.end_time = time.time()
            self._results[run_id] = result
            self._active_run = None
            
            self._emit_event("replay.completed", {
                "run_id": run_id,
                "mode": mode.value,
                "duration": result.duration_seconds(),
                "pnl": result.total_pnl,
            })
            
            logger.info(
                "Replay run %s completed: PnL=%.2f, HitRate=%.1f%%, Duration=%.1fs",
                run_id, result.total_pnl, result.hit_rate * 100, result.duration_seconds()
            )
        
        return result
    
    async def compare_runs(
        self,
        scenario: ReplayScenario,
        progress_callback: Optional[Callable[[str, int, int], None]] = None) -> ReplayComparison:
        """Run both baseline and incentive-tuned, return comparison.
        
        Args:
            scenario: Time window and market filters
            progress_callback: Called with (phase, completed, total)
            
        Returns:
            ReplayComparison with both runs and deltas
        """
        comparison_id = str(uuid.uuid4())[:8]
        
        logger.info("Starting comparison %s: %s", comparison_id, scenario.description)
        
        self._emit_event("comparison.started", {
            "comparison_id": comparison_id,
            "scenario": scenario.description,
        })
        
        # Run A: Baseline
        if progress_callback:
            progress_callback("baseline", 0, 100)
        
        baseline = await self.run_scenario(
            scenario,
            ReplayMode.BASELINE,
            lambda c, t: progress_callback("baseline", c, t) if progress_callback else None)
        
        # Run B: Incentive-tuned
        if progress_callback:
            progress_callback("tuned", 0, 100)
        
        tuned = await self.run_scenario(
            scenario,
            ReplayMode.INCENTIVE_TUNED,
            lambda c, t: progress_callback("tuned", c, t) if progress_callback else None)
        
        comparison = ReplayComparison(
            comparison_id=comparison_id,
            baseline=baseline,
            tuned=tuned)
        
        self._emit_event("comparison.completed", {
            "comparison_id": comparison_id,
            "pnl_diff": comparison.pnl_diff,
            "hit_rate_diff": comparison.hit_rate_diff,
        })
        
        logger.info(
            "Comparison %s: PnL diff=%.2f (%.1f%%), Hit rate diff=%+.1f%%",
            comparison_id, comparison.pnl_diff, comparison.pnl_diff_pct, 
            comparison.hit_rate_diff * 100
        )
        
        return comparison
    
    async def _configure_for_mode(self, mode: ReplayMode) -> None:
        """Configure coordinator for baseline or tuned mode."""
        # LEGACY REMOVAL: Consensus module deleted - configuration disabled
        # from consensus.consensus_coordinator import get_consensus_coordinator
        # coord = get_consensus_coordinator()
        #
        # if mode == ReplayMode.BASELINE:
        #     # Disable social advisory and incentives
        #     coord.config.social_advisory_max_nudge = 0.0
        #     # Reset all social weights to 0
        #     for source in coord.config.social_advisory_weights:
        #         coord.config.social_advisory_weights[source] = 0.0
        #     logger.debug("Configured for BASELINE: incentives disabled")
        #
        # else:  # INCENTIVE_TUNED
        #     # Enable social advisory with conservative defaults
        #     coord.config.social_advisory_max_nudge = 0.05
        #     coord.config.social_advisory_weights = {
        #         "twitter": 0.1,
        #         "reddit": 0.1,
        #         "newsapi": 0.05,
        #     }
        #     logger.debug("Configured for INCENTIVE_TUNED: incentives enabled")
        logger.debug(f"Replay mode configuration disabled - consensus module deleted: {mode}")

    async def _load_historical_events(self, scenario: ReplayScenario) -> List[Dict[str, Any]]:
        """Load historical market events for the scenario window."""
        # Try to load from fixtures first
        events = []
        
        try:
            # Check for fixture files
            import os
            fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures")
            
            if os.path.exists(fixture_dir):
                for fname in os.listdir(fixture_dir):
                    if fname.endswith(".jsonl") or fname.endswith(".json"):
                        fpath = os.path.join(fixture_dir, fname)
                        try:
                            with open(fpath, 'r') as f:
                                import json
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        event = json.loads(line)
                                        # Filter by time window
                                        ts = event.get("timestamp", 0)
                                        if scenario.start_time <= ts <= scenario.end_time:
                                            events.append(event)
                                    except json.JSONDecodeError:
                                        continue
                        except Exception as exc:
                            logger.debug("Failed to load fixture %s: %s", fname, exc)
        
        except Exception as exc:
            logger.warning("Failed to load historical fixtures: %s", exc)
        
        # If no fixtures, generate synthetic events for testing
        if not events:
            logger.info("No historical fixtures found, generating synthetic events")
            events = self._generate_synthetic_events(scenario)
        
        # Sort by timestamp
        events.sort(key=lambda e: e.get("timestamp", 0))
        
        return events
    
    def _generate_synthetic_events(self, scenario: ReplayScenario) -> List[Dict[str, Any]]:
        """Generate synthetic market events for testing."""
        events = []
        duration = scenario.end_time - scenario.start_time
        
        # Generate ~100 events spread across the window
        for i in range(100):
            ts = scenario.start_time + (duration * i / 100)
            events.append({
                "timestamp": ts,
                "type": "market_tick",
                "symbol": "BTC",
                "price": 50000 + (i * 100),  # Simple upward trend
                "volume": 1000,
            })
        
        return events
    
    async def _replay_event(self, event: Dict[str, Any]) -> None:
        """Replay a single event through the event bus."""
        try:
            from core.event_bus import get_event_bus
            bus = get_event_bus()
            
            # Emit to event bus
            await bus.emit(event.get("type", "unknown"), event)
            
            # Small delay to simulate real-time processing
            await asyncio.sleep(0.001)
            
        except Exception as exc:
            logger.debug("Event replay error: %s", exc)
    
    async def _collect_results(self, result: ReplayRunResult) -> ReplayRunResult:
        """Collect final metrics from coordinator and ledger."""
        # LEGACY REMOVAL: Consensus module deleted - metrics collection disabled
        # from consensus.consensus_coordinator import get_consensus_coordinator
        # coord = get_consensus_coordinator()
        #
        # # Get leaderboard snapshot
        # result.agent_leaderboard = coord.incentive_ledger.leaderboard(top_n=25)
        #
        # # Calculate synthetic PnL based on agent performance
        # total_pnl = 0.0
        # for agent in result.agent_leaderboard:
        #     total_pnl += agent.get("pnl", 0.0)
        #
        # result.total_pnl = total_pnl
        #
        # # Synthetic hit rate (would come from actual market resolutions)
        # if result.agent_leaderboard:
        #     accuracies = [a.get("accuracy", 0) for a in result.agent_leaderboard]
        #     result.hit_rate = sum(accuracies) / len(accuracies)
        logger.debug("Results collection disabled - consensus module deleted")
        result.agent_leaderboard = []
        result.total_pnl = 0.0
        result.hit_rate = 0.0
        
        result.resolved_markets = len(result.agent_leaderboard)
        result.total_markets = max(result.resolved_markets, 10)
        
        return result
    
    def cancel_active_run(self) -> None:
        """Cancel the currently active replay run."""
        if self._active_run:
            logger.info("Cancelling replay run %s", self._active_run)
            self._active_run = None
    
    def get_result(self, run_id: str) -> Optional[ReplayRunResult]:
        """Get a stored result by ID."""
        return self._results.get(run_id)
    
    def list_results(self, limit: int = 50) -> List[ReplayRunResult]:
        """List recent results."""
        sorted_results = sorted(
            self._results.values(),
            key=lambda r: r.start_time,
            reverse=True
        )
        return sorted_results[:limit]


# Singleton instance
_harness: Optional[HistoricalReplayHarness] = None


def get_replay_harness() -> HistoricalReplayHarness:
    """Get or create the global replay harness."""
    global _harness
    if _harness is None:
        _harness = HistoricalReplayHarness()
    return _harness


async def run_replay_comparison(
    start_time: float,
    end_time: float,
    market_filters: Optional[Dict[str, Any]] = None) -> ReplayComparison:
    """Convenience function to run a comparison."""
    harness = get_replay_harness()
    
    scenario = ReplayScenario(
        start_time=start_time,
        end_time=end_time,
        market_filters=market_filters or {},
        description=f"Replay {datetime.fromtimestamp(start_time, tz=timezone.utc)} to {datetime.fromtimestamp(end_time, tz=timezone.utc)}")
    
    return await harness.compare_runs(scenario)
