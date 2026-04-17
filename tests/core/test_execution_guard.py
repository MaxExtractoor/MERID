"""Tests for core/execution_guard.py."""
import pytest
from core.execution_guard import (
    ActionType, ExecutionContext, ActionResult, ExecutionGuard, get_execution_guard
)


class TestActionType:
    """Test ActionType enum."""

    def test_action_type_values(self):
        """Test ActionType enum values."""
        assert ActionType.PROPOSE_ORDER == "propose_order"
        assert ActionType.ADJUST_PARAMETER == "adjust_parameter"
        assert ActionType.REQUEST_SIM_RUN == "request_sim_run"
        assert ActionType.INITIATE_PAYMENT == "initiate_payment"
        assert ActionType.EXPLAIN_DECISION == "explain_decision"


class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_creation(self):
        """Test ExecutionContext creation."""
        context = ExecutionContext(
            caller="test_user",
            role="trader",
            environment_flags={"online": True},
            permissions={"propose_order": True}
        )
        assert context.caller == "test_user"
        assert context.role == "trader"
        assert context.environment_flags == {"online": True}
        assert context.permissions == {"propose_order": True}


class TestActionResult:
    """Test ActionResult dataclass."""

    def test_creation(self):
        """Test ActionResult creation."""
        result = ActionResult(
            allowed=True,
            reason="Approved",
            timestamp=1234567890.0
        )
        assert result.allowed is True
        assert result.reason == "Approved"
        assert result.timestamp == 1234567890.0


class TestExecutionGuard:
    """Test ExecutionGuard class."""

    def test_initialization(self):
        """Test ExecutionGuard initialization."""
        guard = ExecutionGuard()
        assert ActionType.PROPOSE_ORDER in guard._policies
        assert ActionType.INITIATE_PAYMENT in guard._policies

    def test_set_policy(self):
        """Test setting custom policy."""
        guard = ExecutionGuard()
        guard.set_policy(ActionType.PROPOSE_ORDER, {"risk_limit": 100000.0})
        assert guard._policies[ActionType.PROPOSE_ORDER]["risk_limit"] == 100000.0

    def test_evaluate_no_policy(self):
        """Test evaluate with no policy returns deny."""
        guard = ExecutionGuard()
        context = ExecutionContext("user", "role", {}, {})
        # Test with action type that has no policy by removing it
        del guard._policies[ActionType.EXPLAIN_DECISION]
        result = guard.evaluate(ActionType.EXPLAIN_DECISION, {}, context)
        assert result.allowed is False
        assert "No policy" in result.reason

    def test_evaluate_offline_mode_blocks_trading(self):
        """Test offline mode blocks trading actions."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"online": False},
            {"propose_order": True}
        )
        result = guard.evaluate(ActionType.PROPOSE_ORDER, {}, context)
        assert result.allowed is False
        assert "Offline" in result.reason

    def test_evaluate_offline_allows_non_trading(self):
        """Test offline mode allows non-trading actions."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"online": False},
            {"explain_decision": True}
        )
        result = guard.evaluate(ActionType.EXPLAIN_DECISION, {}, context)
        assert result.allowed is True

    def test_evaluate_vpn_only_invalid_profile(self):
        """Test VPN-only mode with invalid routing profile."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"vpn_only": True, "routing_profile": "standard"},
            {"propose_order": True}
        )
        result = guard.evaluate(ActionType.PROPOSE_ORDER, {}, context)
        assert result.allowed is False
        assert "VPN" in result.reason

    def test_evaluate_missing_permission(self):
        """Test missing permission denies action."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"online": True},
            {"propose_order": False}
        )
        result = guard.evaluate(ActionType.PROPOSE_ORDER, {}, context)
        assert result.allowed is False
        assert "permission" in result.reason

    def test_evaluate_exceeds_risk_limit(self):
        """Test amount exceeding risk limit is denied."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"online": True},
            {"propose_order": True}
        )
        payload = {"notional": 600000.0}  # Exceeds 500k limit
        result = guard.evaluate(ActionType.PROPOSE_ORDER, payload, context)
        assert result.allowed is False
        assert "exceeds limit" in result.reason

    def test_evaluate_approved(self):
        """Test approved action."""
        guard = ExecutionGuard()
        context = ExecutionContext(
            "user", "role",
            {"online": True},
            {"propose_order": True}
        )
        payload = {"notional": 100000.0}  # Under limit
        result = guard.evaluate(ActionType.PROPOSE_ORDER, payload, context)
        assert result.allowed is True
        assert result.reason == "Approved"

    def test_default_policies(self):
        """Test default policy values."""
        guard = ExecutionGuard()
        assert guard._policies[ActionType.PROPOSE_ORDER]["risk_limit"] == 500000.0
        assert guard._policies[ActionType.INITIATE_PAYMENT]["risk_limit"] == 250000.0
        assert guard._policies[ActionType.ADJUST_PARAMETER]["risk_limit"] is None


class TestGetExecutionGuard:
    """Test get_execution_guard singleton."""

    def test_singleton(self):
        """Test get_execution_guard returns singleton."""
        guard1 = get_execution_guard()
        guard2 = get_execution_guard()
        assert guard1 is guard2
