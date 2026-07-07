"""Tests for order router risk contract validation.

INVARIANT MARKER: This test validates the "No Trade Without Exit" invariant by ensuring
crypto 15m markets require full risk contract linkage (exit_policy_id, window_resolution_id,
risk_tier, max_hold_seconds) before order submission.
"""

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent, _is_crypto_15m_market, _validate_risk_contract_linkage


class TestIsCrypto15mMarket:
    """Tests for _is_crypto_15m_market function."""
    
    def test_btc_15m_market(self):
        """Test BTC 15m market detection."""
        assert _is_crypto_15m_market("KXBTC15M-12345") is True
        assert _is_crypto_15m_market("KXBTC15M-T79299.99") is True
    
    def test_eth_15m_market(self):
        """Test ETH 15m market detection."""
        assert _is_crypto_15m_market("KXETH15M-12345") is True
    
    def test_sol_15m_market(self):
        """Test SOL 15m market detection."""
        assert _is_crypto_15m_market("KXSOL15M-12345") is True
    
    def test_xrp_15m_market(self):
        """Test XRP 15m market detection."""
        assert _is_crypto_15m_market("KXXRP15M-12345") is True
    
    def test_doge_15m_market(self):
        """Test DOGE 15m market detection."""
        assert _is_crypto_15m_market("KXDOGE15M-12345") is True
    
    def test_non_crypto_market(self):
        """Test non-crypto market."""
        assert _is_crypto_15m_market("KXFOREX-USD-12345") is False
        assert _is_crypto_15m_market("KXEVENT-12345") is False
    
    def test_case_insensitive(self):
        """Test case insensitivity."""
        assert _is_crypto_15m_market("kxbtc15m-12345") is True
        assert _is_crypto_15m_market("Kxbtc15m-12345") is True


class TestValidateRiskContractLinkage:
    """Tests for _validate_risk_contract_linkage function."""
    
    def test_non_crypto_market_passes(self):
        """Test that non-crypto markets pass validation."""
        intent = OrderIntent(
            ticker="KXFOREX-USD-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is True
        assert error is None
    
    def test_crypto_15m_entry_with_full_linkage_passes(self):
        """Test that crypto 15m entry with full linkage passes."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            risk_tier="A",
            max_hold_seconds=900,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is True
        assert error is None
    
    def test_crypto_15m_entry_missing_window_resolution_id_fails(self):
        """Test that crypto 15m entry without window_resolution_id fails."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            exit_policy_id="ep_123",
            risk_tier="A",
            max_hold_seconds=900,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "window_resolution_id" in error
    
    def test_crypto_15m_entry_missing_exit_policy_id_fails(self):
        """Test that crypto 15m entry without exit_policy_id fails."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            window_resolution_id="wr_123",
            risk_tier="A",
            max_hold_seconds=900,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "exit_policy_id" in error
    
    def test_crypto_15m_entry_missing_risk_tier_fails(self):
        """Test that crypto 15m entry without risk_tier fails."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            max_hold_seconds=900,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "risk_tier" in error
    
    def test_crypto_15m_entry_missing_max_hold_seconds_fails(self):
        """Test that crypto 15m entry without max_hold_seconds fails."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            risk_tier="A",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "max_hold_seconds" in error
    
    def test_crypto_15m_exit_with_exit_policy_id_passes(self):
        """Test that crypto 15m exit with exit_policy_id passes."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="sell",  # Exit action
            price_cents=50,
            count=10,
            exit_policy_id="ep_123",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is True
        assert error is None
    
    def test_crypto_15m_exit_missing_exit_policy_id_fails(self):
        """Test that crypto 15m exit without exit_policy_id fails."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="sell",  # Exit action
            price_cents=50,
            count=10,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "exit_policy_id" in error
    
    def test_crypto_15m_sell_action_treated_as_exit(self):
        """Test that sell action is treated as exit."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="sell",
            price_cents=50,
            count=10,
            exit_policy_id="ep_123",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        # Sell is exit, so only exit_policy_id required
        assert is_valid is True
    
    def test_crypto_15m_buy_action_requires_full_linkage(self):
        """Test that buy action requires full linkage."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            exit_policy_id="ep_123",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        # Buy is entry, so full linkage required
        assert is_valid is False
        assert "window_resolution_id" in error
    
    def test_crypto_15m_source_take_profit_treated_as_exit(self):
        """Test that take_profit source is treated as exit."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            source="take_profit_manager",
            exit_policy_id="ep_123",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        # Source contains "take_profit", treated as exit
        assert is_valid is True
    
    def test_crypto_15m_source_stop_loss_treated_as_exit(self):
        """Test that stop_loss source is treated as exit."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            source="stop_loss",
            exit_policy_id="ep_123",
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        # Source contains "stop_loss", treated as exit
        assert is_valid is True
    
    def test_multiple_missing_fields_reported(self):
        """Test that multiple missing fields are all reported."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        is_valid, error = _validate_risk_contract_linkage(intent)
        assert is_valid is False
        assert "window_resolution_id" in error
        assert "exit_policy_id" in error
        assert "risk_tier" in error
        assert "max_hold_seconds" in error


class TestOrderIntentRiskContractFields:
    """Tests for OrderIntent risk contract fields."""
    
    def test_order_intent_with_risk_contract_fields(self):
        """Test creating OrderIntent with risk contract fields."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            risk_tier="A",
            trailing_enabled=True,
            max_hold_seconds=900,
        )
        assert intent.window_resolution_id == "wr_123"
        assert intent.exit_policy_id == "ep_123"
        assert intent.risk_tier == "A"
        assert intent.trailing_enabled is True
        assert intent.max_hold_seconds == 900
    
    def test_order_intent_risk_contract_fields_optional(self):
        """Test that risk contract fields are optional."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        assert intent.window_resolution_id is None
        assert intent.exit_policy_id is None
        assert intent.risk_tier is None
        assert intent.trailing_enabled is None
        assert intent.max_hold_seconds is None
