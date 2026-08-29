"""Tests for the resolved live-config loader.

These tests verify that the profile, environment overrides, and cross-field
invariants are resolved into a single, hashed ``ResolvedLiveConfig``.
"""

import os
from decimal import Decimal

import pytest

from merid.config.live_config import (
    LiveConfigInvariantError,
    ResolvedLiveConfig,
    get_resolved_live_config,
    resolve_live_config,
    reset_resolved_live_config,
)


@pytest.fixture(autouse=True)
def _reset_live_config_state():
    """Clear the module singleton before and after each test."""
    reset_resolved_live_config()
    yield
    reset_resolved_live_config()


def test_resolve_live_config_returns_immutable_resolved_object():
    resolved = resolve_live_config()
    assert isinstance(resolved, ResolvedLiveConfig)
    assert resolved.resolved
    assert resolved.config_hash
    assert len(resolved.config_hash) == 64  # SHA-256 hex
    assert resolved.profile_name == "kalshi_crypto_15m_v2"


def test_get_resolved_live_config_returns_same_singleton(monkeypatch):
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    first = get_resolved_live_config()
    second = get_resolved_live_config()
    assert first is second


def test_environment_override_lowers_min_required_edge_is_rejected(monkeypatch):
    """A lower edge floor is unsafe and is ignored; the profile floor wins."""
    monkeypatch.setenv("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.01")
    resolved = resolve_live_config()
    assert resolved.min_required_edge == Decimal("0.05")
    assert any(
        "Min required edge override rejected" in c for c in resolved.conflicts_caught
    )


def test_environment_override_lowers_min_held_price_is_rejected(monkeypatch):
    """A lower held-side price floor is unsafe and is ignored."""
    monkeypatch.setenv("MERID_MIN_HELD_PRICE_CENTS", "20")
    resolved = resolve_live_config()
    assert resolved.min_held_price_cents == Decimal("35")
    assert any(
        "Held-side price floor override rejected" in c for c in resolved.conflicts_caught
    )


def test_environment_override_raises_fixed_exposure_cap_is_rejected(monkeypatch):
    """A higher exposure cap is unsafe and is ignored; the profile cap wins."""
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "3.00")
    resolved = resolve_live_config()
    # profile fixed cap is 0.75; the unsafe 3.00 override is rejected
    assert resolved.fixed_exposure_cap_usd == Decimal("0.75")
    assert any(
        "Exposure cap override rejected" in c for c in resolved.conflicts_caught
    )


def test_environment_override_daily_loss_above_profile_is_rejected(monkeypatch):
    """A higher daily loss pct is unsafe and is ignored; the 5% prod profile wins."""
    # Force prod mode so the profile daily loss is 0.05 and the .env 0.15 is rejected.
    monkeypatch.setenv("MERID_OPERATION_MODE", "prod")
    monkeypatch.setenv("MERID_MAX_DAILY_LOSS_PCT", "0.15")
    resolved = resolve_live_config()
    assert resolved.max_daily_loss_pct == Decimal("0.05")
    assert any(
        "Daily loss override rejected" in c for c in resolved.conflicts_caught
    )


def test_stop_loss_detection_decoupled_from_stop_candidate_execution(monkeypatch):
    """stop_loss_enabled (detection) can be true while execution stays off."""
    monkeypatch.setenv("MERID_ALLOW_UNPROTECTED_ENTRIES", "0")
    resolved = resolve_live_config()
    assert resolved.stop_loss_enabled
    assert not resolved.stop_candidate_submission_enabled
    assert not resolved.unprotected_entries_allowed


def test_stop_candidate_submission_env_request_is_ignored(monkeypatch):
    """MERID_ENABLE_STOP_CANDIDATE_SUBMISSION is a request, not an enablement,
    until the B stop-candidate reducer and replay harness pass."""
    monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
    monkeypatch.setenv("MERID_ALLOW_UNPROTECTED_ENTRIES", "0")
    resolved = resolve_live_config()
    assert not resolved.stop_candidate_submission_enabled
    assert any(
        "Stop-candidate submission env request ignored" in c
        for c in resolved.conflicts_caught
    )


def test_entry_price_floor_env_below_canonical_is_rejected(monkeypatch):
    """A lower entry price floor is unsafe and is ignored."""
    monkeypatch.setenv("MERID_MIN_ENTRY_CENTS", "5")
    resolved = resolve_live_config()
    assert resolved.min_entry_cents == 10
    assert any(
        "Minimum entry price override rejected" in c for c in resolved.conflicts_caught
    )


def test_allowed_environment_override_applies(monkeypatch):
    """A stricter env override (higher edge floor) is accepted and reflected."""
    monkeypatch.setenv("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.12")
    resolved = resolve_live_config()
    assert resolved.min_required_edge == Decimal("0.12")


def test_price_floor_disagreement_is_caught_and_resolved():
    """The YAML has price_range.min=10 and guardrails.min=5; resolver picks 10."""
    resolved = resolve_live_config()
    assert resolved.min_entry_cents == 10
    assert any("Profile price floor disagreement" in c for c in resolved.conflicts_caught)


def test_invariants_checked_lists_every_safety_check():
    """The resolver must report every invariant it evaluated, not just failures."""
    resolved = resolve_live_config()
    assert resolved.invariants_checked
    assert any("Exposure cap" in i for i in resolved.invariants_checked)
    assert any("Daily loss pct" in i for i in resolved.invariants_checked)
    assert any("Price collar" in i for i in resolved.invariants_checked)
    assert any("TIF invariants" in i for i in resolved.invariants_checked)
    assert any("Stop-loss policy" in i for i in resolved.invariants_checked)


def test_config_hash_is_stable(monkeypatch):
    resolved = resolve_live_config()
    first_hash = resolved.config_hash

    # Hash must not include itself (calling again returns same config).
    reset_resolved_live_config()
    second = resolve_live_config()
    assert second.config_hash == first_hash


def test_unresolved_return_value_has_resolved_false():
    reset_resolved_live_config()
    unresolved = get_resolved_live_config(allow_unresolved=True)
    assert unresolved is not None
    assert not unresolved.resolved


def test_schema_rejects_unknown_safety_env_var(monkeypatch):
    """A safety-looking env var that is not in the schema should raise."""
    monkeypatch.setenv("MERID_MAX_RISK_UNKNOWN_PCT", "0.25")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "Declare it in the live-config schema" in str(exc.value)
