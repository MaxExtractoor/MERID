"""Tests for core/time_authority.py."""
import pytest
from datetime import datetime, timezone
from core.time_authority import current_time


class TestCurrentTime:
    """Test current_time function."""

    def test_returns_dict(self):
        """Test returns dictionary with expected keys."""
        result = current_time()
        assert isinstance(result, dict)
        assert "utc_iso" in result
        assert "unix" in result

    def test_utc_iso_format(self):
        """Test UTC ISO format is valid."""
        result = current_time()
        # Should be able to parse the ISO string
        dt = datetime.fromisoformat(result["utc_iso"])
        assert dt.tzinfo == timezone.utc

    def test_unix_timestamp(self):
        """Test unix timestamp is valid."""
        result = current_time()
        assert isinstance(result["unix"], int)
        assert result["unix"] > 0
        # Should be approximately current time (within 1 second)
        import time
        assert abs(result["unix"] - int(time.time())) < 1

    def test_consistency(self):
        """Test utc_iso and unix are consistent."""
        result = current_time()
        # Parse ISO and convert to timestamp
        dt = datetime.fromisoformat(result["utc_iso"])
        iso_unix = int(dt.timestamp())
        # Should match (within 1 second due to rounding)
        assert abs(iso_unix - result["unix"]) <= 1
