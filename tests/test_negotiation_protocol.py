"""
Tests for NegotiationProtocol (S1-03: agent-to-agent negotiation and conflict resolution).

Tests:
- Session lifecycle: propose → counter → accept/reject
- Deadlock detection after max_rounds
- Expiration on timeout
- State machine enforcement (invalid transitions)
- Mediator auto-resolution strategies
- Callback invocation on resolution
- Serialization for dashboards
"""

import time
import json
import unittest
from unittest.mock import MagicMock

from core.negotiation_protocol import (
    NegotiationSession,
    NegotiationState,
    NegotiationError,
    NegotiationMediator,
    Proposal,
)


class TestProposalDataclass(unittest.TestCase):
    """Proposal creation and serialization."""

    def test_proposal_defaults(self):
        p = Proposal(agent_id="agent-1", action="BUY", confidence=0.85)
        self.assertEqual(p.agent_id, "agent-1")
        self.assertEqual(p.action, "BUY")
        self.assertGreater(len(p.proposal_id), 0)

    def test_proposal_to_dict(self):
        p = Proposal(agent_id="agent-1", action="BUY", confidence=0.85, rationale="momentum")
        d = p.to_dict()
        self.assertEqual(d["agent_id"], "agent-1")
        self.assertEqual(d["rationale"], "momentum")
        serialized = json.dumps(d)
        self.assertIn("BUY", serialized)


class TestSessionLifecycle(unittest.TestCase):
    """Full propose → counter → accept lifecycle."""

    def test_propose_accept(self):
        session = NegotiationSession(
            topic="BTC long", initiator="strategy", respondent="risk",
        )
        session.propose(Proposal(agent_id="strategy", action="EXECUTE_LONG", confidence=0.85))
        self.assertEqual(session.state, NegotiationState.PROPOSED)

        session.accept("risk")
        self.assertEqual(session.state, NegotiationState.ACCEPTED)
        self.assertEqual(session.resolution.action, "EXECUTE_LONG")
        self.assertEqual(session.resolved_by, "risk")

    def test_propose_counter_accept(self):
        session = NegotiationSession(
            topic="BTC long", initiator="strategy", respondent="risk",
        )
        session.propose(Proposal(agent_id="strategy", action="EXECUTE_LONG", confidence=0.85))
        session.counter(Proposal(agent_id="risk", action="REDUCE_SIZE_50PCT", confidence=0.70))
        self.assertEqual(session.state, NegotiationState.COUNTERED)

        session.propose(Proposal(agent_id="strategy", action="REDUCE_SIZE_50PCT", confidence=0.80))
        session.accept("risk")
        self.assertEqual(session.state, NegotiationState.ACCEPTED)
        self.assertEqual(session.resolution.action, "REDUCE_SIZE_50PCT")

    def test_propose_reject(self):
        session = NegotiationSession(
            topic="BTC long", initiator="strategy", respondent="risk",
        )
        session.propose(Proposal(agent_id="strategy", action="EXECUTE_LONG", confidence=0.85))
        session.reject("risk", reason="too risky")
        self.assertEqual(session.state, NegotiationState.REJECTED)
        self.assertTrue(session.is_terminal)

    def test_round_counter_increments(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", max_rounds=5,
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        self.assertEqual(session.current_round, 1)
        session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))
        session.propose(Proposal(agent_id="a", action="Z", confidence=0.7))
        self.assertEqual(session.current_round, 2)


class TestDeadlock(unittest.TestCase):
    """Deadlock detection after max_rounds."""

    def test_deadlock_after_max_rounds(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", max_rounds=2,
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))
        session.propose(Proposal(agent_id="a", action="X2", confidence=0.55))
        # Round 2 reached, next counter should deadlock
        session.counter(Proposal(agent_id="b", action="Y2", confidence=0.65))
        self.assertEqual(session.state, NegotiationState.DEADLOCKED)
        self.assertTrue(session.is_terminal)

    def test_deadlock_preserves_proposals(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", max_rounds=1,
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))
        self.assertEqual(session.state, NegotiationState.DEADLOCKED)
        self.assertEqual(len(session.proposals), 1)  # counter not added when deadlocked


class TestExpiration(unittest.TestCase):
    """Session expiration on timeout."""

    def test_expired_session(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", timeout_seconds=0.01,
        )
        time.sleep(0.02)
        # propose() checks expiration first, sets state to EXPIRED, then raises
        with self.assertRaises(NegotiationError):
            session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        self.assertEqual(session.state, NegotiationState.EXPIRED)
        self.assertTrue(session.is_terminal)


class TestStateMachineEnforcement(unittest.TestCase):
    """Invalid state transitions raise NegotiationError."""

    def test_counter_without_propose_raises(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        with self.assertRaises(NegotiationError):
            session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))

    def test_propose_after_accept_raises(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.accept("b")
        with self.assertRaises(NegotiationError):
            session.propose(Proposal(agent_id="a", action="Z", confidence=0.5))

    def test_accept_without_proposal_raises(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        with self.assertRaises(NegotiationError):
            session.accept("b")

    def test_reject_after_reject_raises(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.reject("b")
        with self.assertRaises(NegotiationError):
            session.reject("a")


class TestCallbacks(unittest.TestCase):
    """Callback invocation on resolution."""

    def test_accept_fires_callback(self):
        cb = MagicMock()
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        session.on_resolved(cb)
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.accept("b")
        cb.assert_called_once_with(session)

    def test_reject_fires_callback(self):
        cb = MagicMock()
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        session.on_resolved(cb)
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.reject("b")
        cb.assert_called_once()

    def test_deadlock_fires_callback(self):
        cb = MagicMock()
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", max_rounds=1,
        )
        session.on_resolved(cb)
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))
        cb.assert_called_once()

    def test_callback_error_does_not_crash(self):
        def bad_cb(s):
            raise RuntimeError("boom")
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b",
        )
        session.on_resolved(bad_cb)
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.accept("b")  # Should not raise


class TestMediator(unittest.TestCase):
    """NegotiationMediator manages sessions and auto-resolves deadlocks."""

    def test_create_session(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "strategy", "risk")
        self.assertEqual(session.state, NegotiationState.OPEN)
        self.assertEqual(len(mediator.get_active_sessions()), 1)

    def test_resolved_session_tracked(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "strategy", "risk")
        session.propose(Proposal(agent_id="strategy", action="BUY", confidence=0.85))
        session.accept("risk")
        self.assertEqual(len(mediator.get_resolved_sessions()), 1)
        self.assertEqual(len(mediator.get_active_sessions()), 0)

    def test_auto_resolve_highest_confidence(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "a", "b", max_rounds=1)
        session.propose(Proposal(agent_id="a", action="BUY", confidence=0.85))
        session.counter(Proposal(agent_id="b", action="HOLD", confidence=0.60))
        self.assertEqual(session.state, NegotiationState.DEADLOCKED)

        result = mediator.auto_resolve_deadlock(session, "highest_confidence")
        self.assertIsNotNone(result)
        self.assertEqual(result.action, "BUY")
        self.assertEqual(session.state, NegotiationState.ACCEPTED)
        self.assertEqual(session.resolved_by, "mediator:highest_confidence")

    def test_auto_resolve_last_proposal(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "a", "b", max_rounds=1)
        session.propose(Proposal(agent_id="a", action="BUY", confidence=0.85))
        session.counter(Proposal(agent_id="b", action="HOLD", confidence=0.60))

        result = mediator.auto_resolve_deadlock(session, "last_proposal")
        self.assertEqual(result.action, "BUY")  # only propose was added, counter deadlocked

    def test_auto_resolve_initiator_wins(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "a", "b", max_rounds=1)
        session.propose(Proposal(agent_id="a", action="BUY", confidence=0.85))
        session.counter(Proposal(agent_id="b", action="HOLD", confidence=0.60))

        result = mediator.auto_resolve_deadlock(session, "initiator_wins")
        self.assertEqual(result.agent_id, "a")

    def test_auto_resolve_non_deadlocked_returns_none(self):
        mediator = NegotiationMediator()
        session = mediator.create_session("BTC", "a", "b")
        result = mediator.auto_resolve_deadlock(session)
        self.assertIsNone(result)

    def test_summary(self):
        mediator = NegotiationMediator()
        mediator.create_session("BTC", "a", "b")
        mediator.create_session("ETH", "a", "b")
        summary = mediator.get_summary()
        self.assertEqual(summary["total_sessions"], 2)
        self.assertEqual(summary["active_sessions"], 2)


class TestSerialization(unittest.TestCase):
    """Session serialization for dashboards."""

    def test_session_to_dict(self):
        session = NegotiationSession(
            topic="BTC long", initiator="strategy", respondent="risk",
        )
        session.propose(Proposal(agent_id="strategy", action="BUY", confidence=0.85))
        session.accept("risk")
        d = session.to_dict()
        serialized = json.dumps(d)
        self.assertIn("BTC long", serialized)
        self.assertIn("accepted", serialized)
        self.assertIn("BUY", serialized)

    def test_history_includes_all_proposals(self):
        session = NegotiationSession(
            topic="test", initiator="a", respondent="b", max_rounds=5,
        )
        session.propose(Proposal(agent_id="a", action="X", confidence=0.5))
        session.counter(Proposal(agent_id="b", action="Y", confidence=0.6))
        session.propose(Proposal(agent_id="a", action="Z", confidence=0.7))
        history = session.get_history()
        self.assertEqual(len(history), 3)


if __name__ == "__main__":
    unittest.main()
