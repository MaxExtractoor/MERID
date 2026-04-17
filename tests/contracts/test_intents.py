"""Tests for contracts/intents.py."""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from contracts.intents import (
    IntentType, IntentStatus, IntentPriority, IntentPayload, SimulationResult, Intent,
    INTENT_APPROVAL_THRESHOLDS, INTENT_REQUIRES_SIMULATION, IntentProcessor, get_intent_processor, _intent_processor
)
from contracts.system_contracts import SystemID


class TestIntentType:
    """Test IntentType enum."""

    def test_intent_type_values(self):
        """Test intent type enum values."""
        assert IntentType.ANALYZE.value == "analyze"
        assert IntentType.SIGNAL.value == "signal"
        assert IntentType.PROPOSE.value == "propose"
        assert IntentType.VOTE.value == "vote"
        assert IntentType.TRADE.value == "trade"
        assert IntentType.HEDGE.value == "hedge"
        assert IntentType.CLOSE_POSITION.value == "close_position"
        assert IntentType.MODIFY_ORDER.value == "modify_order"
        assert IntentType.ALLOCATE.value == "allocate"
        assert IntentType.RETURN_CAPITAL.value == "return_capital"
        assert IntentType.DEPLOY_DEFI.value == "deploy_defi"
        assert IntentType.WITHDRAW_DEFI.value == "withdraw_defi"
        assert IntentType.LOCKDOWN.value == "lockdown"
        assert IntentType.RELEASE_LOCKDOWN.value == "release_lockdown"
        assert IntentType.MODIFY_PARAMETER.value == "modify_parameter"
        assert IntentType.VETO.value == "veto"
        assert IntentType.EMERGENCY.value == "emergency"


class TestIntentStatus:
    """Test IntentStatus enum."""

    def test_intent_status_values(self):
        """Test intent status enum values."""
        assert IntentStatus.CREATED.value == "created"
        assert IntentStatus.VALIDATING.value == "validating"
        assert IntentStatus.SIMULATING.value == "simulating"
        assert IntentStatus.AWAITING_APPROVAL.value == "awaiting_approval"
        assert IntentStatus.APPROVED.value == "approved"
        assert IntentStatus.EXECUTING.value == "executing"
        assert IntentStatus.EXECUTED.value == "executed"
        assert IntentStatus.REJECTED.value == "rejected"
        assert IntentStatus.VETOED.value == "vetoed"
        assert IntentStatus.FAILED.value == "failed"
        assert IntentStatus.EXPIRED.value == "expired"


class TestIntentPriority:
    """Test IntentPriority enum."""

    def test_intent_priority_values(self):
        """Test intent priority enum values."""
        assert IntentPriority.LOW.value == 0
        assert IntentPriority.NORMAL.value == 1
        assert IntentPriority.HIGH.value == 2
        assert IntentPriority.CRITICAL.value == 3
        assert IntentPriority.EMERGENCY.value == 4


class TestIntentPayload:
    """Test IntentPayload dataclass."""

    def test_creation(self):
        """Test IntentPayload creation."""
        payload = IntentPayload(
            action="trade",
            parameters={"symbol": "BTC/USD", "side": "buy"},
            target_system=SystemID.EXECUTION,
            amount_usd=10000.0,
            symbol="BTC/USD"
        )
        assert payload.action == "trade"
        assert payload.parameters["symbol"] == "BTC/USD"
        assert payload.target_system == SystemID.EXECUTION

    def test_to_dict(self):
        """Test IntentPayload to_dict."""
        payload = IntentPayload(
            action="trade",
            parameters={"symbol": "BTC/USD"},
            target_system=SystemID.EXECUTION,
            amount_usd=10000.0
        )
        d = payload.to_dict()
        assert d["action"] == "trade"
        assert d["target_system"] == SystemID.EXECUTION.value
        assert d["amount_usd"] == 10000.0

    def test_from_dict(self):
        """Test IntentPayload from_dict."""
        data = {
            "action": "trade",
            "parameters": {"symbol": "BTC/USD"},
            "target_system": SystemID.EXECUTION.value,
            "amount_usd": 10000.0,
            "symbol": "BTC/USD"
        }
        payload = IntentPayload.from_dict(data)
        assert payload.action == "trade"
        assert payload.target_system == SystemID.EXECUTION


class TestSimulationResult:
    """Test SimulationResult dataclass."""

    def test_creation(self):
        """Test SimulationResult creation."""
        result = SimulationResult(
            success=True,
            predicted_outcome={"profit": 100.0},
            risk_score=0.3,
            warnings=["low liquidity"],
            estimated_cost_usd=10.0,
            estimated_duration_ms=150.0,
            side_effects=["price_impact"]
        )
        assert result.success is True
        assert result.risk_score == 0.3
        assert len(result.warnings) == 1

    def test_is_safe(self):
        """Test SimulationResult is_safe method."""
        result = SimulationResult(
            success=True,
            predicted_outcome={},
            risk_score=0.3,
            warnings=[],
            estimated_cost_usd=0.0,
            estimated_duration_ms=100.0,
            side_effects=[]
        )
        assert result.is_safe() is True
        assert result.is_safe(max_risk=0.2) is False

    def test_is_safe_not_success(self):
        """Test is_safe returns False when not successful."""
        result = SimulationResult(
            success=False,
            predicted_outcome={},
            risk_score=0.1,
            warnings=[],
            estimated_cost_usd=0.0,
            estimated_duration_ms=100.0,
            side_effects=[]
        )
        assert result.is_safe() is False


class TestIntent:
    """Test Intent dataclass."""

    def test_creation(self):
        """Test Intent creation."""
        payload = IntentPayload(action="trade", parameters={})
        intent = Intent(
            intent_id="intent_123",
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload,
            priority=IntentPriority.HIGH
        )
        assert intent.intent_id == "intent_123"
        assert intent.intent_type == IntentType.TRADE
        assert intent.source_system == SystemID.ANALYTICS
        assert intent.priority == IntentPriority.HIGH
        assert intent.status == IntentStatus.CREATED

    def test_default_ttl(self):
        """Test default TTL is set."""
        payload = IntentPayload(action="trade", parameters={})
        
        # Test emergency TTL
        intent_emergency = Intent(
            intent_id="e1", intent_type=IntentType.EMERGENCY,
            source_system=SystemID.ANALYTICS, payload=payload
        )
        assert intent_emergency.expires_at - intent_emergency.created_at == 60.0
        
        # Test trade TTL
        intent_trade = Intent(
            intent_id="t1", intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS, payload=payload
        )
        assert intent_trade.expires_at - intent_trade.created_at == 300.0

    def test_is_expired(self):
        """Test is_expired method."""
        payload = IntentPayload(action="trade", parameters={})
        intent = Intent(
            intent_id="i1", intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS, payload=payload
        )
        
        # Not expired initially
        assert intent.is_expired() is False
        
        # Expire it
        intent.expires_at = time.time() - 1
        assert intent.is_expired() is True

    def test_compute_hash(self):
        """Test compute_hash method."""
        payload = IntentPayload(action="trade", parameters={"sym": "BTC"})
        intent = Intent(
            intent_id="i1", intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS, payload=payload
        )
        hash1 = intent.compute_hash()
        hash2 = intent.compute_hash()
        
        assert hash1 == hash2  # Deterministic
        assert len(hash1) == 64  # SHA256 hex

    def test_to_dict(self):
        """Test to_dict method."""
        payload = IntentPayload(action="trade", parameters={})
        intent = Intent(
            intent_id="i1", intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS, payload=payload
        )
        d = intent.to_dict()
        
        assert d["intent_id"] == "i1"
        assert d["intent_type"] == "trade"
        assert "hash" in d


class TestIntentApprovalThresholds:
    """Test INTENT_APPROVAL_THRESHOLDS."""

    def test_analyze_no_approval(self):
        """Test ANALYZE requires no approval."""
        assert INTENT_APPROVAL_THRESHOLDS[IntentType.ANALYZE] == 0

    def test_trade_requires_approval(self):
        """Test TRADE requires 2 approvals."""
        assert INTENT_APPROVAL_THRESHOLDS[IntentType.TRADE] == 2

    def test_emergency_requires_approval(self):
        """Test EMERGENCY requires 2 approvals."""
        assert INTENT_APPROVAL_THRESHOLDS[IntentType.EMERGENCY] == 2

    def test_deploy_defi_high_threshold(self):
        """Test DEPLOY_DEFI requires 4 approvals."""
        assert INTENT_APPROVAL_THRESHOLDS[IntentType.DEPLOY_DEFI] == 4


class TestIntentRequiresSimulation:
    """Test INTENT_REQUIRES_SIMULATION."""

    def test_analyze_no_simulation(self):
        """Test ANALYZE requires no simulation."""
        assert INTENT_REQUIRES_SIMULATION[IntentType.ANALYZE] is False

    def test_trade_requires_simulation(self):
        """Test TRADE requires simulation."""
        assert INTENT_REQUIRES_SIMULATION[IntentType.TRADE] is True

    def test_signal_no_simulation(self):
        """Test SIGNAL requires no simulation."""
        assert INTENT_REQUIRES_SIMULATION[IntentType.SIGNAL] is False


class TestIntentProcessor:
    """Test IntentProcessor class."""

    def test_initialization(self):
        """Test processor initialization."""
        processor = IntentProcessor()
        assert processor._pending_intents == {}
        assert processor._processed_intents == []
        assert processor._simulators == {}
        assert processor._executors == {}

    def test_create_intent(self):
        """Test create_intent method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload,
            priority=IntentPriority.HIGH
        )
        
        assert intent.intent_type == IntentType.TRADE
        assert intent.source_system == SystemID.ANALYTICS
        assert intent.priority == IntentPriority.HIGH
        assert intent.intent_id in processor._pending_intents

    def test_create_intent_sets_approval_threshold(self):
        """Test create_intent sets correct approval threshold."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        assert intent.approval_threshold == 2
        assert intent.requires_approval is True

    def test_approve_intent(self):
        """Test approve_intent method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="analyze", parameters={})
        
        # Create intent that requires 1 approval
        intent = processor.create_intent(
            intent_type=IntentType.PROPOSE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        intent.status = IntentStatus.AWAITING_APPROVAL
        intent.approval_threshold = 1
        
        result = processor.approve_intent(intent.intent_id, "approver_1")
        
        assert result is True
        assert "approver_1" in intent.approvals
        assert intent.status == IntentStatus.APPROVED

    def test_approve_intent_not_found(self):
        """Test approve_intent when intent not found."""
        processor = IntentProcessor()
        result = processor.approve_intent("non_existent", "approver_1")
        assert result is False

    def test_approve_intent_wrong_status(self):
        """Test approve_intent when intent not awaiting approval."""
        processor = IntentProcessor()
        payload = IntentPayload(action="analyze", parameters={})
        intent = processor.create_intent(
            intent_type=IntentType.ANALYZE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        result = processor.approve_intent(intent.intent_id, "approver_1")
        assert result is False

    def test_reject_intent(self):
        """Test reject_intent method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        result = processor.reject_intent(intent.intent_id, "rejector_1", "risk too high")
        
        assert result is True
        assert intent.status == IntentStatus.REJECTED
        assert "rejector_1" in intent.rejections

    def test_veto_intent(self):
        """Test veto_intent method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        result = processor.veto_intent(intent.intent_id, "skeptic-agent-01", "safety concern")
        
        assert result is True
        assert intent.status == IntentStatus.VETOED
        assert intent.veto_by == "skeptic-agent-01"

    def test_veto_intent_not_authority(self):
        """Test veto_intent by non-authority fails."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        result = processor.veto_intent(intent.intent_id, "random_user", "concern")
        assert result is False

    def test_get_pending_intents(self):
        """Test get_pending_intents method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        
        intent1 = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        intent2 = processor.create_intent(
            intent_type=IntentType.SIGNAL,
            source_system=SystemID.GOVERNANCE,
            payload=payload
        )
        
        all_intents = processor.get_pending_intents()
        assert len(all_intents) == 2
        
        analytics_intents = processor.get_pending_intents(system=SystemID.ANALYTICS)
        assert len(analytics_intents) == 1
        
        trade_intents = processor.get_pending_intents(intent_type=IntentType.TRADE)
        assert len(trade_intents) == 1

    def test_get_intent(self):
        """Test get_intent method."""
        processor = IntentProcessor()
        payload = IntentPayload(action="trade", parameters={})
        intent = processor.create_intent(
            intent_type=IntentType.TRADE,
            source_system=SystemID.ANALYTICS,
            payload=payload
        )
        
        retrieved = processor.get_intent(intent.intent_id)
        assert retrieved == intent
        
        assert processor.get_intent("non_existent") is None


class TestGetIntentProcessor:
    """Test get_intent_processor function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _intent_processor
        import contracts.intents as intents
        intents._intent_processor = None

    def test_singleton(self):
        """Test get_intent_processor returns singleton."""
        processor1 = get_intent_processor()
        processor2 = get_intent_processor()
        assert processor1 is processor2
