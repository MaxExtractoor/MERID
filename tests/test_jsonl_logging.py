"""
Tests for JSONL logging format and schema validation.

These tests ensure logs are valid JSON, contain required fields,
and are append-only for audit trail integrity.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from merid.logging.jsonl_logger import JSONLLogger, get_jsonl_logger, validate_jsonl_schema


class TestJSONLLogger:
    """Test JSONL logger functionality."""
    
    def test_log_is_valid_json(self):
        """
        Test that each logged event is valid JSON and can be parsed.
        """
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            log_file = f.name
        
        try:
            logger = JSONLLogger(log_file)
            
            # Log a dual-side evaluation
            logger.log_dual_side_evaluation(
                asset="BTC",
                market_id="KXBTC15M-26JUL211745-45",
                velocity=0.0002,
                velocity_threshold=0.00015,
                yes_side={
                    "price_cents": 68,
                    "in_range": True,
                    "edge_pct": 0.08,
                    "status": "ACCEPTED"
                },
                no_side={
                    "price_cents": 32,
                    "in_range": True,
                    "edge_pct": 0.05,
                    "status": "REJECTED"
                },
                selection={
                    "selected_side": "yes",
                    "selected_edge": 0.08,
                    "selection_method": "HYBRID_ALIGNED",
                    "edge_ratio": 0.625,
                    "velocity_aligned": True
                }
            )
            
            # Read and validate log file
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            assert len(lines) == 1, f"Expected 1 log line, got {len(lines)}"
            
            # Parse JSON
            event = json.loads(lines[0])
            assert event is not None, "Failed to parse JSON"
            assert event["event_type"] == "DUAL_SIDE_EVALUATION"
            
        finally:
            Path(log_file).unlink(missing_ok=True)
    
    def test_log_contains_required_fields(self):
        """
        Test that DUAL_SIDE_EVALUATION log contains all required fields.
        """
        logger = JSONLLogger()  # Log to stdout
        
        # Capture log output (would need to patch logger in real test)
        # For now, just validate the event structure
        event = {
            "event_type": "DUAL_SIDE_EVALUATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": "test_eval_123",
            "asset": "BTC",
            "market_id": "KXBTC15M-26JUL211745-45",
            "velocity": {
                "value": 0.0002,
                "threshold": 0.00015,
                "sign": "positive",
                "role": "edge_boost"
            },
            "yes_side": {
                "price_cents": 68,
                "in_range": True,
                "edge_pct": 0.08,
                "status": "ACCEPTED"
            },
            "no_side": {
                "price_cents": 32,
                "in_range": True,
                "edge_pct": 0.05,
                "status": "REJECTED"
            },
            "selection": {
                "selected_side": "yes",
                "selected_edge": 0.08,
                "selection_method": "HYBRID_ALIGNED",
                "edge_ratio": 0.625,
                "velocity_aligned": True
            },
            "context": {}
        }
        
        # Validate schema
        is_valid = validate_jsonl_schema(event, "DUAL_SIDE_EVALUATION")
        assert is_valid == True, "Event should pass schema validation"
    
    def test_append_only_logging(self):
        """
        Test that logging is append-only - each evaluation adds a new line.
        """
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            log_file = f.name
        
        try:
            logger = JSONLLogger(log_file)
            
            # Log first event
            logger.log_dual_side_evaluation(
                asset="BTC",
                market_id="KXBTC15M-26JUL211745-45",
                velocity=0.0002,
                velocity_threshold=0.00015,
                yes_side={"price_cents": 68, "in_range": True, "edge_pct": 0.08, "status": "ACCEPTED"},
                no_side={"price_cents": 32, "in_range": True, "edge_pct": 0.05, "status": "REJECTED"},
                selection={"selected_side": "yes", "selected_edge": 0.08, "selection_method": "HYBRID_ALIGNED", "edge_ratio": 0.625, "velocity_aligned": True}
            )
            
            # Log second event
            logger.log_dual_side_evaluation(
                asset="ETH",
                market_id="KXETH15M-26JUL211745-45",
                velocity=0.0001,
                velocity_threshold=0.00015,
                yes_side={"price_cents": 45, "in_range": True, "edge_pct": 0.03, "status": "REJECTED"},
                no_side={"price_cents": 55, "in_range": True, "edge_pct": 0.07, "status": "ACCEPTED"},
                selection={"selected_side": "no", "selected_edge": 0.07, "selection_method": "MAX_EDGE_COUNTER_TREND", "edge_ratio": 2.33, "velocity_aligned": False}
            )
            
            # Read and verify
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            assert len(lines) == 2, f"Expected 2 log lines, got {len(lines)}"
            
            # Verify both events are distinct
            event1 = json.loads(lines[0])
            event2 = json.loads(lines[1])
            
            assert event1["asset"] == "BTC"
            assert event2["asset"] == "ETH"
            assert event1["evaluation_id"] != event2["evaluation_id"]
            
        finally:
            Path(log_file).unlink(missing_ok=True)
    
    def test_all_event_types_valid(self):
        """
        Test that all event types are valid JSON and pass schema validation.
        """
        events = [
            {
                "event_type": "SIDE_REJECTION",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evaluation_id": "eval_123",
                "asset": "BTC",
                "side": "no",
                "rejection_stage": "EDGE_CALCULATION",
                "rejection_reason": "EDGE_NOT_POSITIVE",
                "details": {"edge_pct": -0.01}
            },
            {
                "event_type": "PRICE_VALIDATION_FAILURE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evaluation_id": "eval_123",
                "asset": "BTC",
                "side": "yes",
                "failure_type": "N/A_PRICE_DETECTED",
                "details": {"reconstruction_method": "DUALITY_INVERSION", "reconstructed_price": 68},
                "action": "RECONSTRUCTED_AND_PROCEEDED"
            },
            {
                "event_type": "ORDER_SUBMISSION",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evaluation_id": "eval_123",
                "order_id": "ord_456",
                "ticker": "KXBTC15M-26JUL211745-45",
                "side": "yes",
                "action": "buy",
                "price_cents": 42,
                "count": 1,
                "risk_checks": {"exposure": "PASS", "price_band": "PASS"}
            },
            {
                "event_type": "ORDER_REJECTION",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evaluation_id": "eval_123",
                "order_id": "ord_456",
                "ticker": "KXBTC15M-26JUL211745-45",
                "side": "yes",
                "rejection_reason": "EXPOSURE_CAP_EXCEEDED",
                "rejection_stage": "RISK_CHECK",
                "constraints": {"exposure_cap_usd": 1.00, "current_exposure_usd": 0.95}
            },
            {
                "event_type": "VELOCITY_ALIGNMENT_DIAGNOSTIC",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evaluation_id": "eval_123",
                "asset": "BTC",
                "velocity": 0.0002,
                "velocity_expected_side": "yes",
                "velocity_expected_edge": 0.08,
                "opposite_side": "no",
                "opposite_edge": 0.05,
                "actual_selected_side": "yes",
                "actual_selected_edge": 0.08,
                "alignment": "ALIGNED"
            }
        ]
        
        for event in events:
            # Validate JSON serializable
            json_str = json.dumps(event)
            parsed = json.loads(json_str)
            assert parsed == event, f"JSON round-trip failed for {event['event_type']}"
            
            # Validate schema
            is_valid = validate_jsonl_schema(event, event["event_type"])
            assert is_valid == True, f"Schema validation failed for {event['event_type']}"
    
    def test_global_logger_singleton(self):
        """
        Test that get_jsonl_logger returns the same instance.
        """
        logger1 = get_jsonl_logger()
        logger2 = get_jsonl_logger()
        
        assert logger1 is logger2, "Should return singleton instance"
    
    def test_schema_validation_missing_field(self):
        """
        Test that schema validation fails when required fields are missing.
        """
        incomplete_event = {
            "event_type": "DUAL_SIDE_EVALUATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": "eval_123",
            "asset": "BTC"
            # Missing: market_id, velocity, yes_side, no_side, selection
        }
        
        is_valid = validate_jsonl_schema(incomplete_event, "DUAL_SIDE_EVALUATION")
        assert is_valid == False, "Should fail validation with missing fields"
    
    def test_schema_validation_invalid_event_type(self):
        """
        Test that schema validation fails for unknown event types.
        """
        event = {
            "event_type": "UNKNOWN_EVENT",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        is_valid = validate_jsonl_schema(event, "UNKNOWN_EVENT")
        assert is_valid == False, "Should fail validation for unknown event type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
