"""
Shadow Replay Execution for 15-Minute Crypto Markets

End-to-end validation of the complete pipeline from signal to execution
for BTC, ETH, SOL, XRP, DOGE using representative candidates.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
import json

from utils.logger import get_logger

logger = get_logger("merid.shadow_replay_execution")


@dataclass
class ShadowReplayCandidate:
    """Candidate data for shadow replay execution."""
    
    # Identification
    candidate_id: str
    tick_id: str
    asset_ticker: str
    timestamp: datetime
    
    # Signal Data
    p_hat_yes_fraction: float  # Model probability (0-1)
    p_hat_yes_cents: float     # Model probability in cents (0-100)
    signal_side: str           # "yes" or "no"
    
    # Market Data
    yes_bid_cents: int
    yes_ask_cents: int
    no_bid_cents: int
    no_ask_cents: int
    yes_bid_depth: int
    no_bid_depth: int
    time_to_expiry_seconds: int
    
    # Order Intent
    order_side: str            # "yes" or "no"
    order_action: str          # "buy" or "sell"
    order_price_cents: int
    order_count: int
    
    # Policy
    use_maker_economics: bool
    aggressiveness: float
    
    # Expected Outcome
    expected_decision: str      # "accept" or "reject"
    expected_reject_reason: Optional[str] = None
    
    # Metadata
    market_regime: str = "normal"
    volatility_level: str = "medium"
    liquidity_level: str = "medium"


@dataclass
class ShadowReplayResult:
    """Result of shadow replay execution."""
    
    candidate_id: str
    asset_ticker: str
    expected_decision: str
    actual_decision: str
    expected_reject_reason: Optional[str]
    actual_reject_reason: Optional[str]
    decision_match: bool
    reason_match: bool
    gate_trace: List[Dict[str, Any]]
    execution_time_ms: float
    timestamp: datetime


class ShadowReplayExecutor:
    """Execute shadow replay for candidate validation."""
    
    def __init__(self):
        self._orchestrator = None
        self._results: List[ShadowReplayResult] = []
    
    def initialize(self):
        """Initialize gate orchestrator."""
        try:
            from merid.event_venues.kalshi.gate_orchestrator import get_gate_orchestrator
            self._orchestrator = get_gate_orchestrator()
            logger.info("[SHADOW-REPLAY] Gate orchestrator initialized")
        except ImportError as e:
            logger.error(f"[SHADOW-REPLAY] Failed to initialize gate orchestrator: {e}")
            raise
    
    def execute_candidate(self, candidate: ShadowReplayCandidate) -> ShadowReplayResult:
        """Execute single candidate through shadow replay."""
        import time
        
        start_time = time.time()
        
        try:
            # Prepare candidate data for orchestrator
            candidate_data = {
                "agent_id": f"shadow_replay_{candidate.asset_ticker.lower()}",
                "venue": "kalshi"
            }
            
            market_data = {
                "yes_bid_cents": candidate.yes_bid_cents,
                "no_bid_cents": candidate.no_bid_cents,
                "yes_ask_cents": candidate.yes_ask_cents,
                "no_ask_cents": candidate.no_ask_cents,
                "yes_bid_depth": candidate.yes_bid_depth,
                "no_bid_depth": candidate.no_bid_depth,
                "time_to_expiry_seconds": candidate.time_to_expiry_seconds
            }
            
            order_intent = {
                "side": candidate.order_side,
                "action": candidate.order_action,
                "price_cents": candidate.order_price_cents,
                "count": candidate.order_count,
                "use_maker_economics": candidate.use_maker_economics,
                "aggressiveness": candidate.aggressiveness
            }
            
            # Execute through orchestrator
            decision = self._orchestrator.evaluate_candidate(
                candidate_data,
                market_data,
                order_intent,
                candidate.asset_ticker,
                is_15m_market=True
            )
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            # Extract gate trace
            gate_trace = []
            for result in decision.gate_trace:
                gate_trace.append({
                    "stage": result.stage.value,
                    "decision": result.decision.value,
                    "reason": result.reason,
                    "metadata": result.metadata
                })
            
            # Determine actual decision
            actual_decision = "accept" if decision.accepted else "reject"
            actual_reject_reason = decision.first_reject_reason if not decision.accepted else None
            
            # Compare with expected
            decision_match = (actual_decision == candidate.expected_decision)
            reason_match = True
            if candidate.expected_reject_reason and actual_reject_reason:
                reason_match = (actual_reject_reason == candidate.expected_reject_reason)
            
            result = ShadowReplayResult(
                candidate_id=candidate.candidate_id,
                asset_ticker=candidate.asset_ticker,
                expected_decision=candidate.expected_decision,
                actual_decision=actual_decision,
                expected_reject_reason=candidate.expected_reject_reason,
                actual_reject_reason=actual_reject_reason,
                decision_match=decision_match,
                reason_match=reason_match,
                gate_trace=gate_trace,
                execution_time_ms=execution_time_ms,
                timestamp=datetime.now()
            )
            
            logger.info(
                f"[SHADOW-REPLAY] {candidate.asset_ticker} {candidate.candidate_id}: "
                f"expected={candidate.expected_decision}, actual={actual_decision}, "
                f"match={decision_match}"
            )
            
            return result
            
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"[SHADOW-REPLAY] Error executing {candidate.candidate_id}: {e}")
            
            return ShadowReplayResult(
                candidate_id=candidate.candidate_id,
                asset_ticker=candidate.asset_ticker,
                expected_decision=candidate.expected_decision,
                actual_decision="error",
                expected_reject_reason=candidate.expected_reject_reason,
                actual_reject_reason=f"execution_error: {str(e)}",
                decision_match=False,
                reason_match=False,
                gate_trace=[],
                execution_time_ms=execution_time_ms,
                timestamp=datetime.now()
            )
    
    def execute_batch(self, candidates: List[ShadowReplayCandidate]) -> List[ShadowReplayResult]:
        """Execute batch of candidates."""
        logger.info(f"[SHADOW-REPLAY] Executing batch of {len(candidates)} candidates")
        
        results = []
        for candidate in candidates:
            result = self.execute_candidate(candidate)
            results.append(result)
            self._results.append(result)
        
        return results
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate execution report."""
        total = len(self._results)
        matched = sum(1 for r in self._results if r.decision_match)
        decision_mismatch = total - matched
        
        by_asset = {}
        for result in self._results:
            asset = result.asset_ticker
            if asset not in by_asset:
                by_asset[asset] = {"total": 0, "matched": 0, "mismatched": 0}
            by_asset[asset]["total"] += 1
            if result.decision_match:
                by_asset[asset]["matched"] += 1
            else:
                by_asset[asset]["mismatched"] += 1
        
        report = {
            "summary": {
                "total_candidates": total,
                "decision_matches": matched,
                "decision_mismatches": decision_mismatch,
                "match_rate": matched / total if total > 0 else 0
            },
            "by_asset": by_asset,
            "detailed_results": [
                {
                    "candidate_id": r.candidate_id,
                    "asset_ticker": r.asset_ticker,
                    "expected_decision": r.expected_decision,
                    "actual_decision": r.actual_decision,
                    "decision_match": r.decision_match,
                    "expected_reject_reason": r.expected_reject_reason,
                    "actual_reject_reason": r.actual_reject_reason,
                    "reason_match": r.reason_match,
                    "execution_time_ms": r.execution_time_ms,
                    "gate_trace": r.gate_trace
                }
                for r in self._results
            ]
        }
        
        return report


def get_mock_candidates() -> List[ShadowReplayCandidate]:
    """Get mock candidates for shadow replay testing."""
    candidates = []
    
    # BTC Accepted
    candidates.append(ShadowReplayCandidate(
        candidate_id="btc_accepted_001",
        tick_id="tick_20260802_001",
        asset_ticker="BTC",
        timestamp=datetime(2026, 8, 2, 10, 0, 0),
        p_hat_yes_fraction=0.58,
        p_hat_yes_cents=58.0,
        signal_side="yes",
        yes_bid_cents=52,
        yes_ask_cents=53,
        no_bid_cents=47,
        no_ask_cents=48,
        yes_bid_depth=150,
        no_bid_depth=120,
        time_to_expiry_seconds=600,
        order_side="yes",
        order_action="buy",
        order_price_cents=52,
        order_count=10,
        use_maker_economics=True,
        aggressiveness=0.3,
        expected_decision="accept",
        market_regime="normal",
        volatility_level="low",
        liquidity_level="high"
    ))
    
    # BTC Rejected
    candidates.append(ShadowReplayCandidate(
        candidate_id="btc_rejected_001",
        tick_id="tick_20260802_002",
        asset_ticker="BTC",
        timestamp=datetime(2026, 8, 2, 10, 15, 0),
        p_hat_yes_fraction=0.55,
        p_hat_yes_cents=55.0,
        signal_side="yes",
        yes_bid_cents=50,
        yes_ask_cents=65,  # Wide spread (15c)
        no_bid_cents=35,
        no_ask_cents=50,
        yes_bid_depth=80,
        no_bid_depth=60,
        time_to_expiry_seconds=300,
        order_side="yes",
        order_action="buy",
        order_price_cents=50,
        order_count=10,
        use_maker_economics=True,
        aggressiveness=0.3,
        expected_decision="reject",
        expected_reject_reason="spread_too_wide",
        market_regime="normal",
        volatility_level="medium",
        liquidity_level="medium"
    ))
    
    # ETH Accepted
    candidates.append(ShadowReplayCandidate(
        candidate_id="eth_accepted_001",
        tick_id="tick_20260802_003",
        asset_ticker="ETH",
        timestamp=datetime(2026, 8, 2, 10, 30, 0),
        p_hat_yes_fraction=0.53,
        p_hat_yes_cents=53.0,
        signal_side="yes",
        yes_bid_cents=48,
        yes_ask_cents=50,
        no_bid_cents=50,
        no_ask_cents=52,
        yes_bid_depth=120,
        no_bid_depth=100,
        time_to_expiry_seconds=700,
        order_side="yes",
        order_action="buy",
        order_price_cents=48,
        order_count=15,
        use_maker_economics=True,
        aggressiveness=0.4,
        expected_decision="accept",
        market_regime="normal",
        volatility_level="low",
        liquidity_level="high"
    ))
    
    # ETH Rejected
    candidates.append(ShadowReplayCandidate(
        candidate_id="eth_rejected_001",
        tick_id="tick_20260802_004",
        asset_ticker="ETH",
        timestamp=datetime(2026, 8, 2, 10, 45, 0),
        p_hat_yes_fraction=0.51,
        p_hat_yes_cents=51.0,
        signal_side="no",
        yes_bid_cents=55,
        yes_ask_cents=70,  # Wide spread (15c)
        no_bid_cents=30,
        no_ask_cents=45,
        yes_bid_depth=70,
        no_bid_depth=50,
        time_to_expiry_seconds=200,
        order_side="no",
        order_action="sell",
        order_price_cents=45,
        order_count=15,
        use_maker_economics=False,
        aggressiveness=0.4,
        expected_decision="reject",
        expected_reject_reason="spread_too_wide",
        market_regime="normal",
        volatility_level="high",
        liquidity_level="low"
    ))
    
    # SOL Accepted
    candidates.append(ShadowReplayCandidate(
        candidate_id="sol_accepted_001",
        tick_id="tick_20260802_005",
        asset_ticker="SOL",
        timestamp=datetime(2026, 8, 2, 11, 0, 0),
        p_hat_yes_fraction=0.72,
        p_hat_yes_cents=72.0,
        signal_side="yes",
        yes_bid_cents=65,
        yes_ask_cents=68,
        no_bid_cents=32,
        no_ask_cents=35,
        yes_bid_depth=80,
        no_bid_depth=60,
        time_to_expiry_seconds=800,
        order_side="yes",
        order_action="buy",
        order_price_cents=65,
        order_count=20,
        use_maker_economics=True,
        aggressiveness=0.5,
        expected_decision="accept",
        market_regime="normal",
        volatility_level="medium",
        liquidity_level="medium"
    ))
    
    # SOL Rejected
    candidates.append(ShadowReplayCandidate(
        candidate_id="sol_rejected_001",
        tick_id="tick_20260802_006",
        asset_ticker="SOL",
        timestamp=datetime(2026, 8, 2, 11, 15, 0),
        p_hat_yes_fraction=0.68,
        p_hat_yes_cents=68.0,
        signal_side="yes",
        yes_bid_cents=60,
        yes_ask_cents=85,  # Very wide spread (25c)
        no_bid_cents=15,
        no_ask_cents=40,
        yes_bid_depth=40,
        no_bid_depth=30,
        time_to_expiry_seconds=100,
        order_side="yes",
        order_action="buy",
        order_price_cents=60,
        order_count=20,
        use_maker_economics=True,
        aggressiveness=0.5,
        expected_decision="reject",
        expected_reject_reason="spread_too_wide",
        market_regime="normal",
        volatility_level="high",
        liquidity_level="low"
    ))
    
    # XRP Accepted
    candidates.append(ShadowReplayCandidate(
        candidate_id="xrp_accepted_001",
        tick_id="tick_20260802_007",
        asset_ticker="XRP",
        timestamp=datetime(2026, 8, 2, 11, 30, 0),
        p_hat_yes_fraction=0.62,
        p_hat_yes_cents=62.0,
        signal_side="yes",
        yes_bid_cents=55,
        yes_ask_cents=58,
        no_bid_cents=42,
        no_ask_cents=45,
        yes_bid_depth=70,
        no_bid_depth=50,
        time_to_expiry_seconds=750,
        order_side="yes",
        order_action="buy",
        order_price_cents=55,
        order_count=25,
        use_maker_economics=True,
        aggressiveness=0.4,
        expected_decision="accept",
        market_regime="normal",
        volatility_level="medium",
        liquidity_level="medium"
    ))
    
    # XRP Rejected
    candidates.append(ShadowReplayCandidate(
        candidate_id="xrp_rejected_001",
        tick_id="tick_20260802_008",
        asset_ticker="XRP",
        timestamp=datetime(2026, 8, 2, 11, 45, 0),
        p_hat_yes_fraction=0.58,
        p_hat_yes_cents=58.0,
        signal_side="no",
        yes_bid_cents=52,
        yes_ask_cents=78,  # Very wide spread (26c)
        no_bid_cents=22,
        no_ask_cents=48,
        yes_bid_depth=35,
        no_bid_depth=25,
        time_to_expiry_seconds=150,
        order_side="no",
        order_action="sell",
        order_price_cents=48,
        order_count=25,
        use_maker_economics=False,
        aggressiveness=0.4,
        expected_decision="reject",
        expected_reject_reason="spread_too_wide",
        market_regime="normal",
        volatility_level="high",
        liquidity_level="low"
    ))
    
    # DOGE Accepted
    candidates.append(ShadowReplayCandidate(
        candidate_id="doge_accepted_001",
        tick_id="tick_20260802_009",
        asset_ticker="DOGE",
        timestamp=datetime(2026, 8, 2, 12, 0, 0),
        p_hat_yes_fraction=0.32,
        p_hat_yes_cents=32.0,
        signal_side="yes",
        yes_bid_cents=28,
        yes_ask_cents=32,
        no_bid_cents=68,
        no_ask_cents=72,
        yes_bid_depth=50,
        no_bid_depth=40,
        time_to_expiry_seconds=650,
        order_side="yes",
        order_action="buy",
        order_price_cents=28,
        order_count=30,
        use_maker_economics=True,
        aggressiveness=0.6,
        expected_decision="accept",
        market_regime="normal",
        volatility_level="medium",
        liquidity_level="medium"
    ))
    
    # DOGE Rejected
    candidates.append(ShadowReplayCandidate(
        candidate_id="doge_rejected_001",
        tick_id="tick_20260802_010",
        asset_ticker="DOGE",
        timestamp=datetime(2026, 8, 2, 12, 15, 0),
        p_hat_yes_fraction=0.28,
        p_hat_yes_cents=28.0,
        signal_side="yes",
        yes_bid_cents=25,
        yes_ask_cents=60,  # Extremely wide spread (35c)
        no_bid_cents=40,
        no_ask_cents=75,
        yes_bid_depth=20,
        no_bid_depth=15,
        time_to_expiry_seconds=50,
        order_side="yes",
        order_action="buy",
        order_price_cents=25,
        order_count=30,
        use_maker_economics=True,
        aggressiveness=0.6,
        expected_decision="reject",
        expected_reject_reason="spread_too_wide",
        market_regime="normal",
        volatility_level="high",
        liquidity_level="low"
    ))
    
    return candidates


def main():
    """Main execution function."""
    logger.info("[SHADOW-REPLAY] Starting shadow replay execution")
    
    # Initialize executor
    executor = ShadowReplayExecutor()
    executor.initialize()
    
    # Get mock candidates
    candidates = get_mock_candidates()
    logger.info(f"[SHADOW-REPLAY] Loaded {len(candidates)} mock candidates")
    
    # Execute batch
    results = executor.execute_batch(candidates)
    
    # Generate report
    report = executor.generate_report()
    
    # Print summary
    logger.info(f"[SHADOW-REPLAY] Execution complete:")
    logger.info(f"  Total candidates: {report['summary']['total_candidates']}")
    logger.info(f"  Decision matches: {report['summary']['decision_matches']}")
    logger.info(f"  Decision mismatches: {report['summary']['decision_mismatches']}")
    logger.info(f"  Match rate: {report['summary']['match_rate']:.2%}")
    
    # Print by-asset breakdown
    for asset, stats in report['by_asset'].items():
        logger.info(f"  {asset}: {stats['matched']}/{stats['total']} matched ({stats['matched']/stats['total']:.2%})")
    
    # Save report to file
    report_path = "C:/Dev/MERID/shadow_replay_report_2026_08_02.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    logger.info(f"[SHADOW-REPLAY] Report saved to {report_path}")
    
    return report


if __name__ == "__main__":
    main()
