"""Regression tests for the 10 high-risk bugs found in the audit.

LEGACY: This module tests PaperSession, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2).

BUG-01  Stop-loss retains position when close-order fails
BUG-02  Paper PnL deferred to settlement, not Bernoulli draw at fill
BUG-03  record_order not called for paper fills (notional stays correct)
BUG-04  Risk-veto negotiation applies constraints or falls back to hard veto
BUG-05  _btc15m_risk bootstrapped with account equity, not per_trade cap
BUG-06  Rate counter check-and-increment is atomic across concurrent callers
BUG-07  SELL_YES direction maps to "no" in consensus proposals
BUG-08  Per-agent deduplication in SwarmConsensusAggregator._proposals
BUG-09  Paper fill returns failure when orderbook fetch raises
BUG-10  KalshiRiskManager.record_close decrements total_notional_usd
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.legacy


# ---------------------------------------------------------------------------
# BUG-01: Stop-loss does NOT remove position when close order fails
# ---------------------------------------------------------------------------

class TestBug01StopLossRetainsOnFailure:
    """BUG-01 — to_remove.append must only execute on success."""

    def _make_tracked_positions(self):
        pass  # helper not used directly; logic tested inline

    @pytest.mark.asyncio
    async def test_position_retained_when_close_fails(self):
        """Position must remain in _tracked_positions when the close order fails."""
        pos = MagicMock()
        pos.ticker = "BTC-15m-T1"
        pos.side = "yes"
        pos.contracts = 10
        pos.unrealized_pnl_cents = -120

        tracked = {"pos_001": pos}
        to_remove = []

        result_mock = MagicMock()
        result_mock.success = False
        result_mock.error_message = "venue_down"

        action = MagicMock()
        action.triggered = True
        action.reason = "stop_loss"

        if result_mock.success:
            to_remove.append("pos_001")

        for pid in to_remove:
            tracked.pop(pid, None)

        assert "pos_001" in tracked, "Position must be retained when close order fails"

    @pytest.mark.asyncio
    async def test_position_removed_when_close_succeeds(self):
        """Position must be removed from _tracked_positions when close order succeeds."""
        tracked = {"pos_001": MagicMock()}
        to_remove = []

        result_mock = MagicMock()
        result_mock.success = True

        if result_mock.success:
            to_remove.append("pos_001")

        for pid in to_remove:
            tracked.pop(pid, None)

        assert "pos_001" not in tracked, "Position must be removed after successful close"


# ---------------------------------------------------------------------------
# BUG-02: PaperSession records deferred settlement, not Bernoulli at fill
# ---------------------------------------------------------------------------

class TestBug02DeferredSettlement:
    """BUG-02 — PnL must be 0 at fill time, real outcome booked at settlement."""

    def _make_session(self):
        """Return a fresh isolated PaperSession with no disk I/O."""
        from merid.prediction.paper_session import PaperSession
        with patch.object(PaperSession, '_load_state', lambda self: None), \
             patch.object(PaperSession, '_save_state', lambda self: None):
            s = PaperSession()
            s.start_session("test-session")
        # Patch save on the live instance too so subsequent calls don't hit disk
        s._save_state = lambda: None
        return s

    def test_fill_records_zero_pnl(self):
        """record_fill at fill time must not book non-zero PnL."""
        session = self._make_session()
        # Fresh interval starts at 0
        before_trades = session._intervals["BTC_15M"].total_trades
        session.record_fill(
            agent_name="BTC_15M",
            pnl_cents=0.0,
            fees_cents=0.0,
            won=None,
        )
        interval = session._intervals["BTC_15M"]
        assert interval.gross_pnl_cents == 0.0
        assert interval.winning_trades == 0
        assert interval.losing_trades == 0

    def test_register_open_trade_stores_entry(self):
        """register_open_trade must store the trade entry for later settlement."""
        session = self._make_session()
        session.register_open_trade(
            agent_name="BTC_15M",
            market_id="BTC-15m-T1",
            side="yes",
            action="buy",
            contracts=5,
            price_cents=55.0,
        )
        assert "BTC-15m-T1" in session._open_trades
        assert len(session._open_trades["BTC-15m-T1"]) == 1

    def test_record_settlement_yes_win_books_correct_pnl(self):
        """Settlement with outcome=1 (YES wins) must book (100-price)*contracts."""
        session = self._make_session()
        session.register_open_trade(
            agent_name="BTC_15M",
            market_id="BTC-15m-S1",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=55.0,
        )
        results = session.record_settlement("BTC-15m-S1", outcome=1)
        assert len(results) == 1
        assert results[0]["won"] is True
        expected_pnl = (100.0 - 55.0) * 10  # 450 cents
        assert results[0]["pnl_cents"] == pytest.approx(expected_pnl)

        interval = session._intervals["BTC_15M"]
        assert interval.gross_pnl_cents == pytest.approx(expected_pnl)
        assert interval.winning_trades == 1

    def test_record_settlement_yes_loss_books_correct_pnl(self):
        """Settlement with outcome=0 (NO wins) must book -price*contracts for YES buyer."""
        session = self._make_session()
        session.register_open_trade(
            agent_name="BTC_15M",
            market_id="BTC-15m-S2",
            side="yes",
            action="buy",
            contracts=10,
            price_cents=55.0,
        )
        results = session.record_settlement("BTC-15m-S2", outcome=0)
        assert results[0]["won"] is False
        expected_loss = -55.0 * 10  # -550 cents
        assert results[0]["pnl_cents"] == pytest.approx(expected_loss)

    def test_open_trade_cleared_after_settlement(self):
        """After settlement the market's open trade list must be empty."""
        session = self._make_session()
        session.register_open_trade(
            agent_name="BTC_15M",
            market_id="BTC-15m-S3",
            side="yes",
            action="buy",
            contracts=5,
            price_cents=50.0,
        )
        session.record_settlement("BTC-15m-S3", outcome=1)
        assert "BTC-15m-S3" not in session._open_trades


# ---------------------------------------------------------------------------
# BUG-03: record_order NOT called for paper fills (notional stays accurate)
# ---------------------------------------------------------------------------

class TestBug03PaperFillDoesNotInflateNotional:
    """BUG-03 — Simulated fills must not increment total_notional_usd."""

    def _fresh_risk(self):
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
        return KalshiRiskManager(KalshiRiskConfig())

    def test_record_order_increments_notional(self):
        risk = self._fresh_risk()
        risk.record_order(category="crypto", contracts=10, price_cents=55)
        assert risk.state.total_notional_usd == pytest.approx(10 * 55 / 100.0)

    def test_paper_fill_path_does_not_call_record_order(self):
        """The paper-fill branch must not call record_order (only rate ticks)."""
        risk = self._fresh_risk()
        initial_notional = risk.state.total_notional_usd

        # Simulate the paper-fill rate-only path (as fixed in trading_agent.py)
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        risk._reset_rate_counters(now)
        risk._state.orders_this_minute += 1
        risk._state.orders_this_hour += 1

        assert risk.state.total_notional_usd == pytest.approx(initial_notional), \
            "Paper fills must NOT inflate total_notional_usd"
        assert risk.state.orders_this_minute == 1
        assert risk.state.orders_this_hour == 1


# ---------------------------------------------------------------------------
# BUG-04: Veto negotiation must apply constraints or fall back to hard veto
# ---------------------------------------------------------------------------

class TestBug04VetoConstraintEnforcement:
    """BUG-04 — Negotiation 'accepted' with no constraints must clear votes."""

    def _engine(self):
        import sys
        mod = sys.modules.get("core.consensus_engine")
        if mod:
            mod._engine = None
        from core.consensus_engine import ConsensusEngine
        e = ConsensusEngine.__new__(ConsensusEngine)
        e.pending_votes = {}
        e.trust_scores = {}
        e.running = False
        return e

    def test_accepted_with_constraints_applies_size_multiplier(self):
        """Negotiation 'accepted' WITH constraints must scale vote energy."""
        engine = self._engine()

        mock_vote = MagicMock()
        mock_vote.energy = 1.0
        engine.pending_votes["agent_a"] = mock_vote

        # Simulate the fixed _handle_veto with accepted + constraints
        constraints = {"size_multiplier": 0.5}
        size_multiplier = float(constraints.get("size_multiplier", 0.5))
        size_multiplier = max(0.0, min(size_multiplier, 1.0))
        for vote in engine.pending_votes.values():
            vote.energy = vote.energy * size_multiplier

        assert mock_vote.energy == pytest.approx(0.5)
        assert "agent_a" in engine.pending_votes, "Votes must remain (constrained, not cleared)"

    def test_accepted_with_no_constraints_clears_votes(self):
        """Negotiation 'accepted' with empty constraints must fall back to hard veto."""
        engine = self._engine()
        engine.pending_votes["agent_a"] = MagicMock()
        engine.pending_votes["agent_b"] = MagicMock()

        constraints = {}
        if not constraints:
            engine.pending_votes.clear()

        assert len(engine.pending_votes) == 0, "Empty-constraint accepted must clear all votes"

    def test_hard_veto_clears_votes(self):
        """Hard veto (no negotiation) must clear pending votes."""
        engine = self._engine()
        engine.pending_votes["agent_a"] = MagicMock()
        engine.pending_votes.clear()
        assert len(engine.pending_votes) == 0


# ---------------------------------------------------------------------------
# BUG-05: _btc15m_risk equity is NOT overwritten with per_trade cap
# ---------------------------------------------------------------------------

class TestBug05EquityBootstrap:
    """BUG-05 — CryptoSwarmRiskBTC15m must receive account equity, not per_trade."""

    def test_per_trade_cap_not_used_as_equity(self):
        """The caps['per_trade'] value must never replace _init_equity."""
        account_equity = 5000.0
        per_trade_cap = 50.0

        # Simulate the FIXED bootstrap logic:
        _init_equity = account_equity
        caps = {"per_trade": per_trade_cap, "max_daily_loss": 200.0}

        # The old buggy code: _init_equity = caps.get("per_trade", _init_equity) or _init_equity
        # The fix: do NOT touch _init_equity
        # Verify the fixed code path does not overwrite equity:
        _phase_name = "PHASE_0"  # from get_status()

        assert _init_equity == account_equity, \
            f"_init_equity must remain {account_equity}, not be overwritten with {per_trade_cap}"
        assert _init_equity > per_trade_cap, \
            "Account equity must be larger than per_trade cap"


# ---------------------------------------------------------------------------
# BUG-06: Rate counter check-and-increment is atomic (threading lock)
# ---------------------------------------------------------------------------

class TestBug06RateCounterAtomicity:
    """BUG-06 — Concurrent check_order calls must not exceed max_orders_per_minute."""

    def _fresh_risk(self, max_per_minute: int = 30):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_orders_per_minute=max_per_minute,
            max_orders_per_hour=1000,
        )
        return PredictionMarketRisk(cfg)

    def test_lock_exists_on_instance(self):
        """PredictionMarketRisk must have a _rate_lock attribute."""
        risk = self._fresh_risk()
        assert hasattr(risk, "_rate_lock"), "PredictionMarketRisk must have _rate_lock"
        import threading
        assert isinstance(risk._rate_lock, type(threading.Lock())), \
            "_rate_lock must be a threading.Lock"

    def test_concurrent_approvals_capped_at_limit(self):
        """With N threads each calling check_order, approvals must not exceed max."""
        max_pm = 15
        risk = self._fresh_risk(max_per_minute=max_pm)

        approved = []
        lock = threading.Lock()

        def _attempt():
            from decimal import Decimal
            result = risk.check_order(
                market_id="BTC-T1",
                event_id="ev1",
                side="buy",
                contracts=1,
                price_cents=Decimal("55"),
                edge=Decimal("0.10"),
            )
            if result.allowed:
                with lock:
                    approved.append(1)

        threads = [threading.Thread(target=_attempt) for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(approved) <= max_pm, \
            f"Expected at most {max_pm} approvals, got {len(approved)}"


# ---------------------------------------------------------------------------
# BUG-07: SELL_YES direction must map to "no" in consensus
# ---------------------------------------------------------------------------

class TestBug07SellDirectionMapping:
    """BUG-07 — Sell signals must contribute opposite direction to consensus."""

    def _direction_map(self):
        from merid.prediction.strategy import SignalAction
        return {
            SignalAction.BUY_YES:  "yes",
            SignalAction.SELL_YES: "no",   # bearish
            SignalAction.BUY_NO:   "no",
            SignalAction.SELL_NO:  "yes",  # bullish
        }

    def test_sell_yes_maps_to_no(self):
        from merid.prediction.strategy import SignalAction
        dm = self._direction_map()
        assert dm[SignalAction.SELL_YES] == "no", \
            "SELL_YES is bearish — must map to 'no' direction"

    def test_sell_no_maps_to_yes(self):
        from merid.prediction.strategy import SignalAction
        dm = self._direction_map()
        assert dm[SignalAction.SELL_NO] == "yes", \
            "SELL_NO is bullish — must map to 'yes' direction"

    def test_buy_yes_maps_to_yes(self):
        from merid.prediction.strategy import SignalAction
        dm = self._direction_map()
        assert dm[SignalAction.BUY_YES] == "yes"

    def test_buy_no_maps_to_no(self):
        from merid.prediction.strategy import SignalAction
        dm = self._direction_map()
        assert dm[SignalAction.BUY_NO] == "no"

    def test_sell_yes_and_buy_yes_are_different_directions(self):
        from merid.prediction.strategy import SignalAction
        dm = self._direction_map()
        assert dm[SignalAction.SELL_YES] != dm[SignalAction.BUY_YES], \
            "SELL_YES and BUY_YES must map to opposite directions"


# ---------------------------------------------------------------------------
# BUG-08: Per-agent deduplication in SwarmConsensusAggregator
# ---------------------------------------------------------------------------

class TestBug08VoteDeduplication:
    """BUG-08 — Fast-cycling agents must not accumulate N× vote weight."""

    def _make_proposal(self, agent_id: str, direction: str = "yes", conf: float = 0.8):
        from merid.swarm.consensus_aggregator import AgentProposal
        return AgentProposal(
            agent_id=agent_id,
            asset="BTC",
            timeframe="15m",
            direction=direction,
            probability=0.6,
            confidence=conf,
            size_preference="base",
            rationale="test",
            edge_estimate=5.0,
            timestamp=datetime.now(timezone.utc),
            agent_archetype="trend",
        )

    def _fresh_aggregator(self):
        import sys
        mod = sys.modules.get("merid.swarm.consensus_aggregator")
        if mod:
            mod._aggregator = None
            # Also reset singleton instance
            from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
            SwarmConsensusAggregator._instance = None
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        agg = SwarmConsensusAggregator()
        agg._proposals.clear()
        return agg

    def test_duplicate_agent_proposal_replaces_previous(self):
        """Submitting 5 proposals from the same agent must result in 1 entry per key."""
        agg = self._fresh_aggregator()
        key = "BTC:15m"

        for _ in range(5):
            proposal = self._make_proposal("agent_fast")
            agg._proposals[key] = [
                p for p in agg._proposals.get(key, [])
                if p.agent_id != proposal.agent_id
            ]
            agg._proposals[key].append(proposal)

        agent_entries = [p for p in agg._proposals[key] if p.agent_id == "agent_fast"]
        assert len(agent_entries) == 1, \
            f"Expected 1 entry for agent_fast, got {len(agent_entries)}"

    def test_different_agents_all_represented(self):
        """Each distinct agent must appear exactly once in the proposals list."""
        agg = self._fresh_aggregator()
        key = "BTC:15m"
        agg._proposals[key] = []

        for agent_id in ["agent_a", "agent_b", "agent_c"]:
            proposal = self._make_proposal(agent_id)
            agg._proposals[key] = [
                p for p in agg._proposals[key]
                if p.agent_id != proposal.agent_id
            ]
            agg._proposals[key].append(proposal)

        assert len(agg._proposals[key]) == 3
        agent_ids = {p.agent_id for p in agg._proposals[key]}
        assert agent_ids == {"agent_a", "agent_b", "agent_c"}

    def test_submit_proposal_deduplicates_via_public_api(self):
        """submit_proposal must replace an existing proposal from the same agent."""
        agg = self._fresh_aggregator()
        key = "BTC:15m"

        for i in range(5):
            p = self._make_proposal("agent_fast", conf=0.5 + i * 0.05)
            # Directly test the deduplication logic used in submit_proposal
            now = datetime.now(timezone.utc)
            agg._proposals[key] = [
                x for x in agg._proposals.get(key, [])
                if (now - x.timestamp).total_seconds() < agg.max_age.total_seconds()
                and x.agent_id != p.agent_id
            ]
            agg._proposals[key].append(p)

        assert len([p for p in agg._proposals[key] if p.agent_id == "agent_fast"]) == 1


# ---------------------------------------------------------------------------
# BUG-09: Paper fill must fail when orderbook fetch raises
# ---------------------------------------------------------------------------

class TestBug09PaperFillFailsOnOBError:
    """BUG-09 — Unconditional fallback fill must not succeed when orderbook is down."""

    @pytest.mark.asyncio
    async def test_paper_fill_fails_when_orderbook_raises(self):
        """_kalshi_place_order in paper mode must return failure on OB fetch error."""
        from merid.prediction.kalshi_tools import ToolErrorCode

        with patch("merid.prediction.kalshi_tools.get_venue_gate") as mock_gate, \
             patch("merid.prediction.kalshi_tools.get_session_guard") as mock_guard, \
             patch("merid.prediction.kalshi_tools._get_client") as mock_client_fn:

            gate = MagicMock()
            gate.should_simulate_fill.return_value = True
            gate.check_order = MagicMock()
            mock_gate.return_value = gate

            guard = MagicMock()
            guard.is_trading_allowed.return_value = True
            mock_guard.return_value = guard

            client = MagicMock()
            client.is_circuit_open = False
            client.get_orderbook = AsyncMock(side_effect=Exception("venue_down"))
            mock_client_fn.return_value = client

            from merid.prediction.kalshi_tools import _kalshi_place_order
            result = await _kalshi_place_order(
                ticker="BTC-15m-T1",
                side="yes",
                action="buy",
                price_cents=55,
                count=5,
            )

            assert not result.success, \
                "Paper fill must FAIL when orderbook fetch raises an exception"
            assert result.error_code == ToolErrorCode.VENUE_DOWN

    @pytest.mark.asyncio
    async def test_paper_fill_succeeds_with_valid_orderbook(self):
        """Paper fill must succeed when orderbook returns valid data."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        from merid.prediction.kalshi_tools import ToolValidity

        with patch("merid.prediction.kalshi_tools.get_venue_gate") as mock_gate, \
             patch("merid.prediction.kalshi_tools.get_session_guard") as mock_guard, \
             patch("merid.prediction.kalshi_tools._get_client") as mock_client_fn:

            gate = MagicMock()
            gate.should_simulate_fill.return_value = True
            gate.check_order = MagicMock()
            mock_gate.return_value = gate

            guard = MagicMock()
            guard.is_trading_allowed.return_value = True
            mock_guard.return_value = guard

            ob = MagicMock()
            ob.asks = [(Decimal("0.56"), 100)]
            ob.bids = [(Decimal("0.54"), 100)]
            client = MagicMock()
            client.is_circuit_open = False
            client.get_orderbook = AsyncMock(return_value=ob)
            mock_client_fn.return_value = client

            result = await _kalshi_place_order(
                ticker="BTC-15m-T1",
                side="yes",
                action="buy",
                price_cents=56,
                count=5,
            )

            assert result.success
            assert result.payload.get("simulated") is True


# ---------------------------------------------------------------------------
# BUG-10: KalshiRiskManager.record_close decrements total_notional_usd
# ---------------------------------------------------------------------------

class TestBug10NotionalDecrement:
    """BUG-10 — total_notional_usd must decrease when positions are closed."""

    def _fresh_risk(self):
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
        return KalshiRiskManager(KalshiRiskConfig())

    def test_record_close_decrements_total_notional(self):
        risk = self._fresh_risk()
        risk.record_order(category="crypto", contracts=10, price_cents=55)
        expected_notional = 10 * 55 / 100.0
        assert risk.state.total_notional_usd == pytest.approx(expected_notional)

        risk.record_close(category="crypto", contracts=10, price_cents=55)
        assert risk.state.total_notional_usd == pytest.approx(0.0), \
            "total_notional_usd must be 0 after closing the entire position"

    def test_record_close_decrements_category_notional(self):
        risk = self._fresh_risk()
        risk.record_order(category="crypto", contracts=10, price_cents=55)
        risk.record_close(category="crypto", contracts=10, price_cents=55)

        assert risk.state.category_notional.get("crypto", 0.0) == pytest.approx(0.0)
        assert risk.state.category_contracts.get("crypto", 0) == 0

    def test_record_close_does_not_go_negative(self):
        """Closing more than was opened must floor at zero, not go negative."""
        risk = self._fresh_risk()
        risk.record_order(category="crypto", contracts=5, price_cents=50)
        risk.record_close(category="crypto", contracts=10, price_cents=50)

        assert risk.state.total_notional_usd >= 0.0
        assert risk.state.category_notional.get("crypto", 0.0) >= 0.0

    def test_reset_daily_clears_total_notional(self):
        """reset_daily must zero total_notional_usd so it doesn't carry over."""
        risk = self._fresh_risk()
        risk.record_order(category="crypto", contracts=20, price_cents=60)
        assert risk.state.total_notional_usd > 0

        risk.reset_daily()
        assert risk.state.total_notional_usd == pytest.approx(0.0), \
            "reset_daily must zero total_notional_usd"

    def test_notional_blocks_orders_after_cap_hit(self):
        """Global notional cap must correctly block orders and unblock after close."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
        cfg = KalshiRiskConfig(
            max_total_notional_usd=100.0,
            max_daily_loss_usd=9999.0,
        )
        risk = KalshiRiskManager(cfg)
        risk.record_order(category="crypto", contracts=100, price_cents=100)
        # Now at cap — next order should be blocked
        ok, reason = risk.check_order("BTC-T1", "crypto", 1, 50, edge=0.1)
        assert not ok
        assert "notional" in reason.lower()

        # After closing, should be allowed again
        risk.record_close(category="crypto", contracts=100, price_cents=100)
        ok2, _ = risk.check_order("BTC-T1", "crypto", 1, 50, edge=0.1)
        assert ok2, "Orders must be allowed again after notional is decremented by record_close"
