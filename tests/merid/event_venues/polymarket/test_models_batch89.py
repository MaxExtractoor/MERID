"""Tests for merid/event_venues/polymarket/models.py - Batch 89."""
import pytest
from decimal import Decimal

from merid.event_venues.polymarket.models import (
    MarketOutcome, Market, Order, Position
)


class TestMarketOutcome:
    """Tests for MarketOutcome dataclass."""

    def test_outcome_creation(self):
        outcome = MarketOutcome(
            outcome="yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65")
        )
        assert outcome.outcome == "yes"
        assert outcome.price == Decimal("0.65")


class TestMarket:
    """Tests for Market dataclass."""

    def test_market_creation(self):
        market = Market(
            id="market123",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[],
            category="weather"
        )
        assert market.id == "market123"
        assert market.question == "Will it rain?"
        assert market.active is True
