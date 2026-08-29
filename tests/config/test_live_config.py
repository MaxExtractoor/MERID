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


def test_environment_override_lowers_min_required_edge_fails(monkeypatch):
    monkeypatch.setenv("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.01")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "lower the minimum required edge" in str(exc.value)


def test_environment_override_lowers_min_held_price_fails(monkeypatch):
    monkeypatch.setenv("MERID_MIN_HELD_PRICE_CENTS", "20")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "lower the held-side price floor" in str(exc.value)


def test_environment_override_raises_fixed_exposure_cap_fails(monkeypatch):
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "3.00")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "raise the fixed exposure cap" in str(exc.value)


def test_environment_override_daily_loss_above_profile_fails(monkeypatch):
    monkeypatch.setenv("MERID_MAX_DAILY_LOSS_PCT", "0.15")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "raise the daily loss limit" in str(exc.value)


def test_stop_loss_without_submission_or_unprotected_fails(monkeypatch):
    # The conftest autouse fixture sets MERID_ALLOW_UNPROTECTED_ENTRIES=1 for
    # legacy tests; we explicitly clear it here to test the fail-closed path.
    monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "0")
    monkeypatch.setenv("MERID_ALLOW_UNPROTECTED_ENTRIES", "0")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "protective exits cannot be executed" in str(exc.value)


def test_entry_price_floor_env_below_canonical_fails(monkeypatch):
    monkeypatch.setenv("MERID_MIN_ENTRY_CENTS", "5")
    with pytest.raises(LiveConfigInvariantError) as exc:
        resolve_live_config()
    assert "lower the minimum entry price" in str(exc.value)


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
