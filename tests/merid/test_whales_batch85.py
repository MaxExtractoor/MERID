"""Tests for merid/whales.py - Batch 85."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from merid.whales import (
    WhaleEvent, WhaleMonitorConfig, get_sentry_transaction, 
    get_sentry_span, capture_sentry_exception
)


class TestWhaleEvent:
    """Tests for WhaleEvent dataclass."""

    def test_whale_event_creation(self):
        """Test WhaleEvent creation."""
        event = WhaleEvent(
            mint="ABC123",
            owner="owner456",
            amount=1000.0,
            threshold=500.0
        )
        assert event.mint == "ABC123"
        assert event.owner == "owner456"
        assert event.amount == 1000.0
        assert event.threshold == 500.0
        assert event.event_type == "whale"

    def test_whale_event_to_dict(self):
        """Test WhaleEvent to_dict."""
        event = WhaleEvent(
            mint="ABC123",
            owner="owner456",
            amount=1000.0,
            timestamp=datetime(2024, 1, 1, 12, 0, 0)
        )
        result = event.to_dict()
        assert result["mint"] == "ABC123"
        assert result["owner"] == "owner456"
        assert result["amount"] == 1000.0
        assert result["type"] == "whale"


class TestWhaleMonitorConfig:
    """Tests for WhaleMonitorConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = WhaleMonitorConfig()
        assert config.whale_threshold == 100000.0
        assert config.solana_ws_url == "wss://api.mainnet-beta.solana.com"
        assert config.initial_backoff_seconds == 1.0

    def test_custom_config(self):
        """Test custom configuration."""
        config = WhaleMonitorConfig(whale_threshold=50000.0, initial_backoff_seconds=2.0)
        assert config.whale_threshold == 50000.0
        assert config.initial_backoff_seconds == 2.0


class TestSentryHelpers:
    """Tests for Sentry helper functions."""

    def test_get_sentry_transaction(self):
        """Test get_sentry_transaction."""
        ctx = get_sentry_transaction()
        assert ctx is not None

    def test_get_sentry_span(self):
        """Test get_sentry_span."""
        ctx = get_sentry_span(op="test", description="test operation")
        assert ctx is not None

    def test_capture_sentry_exception(self):
        """Test capture_sentry_exception."""
        try:
            raise ValueError("Test exception")
        except Exception as e:
            # Should not raise
            capture_sentry_exception(e)
