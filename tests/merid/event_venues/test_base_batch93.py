"""Tests for merid/event_venues/base.py - Batch 93."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.base import (
    EventVenueClient, EventVenueStream
)


class TestEventVenueClient:
    """Tests for EventVenueClient abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            EventVenueClient()


class TestEventVenueStream:
    """Tests for EventVenueStream abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            EventVenueStream()
