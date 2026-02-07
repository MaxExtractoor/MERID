"""Tests for compliance/audit_logger.py."""
import pytest
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from compliance.audit_logger import (
    AuditCategory, AuditSeverity, AuditEvent, AuditLogger, get_audit_logger, _audit_logger
)


class TestAuditCategory:
    """Test AuditCategory enum."""

    def test_audit_category_values(self):
        """Test audit category enum values."""
        assert AuditCategory.AUTHENTICATION.value == "authentication"
        assert AuditCategory.AUTHORIZATION.value == "authorization"
        assert AuditCategory.TRADING.value == "trading"
        assert AuditCategory.WALLET.value == "wallet"
        assert AuditCategory.CONFIGURATION.value == "configuration"
        assert AuditCategory.SYSTEM.value == "system"
        assert AuditCategory.DATA_ACCESS.value == "data_access"
        assert AuditCategory.COMPLIANCE.value == "compliance"


class TestAuditSeverity:
    """Test AuditSeverity enum."""

    def test_audit_severity_values(self):
        """Test audit severity enum values."""
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"


class TestAuditEvent:
    """Test AuditEvent dataclass."""

    def test_creation(self):
        """Test AuditEvent creation."""
        event = AuditEvent(
            event_id="audit_123",
            category=AuditCategory.TRADING,
            severity=AuditSeverity.INFO,
            action="place_order",
            actor_id="user_456",
            actor_type="user",
            target_type="order",
            target_id="order_789",
            details={"symbol": "BTC/USD", "amount": 1.0},
            result="success",
        )
        assert event.event_id == "audit_123"
        assert event.category == AuditCategory.TRADING
        assert event.severity == AuditSeverity.INFO
        assert event.action == "place_order"

    def test_compute_hash(self):
        """Test compute_hash method."""
        event = AuditEvent(
            event_id="audit_123",
            category=AuditCategory.TRADING,
            severity=AuditSeverity.INFO,
            action="place_order",
            timestamp=1234567890.0,
        )
        hash1 = event.compute_hash()
        hash2 = event.compute_hash()
        
        # Hash should be deterministic
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex

    def test_to_dict(self):
        """Test to_dict method."""
        event = AuditEvent(
            event_id="audit_123",
            category=AuditCategory.TRADING,
            severity=AuditSeverity.INFO,
            action="place_order",
            timestamp=1234567890.0,
        )
        d = event.to_dict()
        
        assert d["event_id"] == "audit_123"
        assert d["category"] == "trading"
        assert d["severity"] == "info"
        assert "timestamp_iso" in d

    def test_from_dict(self):
        """Test from_dict method."""
        data = {
            "event_id": "audit_123",
            "category": "trading",
            "severity": "info",
            "action": "place_order",
            "actor_id": "user_456",
            "actor_type": "user",
            "actor_ip": "127.0.0.1",
            "target_type": "order",
            "target_id": "order_789",
            "details": {"symbol": "BTC/USD"},
            "result": "success",
            "error_message": "",
            "timestamp": 1234567890.0,
            "duration_ms": 100.0,
            "previous_hash": "genesis",
            "event_hash": "abc123",
        }
        event = AuditEvent.from_dict(data)
        
        assert event.event_id == "audit_123"
        assert event.category == AuditCategory.TRADING
        assert event.severity == AuditSeverity.INFO


class TestAuditLogger:
    """Test AuditLogger class."""

    def test_initialization(self, tmp_path):
        """Test audit logger initialization."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        assert logger.log_dir == log_dir
        assert logger._last_hash == "genesis"
        assert len(logger._buffer) == 0
        assert logger._total_events == 0

    def test_log_event(self, tmp_path):
        """Test logging an event."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        event_id = logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            severity=AuditSeverity.INFO,
            actor_id="user_123",
            details={"symbol": "BTC/USD"},
        )
        
        assert event_id.startswith("audit_")
        assert len(logger._buffer) == 1
        assert logger._total_events == 1

    def test_log_critical_flushes(self, tmp_path):
        """Test that critical events flush buffer."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        with patch.object(logger, '_flush') as mock_flush:
            logger.log(
                category=AuditCategory.SYSTEM,
                action="emergency_stop",
                severity=AuditSeverity.CRITICAL,
            )
            
            mock_flush.assert_called()

    def test_flush(self, tmp_path):
        """Test flush method."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            severity=AuditSeverity.INFO,
        )
        
        logger._flush()
        
        assert len(logger._buffer) == 0

    def test_flush_empty_buffer(self, tmp_path):
        """Test flush with empty buffer."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        # Should not raise
        logger._flush()
        assert len(logger._buffer) == 0

    def test_query(self, tmp_path):
        """Test query method."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        # Log some events
        logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            severity=AuditSeverity.INFO,
            actor_id="user_1",
        )
        logger._flush()
        
        # Query by category
        events = logger.query(category=AuditCategory.TRADING)
        assert len(events) == 1
        assert events[0].action == "place_order"

    def test_query_by_actor(self, tmp_path):
        """Test query by actor_id."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            actor_id="user_1",
        )
        logger.log(
            category=AuditCategory.TRADING,
            action="cancel_order",
            actor_id="user_2",
        )
        logger._flush()
        
        events = logger.query(actor_id="user_1")
        assert len(events) == 1
        assert events[0].actor_id == "user_1"

    def test_query_by_time_range(self, tmp_path):
        """Test query by time range."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        now = time.time()
        logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            timestamp=now - 3600,  # 1 hour ago
        )
        logger._flush()
        
        events = logger.query(start_time=now - 7200, end_time=now)
        assert len(events) == 1

    def test_verify_chain_empty(self, tmp_path):
        """Test verify_chain with no events."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        result = logger.verify_chain()
        
        assert result["total_events"] == 0
        assert result["valid_events"] == 0
        assert result["chain_valid"] is True

    def test_get_stats(self, tmp_path):
        """Test get_stats method."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        logger.log(category=AuditCategory.TRADING, action="place_order")
        logger.log(category=AuditCategory.WALLET, action="deposit")
        
        stats = logger.get_stats()
        
        assert stats["total_events"] == 2
        assert stats["events_by_category"]["trading"] == 1
        assert stats["events_by_category"]["wallet"] == 1

    def test_export_json(self, tmp_path):
        """Test export to JSON."""
        log_dir = tmp_path / "audit"
        logger = AuditLogger(log_dir=str(log_dir))
        
        now = time.time()
        logger.log(
            category=AuditCategory.TRADING,
            action="place_order",
            timestamp=now,
        )
        
        export_path = logger.export(
            start_time=now - 3600,
            end_time=now + 3600,
            format="json",
        )
        
        assert export_path.endswith(".json")
        assert Path(export_path).exists()


class TestGetAuditLogger:
    """Test get_audit_logger function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _audit_logger
        import compliance.audit_logger as al
        al._audit_logger = None

    def test_singleton(self, tmp_path):
        """Test get_audit_logger returns singleton."""
        with patch('pathlib.Path.mkdir'):
            logger1 = get_audit_logger()
            logger2 = get_audit_logger()
            assert logger1 is logger2
