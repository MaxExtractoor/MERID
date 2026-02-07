"""
Full-pipeline integration tests (Backlog #5).

Tests the end-to-end flow:
1. Signal → consensus → order decision → audit trail → explainability
2. Blocked venue rejection (route to prohibited venue → verify rejection)
3. Order-size sanity check (reject order > X% of portfolio)
4. Consensus graph round lifecycle
5. Audit trail hash chain integrity after multiple entries
"""

import time
import unittest
from unittest.mock import patch, MagicMock

from core.consensus_graph import (
    ConsensusRound,
    ConsensusConfig,
    ConsensusState,
    AgentVote,
    VoteDecision,
)
from core.consensus_logging import (
    ConsensusLogger,
    VoteType,
    ConsensusOutcome,
)
from core.audit_trail import AuditEntry, AuditTrail
from core.explainability import (
    ExplainabilityService,
    ExplanationType,
    ExplanationContext,
    DecisionRationale,
    FeatureAttribution,
    RuleEvaluation,
)
from core.automated_risk_controls import (
    PortfolioRiskManager,
    RiskControlCoordinator,
    TradingHaltManager,
)


class TestSignalToConsensusFlow(unittest.TestCase):
    """Signal → consensus vote → decision lifecycle."""

    def test_consensus_round_approve_flow(self):
        """3 agents vote APPROVE → round approved."""
        config = ConsensusConfig(quorum_threshold=3, approval_threshold=0.60)
        round_ = ConsensusRound(
            round_id="round-001",
            proposal_id="prop-001",
            proposal_type="trade_signal",
            proposal_payload={"symbol": "BTC", "signal": "bullish"},
            config=config,
        )

        agents = [
            ("research-agent", VoteDecision.APPROVE, 0.85),
            ("strategy-agent", VoteDecision.APPROVE, 0.90),
            ("risk-agent", VoteDecision.APPROVE, 0.70),
        ]

        for agent_id, decision, confidence in agents:
            vote = AgentVote(
                agent_id=agent_id,
                decision=decision,
                confidence=confidence,
                reasoning=f"{agent_id} approves with {confidence:.0%}",
            )
            round_.add_vote(vote)

        # Force evaluation with 3 alive agents so dynamic quorum = 3
        round_.force_evaluate(alive_agents=3)

        self.assertEqual(round_.state, ConsensusState.APPROVED)
        self.assertEqual(round_.final_result, "approved")
        self.assertGreater(round_.final_approval_ratio, 0.5)

    def test_consensus_round_reject_flow(self):
        """3 agents vote REJECT → round rejected."""
        config = ConsensusConfig(quorum_threshold=3, approval_threshold=0.60)
        round_ = ConsensusRound(
            round_id="round-002",
            proposal_id="prop-002",
            proposal_type="trade_signal",
            proposal_payload={"symbol": "ETH", "signal": "bearish"},
            config=config,
        )

        agents = [
            ("research-agent", VoteDecision.REJECT, 0.80),
            ("strategy-agent", VoteDecision.REJECT, 0.75),
            ("risk-agent", VoteDecision.REJECT, 0.90),
        ]

        for agent_id, decision, confidence in agents:
            vote = AgentVote(
                agent_id=agent_id,
                decision=decision,
                confidence=confidence,
                reasoning=f"{agent_id} rejects",
            )
            round_.add_vote(vote)

        # Force evaluation with 3 alive agents so dynamic quorum = 3
        round_.force_evaluate(alive_agents=3)

        self.assertEqual(round_.state, ConsensusState.REJECTED)
        self.assertEqual(round_.final_result, "rejected")

    def test_consensus_round_veto_by_skeptic(self):
        """Skeptic agent vetoes → round vetoed."""
        config = ConsensusConfig(
            skeptic_agent_id="risk-agent",
            skeptic_veto_confidence_threshold=0.80,
        )
        round_ = ConsensusRound(
            round_id="round-003",
            proposal_id="prop-003",
            proposal_type="trade_signal",
            proposal_payload={"symbol": "SOL", "signal": "bullish"},
            config=config,
        )

        # Skeptic votes REJECT with high confidence → veto
        veto_vote = AgentVote(
            agent_id="risk-agent",
            decision=VoteDecision.REJECT,
            confidence=0.95,
            reasoning="Risk too high, vetoing",
        )
        round_.add_vote(veto_vote)

        self.assertEqual(round_.state, ConsensusState.VETOED)
        self.assertEqual(round_.final_result, "rejected")


class TestConsensusLoggingFlow(unittest.TestCase):
    """Consensus logger records full round lifecycle."""

    def test_full_round_lifecycle(self):
        logger = ConsensusLogger()

        round_id = logger.start_round(
            proposal={"type": "market_consensus", "symbol": "BTC"},
            quorum_required=3,
        )

        # Record 3 votes
        for i, (agent, vote_type) in enumerate([
            ("research", VoteType.APPROVE),
            ("strategy", VoteType.APPROVE),
            ("risk", VoteType.REJECT),
        ]):
            logger.record_vote(
                round_id=round_id,
                agent_id=agent,
                vote=vote_type,
                reasoning=f"{agent} votes {vote_type.value}",
                confidence=0.8 + i * 0.05,
                trust_weight=1.0,
            )

        # Record dissent
        logger.record_dissent(
            round_id=round_id,
            agent_id="risk",
            vote=VoteType.REJECT,
            reasoning="Drawdown too high",
            resolution="overruled by majority",
            overruled_by=["research", "strategy"],
        )

        # Complete round
        timeline = logger.complete_round(
            round_id=round_id,
            outcome=ConsensusOutcome.PASSED,
            final_confidence=0.85,
            final_action="EXECUTE_LONG",
        )

        self.assertIsNotNone(timeline)
        self.assertEqual(timeline.outcome, ConsensusOutcome.PASSED)
        self.assertEqual(len(timeline.votes), 3)
        self.assertEqual(len(timeline.dissent), 1)
        self.assertTrue(timeline.quorum_reached)

        # Verify stats
        stats = logger.get_consensus_stats()
        self.assertEqual(stats["total_rounds"], 1)
        self.assertEqual(stats["passed"], 1)
        self.assertAlmostEqual(stats["pass_rate"], 1.0)

    def test_round_serialization(self):
        """Round data is JSON-serializable."""
        import json

        logger = ConsensusLogger()
        round_id = logger.start_round(
            proposal={"type": "test"},
            quorum_required=1,
        )
        logger.record_vote(
            round_id=round_id,
            agent_id="agent-1",
            vote=VoteType.APPROVE,
            reasoning="test",
            confidence=0.9,
            trust_weight=1.0,
        )
        timeline = logger.complete_round(
            round_id=round_id,
            outcome=ConsensusOutcome.PASSED,
            final_confidence=0.9,
            final_action="HOLD",
        )

        serialized = json.dumps(timeline.to_dict())
        self.assertIn("round_id", serialized)
        self.assertIn("passed", serialized)


class TestAuditTrailIntegrity(unittest.TestCase):
    """Audit trail hash chain integrity after multiple entries."""

    def test_hash_chain_integrity_1000_entries(self):
        """Verify hash chain after 1000 entries."""
        trail = AuditTrail.__new__(AuditTrail)
        trail.entries = []
        trail.sequence = 0
        trail.last_hash = "genesis"

        for i in range(1000):
            trail.sequence += 1
            entry = AuditEntry(
                sequence=trail.sequence,
                timestamp=time.time(),
                event_type="test_event",
                source=f"agent-{i % 5}",
                data={"value": i, "action": "test"},
                previous_hash=trail.last_hash,
            )
            trail.entries.append(entry)
            trail.last_hash = entry.entry_hash

        self.assertTrue(trail.verify_chain())
        self.assertEqual(len(trail.entries), 1000)

    def test_tampered_entry_detected(self):
        """Tampering with an entry breaks the chain."""
        trail = AuditTrail.__new__(AuditTrail)
        trail.entries = []
        trail.sequence = 0
        trail.last_hash = "genesis"

        for i in range(10):
            trail.sequence += 1
            entry = AuditEntry(
                sequence=trail.sequence,
                timestamp=time.time(),
                event_type="test_event",
                source="agent-1",
                data={"value": i},
                previous_hash=trail.last_hash,
            )
            trail.entries.append(entry)
            trail.last_hash = entry.entry_hash

        # Tamper with entry 5
        trail.entries[4].data["value"] = 999

        self.assertFalse(trail.verify_chain())

    def test_genesis_chain(self):
        """Empty chain verifies correctly."""
        trail = AuditTrail.__new__(AuditTrail)
        trail.entries = []
        self.assertTrue(trail.verify_chain())


class TestExplainabilityRecording(unittest.TestCase):
    """Explainability service records decisions with rationale."""

    def test_record_trade_explanation(self):
        svc = ExplainabilityService()

        context = ExplanationContext(
            agent_id="strategy-agent",
            strategy="momentum",
            inputs={"price": 50000, "signal": "bullish"},
            constraints={"max_position_pct": 0.05},
            expected_effect={"action": "BTC long entry"},
            environment_flags={"mode": "paper"},
        )
        rationale = DecisionRationale(
            reason="Momentum signal above threshold with consensus approval",
            inputs={"price": 50000, "volume": 1200},
            features=[
                FeatureAttribution(name="momentum_score", value=0.85, importance=0.6),
                FeatureAttribution(name="volume_ratio", value=1.5, importance=0.4),
            ],
            rules_fired=[
                RuleEvaluation(rule_name="momentum_threshold", threshold=0.70, observed_value=0.85, passed=True, notes="score 0.85 > 0.70"),
            ],
        )

        record = svc.record_explanation(
            explanation_type=ExplanationType.ORDER,
            summary="BTC long entry based on momentum signal",
            context=context,
            domain="crypto",
            decision_id="trade-001",
            rationale=rationale,
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.domain, "crypto")
        self.assertEqual(record.decision_id, "trade-001")
        self.assertIn("momentum", record.summary.lower())

        # Verify metrics
        metrics = svc.get_metrics()
        self.assertEqual(metrics["total_records"], 1)
        self.assertIn("order", metrics["coverage"])

    def test_missing_rationale_raises(self):
        """Require_explanation rejects empty rationale."""
        svc = ExplainabilityService()

        bad_rationale = DecisionRationale(
            reason="",
            inputs={"price": 100},
            features=[FeatureAttribution(name="x", value=1, importance=1)],
            rules_fired=[RuleEvaluation(rule_name="r1", threshold=1, observed_value=1, passed=True, notes="ok")],
        )

        from core.explainability import ExplainabilityViolation

        with self.assertRaises(ExplainabilityViolation):
            svc.require_explanation("crypto", "trade-002", bad_rationale)


class TestBlockedVenueRejection(unittest.TestCase):
    """Route order to blocked venue → verify rejection."""

    def test_polymarket_blocked_for_us(self):
        """Polymarket is prohibited for US compliance."""
        from merid.prediction.venue_gate import VenueGate

        gate = VenueGate()
        with self.assertRaises(gate.VenueBlockedError):
            gate.check_venue("polymarket")

    def test_augur_blocked(self):
        """Augur is prohibited."""
        from merid.prediction.venue_gate import VenueGate

        gate = VenueGate()
        with self.assertRaises(gate.VenueBlockedError):
            gate.check_venue("augur")

    def test_kalshi_allowed(self):
        """Kalshi is allowed (CFTC-regulated)."""
        from merid.prediction.venue_gate import VenueGate

        gate = VenueGate()
        gate.check_venue("kalshi")  # Should not raise

    def test_pipeline_instrument_compliance(self):
        """Instrument with compliance_flags=False for a venue rejects order."""
        from merid.pipeline.instruments import InstrumentRegistry, Instrument

        registry = InstrumentRegistry()
        registry.register(Instrument(
            merid_symbol="BLOCKED:TEST",
            domain="prediction",
            display_name="Blocked Test",
            venue_symbols={"blocked_venue": "TEST"},
            compliance_flags={"blocked_venue": False},
        ))

        inst = registry.get("BLOCKED:TEST")
        self.assertFalse(inst.is_allowed("blocked_venue"))


class TestOrderSizeSanityCheck(unittest.TestCase):
    """Reject orders > X% of portfolio."""

    def test_oversized_order_rejected(self):
        """Order > 10% of portfolio is rejected."""
        import asyncio

        pm = PortfolioRiskManager(max_position_size=0.10)
        pm.portfolio_value = 10000

        result = asyncio.get_event_loop().run_until_complete(
            pm.check_position_allowed("BTC", 0.05, 30000)  # $1500 = 15%
        )

        self.assertFalse(result["allowed"])
        violations = result["violations"]
        self.assertTrue(any(v["type"] == "position_size" for v in violations))

    def test_normal_order_allowed(self):
        """Order < 10% of portfolio is allowed."""
        import asyncio

        pm = PortfolioRiskManager(max_position_size=0.10)
        pm.portfolio_value = 100000

        result = asyncio.get_event_loop().run_until_complete(
            pm.check_position_allowed("BTC", 0.01, 50000)  # $500 = 0.5%
        )

        self.assertTrue(result["allowed"])

    def test_leverage_limit_rejection(self):
        """Order that would exceed leverage limit is rejected."""
        import asyncio

        pm = PortfolioRiskManager(max_leverage=2.0)
        pm.portfolio_value = 10000
        pm.total_exposure = 18000  # Already 1.8x

        result = asyncio.get_event_loop().run_until_complete(
            pm.check_position_allowed("ETH", 1.0, 5000)  # Would push to 2.3x
        )

        self.assertFalse(result["allowed"])
        violations = result["violations"]
        self.assertTrue(any(v["type"] == "leverage" for v in violations))


class TestEndToEndPipelineFlow(unittest.TestCase):
    """Full pipeline: signal → consensus → risk check → audit → explain."""

    def test_full_flow(self):
        """End-to-end: signal generates consensus, risk checks, audit, explain."""
        # 1. Signal: 3 agents produce votes
        config = ConsensusConfig(quorum_threshold=3, approval_threshold=0.60)
        round_ = ConsensusRound(
            round_id="e2e-round-001",
            proposal_id="e2e-prop-001",
            proposal_type="trade_signal",
            proposal_payload={"symbol": "BTC", "signal": "bullish", "price": 105000},
            config=config,
        )

        for agent_id, decision, conf in [
            ("research", VoteDecision.APPROVE, 0.85),
            ("strategy", VoteDecision.APPROVE, 0.90),
            ("risk", VoteDecision.APPROVE, 0.70),
        ]:
            round_.add_vote(AgentVote(
                agent_id=agent_id,
                decision=decision,
                confidence=conf,
                reasoning=f"{agent_id} signal",
            ))

        round_.force_evaluate(alive_agents=3)
        self.assertEqual(round_.state, ConsensusState.APPROVED)

        # 2. Consensus logger records the round
        cl = ConsensusLogger()
        rid = cl.start_round(
            proposal={"symbol": "BTC", "action": "EXECUTE_LONG"},
            quorum_required=3,
        )
        for agent_id, vt in [
            ("research", VoteType.APPROVE),
            ("strategy", VoteType.APPROVE),
            ("risk", VoteType.APPROVE),
        ]:
            cl.record_vote(rid, agent_id, vt, f"{agent_id} approves", 0.85, 1.0)
        timeline = cl.complete_round(rid, ConsensusOutcome.PASSED, 0.85, "EXECUTE_LONG")
        self.assertEqual(timeline.outcome, ConsensusOutcome.PASSED)

        # 3. Risk check: order size within limits
        import asyncio
        pm = PortfolioRiskManager(max_position_size=0.10)
        pm.portfolio_value = 50000
        risk_result = asyncio.get_event_loop().run_until_complete(
            pm.check_position_allowed("BTC", 0.01, 105000)  # $1050 = 2.1%
        )
        self.assertTrue(risk_result["allowed"])

        # 4. Trading halt check
        coord = RiskControlCoordinator()
        self.assertTrue(coord.can_trade())

        # 5. Audit trail entry
        trail = AuditTrail.__new__(AuditTrail)
        trail.entries = []
        trail.sequence = 0
        trail.last_hash = "genesis"

        trail.sequence += 1
        entry = AuditEntry(
            sequence=trail.sequence,
            timestamp=time.time(),
            event_type="trade_executed",
            source="trade-router",
            data={
                "symbol": "BTC",
                "side": "buy",
                "size": 0.01,
                "price": 105000,
                "consensus_round": rid,
                "risk_check": "passed",
            },
            previous_hash=trail.last_hash,
        )
        trail.entries.append(entry)
        trail.last_hash = entry.entry_hash
        self.assertTrue(trail.verify_chain())

        # 6. Explainability record
        svc = ExplainabilityService()
        record = svc.record_explanation(
            explanation_type=ExplanationType.ORDER,
            summary="BTC long 0.01 @ 105000 after consensus approval",
            context=ExplanationContext(
                agent_id="trade-router",
                strategy="consensus_execution",
                inputs={"price": 105000, "consensus": "APPROVED"},
                constraints={"max_position_pct": 0.10, "halt_check": "passed"},
                expected_effect={"action": "BTC long position opened"},
                environment_flags={"mode": "paper"},
            ),
            domain="crypto",
            decision_id="trade-e2e-001",
            correlation_id=rid,
            rationale=DecisionRationale(
                reason="Consensus approved BTC long with 85% confidence",
                inputs={"price": 105000, "signal": "bullish"},
                features=[
                    FeatureAttribution(name="consensus_confidence", value=0.85, importance=0.7),
                    FeatureAttribution(name="risk_check", value=1.0, importance=0.3),
                ],
                rules_fired=[
                    RuleEvaluation(rule_name="consensus_quorum", threshold=3, observed_value=3, passed=True, notes="3/3 votes"),
                    RuleEvaluation(rule_name="position_size_limit", threshold=0.10, observed_value=0.021, passed=True, notes="2.1% < 10%"),
                ],
            ),
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.correlation_id, rid)
        self.assertEqual(record.domain, "crypto")

        # Verify full chain
        metrics = svc.get_metrics()
        self.assertEqual(metrics["total_records"], 1)


if __name__ == "__main__":
    unittest.main()
