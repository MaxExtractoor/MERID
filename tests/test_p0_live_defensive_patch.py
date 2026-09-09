"""Focused unit tests for the P0 live-defensive patch.

These tests verify the fail-closed boundary around:
- live runtime state machine
- RTI-only Bachelier spot pricing
- RTI/book freshness and skew gates
- confidence fail-closed behavior
- profile signal_mode alignment
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is importable.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from merid.observability.live_runtime_state import (
    LiveRuntimeState,
    LiveRuntimeStateError,
    ReleaseAssertion,
)
from merid.config.auto_execution import is_auto_execution_enabled
from merid.prediction.trade_decision import _compute_confidence, compute_trade_decision


@pytest.fixture
def temp_state_path(tmp_path: Path) -> Path:
    return tmp_path / "live_runtime_state.json"


@pytest.fixture
def reset_auto_exec_env():
    with patch.dict(
        os.environ,
        {
            "MERID_AUTO_EXECUTION_MODE": "",
        },
        clear=False,
    ):
        yield


class TestLiveRuntimeState:
    def test_default_state_is_halted(self, temp_state_path: Path) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        assert state.live_entries_enabled() is False
        assert state.can_submit_live_entry() is False

    def test_preflight_stays_halted_when_auto_disabled(
        self, temp_state_path: Path
    ) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        state.transition("STARTING", "test")
        state.transition("PREFLIGHT_RUNNING", "test")
        state.complete_preflight(auto_enable=False)
        assert state.live_entries_enabled() is False
        assert state._state == "LIVE_ENTRIES_HALTED"

    def test_preflight_enables_when_auto_enabled(
        self, temp_state_path: Path
    ) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        state.transition("STARTING", "test")
        state.transition("PREFLIGHT_RUNNING", "test")
        state.complete_preflight(auto_enable=True)
        assert state.live_entries_enabled() is True
        assert state._state == "LIVE_ENTRIES_ENABLED"

    def test_illegal_transition_raises(self, temp_state_path: Path) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        with pytest.raises(Exception):
            state.transition("LIVE_ENTRIES_ENABLED", "illegal")

    def test_placeholder_release_assertion_rejected(
        self, temp_state_path: Path
    ) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        state.transition("STARTING", "test")
        state.transition("PREFLIGHT_RUNNING", "test")
        assertion = ReleaseAssertion(
            state="PREFLIGHT_RUNNING",
            manual_release_token_hash="set_from_secret_store",
            emergency_token_hash="set_from_secret_store",
            preflight_snapshot_id="test",
            fresh_reconciliation=True,
        )
        with pytest.raises(LiveRuntimeStateError):
            state.request_live_entries_enabled(assertion)

    def test_halt_from_enabled(self, temp_state_path: Path) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        state.transition("STARTING", "test")
        state.transition("PREFLIGHT_RUNNING", "test")
        state.complete_preflight(auto_enable=True)
        state.halt_entries("circuit_breaker", ["CIRCUIT_BREAKER"])
        assert state._state == "LIVE_ENTRIES_HALTED"

    def test_persistence_round_trip(self, temp_state_path: Path) -> None:
        state = LiveRuntimeState(persistence_path=temp_state_path)
        state.transition("STARTING", "test")
        state.transition("PREFLIGHT_RUNNING", "test")
        state.complete_preflight(auto_enable=True)

        state2 = LiveRuntimeState(persistence_path=temp_state_path)
        assert state2._state == "LIVE_ENTRIES_ENABLED"
        assert state2.transition_history[-1]["new_state"] == "LIVE_ENTRIES_ENABLED"


class TestAutoExecution:
    def test_agents_md_auto_execution_is_one(self, reset_auto_exec_env) -> None:
        # AGENTS.md front matter is the source of truth.
        assert is_auto_execution_enabled() is True

    def test_env_override_can_disable(self, reset_auto_exec_env) -> None:
        with patch.dict(os.environ, {"MERID_AUTO_EXECUTION_MODE": "0"}, clear=False):
            assert is_auto_execution_enabled() is False

    def test_env_override_can_enable(self, reset_auto_exec_env) -> None:
        with patch.dict(os.environ, {"MERID_AUTO_EXECUTION_MODE": "1"}, clear=False):
            assert is_auto_execution_enabled() is True


@dataclass
class FakeCfbObservation:
    value: float
    execution_eligible: bool = True
    observed_ts_ms: int | None = None


class TestBachelierSpotPrice:
    def test_rti_execution_eligible_used(self) -> None:
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        obs = FakeCfbObservation(value=123.45, execution_eligible=True)
        price = _get_bachelier_spot_price(obs, 999.0)
        assert price == 123.45

    def test_rti_not_execution_eligible_returns_none(self) -> None:
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        obs = FakeCfbObservation(value=123.45, execution_eligible=False)
        price = _get_bachelier_spot_price(obs, 999.0)
        assert price is None

    def test_missing_rti_returns_none(self) -> None:
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        price = _get_bachelier_spot_price(None, 999.0)
        assert price is None


class TestTradeSnapshotValidation:
    def test_missing_rti_rejected(self) -> None:
        from merid.prediction.agent_grid_15m import validate_trade_snapshot

        class FakeMarketState:
            book_initialized = True
            live_sequence_confirmed = True
            last_book_update_wall_ts = 1.0

        failures = validate_trade_snapshot(
            asset="XRP",
            market_state=FakeMarketState(),
            cfb_observation=None,
            settlement_reference="cfb_rti_live",
        )
        assert "RTI_OBSERVATION_MISSING" in failures

    def test_stale_rti_rejected(self) -> None:
        from merid.prediction.agent_grid_15m import validate_trade_snapshot

        now_ms = int(1e12)
        old_ms = now_ms - 10_000

        class FakeMarketState:
            book_initialized = True
            live_sequence_confirmed = True
            last_book_update_wall_ts = now_ms / 1000.0

        obs = FakeCfbObservation(value=1.0, execution_eligible=True, observed_ts_ms=old_ms)
        with patch("merid.prediction.agent_grid_15m.time.time", return_value=now_ms / 1000.0):
            failures = validate_trade_snapshot(
                asset="XRP",
                market_state=FakeMarketState(),
                cfb_observation=obs,
                settlement_reference="cfb_rti_live",
            )
        assert any("RTI_STALE" in f for f in failures)

    def test_settlement_reference_mismatch_rejected(self) -> None:
        from merid.prediction.agent_grid_15m import validate_trade_snapshot

        class FakeMarketState:
            book_initialized = True
            live_sequence_confirmed = True
            last_book_update_wall_ts = 1.0

        obs = FakeCfbObservation(value=1.0, execution_eligible=True)
        failures = validate_trade_snapshot(
            asset="XRP",
            market_state=FakeMarketState(),
            cfb_observation=obs,
            settlement_reference="unified_spot",
        )
        assert "SETTLEMENT_SOURCE_NOT_CFB_RTI_LIVE" in failures


class TestConfidenceFailClosed:
    def test_rti_stale_makes_invalid(self) -> None:
        result = _compute_confidence(
            data_quality="good",
            regime="bullish",
            settlement_reference="cfb_rti_live",
            seconds_to_expiry=600.0,
            yes_bid_cents=40.0,
            yes_ask_cents=41.0,
            no_bid_cents=59.0,
            no_ask_cents=60.0,
            yes_depth_cc=500.0,
            no_depth_cc=500.0,
            model_uncertainty=0.05,
            rti_age_ms=5000,
            quote_age_ms=100,
            book_sequence_confirmed=True,
            book_initialized=True,
            cfb_execution_eligible=True,
        )
        assert result.valid is False
        assert any("rti_stale" in r for r in result.reasons)

    def test_book_not_initialized_makes_invalid(self) -> None:
        result = _compute_confidence(
            data_quality="good",
            regime="bullish",
            settlement_reference="cfb_rti_live",
            seconds_to_expiry=600.0,
            yes_bid_cents=40.0,
            yes_ask_cents=41.0,
            no_bid_cents=59.0,
            no_ask_cents=60.0,
            yes_depth_cc=500.0,
            no_depth_cc=500.0,
            model_uncertainty=0.05,
            rti_age_ms=200,
            quote_age_ms=100,
            book_sequence_confirmed=True,
            book_initialized=False,
            cfb_execution_eligible=True,
        )
        assert result.valid is False
        assert any("orderbook_not_initialized" in r for r in result.reasons)

    def test_rti_not_execution_eligible_makes_invalid(self) -> None:
        result = _compute_confidence(
            data_quality="good",
            regime="bullish",
            settlement_reference="cfb_rti_live",
            seconds_to_expiry=600.0,
            yes_bid_cents=40.0,
            yes_ask_cents=41.0,
            no_bid_cents=59.0,
            no_ask_cents=60.0,
            yes_depth_cc=500.0,
            no_depth_cc=500.0,
            model_uncertainty=0.05,
            rti_age_ms=200,
            quote_age_ms=100,
            book_sequence_confirmed=True,
            book_initialized=True,
            cfb_execution_eligible=False,
        )
        assert result.valid is False


class TestReplayFixtures:
    def test_stale_spot_rti_log_replay_rejects_trade(self) -> None:
        """Replay the 2026-09-08 XRP incident: fresh RTI, stale quote, mixed prices.

        The log showed cfb_age_ms=582 and spot_staleness_ms=4853.  Even though
        the RTI observation is execution-eligible, the quote/book age is far
        beyond the 1s execution threshold, so the final decision must be
        no-trade with confidence invalid.
        """
        from merid.prediction.trade_decision import compute_trade_decision

        decision = compute_trade_decision(
            run_id="replay_20260908",
            decision_id="replay_xrp_stale_book",
            ticker="KXXRP15M-26SEP082145-45",
            asset="XRP",
            spot_price=1.4161,
            strike_price=1.4160,
            seconds_to_expiry=600.0,
            yes_bid_cents=60.0,
            yes_ask_cents=61.0,
            no_bid_cents=39.0,
            no_ask_cents=40.0,
            yes_depth_cc=500.0,
            no_depth_cc=500.0,
            fee_per_contract_cents=2.0,
            annualized_vol=1.0,
            model_uncertainty=0.05,
            data_quality="good",
            data_state="healthy",
            regime="normal",
            regime_label="normal",
            regime_probability=1.0,
            p_yes_model=None,
            min_required_edge=0.02,
            settlement_reference="cfb_rti_live",
            quote_age_ms=4853,
            rti_age_ms=582,
            rti_book_skew_ms=4271,
            book_sequence_confirmed=True,
            book_initialized=True,
            cfb_execution_eligible=True,
        )
        assert decision.selected_action is None
        assert decision.confidence_valid is False
        assert decision.no_trade_reason is not None

    def test_stale_rti_fallback_rejects_trade(self) -> None:
        """Aged RTI must produce NO_TRADE; no public-spot fallback is allowed."""
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        obs = FakeCfbObservation(value=1.4163, execution_eligible=False)
        assert _get_bachelier_spot_price(obs, 1.4161) is None


class TestProfileSignalMode:
    def test_profile_yaml_is_bachelier(self) -> None:
        import yaml

        profile_path = REPO_ROOT / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        assert data.get("signal_mode") == "bachelier"
