"""
Backtest Harness for 15m Pipeline Orchestrator

Provides deterministic replay and stress testing for the 15m feature graph.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from merid.pipelines.feature_bundle import FifteenMinuteFeatureBundle, TradeDecision
from merid.pipelines.pipeline_schema import PipelineConfig, PipelineRegistry
from merid.pipelines.kalshi_15m_orchestrator import Kalshi15mOrchestrator
from utils.logger import get_logger

logger = get_logger("merid.pipelines.backtest_harness")


@dataclass
class BacktestScenario:
    """Definition of a backtest scenario."""
    name: str
    description: str
    start_date: datetime
    end_date: datetime
    asset: str
    scenarios: List[str]  # e.g., ["high_volatility", "data_outage", "agent_failure"]


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    scenario_name: str
    total_cycles: int
    decisions_generated: int
    decisions_executed: int
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    agent_failure_rates: Dict[str, float]
    feature_sparsity: Dict[str, float]
    timing_stats: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "total_cycles": self.total_cycles,
            "decisions_generated": self.decisions_generated,
            "decisions_executed": self.decisions_executed,
            "total_pnl": self.total_pnl,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "agent_failure_rates": self.agent_failure_rates,
            "feature_sparsity": self.feature_sparsity,
            "timing_stats": self.timing_stats,
        }


class HistoricalDataProvider:
    """
    Provider of historical market data for backtesting.
    
    In production, this would read from a database or parquet files.
    For now, provides stub implementations.
    """
    
    def __init__(self):
        self.data_cache: Dict[str, Any] = {}
    
    async def get_15m_candles(
        self,
        asset: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Get 15m OHLCV candles for an asset.
        
        Args:
            asset: Asset symbol
            start: Start datetime
            end: End datetime
            
        Returns:
            List of candle dictionaries
        """
        # Stub implementation
        return []
    
    async def get_orderbook_snapshot(
        self,
        asset: str,
        timestamp: datetime,
    ) -> Dict[str, Any]:
        """Get orderbook snapshot at a specific timestamp."""
        # Stub implementation
        return {}
    
    async def stub_feature_agent_output(
        self,
        agent_name: str,
        asset: str,
        timestamp: datetime,
    ) -> Dict[str, float]:
        """
        Generate realistic stub output for external feature agents.
        
        Used for agents that depend on external APIs (news, sentiment, etc.)
        where historical data is not available.
        """
        # Generate realistic distributions based on agent type
        if "sentiment" in agent_name.lower():
            return {
                "headline_sentiment": 0.5,  # Neutral
                "news_flow_intensity": 0.3,
                "event_risk_flag": 0.0,
            }
        elif "vol" in agent_name.lower():
            return {
                "volatility_regime": 1.0,
                "vol_forecast": 0.02,
            }
        else:
            return {}


class BacktestHarness:
    """
    Harness for backtesting the 15m pipeline orchestrator.
    
    Provides:
    - Deterministic replay with historical data
    - Scenario-based stress testing
    - Performance metrics per agent and namespace
    - Graceful degradation testing
    """
    
    def __init__(
        self,
        orchestrator: Kalshi15mOrchestrator,
        data_provider: HistoricalDataProvider,
    ):
        self.orchestrator = orchestrator
        self.data_provider = data_provider
    
    async def run_backtest(
        self,
        scenario: BacktestScenario,
    ) -> BacktestResult:
        """
        Run a backtest scenario.
        
        Args:
            scenario: Backtest scenario definition
            
        Returns:
            BacktestResult with performance metrics
        """
        logger.info(f"Starting backtest: {scenario.name}")
        
        result = BacktestResult(
            scenario_name=scenario.name,
            total_cycles=0,
            decisions_generated=0,
            decisions_executed=0,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            agent_failure_rates={},
            feature_sparsity={},
            timing_stats={},
        )
        
        # Get historical candles
        candles = await self.data_provider.get_15m_candles(
            scenario.asset,
            scenario.start_date,
            scenario.end_date,
        )
        
        logger.info(f"Loaded {len(candles)} candles for backtest")
        
        # Replay each 15m bar
        for candle in candles:
            result.total_cycles += 1
            
            # Build context from candle
            context = self._build_context_from_candle(candle, scenario)
            
            # Apply scenario modifiers
            context = self._apply_scenario_modifiers(context, scenario.scenarios)
            
            try:
                # Run pipeline
                decision = await self.orchestrator.run_pipeline(
                    pipeline_id=f"{scenario.asset.lower()}_15m_pipeline",
                    context=context,
                    account_state={},  # Simplified for backtest
                )
                
                if decision:
                    result.decisions_generated += 1
                    
                    # Simulate execution (stub)
                    # In production, this would use historical orderbook data
                    result.decisions_executed += 1
                    
                    # Simulate PnL (stub)
                    # In production, this would use actual trade outcomes
                    result.total_pnl += self._simulate_pnl(decision, candle)
            
            except Exception as e:
                logger.error(f"Backtest cycle error: {e}")
                # Track agent failure rates
                continue
        
        # Compute metrics
        if result.total_cycles > 0:
            result.sharpe_ratio = self._compute_sharpe(result)
            result.max_drawdown = self._compute_drawdown(result)
        
        # Extract health metrics from orchestrator
        if self.orchestrator.observability:
            health_summary = self.orchestrator.observability.get_health_summary()
            result.feature_sparsity = health_summary.get("feature_sparsity", {})
        
        logger.info(f"Backtest completed: {scenario.name}")
        logger.info(f"  Cycles: {result.total_cycles}, Decisions: {result.decisions_generated}")
        logger.info(f"  PnL: {result.total_pnl:.2f}, Sharpe: {result.sharpe_ratio:.2f}")
        
        return result
    
    def _build_context_from_candle(
        self,
        candle: Dict[str, Any],
        scenario: BacktestScenario,
    ) -> Dict[str, Any]:
        """Build execution context from historical candle."""
        return {
            "asset": scenario.asset,
            "timestamp": candle.get("timestamp"),
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": candle.get("close"),
            "volume": candle.get("volume"),
        }
    
    def _apply_scenario_modifiers(
        self,
        context: Dict[str, Any],
        scenario_types: List[str],
    ) -> Dict[str, Any]:
        """Apply scenario-specific modifiers to context."""
        modified_context = context.copy()
        
        for scenario_type in scenario_types:
            if scenario_type == "high_volatility":
                # Increase volatility by 2x
                modified_context["high"] *= 1.5
                modified_context["low"] *= 0.5
            elif scenario_type == "data_outage":
                # Simulate missing data
                modified_context["volume"] = 0
            elif scenario_type == "agent_failure":
                # This would be handled by the orchestrator's error handling
                pass
        
        return modified_context
    
    def _simulate_pnl(
        self,
        decision: TradeDecision,
        candle: Dict[str, Any],
    ) -> float:
        """Simulate PnL for a decision (stub)."""
        # In production, this would use actual trade outcomes
        # For now, return a small random value
        import random
        return random.uniform(-0.01, 0.02)
    
    def _compute_sharpe(self, result: BacktestResult) -> float:
        """Compute Sharpe ratio (stub)."""
        # In production, this would use actual PnL series
        return result.total_pnl / max(result.total_cycles, 1) * 100
    
    def _compute_drawdown(self, result: BacktestResult) -> float:
        """Compute max drawdown (stub)."""
        # In production, this would use actual PnL series
        return abs(result.total_pnl) * 0.5


async def run_stress_tests(
    orchestrator: Kalshi15mOrchestrator,
    asset: str = "BTC",
) -> Dict[str, BacktestResult]:
    """
    Run standard stress test scenarios.
    
    Args:
        orchestrator: Configured orchestrator
        asset: Asset to test
        
    Returns:
        Dict mapping scenario names to results
    """
    data_provider = HistoricalDataProvider()
    harness = BacktestHarness(orchestrator, data_provider)
    
    scenarios = [
        BacktestScenario(
            name="normal_conditions",
            description="Normal market conditions",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset=asset,
            scenarios=[],
        ),
        BacktestScenario(
            name="high_volatility",
            description="High volatility stress test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset=asset,
            scenarios=["high_volatility"],
        ),
        BacktestScenario(
            name="data_outage",
            description="Data outage stress test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset=asset,
            scenarios=["data_outage"],
        ),
    ]
    
    results = {}
    for scenario in scenarios:
        result = await harness.run_backtest(scenario)
        results[scenario.name] = result
    
    return results
