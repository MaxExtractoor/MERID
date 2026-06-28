"""Tests for core/paper_session.py.

LEGACY: This module tests PaperSessionState, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2).
"""
import pytest

pytestmark = pytest.mark.legacy
from datetime import datetime, timezone
from core.paper_session import (
    PaperSessionState, get_paper_session_state, update_paper_session_state,
    mark_session_start, mark_session_state, reset_session_state, _utc_now_iso
)


class TestUtcNowIso:
    """Test _utc_now_iso function."""

    def test_returns_iso_string(self):
        """Test returns ISO format string."""
        result = _utc_now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO format has T separator


class TestPaperSessionState:
    """Test PaperSessionState dataclass."""

    def test_default_values(self):
        """Test default state values."""
        state = PaperSessionState()
        assert state.mode == "paper"
        assert state.lifecycle == "OFFLINE"
        assert state.symbols == []
        assert state.strategies == []
        assert state.venues == []

    def test_to_dict(self):
        """Test to_dict method."""
        state = PaperSessionState()
        d = state.to_dict()
        assert d["mode"] == "paper"
        assert d["lifecycle"] == "OFFLINE"
        assert "symbols" in d


class TestGetPaperSessionState:
    """Test get_paper_session_state function."""

    def test_returns_dict(self):
        """Test returns state as dict."""
        result = get_paper_session_state()
        assert isinstance(result, dict)
        assert result["mode"] == "paper"


class TestUpdatePaperSessionState:
    """Test update_paper_session_state function."""

    def test_update_valid_field(self):
        """Test updating valid field."""
        reset_session_state()
        update_paper_session_state(mode="live")
        state = get_paper_session_state()
        assert state["mode"] == "live"

    def test_update_invalid_field_ignored(self):
        """Test invalid field is ignored."""
        reset_session_state()
        update_paper_session_state(invalid_field="value")
        # Should not raise

    def test_update_datetime_field(self):
        """Test datetime field conversion."""
        reset_session_state()
        now = datetime.now(timezone.utc)
        update_paper_session_state(started_at=now)
        state = get_paper_session_state()
        assert isinstance(state["started_at"], str)


class TestMarkSessionStart:
    """Test mark_session_start function."""

    def test_mark_start(self):
        """Test marking session start."""
        reset_session_state()
        mark_session_start(
            symbols=["BTC", "ETH"],
            strategies=["strategy1"],
            venues=["venue1"],
            duration_seconds=3600
        )
        state = get_paper_session_state()
        assert state["lifecycle"] == "LIVE"
        assert state["symbols"] == ["BTC", "ETH"]
        assert state["duration_seconds"] == 3600
        assert state["remaining_seconds"] == 3600
        assert state["started_at"] is not None


class TestMarkSessionState:
    """Test mark_session_state function."""

    def test_mark_state(self):
        """Test marking session state."""
        reset_session_state()
        mark_session_state("PAUSED", remaining_seconds=1800)
        state = get_paper_session_state()
        assert state["lifecycle"] == "PAUSED"
        assert state["remaining_seconds"] == 1800

    def test_mark_negative_remaining_clamped(self):
        """Test negative remaining seconds clamped to 0."""
        reset_session_state()
        mark_session_state("ENDED", remaining_seconds=-10)
        state = get_paper_session_state()
        assert state["remaining_seconds"] == 0


class TestResetSessionState:
    """Test reset_session_state function."""

    def test_reset(self):
        """Test resetting session state."""
        mark_session_start(["BTC"], ["s1"], ["v1"], 3600)
        reset_session_state()
        state = get_paper_session_state()
        assert state["lifecycle"] == "OFFLINE"
        assert state["symbols"] == []
