"""Replay/grading schema for MarketOpinion → Kalshi execution pipeline.

This module provides:
1. ApprovedOpinion record: Serializable replay snapshot of consensus decisions
2. GradingPolicy interface: Compute per-opinion metrics (Brier, realized edge, PnL)
3. ReplayRunner: Feed historical opinion streams through the pipeline
4. Grading observers: Attach to MarketOpinionPipelineMachine for metric collection

Design principles:
- Replay records are immutable, serializable, and versioned
- Grading policies are pure functions (opinion + outcome → metrics)
- The ReplayRunner reuses the same MarketOpinionPipelineMachine for consistency
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Callable
from uuid import uuid4

import pytest
from hypothesis import given, strategies as st, settings

# Import existing types
from merid.prediction.market_opinion import (
    MarketOpinion,
    OpinionSource,
    OpinionDirection,
    ConsensusOpinion,
)
from merid.swarm.consensus_aggregator import ConsensusView, ConsensusStatus


# ── Replay Record Schema ─────────────────────────────────────────────────────

class ReplayRecordVersion(str, Enum):
    """Version of the replay record schema for forward compatibility."""
    V1 = "1.0.0"


@dataclass(frozen=True)
class ApprovedOpinionRecord:
    """
    Immutable replay record of a consensus-approved MarketOpinion.
    
    This is the "truth" that gets dumped from live runs and replayed
    for backtesting/grading. Frozen=True ensures immutability.
    
    Fields mirror MarketOpinion and ConsensusOpinion for fidelity.
    """
    # Identity
    record_id: str = field(default_factory=lambda: str(uuid4()))
    version: str = field(default=ReplayRecordVersion.V1.value)
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Market identification
    market_id: str = ""  # Full Kalshi ticker (KXBTC-15M)
    asset_id: str = ""   # BTC, ETH, etc.
    tenor: str = ""      # 15m, 1h, daily, weekly
    expiry_ts: Optional[str] = None  # Contract expiry timestamp
    
    # Opinion content (from MarketOpinion)
    direction: str = ""           # yes/no/neutral
    edge_bps: float = 0.0         # Edge in basis points (1 bp = 0.01%)
    confidence: float = 0.0       # 0-1 confidence
    sim_only: bool = True         # Was this sim-only at approval time?
    
    # Consensus metadata (from ConsensusOpinion)
    consensus_sources: List[str] = field(default_factory=list)  # [news, momentum, rti]
    consensus_agents: int = 0     # Number of agents in consensus
    consensus_confidence: float = 0.0  # Aggregated confidence
    
    # Risk sizing (from SIZE step)
    size_band: str = "base"       # small/base/large
    intended_contracts: int = 0   # Sized contract count
    intended_notional_usd: float = 0.0  # Sized notional
    
    # Source attribution
    originating_source: str = ""  # Primary source (news_sentiment, momentum, etc.)
    strategy_version: str = ""    # Version tag for A/B testing
    
    # Execution outcome (filled in after settlement)
    executed: Optional[bool] = None        # Was order actually placed?
    execution_price_cents: Optional[int] = None  # Fill price if executed
    settlement_price_cents: Optional[int] = None   # Final settlement (100 = YES, 0 = NO)
    realized_pnl_cents: Optional[float] = None     # Actual PnL in cents
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_market_opinion(
        cls,
        opinion: MarketOpinion,
        consensus: ConsensusOpinion,
        size_band: str = "base",
        intended_contracts: int = 0,
    ) -> "ApprovedOpinionRecord":
        """Build record from MarketOpinion + ConsensusOpinion."""
        return cls(
            market_id=consensus.ticker,
            asset_id=consensus.asset,
            tenor=consensus.timeframe,
            direction=consensus.direction.value,
            edge_bps=consensus.implied_probability * 10000,  # Convert to bps
            confidence=consensus.confidence,
            sim_only=consensus.sim_only,
            consensus_sources=[s.value for s in consensus.contributing_sources],
            consensus_agents=consensus.contributing_opinion_count,
            consensus_confidence=consensus.confidence,
            size_band=size_band,
            intended_contracts=intended_contracts,
            originating_source=opinion.source.value,
        )
    
    @property
    def outcome_realized(self) -> Optional[bool]:
        """Determine if the prediction was correct based on settlement."""
        if self.settlement_price_cents is None:
            return None
        
        # Settlement at 100 = YES, 0 = NO (Kalshi binary contracts)
        if self.direction == "yes":
            return self.settlement_price_cents == 100
        elif self.direction == "no":
            return self.settlement_price_cents == 0
        else:
            return None


# ── GradingPolicy Interface ───────────────────────────────────────────────────

class GradingMetrics:
    """Container for all metrics computed by a GradingPolicy."""
    
    def __init__(self):
        # Calibration metrics
        self.brier_score: Optional[float] = None  # (p - o)^2
        self.log_loss: Optional[float] = None     # -[o*log(p) + (1-o)*log(1-p)]
        
        # Edge metrics
        self.predicted_edge_bps: float = 0.0
        self.realized_edge_bps: Optional[float] = None
        self.edge_error_bps: Optional[float] = None  # predicted - realized
        
        # PnL metrics
        self.realized_pnl_cents: Optional[float] = None
        self.roi_pct: Optional[float] = None
        
        # Decision quality
        self.correct_direction: Optional[bool] = None  # Did we get direction right?
        self.profitability: Optional[bool] = None    # Did we make money?
        
        # Kelly/economic metrics
        self.kelly_fraction: float = 0.0
        self.kelly_regret: Optional[float] = None  # Optimal - actual


class GradingPolicy(ABC):
    """
    Abstract grading policy for ApprovedOpinionRecords.
    
    Implementations compute metrics given:
    - The opinion record (direction, confidence, edge)
    - The realized outcome (settlement price)
    - Optional: price path for path-dependent metrics
    """
    
    @abstractmethod
    def grade(
        self,
        record: ApprovedOpinionRecord,
        settlement_price_cents: int,  # 0 or 100 for binary Kalshi contracts
        price_path: Optional[List[float]] = None,
    ) -> GradingMetrics:
        """
        Grade an opinion given its realized outcome.
        
        Args:
            record: The opinion record with predictions
            settlement_price_cents: Final settlement price (0 or 100 for binary)
            price_path: Optional list of mid prices over contract lifetime
            
        Returns:
            GradingMetrics with all computed metrics
        """
        pass


class BinaryContractGradingPolicy(GradingPolicy):
    """
    Standard grading for Kalshi binary contracts (YES/NO).
    
    Computes:
    - Brier score: (p - outcome)^2
    - Log loss: -[outcome*log(p) + (1-outcome)*log(1-p)]
    - Realized edge vs predicted edge
    - PnL based on execution
    """
    
    def __init__(self, fee_bps: float = 10.0):  # Kalshi default ~0.1% per side
        self.fee_bps = fee_bps
    
    def grade(
        self,
        record: ApprovedOpinionRecord,
        settlement_price_cents: int,
        price_path: Optional[List[float]] = None,
    ) -> GradingMetrics:
        """Grade a binary contract opinion."""
        metrics = GradingMetrics()
        
        # Convert confidence to probability (0-1)
        p = record.confidence
        
        # Outcome: 1 for YES (100), 0 for NO (0)
        outcome = 1.0 if settlement_price_cents == 100 else 0.0
        
        # Calibration metrics
        metrics.brier_score = (p - outcome) ** 2
        
        # Avoid log(0)
        p_clipped = max(0.0001, min(0.9999, p))
        metrics.log_loss = -(outcome * __import__('math').log(p_clipped) + 
                            (1 - outcome) * __import__('math').log(1 - p_clipped))
        
        # Edge metrics
        metrics.predicted_edge_bps = record.edge_bps
        
        # Realized edge: if we were right, edge = (100 - entry) - fees
        # If wrong, edge = -entry - fees
        if record.executed and record.execution_price_cents is not None:
            entry = record.execution_price_cents
            
            if record.direction == "yes":
                # Long YES: profit if settlement=100
                gross_pnl = settlement_price_cents - entry
            elif record.direction == "no":
                # Long NO: profit if settlement=0 (we paid 100-entry for NO)
                gross_pnl = (100 - settlement_price_cents) - entry
            else:
                gross_pnl = 0
            
            # Apply fees (both sides)
            fees = self.fee_bps * 2  # Entry + exit
            net_pnl = gross_pnl - fees
            
            metrics.realized_pnl_cents = net_pnl
            metrics.realized_edge_bps = (net_pnl / 100.0) * 10000  # Convert to bps
            metrics.edge_error_bps = metrics.predicted_edge_bps - metrics.realized_edge_bps
            metrics.roi_pct = (net_pnl / entry * 100) if entry > 0 else 0
        
        # Direction correctness
        if record.direction == "yes":
            metrics.correct_direction = settlement_price_cents == 100
        elif record.direction == "no":
            metrics.correct_direction = settlement_price_cents == 0
        else:
            metrics.correct_direction = None
        
        metrics.profitability = (metrics.realized_pnl_cents or 0) > 0
        
        # Kelly metrics
        # Kelly fraction = p - (1-p)/b where b = odds received
        # Simplified: for Kalshi at 50c, b ≈ 1, so Kelly ≈ 2p - 1
        metrics.kelly_fraction = 2 * p - 1
        
        # Regret: if we didn't bet full Kelly, how much did we leave on table?
        if metrics.realized_pnl_cents is not None and metrics.kelly_fraction > 0:
            optimal_contracts = int(metrics.kelly_fraction * 100)  # Assuming 100 unit bankroll
            actual_contracts = record.intended_contracts
            if optimal_contracts > actual_contracts:
                # We underbet
                missed_pnl = (optimal_contracts - actual_contracts) * (metrics.realized_pnl_cents / max(1, actual_contracts))
                metrics.kelly_regret = missed_pnl
        
        return metrics


# ── ReplayRunner ──────────────────────────────────────────────────────────────

@dataclass
class ReplayConfig:
    """Configuration for a replay run."""
    grading_policy: GradingPolicy = field(default_factory=lambda: BinaryContractGradingPolicy())
    max_records: Optional[int] = None
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    tickers_filter: Optional[List[str]] = None
    sources_filter: Optional[List[str]] = None


@dataclass
class ReplayResult:
    """Results from a replay run."""
    total_records: int
    processed: int
    skipped: int
    metrics: List[tuple[ApprovedOpinionRecord, GradingMetrics]]
    
    # Aggregated stats
    avg_brier: float = 0.0
    total_pnl_cents: float = 0.0
    win_rate: float = 0.0
    sharpe: float = 0.0
    
    def to_summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        if not self.metrics:
            return {"error": "No metrics collected"}
        
        briers = [m.brier_score for _, m in self.metrics if m.brier_score is not None]
        pnls = [m.realized_pnl_cents for _, m in self.metrics if m.realized_pnl_cents is not None]
        correct = sum(1 for _, m in self.metrics if m.correct_direction)
        profitable = sum(1 for _, m in self.metrics if m.profitability)
        
        return {
            "total_records": self.total_records,
            "processed": self.processed,
            "avg_brier_score": sum(briers) / len(briers) if briers else 0,
            "total_pnl_cents": sum(pnls) if pnls else 0,
            "win_rate": correct / len(self.metrics) if self.metrics else 0,
            "profitable_rate": profitable / len(self.metrics) if self.metrics else 0,
            "records_with_pnl": len(pnls),
        }


class ReplayRunner:
    """
    Replay historical ApprovedOpinionRecords through grading policies.
    
    Usage:
        runner = ReplayRunner()
        config = ReplayConfig(max_records=1000)
        result = runner.replay_file("path/to/records.jsonl", config)
        print(result.to_summary())
    """
    
    def __init__(self):
        self._grading_policies: Dict[str, GradingPolicy] = {}
    
    def register_policy(self, name: str, policy: GradingPolicy) -> None:
        """Register a grading policy by name."""
        self._grading_policies[name] = policy
    
    def replay_file(
        self,
        filepath: str,
        config: ReplayConfig,
        settlement_lookup: Dict[str, int],  # market_id -> settlement_price_cents
    ) -> ReplayResult:
        """
        Replay records from a JSONL file.
        
        Args:
            filepath: Path to JSONL file with ApprovedOpinionRecords
            config: Replay configuration
            settlement_lookup: Map of market_id to final settlement price
            
        Returns:
            ReplayResult with all grading metrics
        """
        metrics: List[tuple[ApprovedOpinionRecord, GradingMetrics]] = []
        processed = 0
        skipped = 0
        
        path = Path(filepath)
        if not path.exists():
            return ReplayResult(total_records=0, processed=0, skipped=0, metrics=[])
        
        with open(path, 'r') as f:
            for line in f:
                if config.max_records and processed >= config.max_records:
                    break
                
                try:
                    data = json.loads(line)
                    record = ApprovedOpinionRecord(**data)
                    
                    # Apply filters
                    if config.tickers_filter and record.market_id not in config.tickers_filter:
                        skipped += 1
                        continue
                    if config.sources_filter and record.originating_source not in config.sources_filter:
                        skipped += 1
                        continue
                    
                    # Look up settlement
                    settlement = settlement_lookup.get(record.market_id)
                    if settlement is None:
                        skipped += 1
                        continue
                    
                    # Grade
                    grading_metrics = config.grading_policy.grade(record, settlement)
                    metrics.append((record, grading_metrics))
                    processed += 1
                    
                except Exception as exc:
                    skipped += 1
                    continue
        
        # Compute aggregated stats
        result = ReplayResult(
            total_records=processed + skipped,
            processed=processed,
            skipped=skipped,
            metrics=metrics,
        )
        
        # Calculate aggregates
        if metrics:
            briers = [m.brier_score for _, m in metrics if m.brier_score is not None]
            result.avg_brier = sum(briers) / len(briers) if briers else 0
            
            pnls = [m.realized_pnl_cents for _, m in metrics if m.realized_pnl_cents is not None]
            result.total_pnl_cents = sum(pnls) if pnls else 0
            
            correct = sum(1 for _, m in metrics if m.correct_direction)
            result.win_rate = correct / len(metrics)
        
        return result
    
    def replay_stream(
        self,
        records: List[ApprovedOpinionRecord],
        config: ReplayConfig,
        settlement_lookup: Dict[str, int],
    ) -> ReplayResult:
        """Replay from an in-memory list of records."""
        metrics: List[tuple[ApprovedOpinionRecord, GradingMetrics]] = []
        
        for record in records:
            if config.max_records and len(metrics) >= config.max_records:
                break
            
            # Apply filters
            if config.tickers_filter and record.market_id not in config.tickers_filter:
                continue
            if config.sources_filter and record.originating_source not in config.sources_filter:
                continue
            
            # Look up settlement
            settlement = settlement_lookup.get(record.market_id)
            if settlement is None:
                continue
            
            # Grade
            grading_metrics = config.grading_policy.grade(record, settlement)
            metrics.append((record, grading_metrics))
        
        return ReplayResult(
            total_records=len(records),
            processed=len(metrics),
            skipped=len(records) - len(metrics),
            metrics=metrics,
        )


# ── Grading Observers for MarketOpinionPipelineMachine ────────────────────────

class GradingObserver:
    """
    Observer that attaches to MarketOpinionPipelineMachine to collect grading metrics.
    
    Usage:
        observer = GradingObserver(BinaryContractGradingPolicy())
        machine = MarketOpinionPipelineMachine()
        machine.add_observer(observer)
        # ... run machine ...
        report = observer.generate_report()
    """
    
    def __init__(self, policy: GradingPolicy):
        self.policy = policy
        self.records: List[ApprovedOpinionRecord] = []
        self.grades: List[GradingMetrics] = []
        self._pending_outcomes: Dict[str, int] = {}  # market_id -> settlement
    
    def on_opinion_approved(self, record: ApprovedOpinionRecord) -> None:
        """Called when an opinion is approved by the pipeline."""
        self.records.append(record)
    
    def record_outcome(self, market_id: str, settlement_price_cents: int) -> None:
        """Record the realized outcome for a market."""
        self._pending_outcomes[market_id] = settlement_price_cents
        
        # Try to grade any pending records for this market
        for record in self.records:
            if record.market_id == market_id and record.settlement_price_cents is None:
                # Mutate to add settlement (dataclass is frozen, so we create new)
                settled_record = ApprovedOpinionRecord(
                    **{**record.__dict__, "settlement_price_cents": settlement_price_cents}
                )
                metrics = self.policy.grade(settled_record, settlement_price_cents)
                self.grades.append(metrics)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate grading report for all observed opinions."""
        if not self.grades:
            return {"status": "no_grades_collected"}
        
        briers = [g.brier_score for g in self.grades if g.brier_score is not None]
        pnls = [g.realized_pnl_cents for g in self.grades if g.realized_pnl_cents is not None]
        correct = sum(1 for g in self.grades if g.correct_direction)
        
        # Brier score interpretation
        # 0 = perfect, 0.25 = random (for binary), 1 = worst
        avg_brier = sum(briers) / len(briers) if briers else 0
        calibration_quality = "good" if avg_brier < 0.1 else "fair" if avg_brier < 0.2 else "poor"
        
        return {
            "total_opinions": len(self.records),
            "graded_opinions": len(self.grades),
            "avg_brier_score": avg_brier,
            "calibration_quality": calibration_quality,
            "total_pnl_cents": sum(pnls) if pnls else 0,
            "win_rate": correct / len(self.grades) if self.grades else 0,
            "by_source": self._breakdown_by_source(),
        }
    
    def _breakdown_by_source(self) -> Dict[str, Dict[str, Any]]:
        """Break down metrics by originating source."""
        by_source: Dict[str, List[GradingMetrics]] = {}
        
        for record, grade in zip(self.records, self.grades):
            source = record.originating_source
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(grade)
        
        result = {}
        for source, grades in by_source.items():
            briers = [g.brier_score for g in grades if g.brier_score is not None]
            pnls = [g.realized_pnl_cents for g in grades if g.realized_pnl_cents is not None]
            correct = sum(1 for g in grades if g.correct_direction)
            
            result[source] = {
                "count": len(grades),
                "avg_brier": sum(briers) / len(briers) if briers else 0,
                "total_pnl_cents": sum(pnls) if pnls else 0,
                "win_rate": correct / len(grades) if grades else 0,
            }
        
        return result


# ── Tests for Replay/Grading ────────────────────────────────────────────────

class TestApprovedOpinionRecord:
    """Tests for the replay record schema."""
    
    def test_record_is_frozen(self):
        """Records should be immutable."""
        record = ApprovedOpinionRecord(market_id="KXBTC-15M", direction="yes")
        
        with pytest.raises(Exception):  # FrozenInstanceError
            record.market_id = "KXETH-15M"
    
    def test_outcome_realized_property(self):
        """Test outcome_realized property logic."""
        # YES direction, settlement at 100 = correct
        record_yes = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            settlement_price_cents=100,
        )
        assert record_yes.outcome_realized is True
        
        # YES direction, settlement at 0 = incorrect
        record_yes_loss = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            settlement_price_cents=0,
        )
        assert record_yes_loss.outcome_realized is False
        
        # NO direction, settlement at 0 = correct
        record_no = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="no",
            settlement_price_cents=0,
        )
        assert record_no.outcome_realized is True
        
        # No settlement = None
        record_pending = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            settlement_price_cents=None,
        )
        assert record_pending.outcome_realized is None


class TestBinaryContractGradingPolicy:
    """Tests for the binary contract grading policy."""
    
    def test_perfect_prediction_zero_brier(self):
        """Perfect prediction should have Brier score of 0."""
        policy = BinaryContractGradingPolicy()
        record = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            confidence=1.0,
            edge_bps=500,  # 5% edge
            executed=True,
            execution_price_cents=50,
        )
        
        metrics = policy.grade(record, settlement_price_cents=100)
        
        assert metrics.brier_score == 0.0  # (1.0 - 1.0)^2 = 0
        assert metrics.correct_direction is True
        assert metrics.realized_pnl_cents is not None
        assert metrics.realized_pnl_cents > 0  # Made money
    
    def test_worst_prediction_high_brier(self):
        """Worst prediction (100% confident wrong) should have Brier score of 1."""
        policy = BinaryContractGradingPolicy()
        record = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            confidence=1.0,  # 100% confident YES
            edge_bps=500,
            executed=True,
            execution_price_cents=50,
        )
        
        # But settlement is NO (0)
        metrics = policy.grade(record, settlement_price_cents=0)
        
        assert metrics.brier_score == 1.0  # (1.0 - 0.0)^2 = 1
        assert metrics.correct_direction is False
        assert metrics.realized_pnl_cents is not None
        assert metrics.realized_pnl_cents < 0  # Lost money
    
    def test_uncertain_prediction_moderate_brier(self):
        """Uncertain prediction (50%) should have Brier score of 0.25 regardless of outcome."""
        policy = BinaryContractGradingPolicy()
        record = ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            direction="yes",
            confidence=0.5,  # 50% confidence
        )
        
        # Outcome YES
        metrics_yes = policy.grade(record, settlement_price_cents=100)
        assert metrics_yes.brier_score == 0.25  # (0.5 - 1.0)^2 = 0.25
        
        # Outcome NO
        metrics_no = policy.grade(record, settlement_price_cents=0)
        assert metrics_no.brier_score == 0.25  # (0.5 - 0.0)^2 = 0.25


class TestReplayRunner:
    """Tests for the ReplayRunner."""
    
    def test_replay_stream_basic(self):
        """Basic replay of a stream of records."""
        records = [
            ApprovedOpinionRecord(
                market_id="KXBTC-15M",
                direction="yes",
                confidence=0.7,
                executed=True,
                execution_price_cents=50,
            ),
            ApprovedOpinionRecord(
                market_id="KXETH-15M",
                direction="no",
                confidence=0.6,
                executed=True,
                execution_price_cents=45,
            ),
        ]
        
        settlements = {
            "KXBTC-15M": 100,  # YES won
            "KXETH-15M": 0,    # NO won
        }
        
        runner = ReplayRunner()
        config = ReplayConfig()
        result = runner.replay_stream(records, config, settlements)
        
        assert result.processed == 2
        assert result.total_pnl_cents > 0  # Both won
        assert result.win_rate == 1.0


# ── Example Usage Script ───────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example: Create and grade some sample opinions
    
    print("=" * 60)
    print("Replay/Grading Example")
    print("=" * 60)
    
    # Create sample records
    records = [
        ApprovedOpinionRecord(
            market_id="KXBTC-15M",
            asset_id="BTC",
            tenor="15m",
            direction="yes",
            confidence=0.75,
            edge_bps=300,
            originating_source="news_sentiment",
            executed=True,
            execution_price_cents=55,
            settlement_price_cents=100,  # Won
            realized_pnl_cents=35.0,  # (100 - 55) - fees
        ),
        ApprovedOpinionRecord(
            market_id="KXETH-15M",
            asset_id="ETH",
            tenor="15m",
            direction="yes",
            confidence=0.60,
            edge_bps=200,
            originating_source="momentum",
            executed=True,
            execution_price_cents=60,
            settlement_price_cents=0,  # Lost
            realized_pnl_cents=-70.0,  # (0 - 60) - fees
        ),
    ]
    
    # Grade them
    policy = BinaryContractGradingPolicy()
    
    for record in records:
        metrics = policy.grade(record, record.settlement_price_cents or 0)
        print(f"\nMarket: {record.market_id}")
        print(f"  Direction: {record.direction.upper()} @ {record.confidence:.0%} confidence")
        print(f"  Outcome: {'✅ Correct' if metrics.correct_direction else '❌ Wrong'}")
        print(f"  Brier Score: {metrics.brier_score:.4f}")
        print(f"  PnL: {metrics.realized_pnl_cents:+.1f}¢")
        print(f"  ROI: {metrics.roi_pct:+.1f}%")
    
    print("\n" + "=" * 60)
    print("Run pytest for full test suite")
    print("=" * 60)
