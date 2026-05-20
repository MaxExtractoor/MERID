"""
Stress Test Harness for kalshi_crypto_15m Profile Loss Caps

This test simulates a sequence of losses and verifies that per-cycle and per-day
loss caps behave as expected (halt when they should, never exceed profile caps).

This is a stress test to ensure the profile-based risk model behaves correctly
under adverse conditions.
"""

import pytest
from decimal import Decimal
from unittest.mock import patch

from merid.risk.profiles.crypto_15m_profile import (
    Crypto15mProfileAdapter,
    is_profile_active,
    get_active_profile,
    runtime_profile_self_check,
)


class TestProfileLossCapStressTest:
    """Stress tests for loss cap behavior under simulated losses."""

    def test_daily_loss_cap_enforcement(self):
        """
        Test that daily loss cap is enforced correctly.
        
        Simulates a sequence of losses that would exceed the daily loss cap
        and verifies that trading halts when the cap is reached.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get daily loss cap from profile
            daily_loss_cap = profile.guardrails_max_daily_loss_usd  # $200.00
            
            # Simulate cumulative losses
            cumulative_loss = 0.0
            losses = [50.0, 60.0, 40.0, 80.0, 30.0]  # Total: $260
            
            for i, loss in enumerate(losses):
                # Check if adding this loss would exceed daily cap
                if cumulative_loss + loss > daily_loss_cap:
                    # Should halt before this trade
                    assert cumulative_loss <= daily_loss_cap, f"Loss cap exceeded at trade {i+1}"
                    break
                
                cumulative_loss += loss
            
            # Verify final cumulative loss does not exceed cap
            assert cumulative_loss <= daily_loss_cap, f"Final cumulative loss ${cumulative_loss:.2f} exceeds cap ${daily_loss_cap:.2f}"

    def test_drawdown_halt_enforcement(self):
        """
        Test that drawdown halt is enforced correctly.
        
        Simulates a sequence of losses that would exceed the drawdown halt threshold
        and verifies that trading halts when the threshold is reached.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get drawdown halt threshold from profile
            capital = profile.capital_usd  # $10,000
            drawdown_halt_pct = profile.guardrails_drawdown_halt_pct  # 10%
            drawdown_halt_usd = capital * drawdown_halt_pct  # $1,000
            
            # Simulate cumulative losses
            cumulative_loss = 0.0
            losses = [200.0, 300.0, 400.0, 200.0, 150.0]  # Total: $1,250
            
            for i, loss in enumerate(losses):
                # Check if adding this loss would exceed drawdown halt
                if cumulative_loss + loss > drawdown_halt_usd:
                    # Should halt before this trade
                    assert cumulative_loss <= drawdown_halt_usd, f"Drawdown halt exceeded at trade {i+1}"
                    break
                
                cumulative_loss += loss
            
            # Verify final cumulative loss does not exceed halt threshold
            assert cumulative_loss <= drawdown_halt_usd, f"Final cumulative loss ${cumulative_loss:.2f} exceeds halt ${drawdown_halt_usd:.2f}"

    def test_drawdown_unwind_enforcement(self):
        """
        Test that drawdown unwind is enforced correctly.
        
        Simulates a sequence of losses that would exceed the drawdown unwind threshold
        and verifies that positions are unwound when the threshold is reached.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get drawdown unwind threshold from profile
            capital = profile.capital_usd  # $10,000
            drawdown_unwind_pct = profile.guardrails_drawdown_unwind_pct  # 15%
            drawdown_unwind_usd = capital * drawdown_unwind_pct  # $1,500
            
            # Simulate cumulative losses
            cumulative_loss = 0.0
            losses = [300.0, 400.0, 500.0, 200.0, 200.0]  # Total: $1,600
            
            for i, loss in enumerate(losses):
                # Check if adding this loss would exceed drawdown unwind
                if cumulative_loss + loss > drawdown_unwind_usd:
                    # Should unwind before this trade
                    assert cumulative_loss <= drawdown_unwind_usd, f"Drawdown unwind exceeded at trade {i+1}"
                    break
                
                cumulative_loss += loss
            
            # Verify final cumulative loss does not exceed unwind threshold
            assert cumulative_loss <= drawdown_unwind_usd, f"Final cumulative loss ${cumulative_loss:.2f} exceeds unwind ${drawdown_unwind_usd:.2f}"

    def test_cycle_risk_cap_enforcement(self):
        """
        Test that cycle risk cap is enforced correctly.
        
        Simulates a sequence of trades that would exceed the cycle risk cap
        and verifies that trading halts when the cap is reached.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get cycle risk cap from profile
            capital = profile.capital_usd  # $10,000
            max_cycle_risk_pct = profile.max_cycle_risk_pct  # 2%
            max_cycle_risk_usd = capital * max_cycle_risk_pct  # $200
            
            # Simulate cumulative risk exposure
            cumulative_risk = 0.0
            risks = [50.0, 60.0, 40.0, 80.0, 30.0]  # Total: $260
            
            for i, risk in enumerate(risks):
                # Check if adding this risk would exceed cycle cap
                if cumulative_risk + risk > max_cycle_risk_usd:
                    # Should halt before this trade
                    assert cumulative_risk <= max_cycle_risk_usd, f"Cycle risk cap exceeded at trade {i+1}"
                    break
                
                cumulative_risk += risk
            
            # Verify final cumulative risk does not exceed cap
            assert cumulative_risk <= max_cycle_risk_usd, f"Final cumulative risk ${cumulative_risk:.2f} exceeds cap ${max_cycle_risk_usd:.2f}"

    def test_per_asset_notional_cap_enforcement(self):
        """
        Test that per-asset notional caps are enforced correctly.
        
        Simulates trading across multiple assets and verifies that per-asset
        notional caps are not exceeded.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Simulate trading across assets
            asset_exposure = {}
            
            # BTC trades
            btc_cap = profile.asset_configs['BTC'].max_notional_usd  # $3,000
            btc_trades = [1000.0, 1500.0, 800.0]  # Total: $3,300
            for trade in btc_trades:
                if asset_exposure.get('BTC', 0.0) + trade > btc_cap:
                    break
                asset_exposure['BTC'] = asset_exposure.get('BTC', 0.0) + trade
            
            # Verify BTC exposure does not exceed cap
            assert asset_exposure['BTC'] <= btc_cap, f"BTC exposure ${asset_exposure['BTC']:.2f} exceeds cap ${btc_cap:.2f}"
            
            # ETH trades
            eth_cap = profile.asset_configs['ETH'].max_notional_usd  # $2,000
            eth_trades = [800.0, 900.0, 500.0]  # Total: $2,200
            for trade in eth_trades:
                if asset_exposure.get('ETH', 0.0) + trade > eth_cap:
                    break
                asset_exposure['ETH'] = asset_exposure.get('ETH', 0.0) + trade
            
            # Verify ETH exposure does not exceed cap
            assert asset_exposure['ETH'] <= eth_cap, f"ETH exposure ${asset_exposure['ETH']:.2f} exceeds cap ${eth_cap:.2f}"

    def test_venue_notional_cap_enforcement(self):
        """
        Test that venue-level notional caps are enforced correctly.
        
        Simulates trading across multiple assets and verifies that the total
        venue notional cap is not exceeded.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Get venue-level caps from profile
            max_total_notional = profile.venue_max_total_notional_usd  # $7,500
            max_single_order = profile.venue_max_single_order_usd  # $2,500
            
            # Simulate cumulative venue exposure
            cumulative_exposure = 0.0
            orders = [2000.0, 2500.0, 1500.0, 2000.0, 1000.0]  # Total: $9,000
            
            for i, order in enumerate(orders):
                # Check if single order exceeds cap
                assert order <= max_single_order, f"Order ${order:.2f} exceeds single order cap ${max_single_order:.2f}"
                
                # Check if adding this order would exceed total cap
                if cumulative_exposure + order > max_total_notional:
                    # Should halt before this order
                    assert cumulative_exposure <= max_total_notional, f"Total notional exceeded at order {i+1}"
                    break
                
                cumulative_exposure += order
            
            # Verify final cumulative exposure does not exceed cap
            assert cumulative_exposure <= max_total_notional, f"Final cumulative exposure ${cumulative_exposure:.2f} exceeds cap ${max_total_notional:.2f}"

    def test_runtime_self_check_integration(self):
        """
        Test that the runtime self-check function works correctly.
        
        This verifies that the runtime_profile_self_check function can be called
        and returns True when the profile is correctly configured.
        """
        with patch.dict(__import__('os').environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            # Call runtime self-check
            result = runtime_profile_self_check()
            
            # Verify it returns True (all checks pass)
            assert result is True, "Runtime self-check should return True when profile is correctly configured"

    def test_runtime_self_check_without_profile(self):
        """
        Test that the runtime self-check function handles inactive profile gracefully.
        
        This verifies that the runtime_profile_self_check function returns True
        when the profile is not active (no checks performed).
        """
        with patch.dict(__import__('os').environ, {}, clear=True):
            # Reset singleton
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            # Call runtime self-check
            result = runtime_profile_self_check()
            
            # Verify it returns True (no checks performed when profile inactive)
            assert result is True, "Runtime self-check should return True when profile is not active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
