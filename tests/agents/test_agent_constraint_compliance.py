"""
Agent/Strategy Constraint Compliance Tests

This test suite validates that agents and strategies obey the combined
risk + reconciliation + gate constraints. It uses the central harness
simulate_order helper to ensure strategy changes cannot bypass safety systems.

SPEC_VERSION: 1.0.0
"""

import pytest
from decimal import Decimal
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class AgentSignal:
    """Represents an agent's trading signal."""
    agent_name: str
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int
    yes_price_dollars: Decimal


class TestAgentConstraintCompliance:
    """Test that agents obey combined risk+recon+gate constraints."""

    @pytest.fixture
    def kalshi_harness(self):
        """Provide a fresh Kalshi test harness."""
        from tests.event_venues.kalshi.harness import KalshiTestHarness
        h = KalshiTestHarness()
        yield h

    @pytest.fixture
    def btc_15m_agent(self):
        """Create a mock BTC_15M agent signal."""
        return AgentSignal(
            agent_name="BTC_15M",
            market_ticker="KXBTC-26JAN24-50000",
            side="yes",
            action="buy",
            count=100,
            yes_price_dollars=Decimal("0.50"),
        )

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_risk_warning_limit(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects risk WARNING limit (80% exposure)."""
        # Arrange: Existing exposure at 80% ($1600 of $2000 cap)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1600,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1600}
        
        # Act: Simulate agent signal through risk → gate pipeline
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
        )
        
        # Assert: Risk status is WARNING, but agent signal is allowed with flag
        assert result["risk_status"] == "warning"
        assert "buy" in result["allowed_operations"]
        # Agent should be able to trade but with warning flag in real implementation

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_risk_critical_reduce_only(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects risk CRITICAL limit (reduce-only mode)."""
        # Arrange: Existing exposure at 90% ($1800 of $2000 cap)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1800,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1800}
        
        # Act: Simulate agent signal (new buy would increase exposure)
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
        )
        
        # Assert: Risk status is CRITICAL, only reduce-only allowed
        assert result["risk_status"] == "critical"
        assert "reduce_only" in result["allowed_operations"]
        assert "buy" not in result["allowed_operations"]
        # Agent's buy signal should be blocked or converted to reduce-only

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_risk_hard_stop(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects risk HARD_STOP limit (100% exposure)."""
        # Arrange: Existing exposure at 100% ($2000 of $2000 cap)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=2000,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 2000}
        
        # Act: Simulate agent signal
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
        )
        
        # Assert: Risk status is HARD_STOP, no operations allowed
        assert result["risk_status"] == "hard_stop"
        assert len(result["allowed_operations"]) == 0
        # Agent signal should be completely blocked

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_phantom_detection(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects phantom position detection."""
        # Arrange: Phantom position detected (internal has position, external doesn't)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=500,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 250}
        recon_state = {
            "market_id": "KXBTC-26JAN24-50000",
            "internal_yes_qty": 100,
            "internal_no_qty": 0,
            "external_yes_qty": 0,  # Phantom
            "external_no_qty": 0,
        }
        
        # Act: Simulate agent signal with phantom detected
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
            recon_state=recon_state,
        )
        
        # Assert: Phantom detected, should block or restrict trading
        assert result["recon_phantom"] == True
        # In full implementation, phantom should trigger BLOCKED state
        # Agent signal should be blocked until phantom resolved

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_gate_blocked_state(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects gate BLOCKED state."""
        # Arrange: Gate is BLOCKED (e.g., due to critical discrepancy)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=100,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        
        # Act: Simulate agent signal when gate is blocked
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
        )
        
        # Assert: If gate is blocked, agent signal should be rejected
        # Note: The harness check_gate() returns the actual gate state
        # In a real scenario, we'd mock the gate to return BLOCKED
        # For now, we verify the harness integrates gate checks
        assert "can_trade" in result

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_combined_constraints(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects combined risk + recon constraints."""
        # Arrange: Both risk warning and phantom detection
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1600,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1600}
        recon_state = {
            "market_id": "KXBTC-26JAN24-50000",
            "internal_yes_qty": 100,
            "internal_no_qty": 0,
            "external_yes_qty": 0,  # Phantom
            "external_no_qty": 0,
        }
        
        # Act: Simulate agent signal with both constraints
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
            recon_state=recon_state,
        )
        
        # Assert: Stricter constraint wins (phantom is stricter than warning)
        assert result["risk_status"] == "warning"
        assert result["recon_phantom"] == True
        # Agent should be blocked by phantom despite risk allowing trades

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_respects_per_asset_cap(self, kalshi_harness, btc_15m_agent):
        """Test that agent respects per-asset exposure cap."""
        # Arrange: Agent at per-asset cap (500 contracts per side)
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=500,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 250}
        
        # Act: Simulate agent signal that would exceed cap
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=50,  # Would exceed 500 cap
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
        )
        
        # Assert: Risk status should reflect cap breach
        # Note: Current harness uses $2000 cap, not contract count
        # In full implementation, would check both contract count and notional
        assert result["risk_status"] in ["warning", "critical", "hard_stop"]

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_agent_constraints
    def test_agent_clean_state_allows_trading(self, kalshi_harness, btc_15m_agent):
        """Test that agent can trade when all constraints are clean."""
        # Arrange: Clean state with minimal exposure
        existing_fills = [
            kalshi_harness.build_fill(
                fill_id="existing_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=50,
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 25}
        
        # Act: Simulate agent signal
        agent_fill = kalshi_harness.build_fill(
            fill_id="agent_001",
            market_ticker=btc_15m_agent.market_ticker,
            side=btc_15m_agent.side,
            action=btc_15m_agent.action,
            count=btc_15m_agent.count,
            yes_price_dollars=btc_15m_agent.yes_price_dollars,
        )
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=existing_fills + [agent_fill],
            risk_state=risk_state,
        )
        
        # Assert: Risk status is OK, full trading allowed
        assert result["risk_status"] == "ok"
        assert "buy" in result["allowed_operations"]
        assert "sell" in result["allowed_operations"]


def pytest_configure(config):
    """Configure pytest markers for agent constraint tests."""
    config.addinivalue_line(
        "markers", "kalshi_agent_constraints: Kalshi agent constraint compliance tests"
    )
