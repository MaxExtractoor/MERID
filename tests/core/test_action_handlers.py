"""Tests for core/action_handlers.py."""
import pytest
from unittest.mock import patch
from core.action_handlers import (
    _handle_propose_order, _handle_explain_decision, _handle_request_sim,
    register_default_actions
)


class TestHandleProposeOrder:
    """Test _handle_propose_order handler."""

    def test_handle_propose_order(self):
        """Test order proposal handler."""
        payload = {"symbol": "BTC", "side": "buy", "amount": 1.0}
        result = _handle_propose_order(payload)
        assert result["accepted"] is True
        assert result["details"] == payload


class TestHandleExplainDecision:
    """Test _handle_explain_decision handler."""

    def test_handle_explain_decision(self):
        """Test explain decision handler."""
        payload = {"decision_id": "d1"}
        result = _handle_explain_decision(payload)
        assert "explanation" in result
        assert result["payload"] == payload


class TestHandleRequestSim:
    """Test _handle_request_sim handler."""

    def test_handle_request_sim(self):
        """Test simulation request handler."""
        payload = {"scenario": "bull_market"}
        result = _handle_request_sim(payload)
        assert result["scheduled"] is True
        assert "bull_market" in result["job_id"]

    def test_handle_request_sim_default(self):
        """Test simulation request with default scenario."""
        payload = {}
        result = _handle_request_sim(payload)
        assert result["scheduled"] is True
        assert "default" in result["job_id"]


class TestRegisterDefaultActions:
    """Test register_default_actions function."""

    def test_register_actions(self):
        """Test actions are registered."""
        with patch('core.action_handlers.get_function_router') as mock_get_router:
            mock_router = mock_get_router.return_value
            register_default_actions()
            assert mock_router.register.call_count == 4
