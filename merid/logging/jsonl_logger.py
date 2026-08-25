"""
JSONL (JSON Lines) logging utility for dual-side evaluation events.

This module provides structured logging in JSON Lines format where each event
is one line of valid JSON. This format is standard for ingestion tools and
makes downstream analysis easy.

Event Types:
- DUAL_SIDE_EVALUATION: Complete dual-side evaluation with both edges
- SIDE_REJECTION: Rejection of one side with reason
- PRICE_VALIDATION_FAILURE: Price reconstruction events
- ORDER_SUBMISSION: Order submission linked to evaluation
- ORDER_REJECTION: Order rejection with reason and stage
- VELOCITY_ALIGNMENT_DIAGNOSTIC: Velocity alignment tracking
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path
import uuid


class JSONLLogger:
    """
    JSON Lines logger for structured event logging.
    
    Each event is logged as one line of valid JSON, making it easy to
    parse and ingest into log aggregation systems.
    """
    
    def __init__(self, log_file: Optional[str] = None):
        """
        Initialize JSONL logger.
        
        Args:
            log_file: Optional file path for persistent logging.
                     If None, logs to stdout via standard logger.
        """
        self.log_file = log_file
        self.logger = logging.getLogger("jsonl_logger")
        
        if log_file:
            # Ensure log directory exists
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _write_line(self, event: Dict[str, Any]) -> None:
        """
        Write a single event as one JSON line.
        
        Args:
            event: Event dictionary to log
        """
        try:
            json_line = json.dumps(event, separators=(',', ':'))
            
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(json_line + '\n')
            else:
                # Log via standard logger
                self.logger.info(json_line)
                
        except Exception as e:
            self.logger.error(f"Failed to write JSONL event: {e}")
    
    def log_dual_side_evaluation(
        self,
        asset: str,
        market_id: str,
        velocity: float,
        velocity_threshold: float,
        yes_side: Dict[str, Any],
        no_side: Dict[str, Any],
        selection: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log complete dual-side evaluation event.
        
        Args:
            asset: Asset identifier (BTC, ETH, etc.)
            market_id: Kalshi market ID
            velocity: Velocity value
            velocity_threshold: Velocity threshold
            yes_side: YES side data (price, edge, validation, status)
            no_side: NO side data (price, edge, validation, status)
            selection: Selection data (selected_side, edge_ratio, etc.)
            context: Optional context data (strike_target, regime, etc.)
        """
        event = {
            "event_type": "DUAL_SIDE_EVALUATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": str(uuid.uuid4()),
            "asset": asset,
            "market_id": market_id,
            "velocity": {
                "value": velocity,
                "threshold": velocity_threshold,
                "sign": "positive" if velocity > 0 else "negative",
                "role": "edge_boost"
            },
            "yes_side": yes_side,
            "no_side": no_side,
            "selection": selection,
            "context": context or {}
        }
        
        self._write_line(event)
    
    def log_side_rejection(
        self,
        evaluation_id: str,
        asset: str,
        side: str,
        rejection_stage: str,
        rejection_reason: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log side rejection event.
        
        Args:
            evaluation_id: Evaluation ID
            asset: Asset identifier
            side: Side being rejected (yes/no)
            rejection_stage: Stage where rejection occurred
            rejection_reason: Reason for rejection
            details: Optional details about rejection
        """
        event = {
            "event_type": "SIDE_REJECTION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": evaluation_id,
            "asset": asset,
            "side": side,
            "rejection_stage": rejection_stage,
            "rejection_reason": rejection_reason,
            "details": details or {}
        }
        
        self._write_line(event)
    
    def log_price_validation_failure(
        self,
        evaluation_id: str,
        asset: str,
        side: str,
        failure_type: str,
        details: Dict[str, Any],
        action: str
    ) -> None:
        """
        Log price validation failure event.
        
        Args:
            evaluation_id: Evaluation ID
            asset: Asset identifier
            side: Side with price issue
            failure_type: Type of failure (N/A_PRICE_DETECTED, etc.)
            details: Details about failure and reconstruction
            action: Action taken (RECONSTRUCTED_AND_PROCEEDED, REJECTED, etc.)
        """
        event = {
            "event_type": "PRICE_VALIDATION_FAILURE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": evaluation_id,
            "asset": asset,
            "side": side,
            "failure_type": failure_type,
            "details": details,
            "action": action
        }
        
        self._write_line(event)
    
    def log_order_submission(
        self,
        evaluation_id: str,
        order_id: str,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        count: int,
        risk_checks: Dict[str, Any]
    ) -> None:
        """
        Log order submission event.
        
        Args:
            evaluation_id: Evaluation ID
            order_id: Order ID
            ticker: Market ticker
            side: Order side (yes/no)
            action: Order action (buy/sell)
            price_cents: Order price in cents
            count: Order count
            risk_checks: Risk check results
        """
        event = {
            "event_type": "ORDER_SUBMISSION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": evaluation_id,
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "action": action,
            "price_cents": price_cents,
            "count": count,
            "risk_checks": risk_checks
        }
        
        self._write_line(event)
    
    def log_order_rejection(
        self,
        evaluation_id: str,
        order_id: str,
        ticker: str,
        side: str,
        rejection_reason: str,
        rejection_stage: str,
        constraints: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log order rejection event.
        
        Args:
            evaluation_id: Evaluation ID
            order_id: Order ID
            ticker: Market ticker
            side: Order side
            rejection_reason: Reason for rejection
            rejection_stage: Stage where rejection occurred
            constraints: Constraint details that caused rejection
        """
        event = {
            "event_type": "ORDER_REJECTION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": evaluation_id,
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "rejection_reason": rejection_reason,
            "rejection_stage": rejection_stage,
            "constraints": constraints or {}
        }
        
        self._write_line(event)
    
    def log_velocity_alignment_diagnostic(
        self,
        evaluation_id: str,
        asset: str,
        velocity: float,
        velocity_expected_side: str,
        velocity_expected_edge: float,
        opposite_side: str,
        opposite_edge: float,
        actual_selected_side: str,
        actual_selected_edge: float,
        alignment: str
    ) -> None:
        """
        Log velocity alignment diagnostic event.
        
        Args:
            evaluation_id: Evaluation ID
            asset: Asset identifier
            velocity: Velocity value
            velocity_expected_side: Side expected from velocity
            velocity_expected_edge: Edge on velocity-expected side
            opposite_side: Opposite side
            opposite_edge: Edge on opposite side
            actual_selected_side: Actually selected side
            actual_selected_edge: Actually selected edge
            alignment: ALIGNED or COUNTER_TREND
        """
        event = {
            "event_type": "VELOCITY_ALIGNMENT_DIAGNOSTIC",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": evaluation_id,
            "asset": asset,
            "velocity": velocity,
            "velocity_expected_side": velocity_expected_side,
            "velocity_expected_edge": velocity_expected_edge,
            "opposite_side": opposite_side,
            "opposite_edge": opposite_edge,
            "actual_selected_side": actual_selected_side,
            "actual_selected_edge": actual_selected_edge,
            "alignment": alignment
        }
        
        self._write_line(event)


# Global logger instance
_global_jsonl_logger: Optional[JSONLLogger] = None


def get_jsonl_logger(log_file: Optional[str] = None) -> JSONLLogger:
    """
    Get or create the global JSONL logger instance.
    
    Args:
        log_file: Optional log file path
        
    Returns:
        JSONLLogger instance
    """
    global _global_jsonl_logger
    
    if _global_jsonl_logger is None:
        _global_jsonl_logger = JSONLLogger(log_file)
    
    return _global_jsonl_logger


def validate_jsonl_schema(event: Dict[str, Any], event_type: str) -> bool:
    """
    Validate that an event has the required fields for its event type.
    
    Args:
        event: Event dictionary
        event_type: Expected event type
        
    Returns:
        True if valid, False otherwise
    """
    required_fields = {
        "DUAL_SIDE_EVALUATION": [
            "event_type", "timestamp", "evaluation_id", "asset", "market_id",
            "velocity", "yes_side", "no_side", "selection"
        ],
        "SIDE_REJECTION": [
            "event_type", "timestamp", "evaluation_id", "asset", "side",
            "rejection_stage", "rejection_reason"
        ],
        "PRICE_VALIDATION_FAILURE": [
            "event_type", "timestamp", "evaluation_id", "asset", "side",
            "failure_type", "details", "action"
        ],
        "ORDER_SUBMISSION": [
            "event_type", "timestamp", "evaluation_id", "order_id", "ticker",
            "side", "action", "price_cents", "count", "risk_checks"
        ],
        "ORDER_REJECTION": [
            "event_type", "timestamp", "evaluation_id", "order_id", "ticker",
            "side", "rejection_reason", "rejection_stage"
        ],
        "VELOCITY_ALIGNMENT_DIAGNOSTIC": [
            "event_type", "timestamp", "evaluation_id", "asset", "velocity",
            "velocity_expected_side", "actual_selected_side", "alignment"
        ]
    }
    
    if event_type not in required_fields:
        return False
    
    for field in required_fields[event_type]:
        if field not in event:
            return False
    
    return True
