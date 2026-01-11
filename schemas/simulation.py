"""
SimulationReport Schema - Canonical simulation result structure.

Records the complete outcome of any simulation run, including
scenario parameters, results, and recommendations.

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class SimulationType(Enum):
    """Types of simulations."""
    INTENT_PREVIEW = "intent_preview"      # Preview single intent
    BACKTEST = "backtest"                  # Historical backtest
    MONTE_CARLO = "monte_carlo"            # Monte Carlo simulation
    STRESS_TEST = "stress_test"            # Stress testing
    SCENARIO = "scenario"                  # What-if scenario
    ARBITRAGE_PREVIEW = "arbitrage_preview" # Arbitrage opportunity preview
    PORTFOLIO_REBALANCE = "portfolio_rebalance"  # Rebalance preview


class SimulationStatus(Enum):
    """Status of a simulation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimulationOutcome(Enum):
    """Outcome recommendation from simulation."""
    PROCEED = "proceed"
    PROCEED_WITH_CAUTION = "proceed_with_caution"
    REDUCE_SIZE = "reduce_size"
    DO_NOT_PROCEED = "do_not_proceed"
    NEEDS_REVIEW = "needs_review"


@dataclass
class SimulationScenario:
    """A single scenario within a simulation."""
    scenario_id: str = field(default_factory=lambda: f"scen_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    
    # Scenario parameters
    price_change_pct: float = 0.0
    volatility_multiplier: float = 1.0
    liquidity_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    fee_multiplier: float = 1.0
    
    # Results
    simulated_pnl: float = 0.0
    simulated_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Risk metrics
    var_95: float = 0.0  # Value at Risk 95%
    var_99: float = 0.0  # Value at Risk 99%
    expected_shortfall: float = 0.0
    
    # Probability
    probability: float = 0.0  # Probability of this scenario
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "price_change_pct": self.price_change_pct,
            "volatility_multiplier": self.volatility_multiplier,
            "liquidity_multiplier": self.liquidity_multiplier,
            "slippage_multiplier": self.slippage_multiplier,
            "fee_multiplier": self.fee_multiplier,
            "simulated_pnl": self.simulated_pnl,
            "simulated_pnl_pct": self.simulated_pnl_pct,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "var_95": self.var_95,
            "var_99": self.var_99,
            "expected_shortfall": self.expected_shortfall,
            "probability": self.probability,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationScenario":
        return cls(
            scenario_id=data.get("scenario_id", f"scen_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            price_change_pct=data.get("price_change_pct", 0.0),
            volatility_multiplier=data.get("volatility_multiplier", 1.0),
            liquidity_multiplier=data.get("liquidity_multiplier", 1.0),
            slippage_multiplier=data.get("slippage_multiplier", 1.0),
            fee_multiplier=data.get("fee_multiplier", 1.0),
            simulated_pnl=data.get("simulated_pnl", 0.0),
            simulated_pnl_pct=data.get("simulated_pnl_pct", 0.0),
            max_drawdown=data.get("max_drawdown", 0.0),
            win_rate=data.get("win_rate", 0.0),
            sharpe_ratio=data.get("sharpe_ratio", 0.0),
            var_95=data.get("var_95", 0.0),
            var_99=data.get("var_99", 0.0),
            expected_shortfall=data.get("expected_shortfall", 0.0),
            probability=data.get("probability", 0.0),
        )


@dataclass
class SimulationReport:
    """
    Complete simulation report with all scenarios and recommendations.
    
    This is the canonical structure for any simulation in MERID.
    """
    
    # Identity
    report_id: str = field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:12]}")
    
    # Type and status
    sim_type: SimulationType = SimulationType.INTENT_PREVIEW
    status: SimulationStatus = SimulationStatus.PENDING
    
    # Subject
    intent_id: Optional[str] = None
    intent_hash: Optional[str] = None
    symbol: str = ""
    
    # Configuration
    initial_capital: float = 0.0
    position_size: float = 0.0
    leverage: int = 1
    
    # Time range (for backtests)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    data_points: int = 0
    
    # Scenarios
    scenarios: List[SimulationScenario] = field(default_factory=list)
    
    # Aggregate results
    expected_pnl: float = 0.0
    expected_pnl_pct: float = 0.0
    best_case_pnl: float = 0.0
    worst_case_pnl: float = 0.0
    probability_of_profit: float = 0.0
    probability_of_loss: float = 0.0
    
    # Risk metrics
    max_drawdown: float = 0.0
    var_95: float = 0.0
    var_99: float = 0.0
    expected_shortfall: float = 0.0
    risk_reward_ratio: float = 0.0
    
    # Performance metrics (for backtests)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # Recommendation
    outcome: SimulationOutcome = SimulationOutcome.NEEDS_REVIEW
    confidence: float = 0.0
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)
    
    # Timing
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_ms: float = 0.0
    
    # Metadata
    iterations: int = 0
    seed: Optional[int] = None
    notes: str = ""
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the report."""
        hash_data = {
            "report_id": self.report_id,
            "sim_type": self.sim_type.value,
            "intent_id": self.intent_id,
            "symbol": self.symbol,
            "created_at": self.created_at,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def add_scenario(self, scenario: SimulationScenario) -> None:
        """Add a scenario to the report."""
        self.scenarios.append(scenario)
    
    def calculate_aggregates(self) -> None:
        """Calculate aggregate metrics from scenarios."""
        if not self.scenarios:
            return
        
        # Weighted averages by probability
        total_prob = sum(s.probability for s in self.scenarios)
        if total_prob <= 0:
            total_prob = len(self.scenarios)
            for s in self.scenarios:
                s.probability = 1.0 / len(self.scenarios)
        
        self.expected_pnl = sum(s.simulated_pnl * s.probability for s in self.scenarios)
        self.expected_pnl_pct = sum(s.simulated_pnl_pct * s.probability for s in self.scenarios)
        
        # Best/worst case
        self.best_case_pnl = max(s.simulated_pnl for s in self.scenarios)
        self.worst_case_pnl = min(s.simulated_pnl for s in self.scenarios)
        
        # Probability of profit/loss
        profitable = [s for s in self.scenarios if s.simulated_pnl > 0]
        self.probability_of_profit = sum(s.probability for s in profitable)
        self.probability_of_loss = 1 - self.probability_of_profit
        
        # Risk metrics
        self.max_drawdown = max(s.max_drawdown for s in self.scenarios)
        self.var_95 = sum(s.var_95 * s.probability for s in self.scenarios)
        self.var_99 = sum(s.var_99 * s.probability for s in self.scenarios)
        
        # Risk/reward
        if self.worst_case_pnl != 0:
            self.risk_reward_ratio = abs(self.best_case_pnl / self.worst_case_pnl)
    
    def determine_outcome(self) -> SimulationOutcome:
        """Determine recommendation based on simulation results."""
        self.calculate_aggregates()
        
        # Check for red flags
        if self.probability_of_loss > 0.7:
            self.outcome = SimulationOutcome.DO_NOT_PROCEED
            self.reasoning = f"High probability of loss ({self.probability_of_loss:.1%})"
            self.warnings.append("Loss probability exceeds 70%")
            return self.outcome
        
        if self.max_drawdown > 0.20:  # 20% drawdown
            self.outcome = SimulationOutcome.REDUCE_SIZE
            self.reasoning = f"Max drawdown too high ({self.max_drawdown:.1%})"
            self.warnings.append("Max drawdown exceeds 20%")
            return self.outcome
        
        if self.risk_reward_ratio < 1.0:
            self.outcome = SimulationOutcome.PROCEED_WITH_CAUTION
            self.reasoning = f"Risk/reward ratio below 1:1 ({self.risk_reward_ratio:.2f})"
            self.warnings.append("Unfavorable risk/reward ratio")
            return self.outcome
        
        if self.probability_of_profit > 0.6 and self.risk_reward_ratio >= 1.5:
            self.outcome = SimulationOutcome.PROCEED
            self.reasoning = f"Favorable conditions: {self.probability_of_profit:.1%} win prob, {self.risk_reward_ratio:.2f} R:R"
            return self.outcome
        
        self.outcome = SimulationOutcome.PROCEED_WITH_CAUTION
        self.reasoning = "Mixed signals - manual review recommended"
        return self.outcome
    
    def finalize(self) -> None:
        """Finalize the simulation report."""
        self.status = SimulationStatus.COMPLETED
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.created_at) * 1000
        self.determine_outcome()
        
        # Set confidence based on data quality
        if self.iterations >= 1000:
            self.confidence = 0.9
        elif self.iterations >= 100:
            self.confidence = 0.7
        elif self.iterations >= 10:
            self.confidence = 0.5
        else:
            self.confidence = 0.3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "hash": self.compute_hash(),
            "sim_type": self.sim_type.value,
            "status": self.status.value,
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "symbol": self.symbol,
            "initial_capital": self.initial_capital,
            "position_size": self.position_size,
            "leverage": self.leverage,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "data_points": self.data_points,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "expected_pnl": self.expected_pnl,
            "expected_pnl_pct": self.expected_pnl_pct,
            "best_case_pnl": self.best_case_pnl,
            "worst_case_pnl": self.worst_case_pnl,
            "probability_of_profit": self.probability_of_profit,
            "probability_of_loss": self.probability_of_loss,
            "max_drawdown": self.max_drawdown,
            "var_95": self.var_95,
            "var_99": self.var_99,
            "expected_shortfall": self.expected_shortfall,
            "risk_reward_ratio": self.risk_reward_ratio,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "outcome": self.outcome.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "iterations": self.iterations,
            "seed": self.seed,
            "notes": self.notes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationReport":
        scenarios = [SimulationScenario.from_dict(s) for s in data.get("scenarios", [])]
        
        return cls(
            report_id=data.get("report_id", f"sim_{uuid.uuid4().hex[:12]}"),
            sim_type=SimulationType(data.get("sim_type", "intent_preview")),
            status=SimulationStatus(data.get("status", "pending")),
            intent_id=data.get("intent_id"),
            intent_hash=data.get("intent_hash"),
            symbol=data.get("symbol", ""),
            initial_capital=data.get("initial_capital", 0.0),
            position_size=data.get("position_size", 0.0),
            leverage=data.get("leverage", 1),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            data_points=data.get("data_points", 0),
            scenarios=scenarios,
            expected_pnl=data.get("expected_pnl", 0.0),
            expected_pnl_pct=data.get("expected_pnl_pct", 0.0),
            best_case_pnl=data.get("best_case_pnl", 0.0),
            worst_case_pnl=data.get("worst_case_pnl", 0.0),
            probability_of_profit=data.get("probability_of_profit", 0.0),
            probability_of_loss=data.get("probability_of_loss", 0.0),
            max_drawdown=data.get("max_drawdown", 0.0),
            var_95=data.get("var_95", 0.0),
            var_99=data.get("var_99", 0.0),
            expected_shortfall=data.get("expected_shortfall", 0.0),
            risk_reward_ratio=data.get("risk_reward_ratio", 0.0),
            total_trades=data.get("total_trades", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            win_rate=data.get("win_rate", 0.0),
            profit_factor=data.get("profit_factor", 0.0),
            sharpe_ratio=data.get("sharpe_ratio", 0.0),
            sortino_ratio=data.get("sortino_ratio", 0.0),
            calmar_ratio=data.get("calmar_ratio", 0.0),
            outcome=SimulationOutcome(data.get("outcome", "needs_review")),
            confidence=data.get("confidence", 0.0),
            reasoning=data.get("reasoning", ""),
            warnings=data.get("warnings", []),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms", 0.0),
            iterations=data.get("iterations", 0),
            seed=data.get("seed"),
            notes=data.get("notes", ""),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "SimulationReport":
        return cls.from_dict(json.loads(json_str))
