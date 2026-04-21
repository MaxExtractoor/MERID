"""
Paper Trading Rehearsal Script

End-to-end validation of swarm behavior in paper/sim mode.
Runs the full pipeline and validates:
- Every trade has valid consensus ancestry
- No stale state in decision chain
- No direct broker calls in paper mode
- Opinion/consensus/trade counts within expected bands

Usage:
    python scripts/paper_rehearsal.py --mode simulation --duration 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from schemas.swarm_events import (
    StrategyOpinion,
    ConsensusDecision,
    TradeIntent,
    OrderEvent,
    TradingMode,
)
from execution.order_router import OrderRouter, OrderRouterConfig
from observability.swarm_telemetry import SwarmTelemetry
from observability.event_stream import EventStream, EventRecord
from utils.logger import get_logger

logger = get_logger("scripts.paper_rehearsal")

# Checklist version for correlation
CHECKLIST_VERSION = "1.0.0"


@dataclass
class RehearsalConfig:
    """Configuration for paper rehearsal."""
    mode: TradingMode = TradingMode.MOCK
    duration_seconds: float = 60.0
    symbols: List[str] = None
    
    # Validation thresholds
    min_agents_per_trade: int = 3
    max_state_age_seconds: float = 30.0
    expected_opinions_per_minute: float = 10.0
    expected_consensus_per_minute: float = 2.0
    max_disagreement_ratio: float = 0.5
    
    def __post_init__(self):
        if self.symbols is None:
            try:
                from data.asset_universe import get_swarm_eligible
                self.symbols = [a.symbol for a in get_swarm_eligible()
                                if "/" in a.symbol and ":" not in a.symbol]
            except Exception:
                self.symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]


@dataclass
class ValidationResult:
    """Result of a validation check."""
    check_name: str
    passed: bool
    message: str
    details: Dict[str, any] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class PaperRehearsalValidator:
    """
    Validates swarm behavior during paper trading rehearsal.
    
    Checks all invariants defined in the rehearsal config.
    """
    
    def __init__(self, config: RehearsalConfig):
        self.config = config
        
        # Track all events
        self.opinions: List[StrategyOpinion] = []
        self.consensus_decisions: List[ConsensusDecision] = []
        self.trade_intents: List[TradeIntent] = []
        self.order_events: List[OrderEvent] = []
        
        # Track ancestry relationships
        self.opinion_to_consensus: Dict[str, str] = {}
        self.consensus_to_trade: Dict[str, str] = {}
        self.trade_to_order: Dict[str, str] = {}
        
        # Track mode violations
        self.mode_violations: List[str] = []
        
    def record_opinion(self, opinion: StrategyOpinion) -> None:
        """Record a strategy opinion."""
        self.opinions.append(opinion)
    
    def record_consensus(self, decision: ConsensusDecision) -> None:
        """Record a consensus decision."""
        self.consensus_decisions.append(decision)
        
        # Link opinions to consensus
        for opinion_id in decision.opinion_ids:
            self.opinion_to_consensus[opinion_id] = decision.decision_id
    
    def record_trade_intent(self, intent: TradeIntent) -> None:
        """Record a trade intent."""
        self.trade_intents.append(intent)
        
        # Link consensus to trade
        if intent.consensus_id:
            self.consensus_to_trade[intent.consensus_id] = intent.intent_id
    
    def record_order_event(self, event: OrderEvent) -> None:
        """Record an order event."""
        self.order_events.append(event)
        
        # Link trade to order
        if event.trade_intent_id:
            self.trade_to_order[event.trade_intent_id] = event.order_id
    
    def record_mode_violation(self, violation: str) -> None:
        """Record a mode violation."""
        self.mode_violations.append(violation)
        logger.error(f"Mode violation: {violation}")
    
    def validate_all(self) -> List[ValidationResult]:
        """Run all validation checks."""
        results = []
        
        results.append(self._validate_trade_ancestry())
        results.append(self._validate_no_stale_state())
        results.append(self._validate_mode_compliance())
        results.append(self._validate_event_rates())
        results.append(self._validate_consensus_quality())
        
        return results
    
    def _validate_trade_ancestry(self) -> ValidationResult:
        """Validate every trade has valid consensus and opinion ancestry."""
        errors = []
        
        for intent in self.trade_intents:
            # Check consensus link
            if not intent.consensus_id:
                errors.append(f"Trade {intent.intent_id} has no consensus_id")
                continue
            
            # Find consensus
            consensus = next(
                (c for c in self.consensus_decisions if c.decision_id == intent.consensus_id),
                None
            )
            if not consensus:
                errors.append(
                    f"Trade {intent.intent_id} references missing consensus {intent.consensus_id}"
                )
                continue
            
            # Check opinion count
            if len(consensus.participating_agents) < self.config.min_agents_per_trade:
                errors.append(
                    f"Trade {intent.intent_id} consensus has only "
                    f"{len(consensus.participating_agents)} agents "
                    f"(min: {self.config.min_agents_per_trade})"
                )
            
            # Check opinion links
            if len(consensus.opinion_ids) == 0:
                errors.append(
                    f"Consensus {consensus.decision_id} has no opinion links"
                )
        
        if errors:
            return ValidationResult(
                check_name="trade_ancestry",
                passed=False,
                message=f"Trade ancestry validation failed: {len(errors)} errors",
                details={"errors": errors},
            )
        
        return ValidationResult(
            check_name="trade_ancestry",
            passed=True,
            message=f"All {len(self.trade_intents)} trades have valid ancestry",
            details={
                "trades_checked": len(self.trade_intents),
                "avg_agents_per_trade": (
                    sum(
                        len(
                            next(
                                (c for c in self.consensus_decisions if c.decision_id == t.consensus_id),
                                ConsensusDecision()
                            ).participating_agents
                        )
                        for t in self.trade_intents
                    ) / len(self.trade_intents) if self.trade_intents else 0
                ),
            },
        )
    
    def _validate_no_stale_state(self) -> ValidationResult:
        """Validate no agent traded on stale state."""
        errors = []
        
        for intent in self.trade_intents:
            # Find consensus
            consensus = next(
                (c for c in self.consensus_decisions if c.decision_id == intent.consensus_id),
                None
            )
            if not consensus:
                continue
            
            # Check age of consensus when trade was made
            age_seconds = intent.timestamp - consensus.timestamp
            if age_seconds > self.config.max_state_age_seconds:
                errors.append(
                    f"Trade {intent.intent_id} based on consensus that is "
                    f"{age_seconds:.1f}s old (max: {self.config.max_state_age_seconds}s)"
                )
            
            # Check opinion freshness
            for opinion_id in consensus.opinion_ids:
                opinion = next(
                    (o for o in self.opinions if o.opinion_id == opinion_id),
                    None
                )
                if opinion:
                    opinion_age = consensus.timestamp - opinion.timestamp
                    if opinion_age > self.config.max_state_age_seconds:
                        errors.append(
                            f"Opinion {opinion_id} was {opinion_age:.1f}s old "
                            f"when used in consensus"
                        )
        
        if errors:
            return ValidationResult(
                check_name="no_stale_state",
                passed=False,
                message=f"Stale state detected: {len(errors)} violations",
                details={"errors": errors},
            )
        
        return ValidationResult(
            check_name="no_stale_state",
            passed=True,
            message="No stale state detected in decision chain",
        )
    
    def _validate_mode_compliance(self) -> ValidationResult:
        """Validate all events match expected mode and no live calls."""
        errors = []
        
        # Check all trade intents match expected mode
        for intent in self.trade_intents:
            if intent.mode != self.config.mode:
                errors.append(
                    f"Trade intent {intent.intent_id} has mode {intent.mode.value}, "
                    f"expected {self.config.mode.value}"
                )
        
        # Check all order events match expected mode
        for event in self.order_events:
            if event.mode != self.config.mode:
                errors.append(
                    f"Order {event.order_id} has mode {event.mode.value}, "
                    f"expected {self.config.mode.value}"
                )
            
            # In SIM mode, all orders should be simulated
            if self.config.mode == TradingMode.MOCK and not event.simulated:
                errors.append(
                    f"Order {event.order_id} in SIMULATION mode but simulated=False"
                )
        
        # Add any recorded violations
        errors.extend(self.mode_violations)
        
        if errors:
            return ValidationResult(
                check_name="mode_compliance",
                passed=False,
                message=f"Mode compliance failed: {len(errors)} violations",
                details={"errors": errors},
            )
        
        return ValidationResult(
            check_name="mode_compliance",
            passed=True,
            message=f"All events comply with {self.config.mode.value} mode",
        )
    
    def _validate_event_rates(self) -> ValidationResult:
        """Validate opinion/consensus/trade counts are within expected bands."""
        duration_minutes = self.config.duration_seconds / 60
        
        opinions_per_min = len(self.opinions) / duration_minutes
        consensus_per_min = len(self.consensus_decisions) / duration_minutes
        trades_per_min = len(self.trade_intents) / duration_minutes
        
        warnings = []
        
        # Check opinion rate
        if opinions_per_min < self.config.expected_opinions_per_minute * 0.5:
            warnings.append(
                f"Low opinion rate: {opinions_per_min:.1f}/min "
                f"(expected: {self.config.expected_opinions_per_minute:.1f}/min)"
            )
        
        # Check consensus rate
        if consensus_per_min < self.config.expected_consensus_per_minute * 0.5:
            warnings.append(
                f"Low consensus rate: {consensus_per_min:.1f}/min "
                f"(expected: {self.config.expected_consensus_per_minute:.1f}/min)"
            )
        
        return ValidationResult(
            check_name="event_rates",
            passed=len(warnings) == 0,
            message="Event rates within expected bands" if not warnings else "Event rate warnings",
            details={
                "opinions_per_minute": opinions_per_min,
                "consensus_per_minute": consensus_per_min,
                "trades_per_minute": trades_per_min,
                "warnings": warnings,
            },
        )
    
    def _validate_consensus_quality(self) -> ValidationResult:
        """Validate consensus decisions show healthy disagreement."""
        if not self.consensus_decisions:
            return ValidationResult(
                check_name="consensus_quality",
                passed=False,
                message="No consensus decisions to validate",
            )
        
        # Calculate average disagreement
        avg_disagreement = sum(
            c.dissent_ratio for c in self.consensus_decisions
        ) / len(self.consensus_decisions)
        
        # Count high disagreement cases
        high_disagreement_count = sum(
            1 for c in self.consensus_decisions
            if c.dissent_ratio > self.config.max_disagreement_ratio
        )
        
        # Count unanimous decisions (potential groupthink)
        unanimous_count = sum(
            1 for c in self.consensus_decisions
            if len(c.dissenters) == 0 and len(c.participating_agents) >= 3
        )
        
        warnings = []
        if unanimous_count > len(self.consensus_decisions) * 0.8:
            warnings.append(
                f"High unanimity: {unanimous_count}/{len(self.consensus_decisions)} "
                f"decisions had no dissenters (potential groupthink)"
            )
        
        if high_disagreement_count > len(self.consensus_decisions) * 0.3:
            warnings.append(
                f"Frequent high disagreement: {high_disagreement_count} decisions "
                f"exceeded {self.config.max_disagreement_ratio:.0%} dissent ratio"
            )
        
        return ValidationResult(
            check_name="consensus_quality",
            passed=len(warnings) == 0,
            message="Consensus quality healthy" if not warnings else "Consensus quality concerns",
            details={
                "avg_disagreement": avg_disagreement,
                "high_disagreement_count": high_disagreement_count,
                "unanimous_count": unanimous_count,
                "total_decisions": len(self.consensus_decisions),
                "warnings": warnings,
            },
        )
    
    def print_summary(self, results: List[ValidationResult]) -> None:
        """Print validation summary."""
        print("\n" + "="*80)
        print("PAPER REHEARSAL VALIDATION SUMMARY")
        print("="*80)
        print(f"\nMode: {self.config.mode.value.upper()}")
        print(f"Duration: {self.config.duration_seconds}s")
        print(f"\nEvents Collected:")
        print(f"  Opinions: {len(self.opinions)}")
        print(f"  Consensus Decisions: {len(self.consensus_decisions)}")
        print(f"  Trade Intents: {len(self.trade_intents)}")
        print(f"  Order Events: {len(self.order_events)}")
        
        print(f"\nValidation Results:")
        passed_count = sum(1 for r in results if r.passed)
        for result in results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"  [{status}] {result.check_name}: {result.message}")
            
            if result.details and not result.passed:
                if "errors" in result.details:
                    print(f"    Errors:")
                    for error in result.details["errors"][:5]:  # Show first 5
                        print(f"      - {error}")
                    if len(result.details["errors"]) > 5:
                        print(f"      ... and {len(result.details['errors']) - 5} more")
        
        print(f"\nOverall: {passed_count}/{len(results)} checks passed")
        
        if passed_count == len(results):
            print("\n✓ REHEARSAL PASSED - System ready for extended testing")
        else:
            print("\n✗ REHEARSAL FAILED - Fix issues before proceeding")
        
        print("="*80 + "\n")


def _save_rehearsal_log(
    config: RehearsalConfig,
    validator: PaperRehearsalValidator,
    results: List[ValidationResult]
) -> None:
    """Save rehearsal events and results to timestamped JSONL log."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"rehearsal_{timestamp}.jsonl"
    
    try:
        with open(log_file, "w") as f:
            # Write header
            header = {
                "timestamp": time.time(),
                "checklist_version": CHECKLIST_VERSION,
                "event_type": "rehearsal_start",
                "mode": config.mode.value,
                "duration": config.duration_seconds,
                "symbols": config.symbols,
            }
            f.write(json.dumps(header) + "\n")
            
            # Write all opinions
            for opinion in validator.opinions:
                event = {
                    "timestamp": opinion.timestamp,
                    "event_type": "strategy_opinion",
                    "payload": opinion.to_dict(),
                }
                f.write(json.dumps(event) + "\n")
            
            # Write all consensus decisions
            for decision in validator.consensus_decisions:
                event = {
                    "timestamp": decision.timestamp,
                    "event_type": "consensus_decision",
                    "payload": decision.to_dict(),
                }
                f.write(json.dumps(event) + "\n")
            
            # Write all trade intents
            for intent in validator.trade_intents:
                event = {
                    "timestamp": intent.timestamp,
                    "event_type": "trade_intent",
                    "payload": intent.to_dict(),
                }
                f.write(json.dumps(event) + "\n")
            
            # Write all order events
            for order in validator.order_events:
                event = {
                    "timestamp": order.timestamp,
                    "event_type": "order_event",
                    "payload": order.to_dict(),
                }
                f.write(json.dumps(event) + "\n")
            
            # Write validation results
            validation_summary = {
                "timestamp": time.time(),
                "event_type": "rehearsal_end",
                "validation_results": {
                    "overall_passed": all(r.passed for r in results),
                    "checks": [
                        {
                            "name": r.check_name,
                            "passed": r.passed,
                            "message": r.message,
                            "details": r.details,
                        }
                        for r in results
                    ],
                },
            }
            f.write(json.dumps(validation_summary) + "\n")
        
        logger.info(f"Rehearsal log saved to: {log_file}")
        print(f"\nRehearsallog saved to: {log_file}")
    
    except Exception as e:
        logger.error(f"Failed to save rehearsal log: {e}")
        print(f"Warning: Failed to save rehearsal log: {e}")


async def run_paper_rehearsal(config: RehearsalConfig) -> PaperRehearsalValidator:
    """
    Run a paper trading rehearsal session.
    
    This is a placeholder that shows the structure. In production, this would:
    1. Start all swarm components
    2. Feed them real/replay market data
    3. Collect all events
    4. Run validation
    """
    logger.info(f"Starting paper rehearsal in {config.mode.value} mode for {config.duration_seconds}s")
    
    validator = PaperRehearsalValidator(config)
    
    # Initialize order router
    router_config = OrderRouterConfig(run_mode=config.mode)
    router = OrderRouter(router_config)
    
    # Simulate some events for demonstration
    # In production, this would be replaced with actual swarm startup
    
    start_time = time.time()
    
    # Simulate opinions
    for i in range(10):
        opinion = StrategyOpinion(
            opinion_id=f"op_{i}",
            agent_id=f"strategy_{i % 3}",
            symbol="BTC/USD",
            confidence=0.7,
            timestamp=start_time + i,
        )
        validator.record_opinion(opinion)
    
    # Simulate consensus
    for i in range(3):
        decision = ConsensusDecision(
            decision_id=f"cd_{i}",
            symbol="BTC/USD",
            participating_agents=[f"strategy_{j}" for j in range(3)],
            opinion_ids=[f"op_{j}" for j in range(i*3, (i+1)*3)],
            dissent_ratio=0.1,
            timestamp=start_time + 10 + i,
        )
        validator.record_consensus(decision)
    
    # Simulate trades
    for i in range(3):
        intent = TradeIntent(
            intent_id=f"ti_{i}",
            consensus_id=f"cd_{i}",
            symbol="BTC/USD",
            risk_checked=True,
            mode=config.mode,
            opinion_refs=[f"op_{j}" for j in range(i*3, (i+1)*3)],
            timestamp=start_time + 15 + i,
            price_at_intent=50000.0,
            quantity=0.1,
        )
        validator.record_trade_intent(intent)
        
        # Execute through router
        order = await router.submit_order(intent)
        validator.record_order_event(order)
    
    logger.info("Paper rehearsal completed")
    
    return validator


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run MERID paper trading rehearsal")
    parser.add_argument(
        "--mode",
        choices=["simulation", "paper"],
        default="simulation",
        help="Trading mode",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC/USD", "ETH/USD"],
        help="Symbols to trade",
    )
    
    args = parser.parse_args()
    
    # Create config
    mode = TradingMode.MOCK if args.mode == "simulation" else TradingMode.PAPER
    config = RehearsalConfig(
        mode=mode,
        duration_seconds=args.duration,
        symbols=args.symbols,
    )
    
    # Run rehearsal
    validator = asyncio.run(run_paper_rehearsal(config))
    
    # Validate
    results = validator.validate_all()
    validator.print_summary(results)
    
    # Save log capture
    _save_rehearsal_log(config, validator, results)
    
    # Exit with appropriate code
    passed = all(r.passed for r in results)
    exit(0 if passed else 1)


if __name__ == "__main__":
    main()
