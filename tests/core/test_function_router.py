"""Tests for core/function_router.py."""
import pytest
from unittest.mock import Mock, patch
from core.function_router import (
    FunctionSignature, FunctionRouter, get_function_router
)
from core.execution_guard import ActionType


class TestFunctionSignature:
    """Test FunctionSignature dataclass."""

    def test_creation(self):
        """Test FunctionSignature creation."""
        func = lambda x: x
        sig = FunctionSignature(
            action_type=ActionType.PROPOSE_ORDER,
            func=func,
            required_permissions={"propose_order": True}
        )
        assert sig.action_type == ActionType.PROPOSE_ORDER
        assert sig.func == func
        assert sig.required_permissions == {"propose_order": True}


class TestFunctionRouter:
    """Test FunctionRouter class."""

    def test_initialization(self):
        """Test FunctionRouter initialization."""
        router = FunctionRouter()
        assert router._signatures == {}

    def test_register_function(self):
        """Test registering a function."""
        router = FunctionRouter()
        func = lambda x: x
        sig = FunctionSignature(
            action_type=ActionType.PROPOSE_ORDER,
            func=func,
            required_permissions={}
        )
        router.register("test_func", sig)
        assert "test_func" in router._signatures

    def test_register_overwrite_warning(self):
        """Test warning on function overwrite."""
        router = FunctionRouter()
        sig = FunctionSignature(ActionType.PROPOSE_ORDER, lambda x: x, {})
        router.register("func", sig)
        # Should not raise, just log warning
        router.register("func", sig)

    @patch('core.function_router.get_execution_guard')
    @patch('core.function_router.get_environment_flags')
    def test_call_allowed(self, mock_get_flags, mock_get_guard):
        """Test calling an allowed function."""
        mock_flags = Mock()
        mock_flags.online = True
        mock_flags.enforced_routing_profile.value = "standard"
        mock_flags.vpn_only = False
        mock_flags.privacy_mode = False
        mock_get_flags.return_value = mock_flags

        mock_guard = Mock()
        mock_result = Mock()
        mock_result.allowed = True
        mock_result.reason = None
        mock_guard.evaluate.return_value = mock_result
        mock_get_guard.return_value = mock_guard

        router = FunctionRouter()
        func = Mock(return_value={"result": "success"})
        sig = FunctionSignature(ActionType.PROPOSE_ORDER, func, {"propose_order": True})
        router.register("test", sig)

        result = router.call("test", {"key": "value"}, "caller", "role")

        assert result["status"] == "ok"
        assert result["output"] == {"result": "success"}
        func.assert_called_once_with({"key": "value"})

    @patch('core.function_router.get_execution_guard')
    @patch('core.function_router.get_environment_flags')
    def test_call_denied(self, mock_get_flags, mock_get_guard):
        """Test calling a denied function."""
        mock_flags = Mock()
        mock_flags.online = True
        mock_flags.enforced_routing_profile.value = "standard"
        mock_flags.vpn_only = False
        mock_flags.privacy_mode = False
        mock_get_flags.return_value = mock_flags

        mock_guard = Mock()
        mock_result = Mock()
        mock_result.allowed = False
        mock_result.reason = "Permission denied"
        mock_guard.evaluate.return_value = mock_result
        mock_get_guard.return_value = mock_guard

        router = FunctionRouter()
        func = Mock()
        sig = FunctionSignature(ActionType.PROPOSE_ORDER, func, {})
        router.register("test", sig)

        result = router.call("test", {}, "caller", "role")

        assert result["status"] == "denied"
        assert result["reason"] == "Permission denied"
        func.assert_not_called()

    def test_call_unregistered_raises(self):
        """Test calling unregistered function raises."""
        router = FunctionRouter()
        with pytest.raises(ValueError, match="not registered"):
            router.call("unknown", {}, "caller", "role")


class TestGetFunctionRouter:
    """Test get_function_router singleton."""

    def test_singleton(self):
        """Test get_function_router returns singleton."""
        router1 = get_function_router()
        router2 = get_function_router()
        assert router1 is router2
