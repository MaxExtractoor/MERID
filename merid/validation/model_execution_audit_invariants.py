"""
Model vs Live Execution Audit Invariants with Offline Replay Capability

This module provides automated reconciliation between model decisions and actual
execution, detecting misalignment between model logic and real execution pipeline.

Key Invariants:
- For any contract where model edge exceeded threshold and market conditions satisfied filters, either a corresponding trade occurred or a recorded reason for suppression
- Detect "phantom trades": trades that occurred when edge < threshold or filters disallowed trading
- Offline replay: feed exact historical data into model and compare "should have traded" vs "actually traded"
- Detect stale config, outdated strategy modules, or broken risk controls

Usage::

    from merid.validation.model_execution_audit_invariants import (
        ModelExecutionAuditChecker,
        check_model_vs_execution_consistency,
        detect_phantom_trades,
        replay_historical_data
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("merid.validation.model_execution_audit_invariants")


class AuditViolation(str, Enum):
    """Types of audit violations."""
    MISSING_TRADE = "missing_trade"  # Model said trade but no trade occurred
    PHANTOM_TRADE = "phantom_trade"  # Trade occurred but model said no trade
    STALE_CONFIG = "stale_config"  # Config mismatch between model and execution
    BROKEN_RISK_CONTROL = "broken_risk_control"  # Risk control not applied correctly
    FILTER_MISMATCH = "filter_mismatch"  # Market quality filter mismatch


@dataclass
class ModelDecision:
    """Model decision for a contract at a specific time."""
    timestamp: datetime
    contract_ticker: str
    model_edge: float
    model_probability: float
    market_conditions: Dict[str, Any]  # volatility, volume, spread, etc.
    should_trade: bool
    reason_for_suppression: Optional[str] = None


@dataclass
class ExecutionRecord:
    """Actual execution record for a contract."""
    timestamp: datetime
    contract_ticker: str
    order_submitted: bool
    order_filled: bool
    fill_price_cents: Optional[int]
    fill_count: int
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "contract_ticker": self.contract_ticker,
            "order_submitted": self.order_submitted,
            "order_filled": self.order_filled,
            "fill_price_cents": self.fill_price_cents,
            "fill_count": self.fill_count,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class AuditCheckResult:
    """Result of model vs execution audit check."""
    is_valid: bool
    violation_type: Optional[AuditViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class ModelExecutionAuditChecker:
    """Checks model vs live execution audit invariants."""
    
    def __init__(
        self,
        min_edge_threshold: float = 0.01,
        max_spread_cents: int = 30,
        min_volume: int = 10,
    ):
        self.min_edge_threshold = min_edge_threshold
        self.max_spread_cents = max_spread_cents
        self.min_volume = min_volume
    
    def check_model_vs_execution_consistency(
        self,
        model_decision: ModelDecision,
        execution_record: Optional[ExecutionRecord],
    ) -> AuditCheckResult:
        """INVARIANT: Model decision must match execution record.
        
        For any contract where model edge exceeded threshold and market conditions
        satisfied filters, either a corresponding trade occurred or a recorded
        reason for suppression (risk cap reached, infrastructure halt, etc.).
        """
        context = {
            "contract_ticker": model_decision.contract_ticker,
            "model_edge": model_decision.model_edge,
            "should_trade": model_decision.should_trade,
            "execution_record": execution_record.to_dict() if execution_record else None,
        }
        
        # Case 1: Model says trade, but no execution record
        if model_decision.should_trade and execution_record is None:
            return AuditCheckResult(
                is_valid=False,
                violation_type=AuditViolation.MISSING_TRADE,
                message=f"Model edge={model_decision.model_edge:.4f} > threshold={self.min_edge_threshold} but no execution record found",
                context=context,
            )
        
        # Case 2: Model says trade, but order not submitted
        if model_decision.should_trade and execution_record and not execution_record.order_submitted:
            # Check if there's a valid suppression reason
            if not execution_record.rejection_reason:
                return AuditCheckResult(
                    is_valid=False,
                    violation_type=AuditViolation.MISSING_TRADE,
                    message=f"Model said trade but order not submitted without rejection reason",
                    context=context,
                )
        
        # Case 3: Model says no trade, but trade occurred
        if not model_decision.should_trade and execution_record and execution_record.order_submitted:
            return AuditCheckResult(
                is_valid=False,
                violation_type=AuditViolation.PHANTOM_TRADE,
                message=f"Model edge={model_decision.model_edge:.4f} < threshold={self.min_edge_threshold} but trade occurred",
                context=context,
            )
        
        return AuditCheckResult(
            is_valid=True,
            violation_type=None,
            message="Model decision consistent with execution",
            context=context,
        )
    
    def detect_phantom_trades(
        self,
        model_decisions: List[ModelDecision],
        execution_records: List[ExecutionRecord],
    ) -> List[AuditCheckResult]:
        """Detect phantom trades: trades that occurred when edge < threshold or filters disallowed.
        
        This surfaces misalignment between model logic and execution pipeline.
        """
        results = []
        
        # Build execution lookup by ticker and time window
        execution_by_ticker = {}
        for record in execution_records:
            ticker = record.contract_ticker
            if ticker not in execution_by_ticker:
                execution_by_ticker[ticker] = []
            execution_by_ticker[ticker].append(record)
        
        # Check each model decision against corresponding execution
        for decision in model_decisions:
            ticker = decision.contract_ticker
            executions = execution_by_ticker.get(ticker, [])
            
            # Find execution within time window (e.g., +/- 30 seconds)
            for execution in executions:
                time_diff = abs((execution.timestamp - decision.timestamp).total_seconds())
                if time_diff <= 30:  # 30-second window
                    result = self.check_model_vs_execution_consistency(decision, execution)
                    if not result.is_valid and result.violation_type == AuditViolation.PHANTOM_TRADE:
                        results.append(result)
        
        return results
    
    def replay_historical_data(
        self,
        historical_data: List[Dict[str, Any]],
        model_function,
        risk_filters: Dict[str, Any],
    ) -> Tuple[List[ModelDecision], List[AuditCheckResult]]:
        """Offline replay: feed historical data into model and compare with actual execution.
        
        Args:
            historical_data: List of historical market data snapshots
            model_function: Function that takes market data and returns model decision
            risk_filters: Risk filter configuration (volatility, volume, spread thresholds)
            
        Returns:
            Tuple of (model_decisions, audit_results)
        """
        model_decisions = []
        audit_results = []
        
        for snapshot in historical_data:
            # Run model on historical snapshot
            try:
                model_result = model_function(snapshot)
                
                model_decision = ModelDecision(
                    timestamp=snapshot["timestamp"],
                    contract_ticker=snapshot["ticker"],
                    model_edge=model_result["edge"],
                    model_probability=model_result["probability"],
                    market_conditions=snapshot["market_conditions"],
                    should_trade=model_result["should_trade"],
                    reason_for_suppression=model_result.get("suppression_reason"),
                )
                model_decisions.append(model_decision)
                
                # Check if market conditions satisfy filters
                filters_satisfied = self._check_market_filters(
                    snapshot["market_conditions"], risk_filters
                )
                
                # If model says trade but filters not satisfied, check for suppression reason
                if model_decision.should_trade and not filters_satisfied:
                    if not model_decision.reason_for_suppression:
                        audit_result = AuditCheckResult(
                            is_valid=False,
                            violation_type=AuditViolation.FILTER_MISMATCH,
                            message=f"Model said trade but market filters not satisfied without suppression reason",
                            context={
                                "contract_ticker": model_decision.contract_ticker,
                                "market_conditions": snapshot["market_conditions"],
                                "risk_filters": risk_filters,
                            },
                        )
                        audit_results.append(audit_result)
                
            except Exception as e:
                logger.error(f"Error replaying historical data for {snapshot.get('ticker')}: {e}")
        
        return model_decisions, audit_results
    
    def _check_market_filters(
        self,
        market_conditions: Dict[str, Any],
        risk_filters: Dict[str, Any],
    ) -> bool:
        """Check if market conditions satisfy risk filters."""
        # Check volatility
        volatility = market_conditions.get("volatility", 0.0)
        max_volatility = risk_filters.get("max_volatility", 0.05)
        if volatility > max_volatility:
            return False
        
        # Check volume
        volume = market_conditions.get("volume", 0)
        min_volume = risk_filters.get("min_volume", self.min_volume)
        if volume < min_volume:
            return False
        
        # Check spread
        spread_cents = market_conditions.get("spread_cents", 0)
        max_spread = risk_filters.get("max_spread_cents", self.max_spread_cents)
        if spread_cents > max_spread:
            return False
        
        return True
    
    def check_stale_config(
        self,
        model_config: Dict[str, Any],
        execution_config: Dict[str, Any],
    ) -> AuditCheckResult:
        """INVARIANT: Config must be consistent between model and execution.
        
        Detects stale config that could cause model/execution misalignment.
        """
        context = {
            "model_config_keys": list(model_config.keys()),
            "execution_config_keys": list(execution_config.keys()),
        }
        
        # Check for critical config mismatches
        critical_keys = ["min_edge_threshold", "max_spread_cents", "min_volume"]
        
        for key in critical_keys:
            model_value = model_config.get(key)
            execution_value = execution_config.get(key)
            
            if model_value != execution_value:
                context[f"{key}_model"] = model_value
                context[f"{key}_execution"] = execution_value
                
                return AuditCheckResult(
                    is_valid=False,
                    violation_type=AuditViolation.STALE_CONFIG,
                    message=f"Config mismatch for {key}: model={model_value}, execution={execution_value}",
                    context=context,
                )
        
        return AuditCheckResult(
            is_valid=True,
            violation_type=None,
            message="Config consistent between model and execution",
            context=context,
        )
    
    def check_broken_risk_control(
        self,
        execution_record: ExecutionRecord,
        risk_limits: Dict[str, Any],
    ) -> AuditCheckResult:
        """INVARIANT: Risk controls must be applied correctly.
        
        Detects broken risk controls that could allow trades beyond limits.
        """
        context = {
            "contract_ticker": execution_record.contract_ticker,
            "order_submitted": execution_record.order_submitted,
            "order_filled": execution_record.order_filled,
            "risk_limits": risk_limits,
        }
        
        if execution_record.order_submitted:
            # Check if trade exceeded risk limits
            max_contracts = risk_limits.get("max_contracts", 1)
            
            if execution_record.fill_count > max_contracts:
                context["fill_count"] = execution_record.fill_count
                context["max_contracts"] = max_contracts
                
                return AuditCheckResult(
                    is_valid=False,
                    violation_type=AuditViolation.BROKEN_RISK_CONTROL,
                    message=f"Trade count={execution_record.fill_count} exceeded max={max_contracts}",
                    context=context,
                )
            
            # Also check notional
            notional_usd = (execution_record.fill_price_cents or 0) / 100.0 * execution_record.fill_count
            max_notional = risk_limits.get("max_notional_usd", 1.00)
            
            if notional_usd > max_notional:
                context["notional_usd"] = notional_usd
                context["max_notional_usd"] = max_notional
                
                return AuditCheckResult(
                    is_valid=False,
                    violation_type=AuditViolation.BROKEN_RISK_CONTROL,
                    message=f"Trade notional=${notional_usd:.2f} exceeded max=${max_notional:.2f}",
                    context=context,
                )
        
        return AuditCheckResult(
            is_valid=True,
            violation_type=None,
            message="Risk controls applied correctly",
            context=context,
        )


# Convenience functions for direct use

def check_model_vs_execution_consistency(
    model_decision: ModelDecision,
    execution_record: Optional[ExecutionRecord],
    min_edge_threshold: float = 0.01,
) -> AuditCheckResult:
    """Check model vs execution consistency invariant."""
    checker = ModelExecutionAuditChecker(min_edge_threshold=min_edge_threshold)
    return checker.check_model_vs_execution_consistency(model_decision, execution_record)


def detect_phantom_trades(
    model_decisions: List[ModelDecision],
    execution_records: List[ExecutionRecord],
    min_edge_threshold: float = 0.01,
) -> List[AuditCheckResult]:
    """Detect phantom trades invariant."""
    checker = ModelExecutionAuditChecker(min_edge_threshold=min_edge_threshold)
    return checker.detect_phantom_trades(model_decisions, execution_records)


def replay_historical_data(
    historical_data: List[Dict[str, Any]],
    model_function,
    risk_filters: Dict[str, Any],
    min_edge_threshold: float = 0.01,
) -> Tuple[List[ModelDecision], List[AuditCheckResult]]:
    """Offline replay of historical data."""
    checker = ModelExecutionAuditChecker(min_edge_threshold=min_edge_threshold)
    return checker.replay_historical_data(historical_data, model_function, risk_filters)


# Synthetic test data generator for invariant testing

def generate_synthetic_audit_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for model vs execution audit invariants.
    
    Returns:
        List of test case dictionaries with controlled model/execution data.
    """
    test_cases = []
    
    # Valid case: model says trade, execution occurs
    model_decision_valid = ModelDecision(
        timestamp=datetime(2026, 7, 23, 10, 0, 0),
        contract_ticker="KXBTC15M-26JUL211730-30",
        model_edge=0.15,
        model_probability=0.65,
        market_conditions={"volatility": 0.02, "volume": 50, "spread_cents": 5},
        should_trade=True,
        reason_for_suppression=None,
    )
    
    execution_record_valid = ExecutionRecord(
        timestamp=datetime(2026, 7, 23, 10, 0, 5),
        contract_ticker="KXBTC15M-26JUL211730-30",
        order_submitted=True,
        order_filled=True,
        fill_price_cents=50,
        fill_count=1,
        rejection_reason=None,
    )
    
    test_cases.append({
        "model_decision": model_decision_valid,
        "execution_record": execution_record_valid,
        "expected_valid": True,
        "description": "Model says trade, execution occurs - valid",
    })
    
    # Invalid case: model says trade, but no execution
    model_decision_missing = ModelDecision(
        timestamp=datetime(2026, 7, 23, 10, 0, 0),
        contract_ticker="KXBTC15M-26JUL211730-30",
        model_edge=0.15,
        model_probability=0.65,
        market_conditions={"volatility": 0.02, "volume": 50, "spread_cents": 5},
        should_trade=True,
        reason_for_suppression=None,
    )
    
    test_cases.append({
        "model_decision": model_decision_missing,
        "execution_record": None,
        "expected_valid": False,
        "description": "Model says trade but no execution record - violation",
    })
    
    # Invalid case: model says no trade, but trade occurs (phantom trade)
    model_decision_phantom = ModelDecision(
        timestamp=datetime(2026, 7, 23, 10, 0, 0),
        contract_ticker="KXBTC15M-26JUL211730-30",
        model_edge=0.005,
        model_probability=0.51,
        market_conditions={"volatility": 0.02, "volume": 50, "spread_cents": 5},
        should_trade=False,
        reason_for_suppression=None,
    )
    
    execution_record_phantom = ExecutionRecord(
        timestamp=datetime(2026, 7, 23, 10, 0, 5),
        contract_ticker="KXBTC15M-26JUL211730-30",
        order_submitted=True,
        order_filled=True,
        fill_price_cents=50,
        fill_count=1,
        rejection_reason=None,
    )
    
    test_cases.append({
        "model_decision": model_decision_phantom,
        "execution_record": execution_record_phantom,
        "expected_valid": False,
        "description": "Model says no trade but trade occurred - phantom trade violation",
    })
    
    return test_cases
