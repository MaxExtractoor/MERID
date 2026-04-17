"""Tests for merid/event_venues/kalshi/client.py - Batch 103."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient


class TestKalshiVenueClient:
    """Tests for KalshiVenueClient."""

    def test_client_initialization(self):
        with patch.dict('os.environ', {'KALSHI_API_KEY': 'test_key'}):
            client = KalshiVenueClient()
            assert client is not None
            assert client.venue_name == "kalshi"

    def test_venue_name_property(self):
        with patch.dict('os.environ', {'KALSHI_API_KEY': 'test_key'}):
            client = KalshiVenueClient()
            assert client.venue_name == "kalshi"
