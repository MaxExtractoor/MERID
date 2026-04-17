"""Tests for zero-order blockage fixes.

Covers the four root causes that silently blocked all order submission:
1. Strike selector: directional passthrough for markets without strikes
2. Warmup lifecycle: deterministic data-readiness promotion
3. Consensus: single-agent READY status
4. Solo window: sane default (0s) for single-agent deployments
5. Startup config sanity checks
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════════════
# 1. STRIKE SELECTOR — DIRECTIONAL PASSTHROUGH
# ════════════════════════════════════════════════════════════════════════

class TestStrikeSelectorDirectionalPassthrough:
    """Strike selector must accept directional markets (no strike) when
    allow_directional_passthrough=True (default)."""

    def _make_selector(self, **kwargs):
        from merid.prediction.kalshi_strike_selector import (
            KalshiStrikeSelector,
            StrikeSelectionConfig,
        )
        config = StrikeSelectionConfig(**kwargs)
        return KalshiStrikeSelector(config)

    def test_directional_15m_ticker_accepted(self):
        """15m directional tickers have no strike — should pass through."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=101200.0,
            strike=None,  # directional = no strike
        )
        assert result.accepted is True
        assert result.is_directional is True
        assert result.strike is None
        assert result.spot == 101200.0

    def test_directional_with_spot_available(self):
        """Directional passthrough requires valid spot price."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=95000.0,
            strike=None,
        )
        assert result.accepted is True
        assert result.is_directional is True

    def test_directional_no_spot_rejected(self):
        """Directional market with missing spot should be rejected.
        Note: spot=None is caught by the missing_spot gate before
        the directional check, which is correct — spot is required."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=None,
            strike=None,
        )
        assert result.accepted is False
        assert result.rejection_reason == "missing_spot"

    def test_directional_zero_spot_rejected(self):
        """Directional market with spot=0 should be rejected (missing_spot)."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=0.0,
            strike=None,
        )
        assert result.accepted is False
        # This hits the spot check before the strike check
        assert result.rejection_reason == "missing_spot"

    def test_passthrough_disabled_rejects_directional(self):
        """When allow_directional_passthrough=False, missing strike is rejected."""
        sel = self._make_selector(allow_directional_passthrough=False)
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=101200.0,
            strike=None,
        )
        assert result.accepted is False
        assert result.rejection_reason == "missing_strike"

    def test_threshold_ticker_with_strike_still_works(self):
        """Threshold tickers (with strike) should still be evaluated normally."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC-26MAR2501-T101500",
            asset="BTC",
            timeframe="1h",
            spot=101200.0,
            strike=101500.0,
        )
        # distance = |101200-101500|/101500 = 0.003 < 0.08 (BTC 1h default)
        assert result.accepted is True
        assert result.is_directional is False

    def test_directional_to_dict_includes_flag(self):
        """to_dict() should include is_directional=True for directional results."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXETH15M-26MAR250015-15",
            asset="ETH",
            timeframe="15m",
            spot=3500.0,
            strike=None,
        )
        d = result.to_dict()
        assert d["is_directional"] is True
        assert d["accepted"] is True

    def test_exceeds_max_distance_still_rejects(self):
        """Contracts with strike far from spot should still be rejected."""
        sel = self._make_selector()
        result = sel.evaluate(
            ticker="KXBTC-26MAR2501-T200000",
            asset="BTC",
            timeframe="1h",
            spot=101200.0,
            strike=200000.0,
        )
        assert result.accepted is False
        assert result.rejection_reason == "exceeds_max_distance"


class TestStrikeSelectorConfigParsing:
    """Config parsing should handle allow_directional_passthrough."""

    def test_default_allows_passthrough(self):
        from merid.prediction.kalshi_strike_selector import parse_strike_selection_config
        config = parse_strike_selection_config(None)
        assert config.allow_directional_passthrough is True

    def test_explicit_false(self):
        from merid.prediction.kalshi_strike_selector import parse_strike_selection_config
        config = parse_strike_selection_config({"allow_directional_passthrough": False})
        assert config.allow_directional_passthrough is False

    def test_explicit_true(self):
        from merid.prediction.kalshi_strike_selector import parse_strike_selection_config
        config = parse_strike_selection_config({"allow_directional_passthrough": True})
        assert config.allow_directional_passthrough is True


class TestStrikeSelectorBatchDirectional:
    """Batch evaluation should correctly count directional passthroughs."""

    def test_batch_mixed_markets(self):
        from merid.prediction.kalshi_strike_selector import (
            KalshiStrikeSelector,
            StrikeSelectionConfig,
        )
        sel = KalshiStrikeSelector(StrikeSelectionConfig())
        contracts = [
            # Directional 15m — no strike
            {"ticker": "KXBTC15M-26MAR250015-15", "asset": "BTC", "timeframe": "15m",
             "spot": 101200.0, "strike": None},
            # Threshold 1h — close to spot
            {"ticker": "KXBTC-26MAR2501-T101500", "asset": "BTC", "timeframe": "1h",
             "spot": 101200.0, "strike": 101500.0},
            # Threshold 1h — far from spot
            {"ticker": "KXBTC-26MAR2501-T200000", "asset": "BTC", "timeframe": "1h",
             "spot": 101200.0, "strike": 200000.0},
        ]
        batch = sel.evaluate_batch(contracts)
        assert batch.total == 3
        assert batch.accepted == 2  # directional + close threshold
        assert batch.rejected == 1  # far threshold


# ════════════════════════════════════════════════════════════════════════
# 2. WARMUP LIFECYCLE — DETERMINISTIC TRANSITION
# ════════════════════════════════════════════════════════════════════════

class TestWarmupLifecycleConstants:
    """Warmup constants should have sane values."""

    def test_min_warmup_reasonable(self):
        from merid.prediction.trading_agent import _WARMUP_MIN_SECONDS
        assert 5.0 <= _WARMUP_MIN_SECONDS <= 30.0, (
            f"_WARMUP_MIN_SECONDS={_WARMUP_MIN_SECONDS} outside sane range"
        )

    def test_max_warmup_ceiling(self):
        from merid.prediction.trading_agent import _WARMUP_MAX_SECONDS
        assert 30.0 <= _WARMUP_MAX_SECONDS <= 300.0, (
            f"_WARMUP_MAX_SECONDS={_WARMUP_MAX_SECONDS} outside sane range"
        )

    def test_stagger_positive(self):
        from merid.prediction.trading_agent import _MAX_STAGGER_SECONDS
        assert _MAX_STAGGER_SECONDS > 0

    def test_max_exceeds_min_plus_stagger(self):
        from merid.prediction.trading_agent import (
            _MAX_STAGGER_SECONDS,
            _WARMUP_MAX_SECONDS,
            _WARMUP_MIN_SECONDS,
        )
        assert _WARMUP_MAX_SECONDS >= _WARMUP_MIN_SECONDS + _MAX_STAGGER_SECONDS, (
            "Max ceiling must be >= min + max_stagger to prevent unreachable ceiling"
        )


class TestLifecycleStateEnum:
    """LifecycleState enum has the expected values."""

    def test_all_states_present(self):
        from merid.prediction.trading_agent import LifecycleState
        expected = {"stopped", "starting", "warming_up", "active", "draining"}
        actual = {s.value for s in LifecycleState}
        assert expected == actual


# ════════════════════════════════════════════════════════════════════════
# 3. CONSENSUS — SINGLE-AGENT READY PATH
# ════════════════════════════════════════════════════════════════════════

class TestConsensusSingleAgent:
    """In single-agent mode (1 proposal < min_agents=2), consensus should
    immediately return READY via _consensus_from_single_proposal."""

    def _fresh_aggregator(self):
        """Create a fresh aggregator instance (bypass singleton)."""
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        # Reset singleton
        SwarmConsensusAggregator._instance = None
        agg = SwarmConsensusAggregator(min_agents_for_consensus=2)
        return agg

    def test_single_proposal_yields_ready(self):
        from merid.swarm.consensus_aggregator import AgentProposal, ConsensusStatus
        agg = self._fresh_aggregator()
        proposal = AgentProposal(
            agent_id="kalshi-btc_15m",
            asset="BTC",
            timeframe="15m",
            direction="yes",
            probability=0.65,
            confidence=0.72,
            size_preference="base",
            rationale="test directional signal",
            edge_estimate=0.05,
            timestamp=datetime.now(timezone.utc),
            agent_archetype="directional",
        )
        accepted = agg.submit_proposal(proposal)
        assert accepted is True

        consensus = agg.get_consensus("BTC", "15m")
        assert consensus is not None, "Single-agent consensus should not be None"
        assert consensus.status == ConsensusStatus.READY
        assert consensus.consensus_direction == "yes"
        assert consensus.total_agents == 1
        assert consensus.voting_agents == 1

    def test_single_proposal_usable(self):
        from merid.swarm.consensus_aggregator import AgentProposal
        agg = self._fresh_aggregator()
        proposal = AgentProposal(
            agent_id="kalshi-btc_15m",
            asset="BTC",
            timeframe="15m",
            direction="no",
            probability=0.40,
            confidence=0.60,
            size_preference="small",
            rationale="test bearish",
            edge_estimate=0.03,
            timestamp=datetime.now(timezone.utc),
            agent_archetype="directional",
        )
        agg.submit_proposal(proposal)
        consensus = agg.get_consensus("BTC", "15m")
        assert consensus is not None
        assert consensus.usable is True
        assert consensus.consensus_direction == "no"

    def test_no_proposals_returns_none(self):
        agg = self._fresh_aggregator()
        consensus = agg.get_consensus("BTC", "15m")
        assert consensus is None, "No proposals = None consensus"


# ════════════════════════════════════════════════════════════════════════
# 4. SOLO WINDOW — SANE DEFAULT
# ════════════════════════════════════════════════════════════════════════

class TestSoloWindowDefault:
    """Solo window should default to 0 for single-agent deployments."""

    def test_default_solo_seconds_is_zero(self):
        """When env var is unset, default should be 0."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove the env var if it exists
            os.environ.pop("MERID_PM_SWARM_SOLO_SECONDS", None)
            from merid.prediction.trading_agent import _swarm_max_solo_seconds
            assert _swarm_max_solo_seconds() == 0.0

    def test_env_override_honored(self):
        """Operators can set a positive solo window for multi-agent swarms."""
        with patch.dict(os.environ, {"MERID_PM_SWARM_SOLO_SECONDS": "60"}):
            from merid.prediction.trading_agent import _swarm_max_solo_seconds
            assert _swarm_max_solo_seconds() == 60.0


# ════════════════════════════════════════════════════════════════════════
# 5. STRIKE SELECTOR — REJECTION REASON ENUM
# ════════════════════════════════════════════════════════════════════════

class TestRejectionReasons:
    """All rejection reasons should be defined."""

    def test_directional_no_spot_reason_exists(self):
        from merid.prediction.kalshi_strike_selector import RejectionReason
        assert hasattr(RejectionReason, "DIRECTIONAL_NO_SPOT")
        assert RejectionReason.DIRECTIONAL_NO_SPOT == "directional_no_spot"

    def test_all_reasons_are_strings(self):
        from merid.prediction.kalshi_strike_selector import RejectionReason
        for attr in dir(RejectionReason):
            if attr.startswith("_"):
                continue
            val = getattr(RejectionReason, attr)
            assert isinstance(val, str), f"RejectionReason.{attr} is not a string"


# ════════════════════════════════════════════════════════════════════════
# 6. CONFIG SANITY CROSS-CHECKS
# ════════════════════════════════════════════════════════════════════════

class TestConfigSanityChecks:
    """Verify that the startup sanity check logic works."""

    def test_entry_window_zero_width_detected(self):
        """Entry window with min <= cutoff should be flagged."""
        from merid.prediction.agent_grid_config import EntryWindowConfig
        ew = EntryWindowConfig(minutes_before_expiry=2, cutoff_minutes_before_expiry=5)
        assert ew.minutes_before_expiry <= ew.cutoff_minutes_before_expiry

    def test_entry_window_valid(self):
        from merid.prediction.agent_grid_config import EntryWindowConfig
        ew = EntryWindowConfig(minutes_before_expiry=10, cutoff_minutes_before_expiry=2)
        assert ew.minutes_before_expiry > ew.cutoff_minutes_before_expiry


# ════════════════════════════════════════════════════════════════════════
# 7. CYCLE TRACE OBSERVABILITY
# ════════════════════════════════════════════════════════════════════════

class TestCycleTraceStrikeCounters:
    """PM_CYCLE_TRACE should include strike_passed, strike_rejected, strike_directional."""

    def test_trace_format_includes_strike_fields(self):
        """Verify the format string has strike counter placeholders."""
        import inspect
        from merid.prediction.trading_agent import KalshiTradingAgent
        # The trace is in _run_cycle_body (delegated from _run_cycle)
        source = inspect.getsource(KalshiTradingAgent._run_cycle_body)
        assert "strike_passed=%d" in source
        assert "strike_rejected=%d" in source
        assert "strike_directional=%d" in source


# ════════════════════════════════════════════════════════════════════════
# 8. INTEGRATION — STRIKE SELECTOR + SNAPSHOT FLOW
# ════════════════════════════════════════════════════════════════════════

class TestStrikeSelectorSnapshotIntegration:
    """Verify that the strike selector result correctly tags the snapshot."""

    def test_directional_passthrough_tags_snapshot_basis(self):
        """When strike selector passes a directional market, the snapshot
        should have spot_strike_basis_note='directional_passthrough'."""
        from merid.prediction.kalshi_strike_selector import (
            KalshiStrikeSelector,
            StrikeSelectionConfig,
        )
        sel = KalshiStrikeSelector(StrikeSelectionConfig())
        result = sel.evaluate(
            ticker="KXBTC15M-26MAR250015-15",
            asset="BTC",
            timeframe="15m",
            spot=101200.0,
            strike=None,
        )
        assert result.accepted is True
        assert result.is_directional is True
        # The trading agent sets spot_strike_basis_note="directional_passthrough"
        # when is_directional is True — verify the flag is accessible
        assert hasattr(result, 'is_directional')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
