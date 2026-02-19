"""Regression tests for bugfixes: matching engine DOMAIN_CONFIGS import
and swarm/performance.py _coerce_dt naive/aware datetime mismatch.
"""

import pytest
from datetime import datetime, timezone, timedelta


# ======================================================================
# §1 init_matching_engines — DOMAIN_CONFIGS import regression
# ======================================================================

class TestInitMatchingEngines:
    """Verify init_matching_engines() no longer raises NameError."""

    def test_import_does_not_raise(self):
        """init_matching_engines must not raise NameError on DOMAIN_CONFIGS."""
        from merid.matching_engine import init_matching_engines
        # Should not raise NameError: name 'DOMAIN_CONFIGS' is not defined
        engines = init_matching_engines()
        assert isinstance(engines, dict)

    def test_returns_dict_of_engines(self):
        from merid.matching_engine import init_matching_engines, MatchingEngine
        engines = init_matching_engines()
        for name, engine in engines.items():
            assert isinstance(name, str)
            assert isinstance(engine, MatchingEngine)

    def test_prediction_engine_present(self):
        """Paper config enables a prediction matching engine."""
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        assert "prediction" in engines, (
            "Expected 'prediction' domain engine from paper_config"
        )

    def test_engine_has_correct_domain(self):
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        for name, engine in engines.items():
            assert engine.domain == name

    def test_from_config_classmethod(self):
        """MatchingEngine.from_config also imports DOMAIN_CONFIGS correctly."""
        from merid.matching_engine import MatchingEngine
        engine = MatchingEngine.from_config("prediction")
        assert engine.domain == "prediction"


# ======================================================================
# §2 _coerce_dt — naive/aware datetime fix
# ======================================================================

class TestCoerceDt:
    """Verify _coerce_dt always returns timezone-aware datetimes."""

    def test_z_suffix_returns_aware(self):
        """ISO string with Z suffix must produce UTC-aware datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00Z")
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 14
        assert dt.hour == 20

    def test_plus_zero_offset_returns_aware(self):
        """ISO string with +00:00 must produce UTC-aware datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00+00:00")
        assert dt.tzinfo is not None

    def test_naive_iso_string_gets_utc(self):
        """ISO string without timezone must get UTC attached."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00")
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc

    def test_non_utc_offset_preserved(self):
        """ISO string with non-UTC offset should preserve that offset."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T15:00:00-05:00")
        assert dt.tzinfo is not None
        # Should be 20:00 UTC
        utc_dt = dt.astimezone(timezone.utc)
        assert utc_dt.hour == 20

    def test_fallback_on_garbage_returns_aware(self):
        """Invalid string must fall back to aware UTC datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("not-a-date")
        assert dt.tzinfo is not None
        # Should be close to now
        diff = abs((datetime.now(timezone.utc) - dt).total_seconds())
        assert diff < 5

    def test_subtraction_from_aware_datetime_succeeds(self):
        """Core regression: subtracting _coerce_dt result from aware now must not raise."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00Z")
        now = datetime.now(timezone.utc)
        # This was the exact operation that raised TypeError before the fix
        diff = now - dt
        assert isinstance(diff, timedelta)

    def test_subtraction_from_naive_iso_succeeds(self):
        """Naive ISO input must also be subtractable from aware now."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00")
        now = datetime.now(timezone.utc)
        diff = now - dt
        assert isinstance(diff, timedelta)

    def test_z_and_plus_zero_are_equal(self):
        """Z suffix and +00:00 for same time must produce equal datetimes."""
        from swarm.performance import _coerce_dt
        dt_z = _coerce_dt("2026-02-14T20:00:00Z")
        dt_plus = _coerce_dt("2026-02-14T20:00:00+00:00")
        assert dt_z == dt_plus
