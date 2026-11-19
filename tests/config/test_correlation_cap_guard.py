"""Tests for the correlation-mode precondition on exposure-cap lifts.

``_apply_correlation_cap_guard`` fails closed to the audited $11 cap when the
resolved cap exceeds it unless the profile's correlation-aware sizing stack
(``correlation_tracking.enabled`` AND ``real_time_monitoring``) is live.
"""

from decimal import Decimal
from types import SimpleNamespace

from merid.config.live_config import (
    _AUDITED_EXPOSURE_CAP_USD,
    _apply_correlation_cap_guard,
)


def _profile(enabled=True, rt=False):
    return SimpleNamespace(
        correlation_tracking_enabled=enabled,
        correlation_tracking_real_time_monitoring=rt,
    )


def _run(cap, profile):
    conflicts, invariants = [], []
    resolved = _apply_correlation_cap_guard(Decimal(str(cap)), profile, conflicts, invariants)
    return resolved, conflicts, invariants


def test_cap_at_or_below_audited_bound_passes_through():
    resolved, conflicts, invariants = _run(11.00, _profile(enabled=False, rt=False))
    assert resolved == Decimal("11.00")
    assert conflicts == []


def test_cap_lift_without_correlation_stack_fails_closed():
    resolved, conflicts, invariants = _run(50.00, _profile(enabled=True, rt=False))
    assert resolved == _AUDITED_EXPOSURE_CAP_USD
    assert len(conflicts) == 1
    assert "lift rejected" in conflicts[0]
    assert invariants == []


def test_cap_lift_with_tracking_but_no_rt_monitoring_fails_closed():
    # real_time_monitoring is the flag the 0.80/3-asset thresholds hang off;
    # enabled=True alone is not sufficient.
    resolved, conflicts, _ = _run(25.00, _profile(enabled=True, rt=False))
    assert resolved == _AUDITED_EXPOSURE_CAP_USD
    assert conflicts


def test_cap_lift_with_full_correlation_stack_permitted():
    resolved, conflicts, invariants = _run(50.00, _profile(enabled=True, rt=True))
    assert resolved == Decimal("50.00")
    assert conflicts == []
    assert any("lift permitted" in s for s in invariants)


def test_profile_missing_correlation_fields_fails_closed():
    resolved, conflicts, _ = _run(30.00, SimpleNamespace())
    assert resolved == _AUDITED_EXPOSURE_CAP_USD
    assert conflicts
