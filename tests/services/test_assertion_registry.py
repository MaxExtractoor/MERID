"""Tests for services/assertion_registry.py Pydantic models."""
import pytest
from services.assertion_registry import (
    AssertionRegistration, AssertionUpdate, AssertionRecord, AssertionFilter
)


class TestAssertionRegistration:
    """Test AssertionRegistration Pydantic model."""

    def test_creation(self):
        """Test AssertionRegistration creation."""
        registration = AssertionRegistration(
            template_id="template_123",
            subject={"type": "trade", "id": "trade_456"},
            parameters={"volume": 1000},
            severity="high",
            owner_team="trading",
            extra={"source": "manual"}
        )
        assert registration.template_id == "template_123"
        assert registration.subject["type"] == "trade"
        assert registration.parameters["volume"] == 1000
        assert registration.severity == "high"
        assert registration.owner_team == "trading"

    def test_optional_fields(self):
        """Test AssertionRegistration with optional fields."""
        registration = AssertionRegistration(
            template_id="template_123",
            subject={},
            parameters={}
        )
        assert registration.severity is None
        assert registration.owner_team is None
        assert registration.extra is None


class TestAssertionUpdate:
    """Test AssertionUpdate Pydantic model."""

    def test_creation(self):
        """Test AssertionUpdate creation."""
        update = AssertionUpdate(
            assertion_id="assert_123",
            status="passed",
            details="All checks passed",
            timestamp=1234567890.0
        )
        assert update.assertion_id == "assert_123"
        assert update.status == "passed"
        assert update.details == "All checks passed"
        assert update.timestamp == 1234567890.0

    def test_optional_details(self):
        """Test AssertionUpdate with optional details."""
        update = AssertionUpdate(
            assertion_id="assert_123",
            status="failed",
            timestamp=1234567890.0
        )
        assert update.details is None


class TestAssertionRecord:
    """Test AssertionRecord Pydantic model."""

    def test_creation(self):
        """Test AssertionRecord creation."""
        record = AssertionRecord(
            assertion_id="assert_123",
            template_id="template_456",
            status="passed",
            parameters={"check": "value"},
            subject={"type": "order"},
            details="Verification complete",
            timestamp=1234567890.0
        )
        assert record.assertion_id == "assert_123"
        assert record.template_id == "template_456"
        assert record.status == "passed"
        assert record.subject["type"] == "order"

    def test_optional_fields(self):
        """Test AssertionRecord with optional fields."""
        record = AssertionRecord(
            assertion_id="assert_123",
            template_id="template_456",
            status="new",
            parameters={},
            timestamp=1234567890.0
        )
        assert record.subject is None
        assert record.details is None


class TestAssertionFilter:
    """Test AssertionFilter Pydantic model."""

    def test_creation(self):
        """Test AssertionFilter creation."""
        filter_obj = AssertionFilter(
            status="active",
            template_id="template_123",
            owner_team="trading",
            severity="high",
            category="risk",
            since=1234567890.0,
            limit=50
        )
        assert filter_obj.status == "active"
        assert filter_obj.template_id == "template_123"
        assert filter_obj.owner_team == "trading"
        assert filter_obj.severity == "high"
        assert filter_obj.category == "risk"
        assert filter_obj.since == 1234567890.0
        assert filter_obj.limit == 50

    def test_default_limit(self):
        """Test AssertionFilter default limit."""
        filter_obj = AssertionFilter()
        assert filter_obj.limit == 100

    def test_all_optional(self):
        """Test AssertionFilter with all optional fields."""
        filter_obj = AssertionFilter()
        assert filter_obj.status is None
        assert filter_obj.template_id is None
        assert filter_obj.owner_team is None
        assert filter_obj.severity is None
        assert filter_obj.category is None
        assert filter_obj.since is None
