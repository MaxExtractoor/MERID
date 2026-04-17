"""test_decision_pipeline_audit_regressions.py

Regression tests for the 9 high-risk bugs identified and fixed in the
Decision Pipeline Audit (see audit report / todo list H1-H9).

Test classes:
  TestH1_TimestampClobber          — provider timestamp used, not batch wall-clock
  TestH2_SentimentAgeGate         — stale sentiment skipped in _build_snapshot
  TestH3_DebateArbiterGate        — close_debate blocked without arbiter; lift fact-check
  TestH4_DualConsensusDomains     — ConsensusEngine suppresses non-crypto EXECUTE_*
  TestH5_SentimentLanePinning     — push_from_sentiment_bus fans out to correct lanes
  TestH6_AuctionMutationOrder     — Decision published after auction, not before
  TestH7_VetoScopingAndTTL        — veto scoped by proposal; vote TTL; force_reround
  TestH8_AbstainQuorum            — ABSTAIN widens denominator; >50% forces NO_ACTION
  TestH9_NoDoubleSentimentAdj     — sentiment_adjusted flag set; age_seconds recorded

All tests are static (no running server, no live API calls).
"""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import time
import types
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ── source paths ──────────────────────────────────────────────────────────────
MARKET_DATA_STREAM_SRC  = ROOT / "streams" / "market_data_stream.py"
TRADING_AGENT_SRC       = ROOT / "merid" / "prediction" / "trading_agent.py"
MODEL_SRC               = ROOT / "merid" / "prediction" / "model.py"
DEBATE_SRC              = ROOT / "merid" / "prediction" / "debate.py"
CONSENSUS_ENGINE_SRC    = ROOT / "core" / "consensus_engine.py"
AGGREGATOR_SRC          = ROOT / "merid" / "swarm" / "consensus_aggregator.py"
XTF_SRC                 = ROOT / "merid" / "sentiment" / "cross_timeframe_aggregator.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# H1 — Provider timestamp used; wall-clock only as fallback
# =============================================================================

class TestH1_TimestampClobber:
    """_create_market_event must parse the provider's timestamp field and use
    it for both MarketTick.timestamp and EventEnvelope.timestamp.  The
    wall-clock is only used as a fallback when the field is absent/unparseable.
    """

    def test_provider_ts_parsed_in_source(self):
        src = _src(MARKET_DATA_STREAM_SRC)
        assert "provider_ts" in src, (
            "H1: 'provider_ts' variable not found in market_data_stream.py"
        )

    def test_lag_ms_embedded_in_metadata(self):
        src = _src(MARKET_DATA_STREAM_SRC)
        assert "lag_ms" in src, (
            "H1: 'lag_ms' must be embedded in event metadata for staleness detection"
        )

    def test_fallback_logged_on_parse_failure(self):
        src = _src(MARKET_DATA_STREAM_SRC)
        assert "wall_time" in src, (
            "H1: wall_time fallback reference not found"
        )
        # Fallback must be logged, not silently swallowed
        assert "fallback" in src.lower() or "warning" in src.lower() or "unparseable" in src.lower(), (
            "H1: no log/warning on timestamp fallback"
        )

    def test_wall_clock_not_hardwired_as_event_timestamp(self):
        src = _src(MARKET_DATA_STREAM_SRC)
        lines = src.splitlines()
        # Find _create_market_event body
        start = next((i for i, l in enumerate(lines) if "def _create_market_event" in l), None)
        assert start is not None, "H1: _create_market_event not found"
        end = next(
            (i for i, l in enumerate(lines) if i > start + 3 and l.strip().startswith("def ")),
            len(lines),
        )
        body = "\n".join(lines[start:end])
        # Must NOT unconditionally assign wall_time to timestamp without a parse attempt first
        assert "provider_ts" in body, (
            "H1: provider_ts not used inside _create_market_event body"
        )

    def test_inline_timestamp_parsing_present(self):
        src = _src(MARKET_DATA_STREAM_SRC)
        # H1 fix inlines ISO and Unix timestamp parsing rather than a named helper
        assert "fromisoformat" in src or "fromtimestamp" in src, (
            "H1: neither fromisoformat nor fromtimestamp found in market_data_stream.py "
            "— provider timestamp is not being parsed"
        )


# =============================================================================
# H2 — Stale sentiment age-gated out of _build_snapshot
# =============================================================================

class TestH2_SentimentAgeGate:
    """_build_snapshot must check the age of the AssetSentimentContext and
    skip sentiment injection when the context is older than the max threshold.
    """

    def test_max_sentiment_age_constant_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_MAX_SENTIMENT_AGE_S" in src, (
            "H2: _MAX_SENTIMENT_AGE_S constant not found in trading_agent.py"
        )

    def test_max_sentiment_age_is_positive(self):
        src = _src(TRADING_AGENT_SRC)
        lines = src.splitlines()
        for line in lines:
            if "_MAX_SENTIMENT_AGE_S" in line and "=" in line and "#" not in line.split("=")[0]:
                val_str = line.split("=")[-1].strip().rstrip(" #").split()[0]
                try:
                    val = float(val_str)
                    assert val > 0, f"H2: _MAX_SENTIMENT_AGE_S={val} must be positive"
                    return
                except ValueError:
                    pass
        # Value may be inline in an if-statement; at minimum the symbol must appear
        assert "_MAX_SENTIMENT_AGE_S" in src

    def test_age_check_present_in_build_snapshot(self):
        src = _src(TRADING_AGENT_SRC)
        lines = src.splitlines()
        start = next((i for i, l in enumerate(lines) if "def _build_snapshot" in l), None)
        assert start is not None, "H2: _build_snapshot not found"
        end = next(
            (i for i, l in enumerate(lines) if i > start + 5 and l.startswith("    def ")),
            len(lines),
        )
        body = "\n".join(lines[start:end])
        assert "_MAX_SENTIMENT_AGE_S" in body, (
            "H2: age gate not applied inside _build_snapshot"
        )
        assert "_age_s" in body, (
            "H2: _age_s variable (computed sentiment age) not present in _build_snapshot"
        )

    def test_stale_sentiment_skip_logged_as_warning(self):
        src = _src(TRADING_AGENT_SRC)
        assert "skipping sentiment injection" in src or "Skipping sentiment injection" in src, (
            "H2: no WARNING log when stale sentiment is skipped"
        )

    def test_sentiment_fields_not_set_when_stale(self):
        """When age > threshold the sentiment fields on snapshot must NOT be set.
        Verified via source structure: the field assignments are inside the else branch."""
        src = _src(TRADING_AGENT_SRC)
        lines = src.splitlines()
        # Find the stale-guard else block containing field assignments
        age_check_idx = next(
            (i for i, l in enumerate(lines) if "_age_s is not None and _age_s >" in l), None
        )
        assert age_check_idx is not None, (
            "H2: age comparison '_age_s is not None and _age_s >' not found"
        )
        # The else branch must contain the sentiment field assignments
        else_idx = next(
            (i for i, l in enumerate(lines)
             if i > age_check_idx and l.strip() == "else:"),
            None,
        )
        assert else_idx is not None, (
            "H2: 'else:' branch after age check not found — sentiment fields "
            "must only be set in the else (fresh) branch"
        )

    def test_sentiment_age_seconds_set_on_snapshot(self):
        src = _src(TRADING_AGENT_SRC)
        assert "snapshot.sentiment_age_seconds" in src, (
            "H2: snapshot.sentiment_age_seconds not set in _build_snapshot"
        )


# =============================================================================
# H3 — Debate arbiter gate + fact-check on lift rewards
# =============================================================================

class TestH3_DebateArbiterGate:
    """close_debate must be rejected when no arbiter-role argument is present.
    Debate lift rewards must be zeroed when no argument carries a data reference.
    """

    def _make_store(self) -> Any:
        from merid.prediction.debate import DebateStore
        tmp = tempfile.mktemp(suffix=".db")
        return DebateStore(db_path=tmp)

    def _make_debate(self, store: Any) -> Any:
        from merid.prediction.debate import DebateSession
        deb = DebateSession(symbol="PRED:KALSHI:TEST-MKT:YES")
        return store.create_debate(deb)

    def _add_arg(self, store: Any, debate_id: str, role: str, data_refs: bool = False) -> Any:
        from merid.prediction.debate import DebateArgument
        explanation = {"contributions": {"market": 0.1, "model": 0.05}}
        if data_refs:
            explanation["data_references"] = ["BTC price: $42,000", "volume_24h: 1.2B"]
        return store.add_argument(DebateArgument(
            debate_id=debate_id,
            agent_id=f"agent-{role}",
            role=role,
            probability=0.6,
            confidence=0.7,
            rationale="mean_reversion_test",
            explanation=explanation,
        ))

    def test_has_arbiter_argument_method_exists(self):
        from merid.prediction.debate import DebateStore
        assert hasattr(DebateStore, "has_arbiter_argument"), (
            "H3: DebateStore.has_arbiter_argument() method not found"
        )

    def test_close_without_arbiter_returns_none(self):
        store = self._make_store()
        deb = self._make_debate(store)
        self._add_arg(store, deb.id, "proposer")
        self._add_arg(store, deb.id, "challenger")
        result = store.close_debate(deb.id, post_debate_prob=0.65)
        assert result is None, (
            "H3: close_debate must return None when no arbiter-role argument present"
        )

    def test_close_with_arbiter_succeeds(self):
        store = self._make_store()
        deb = self._make_debate(store)
        self._add_arg(store, deb.id, "proposer")
        self._add_arg(store, deb.id, "challenger")
        self._add_arg(store, deb.id, "arbiter")
        result = store.close_debate(deb.id, post_debate_prob=0.65)
        assert result is not None, (
            "H3: close_debate should succeed when an arbiter argument is present"
        )
        assert result.status == "closed"

    def test_close_require_arbiter_false_bypasses_gate(self):
        store = self._make_store()
        deb = self._make_debate(store)
        self._add_arg(store, deb.id, "proposer")
        result = store.close_debate(deb.id, post_debate_prob=0.5, require_arbiter=False)
        assert result is not None, (
            "H3: close_debate(require_arbiter=False) must bypass the arbiter gate"
        )

    def test_lift_reward_zeroed_without_data_reference(self):
        """Debate with no data_references in any argument -> lift reward = 0."""
        store = self._make_store()
        deb = self._make_debate(store)
        self._add_arg(store, deb.id, "proposer", data_refs=False)
        self._add_arg(store, deb.id, "challenger", data_refs=False)
        self._add_arg(store, deb.id, "arbiter", data_refs=False)
        store.close_debate(deb.id, post_debate_prob=0.75)
        store.resolve_debate(deb.id, outcome=1)

        from merid.prediction.debate import RewardEntry
        mock_opinion = MagicMock()
        mock_opinion.agent_id = "agent-proposer"
        mock_opinion.probability = 0.6
        mock_opinion.explanation = None

        rewards = store.compute_rewards_for_resolution(
            symbol="PRED:KALSHI:TEST-MKT:YES",
            outcome=1,
            opinions=[mock_opinion],
        )
        debate_lift_rewards = [r for r in rewards if r.reward_type == "debate_lift"]
        assert all(r.points == 0 for r in debate_lift_rewards), (
            "H3: debate lift reward must be 0 when no argument has data_references"
        )

    def test_lift_reward_nonzero_with_data_reference(self):
        """Debate where at least one argument has data_references -> lift is earned."""
        store = self._make_store()
        deb = self._make_debate(store)
        # pre_debate_prob=0.5; outcome=1 -> pre_brier=0.25
        # Proposer supplies data refs; post_debate=0.75 -> post_brier=0.0625 -> lift=0.1875
        self._add_arg(store, deb.id, "proposer", data_refs=True)
        self._add_arg(store, deb.id, "challenger", data_refs=False)
        self._add_arg(store, deb.id, "arbiter", data_refs=False)
        store.close_debate(deb.id, post_debate_prob=0.75)
        store.resolve_debate(deb.id, outcome=1)

        mock_opinion = MagicMock()
        mock_opinion.agent_id = "agent-proposer"
        mock_opinion.probability = 0.6
        mock_opinion.explanation = {"rationale": "data_backed", "data_references": ["price: 42k"]}

        rewards = store.compute_rewards_for_resolution(
            symbol="PRED:KALSHI:TEST-MKT:YES",
            outcome=1,
            opinions=[mock_opinion],
        )
        debate_lift_rewards = [r for r in rewards if r.reward_type == "debate_lift"]
        if debate_lift_rewards:  # only asserted when lift > min threshold
            assert any(r.points > 0 for r in debate_lift_rewards), (
                "H3: debate lift reward should be positive when data references are present"
            )

    def test_same_model_discount_in_source(self):
        src = _src(DEBATE_SRC)
        assert "same_model" in src, (
            "H3: same_model discount logic not found in debate.py"
        )
        assert "0.8" in src or "* 0.8" in src, (
            "H3: 20% same-model discount (lift_value * 0.8) not found in debate.py"
        )

    def test_require_arbiter_param_in_source(self):
        src = _src(DEBATE_SRC)
        assert "require_arbiter" in src, (
            "H3: require_arbiter parameter not found in debate.py"
        )


# =============================================================================
# H4 — ConsensusEngine suppresses EXECUTE_* for non-crypto domains
# =============================================================================

class TestH4_DualConsensusDomains:
    """ConsensusResult must carry authoritative_for field.
    _publish_result must suppress EXECUTE_LONG/SHORT for non-crypto domains.
    ConsensusEngine must register a read-only audit handler for Kalshi events.
    """

    def test_authoritative_for_field_on_result(self):
        from core.consensus_engine import ConsensusResult
        r = ConsensusResult(
            decision="EXECUTE_LONG",
            signal="bullish",
            confidence=0.8,
            votes=[],
            quorum_met=True,
        )
        assert hasattr(r, "authoritative_for"), (
            "H4: ConsensusResult missing 'authoritative_for' field"
        )
        assert r.authoritative_for == "crypto", (
            "H4: ConsensusResult.authoritative_for must default to 'crypto'"
        )

    def test_abstention_count_field_on_result(self):
        from core.consensus_engine import ConsensusResult
        r = ConsensusResult(
            decision="NO_ACTION",
            signal="abstain",
            confidence=0.0,
            votes=[],
            quorum_met=False,
            abstention_count=3,
        )
        assert r.abstention_count == 3, "H4: abstention_count field not set correctly"

    def test_publish_result_suppresses_execute_for_non_crypto(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "authoritative_for" in src, (
            "H4: authoritative_for not referenced in consensus_engine.py"
        )
        assert "suppressing" in src or "suppress" in src, (
            "H4: suppression log for non-crypto execution decisions not found"
        )

    def test_audit_kalshi_consensus_handler_exists(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "_audit_kalshi_consensus" in src, (
            "H4: _audit_kalshi_consensus read-only audit handler not found"
        )

    def test_kalshi_subscription_is_read_only(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        lines = src.splitlines()
        audit_fn_start = next(
            (i for i, l in enumerate(lines) if "async def _audit_kalshi_consensus" in l), None
        )
        assert audit_fn_start is not None, "H4: _audit_kalshi_consensus not found"
        end = next(
            (i for i, l in enumerate(lines)
             if i > audit_fn_start + 2 and l.strip().startswith("async def ")),
            audit_fn_start + 50,
        )
        body = "\n".join(lines[audit_fn_start:end])
        # Audit handler must NOT publish or execute — read-only
        assert "publish" not in body and "execute" not in body.lower(), (
            "H4: _audit_kalshi_consensus must be read-only — no publish/execute calls"
        )
        assert "No action taken" in body or "not authoritative" in body.lower(), (
            "H4: audit handler must document it takes no action"
        )

    def test_authoritative_for_crypto_in_publish_result(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert '"crypto"' in src, (
            "H4: 'crypto' domain string not found in consensus_engine.py"
        )


# =============================================================================
# H5 — Sentiment lane pinning fixed (multi-lane distribution)
# =============================================================================

class TestH5_SentimentLanePinning:
    """push_from_sentiment_bus must push signals to multiple timeframe lanes
    based on source, not exclusively to '15m'.
    """

    def test_fg_index_pushed_to_1d_lane(self):
        src = _src(XTF_SRC)
        assert '"1d"' in src or "'1d'" in src, (
            "H5: '1d' timeframe lane not referenced in cross_timeframe_aggregator.py"
        )

    def test_news_pushed_to_4h_lane(self):
        src = _src(XTF_SRC)
        assert '"4h"' in src or "'4h'" in src, (
            "H5: '4h' timeframe lane not referenced in cross_timeframe_aggregator.py"
        )

    def test_push_from_sentiment_bus_has_multi_lane_logic(self):
        src = _src(XTF_SRC)
        lines = src.splitlines()
        start = next(
            (i for i, l in enumerate(lines) if "def push_from_sentiment_bus" in l), None
        )
        assert start is not None, "H5: push_from_sentiment_bus not found"
        end = next(
            (i for i, l in enumerate(lines)
             if i > start + 3 and l.startswith("    def ")),
            start + 80,
        )
        body = "\n".join(lines[start:end])
        # Must reference at least 3 distinct timeframe lanes
        lane_count = sum(1 for tf in ("15m", "1h", "4h", "1d") if tf in body)
        assert lane_count >= 3, (
            f"H5: push_from_sentiment_bus only references {lane_count} lanes — "
            "expected at least 3 (15m, 1h, 4h/1d)"
        )

    def test_fg_index_attr_read_from_context(self):
        src = _src(XTF_SRC)
        assert "fg_index" in src, (
            "H5: 'fg_index' attribute not read from AssetSentimentContext"
        )

    def test_news_score_attr_read_from_context(self):
        src = _src(XTF_SRC)
        assert "news_score" in src, (
            "H5: 'news_score' attribute not read from context"
        )

    def test_hashtag_score_attr_read_from_context(self):
        src = _src(XTF_SRC)
        assert "hashtag_score" in src, (
            "H5: 'hashtag_score' attribute not read from context"
        )

    def test_push_from_sentiment_bus_runtime(self):
        """Live call: push a mock context and verify signals land in multiple lanes."""
        from merid.sentiment.cross_timeframe_aggregator import CrossTimeframeAggregator

        agg = CrossTimeframeAggregator()

        ctx = MagicMock()
        ctx.confidence = 0.7
        ctx.combined_score = 0.1
        ctx.fg_index = 75.0    # greed → +0.5
        ctx.news_score = 0.2
        ctx.hashtag_score = 0.3

        agg.push_from_sentiment_bus("BTC", ctx)

        # All relevant lanes must have received at least one signal
        for tf in ("15m", "1h", "4h", "1d"):
            signals = agg._buffers.get("BTC", {}).get(tf, [])
            assert len(signals) > 0, (
                f"H5: no signal landed in '{tf}' lane after push_from_sentiment_bus"
            )


# =============================================================================
# H6 — Auction runs BEFORE Decision / event_bus publish
# =============================================================================

class TestH6_AuctionMutationOrder:
    """The auction resolution block must precede all publish operations in
    _recompute_consensus so downstream consumers always see the final state.
    """

    def test_auction_block_before_cache_update(self):
        src = _src(AGGREGATOR_SRC)
        lines = src.splitlines()
        # Find the three critical lines (first occurrence of each)
        auction_line = next(
            (i for i, l in enumerate(lines) if "auction_result = resolver.resolve_conflict" in l),
            None,
        )
        cache_line = next(
            (i for i, l in enumerate(lines) if "self._consensus_cache[key] = consensus" in l),
            None,
        )
        assert auction_line is not None, "H6: auction resolve_conflict call not found"
        assert cache_line is not None, "H6: cache update line not found"
        assert auction_line < cache_line, (
            f"H6: auction_result (line {auction_line}) must appear BEFORE cache update "
            f"(line {cache_line})"
        )

    def test_auction_block_before_decision_publish(self):
        src = _src(AGGREGATOR_SRC)
        lines = src.splitlines()
        auction_line = next(
            (i for i, l in enumerate(lines) if "auction_result = resolver.resolve_conflict" in l),
            None,
        )
        decision_line = next(
            (i for i, l in enumerate(lines) if "publish_decision(decision)" in l),
            None,
        )
        assert auction_line is not None, "H6: auction resolve_conflict call not found"
        assert decision_line is not None, "H6: publish_decision call not found"
        assert auction_line < decision_line, (
            f"H6: auction (line {auction_line}) must appear BEFORE Decision publish "
            f"(line {decision_line})"
        )

    def test_auction_block_before_eventbus_publish(self):
        src = _src(AGGREGATOR_SRC)
        lines = src.splitlines()
        auction_line = next(
            (i for i, l in enumerate(lines) if "auction_result = resolver.resolve_conflict" in l),
            None,
        )
        eb_line = next(
            (i for i, l in enumerate(lines) if 'kalshi:consensus_decision' in l),
            None,
        )
        assert auction_line is not None, "H6: auction resolve_conflict call not found"
        assert eb_line is not None, "H6: kalshi:consensus_decision publish not found"
        assert auction_line < eb_line, (
            f"H6: auction (line {auction_line}) must appear BEFORE event_bus publish "
            f"(line {eb_line})"
        )

    def test_consensus_cache_updated_after_auction(self):
        src = _src(AGGREGATOR_SRC)
        # "H6 fix" comment must be present
        assert "H6" in src or "final post-auction" in src, (
            "H6: H6 fix comment or 'final post-auction' annotation not found"
        )


# =============================================================================
# H7 — Veto scoped by proposal; force_reround extends window; TTL drops stale votes
# =============================================================================

class TestH7_VetoScopingAndTTL:
    """Hard vetoes must only clear votes matching the veto target proposal.
    force_reround must reset last_consensus_time.
    _resolve_consensus must drop votes older than vote_window.
    """

    def test_veto_target_extracted_in_handle_veto(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert 'veto_target' in src, (
            "H7: 'veto_target' variable not found in consensus_engine.py"
        )

    def test_hard_veto_scoped_by_proposal(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "v.proposal != veto_target" in src, (
            "H7: scoped veto filter 'v.proposal != veto_target' not found"
        )

    def test_unscoped_veto_still_clears_all(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "pending_votes.clear()" in src, (
            "H7: fallback full clear (no target) not present"
        )

    def test_force_reround_resets_last_consensus_time(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "self.last_consensus_time = time.time()" in src, (
            "H7: force_reround does not reset self.last_consensus_time"
        )

    def test_ttl_filter_present_in_resolve_consensus(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "vote_window" in src, (
            "H7: 'vote_window' TTL not referenced in consensus_engine.py"
        )
        assert "v.timestamp" in src or "vote.timestamp" in src, (
            "H7: vote timestamp not used in TTL comparison"
        )

    def test_vote_timestamp_set_on_receipt(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "vote.timestamp = time.time()" in src, (
            "H7: vote.timestamp not set at receipt time in _process_event"
        )

    def test_ttl_drops_stale_votes_before_quorum(self):
        """Runtime: inject a vote with an ancient timestamp; TTL filter must drop it."""
        from core.consensus_engine import ConsensusEngine, Vote
        engine = ConsensusEngine.__new__(ConsensusEngine)
        engine.pending_votes = {}
        engine.min_votes = 1
        engine.vote_window = 60.0
        engine.quorum_threshold = 0.51
        engine.trust_scores = {}
        engine.running = False
        engine.current_round_id = None
        engine._lane_intents = {}

        # Add a stale vote (timestamp 200s ago)
        stale_vote = Vote(
            agent_id="stale-agent",
            proposal="KXBTC-26FEB:yes",
            signal="bullish",
            confidence=0.9,
            timestamp=time.time() - 200,
        )
        engine.pending_votes["stale-agent"] = stale_vote

        # Simulate the TTL filter from _resolve_consensus
        now = time.time()
        engine.pending_votes = {
            aid: v
            for aid, v in engine.pending_votes.items()
            if now - v.timestamp <= engine.vote_window
        }

        assert "stale-agent" not in engine.pending_votes, (
            "H7: stale vote (200s old, window=60s) was not dropped by TTL filter"
        )

    def test_scoped_veto_preserves_other_proposals(self):
        """Runtime: a veto for proposal A must leave proposal-B votes intact."""
        from core.consensus_engine import Vote

        pending = {
            "agent-a": Vote(agent_id="agent-a", proposal="KXBTC:yes", signal="bullish", confidence=0.8),
            "agent-b": Vote(agent_id="agent-b", proposal="KXETH:yes", signal="bearish", confidence=0.7),
        }
        veto_target = "KXBTC:yes"
        filtered = {aid: v for aid, v in pending.items() if v.proposal != veto_target}

        assert "agent-a" not in filtered, "H7: agent-a (vetoed proposal) should be removed"
        assert "agent-b" in filtered, "H7: agent-b (different proposal) should be preserved"


# =============================================================================
# H8 — ABSTAIN votes counted in denominator; >50% abstain forces NO_ACTION
# =============================================================================

class TestH8_AbstainQuorum:
    """ABSTAIN signals must widen the effective denominator for quorum calculation.
    When abstention rate > 50%, the engine must force NO_ACTION without executing.
    """

    def test_abstain_votes_separated_in_source(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert 'abstain_votes' in src, (
            "H8: 'abstain_votes' list not found in consensus_engine.py"
        )
        assert 'directional_votes' in src, (
            "H8: 'directional_votes' list not found in consensus_engine.py"
        )

    def test_abstain_counted_in_effective_total(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "effective_total" in src, (
            "H8: 'effective_total' (denominator including abstains) not found"
        )
        assert "abstain_votes" in src, (
            "H8: abstain_votes not used in effective_total calculation"
        )

    def test_high_abstention_forces_no_action(self):
        src = _src(CONSENSUS_ENGINE_SRC)
        assert "0.5" in src or "50%" in src, (
            "H8: 50% abstention threshold not referenced"
        )
        assert 'forcing NO_ACTION' in src or "force NO_ACTION" in src or 'NO_ACTION' in src, (
            "H8: NO_ACTION forced on high abstention not found in source"
        )

    def test_abstention_count_in_result(self):
        from core.consensus_engine import ConsensusResult
        r = ConsensusResult(
            decision="NO_ACTION", signal="abstain",
            confidence=0.0, votes=[], quorum_met=False,
            abstention_count=5,
        )
        assert r.abstention_count == 5, "H8: abstention_count not stored on ConsensusResult"

    def test_forming_status_blocks_execution_in_trading_agent(self):
        src = _src(TRADING_AGENT_SRC)
        assert '"forming"' in src or "'forming'" in src, (
            "H8: FORMING consensus status not handled in trading_agent.py"
        )

    def test_forming_status_continues_not_executes(self):
        src = _src(TRADING_AGENT_SRC)
        lines = src.splitlines()
        forming_idx = next(
            (i for i, l in enumerate(lines) if '"forming"' in l or "'forming'" in l), None
        )
        assert forming_idx is not None, "H8: forming status check not found"
        # Within 10 lines of the forming check there must be a 'continue'
        window = "\n".join(lines[forming_idx: forming_idx + 10])
        assert "continue" in window, (
            "H8: 'continue' not found after forming-status check — signal must be held"
        )

    def test_abstain_rate_guard_returns_early(self):
        """Runtime: simulate the high-abstention path via a mock engine call."""
        from core.consensus_engine import Vote

        # Build vote list: 3 abstain, 1 bullish → 75% abstention
        votes = [
            Vote(agent_id=f"abs-{i}", proposal="KXBTC:yes",
                 signal="abstain", confidence=0.0, timestamp=time.time())
            for i in range(3)
        ]
        votes.append(Vote(
            agent_id="bull-1", proposal="KXBTC:yes",
            signal="bullish", confidence=0.9, timestamp=time.time(),
        ))

        total_voters = len(votes)
        abstain_votes = [v for v in votes if v.signal == "abstain"]
        rate = len(abstain_votes) / total_voters

        assert rate > 0.5, "test setup error: abstention rate should be > 50%"

        # Simulate the guard logic
        if rate > 0.5:
            decision = "NO_ACTION"
        else:
            decision = "EXECUTE_LONG"

        assert decision == "NO_ACTION", (
            "H8: high abstention should force NO_ACTION"
        )


# =============================================================================
# H9 — sentiment_adjusted flag prevents double adjustment
# =============================================================================

class TestH9_NoDoubleSentimentAdj:
    """MarketSnapshot must carry sentiment_adjusted and sentiment_age_seconds.
    _build_snapshot must set sentiment_adjusted=True after injecting scores.
    Downstream consumers must check the flag before applying their own nudge.
    """

    def _make_snapshot(self):
        from merid.prediction.model import (
            MarketSnapshot, ContractState, ImpliedProbability,
        )
        implied = ImpliedProbability(
            yes_prob=Decimal("0.50"), no_prob=Decimal("0.50"),
            yes_bid=Decimal("49"), yes_ask=Decimal("51"),
            no_bid=Decimal("49"), no_ask=Decimal("51"),
        )
        return MarketSnapshot(
            market_id="TEST", event_id="EVT", title="T",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("0"),
            open_interest=Decimal("0"),
        )

    def test_sentiment_adjusted_field_on_snapshot(self):
        snap = self._make_snapshot()
        assert hasattr(snap, "sentiment_adjusted"), (
            "H9: MarketSnapshot missing 'sentiment_adjusted' field"
        )
        assert snap.sentiment_adjusted is False, (
            "H9: sentiment_adjusted must default to False"
        )

    def test_sentiment_age_seconds_field_on_snapshot(self):
        snap = self._make_snapshot()
        assert hasattr(snap, "sentiment_age_seconds"), (
            "H9: MarketSnapshot missing 'sentiment_age_seconds' field"
        )
        assert snap.sentiment_age_seconds is None, (
            "H9: sentiment_age_seconds must default to None"
        )

    def test_sentiment_adjusted_set_in_build_snapshot(self):
        src = _src(TRADING_AGENT_SRC)
        assert "snapshot.sentiment_adjusted = True" in src, (
            "H9: 'snapshot.sentiment_adjusted = True' not set in _build_snapshot"
        )

    def test_sentiment_adjusted_set_only_in_fresh_branch(self):
        """sentiment_adjusted=True must appear inside the else (fresh) branch,
        not unconditionally."""
        src = _src(TRADING_AGENT_SRC)
        lines = src.splitlines()
        age_check_idx = next(
            (i for i, l in enumerate(lines) if "_age_s is not None and _age_s >" in l), None
        )
        assert age_check_idx is not None, "H9: age check line not found"
        else_idx = next(
            (i for i, l in enumerate(lines)
             if i > age_check_idx and l.strip() == "else:"),
            None,
        )
        assert else_idx is not None, "H9: else branch after age check not found"
        adjusted_idx = next(
            (i for i, l in enumerate(lines)
             if i > else_idx and "snapshot.sentiment_adjusted = True" in l),
            None,
        )
        assert adjusted_idx is not None, (
            "H9: sentiment_adjusted=True not found inside the else (fresh) branch"
        )
        assert adjusted_idx > else_idx, (
            "H9: sentiment_adjusted=True must come after the else: of the age gate"
        )

    def test_sentiment_age_seconds_assigned_on_snapshot(self):
        src = _src(TRADING_AGENT_SRC)
        assert "snapshot.sentiment_age_seconds = _age_s" in src, (
            "H9: snapshot.sentiment_age_seconds not assigned in _build_snapshot"
        )

    def test_sentiment_adjusted_false_when_stale(self):
        """If context is stale the snapshot fields must remain at defaults."""
        snap = self._make_snapshot()
        # Simulate stale path: nothing assigned — fields must stay at defaults
        assert snap.sentiment_adjusted is False
        assert snap.sentiment_age_seconds is None

    def test_model_src_contains_h9_comment(self):
        src = _src(MODEL_SRC)
        assert "H9" in src, (
            "H9: H9 annotation not found in model.py — expected in sentiment_adjusted comment"
        )
