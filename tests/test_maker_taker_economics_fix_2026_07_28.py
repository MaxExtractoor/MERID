"""
Test suite for maker/taker economics fix (2026-07-28)

This test suite validates the critical fixes for:
1. Economics selection based on aggressiveness (resting=maker, marketable=taker)
2. Hedge universe coverage (all 5 crypto assets included by default)
3. Threshold logic (dynamic threshold for taker, passive threshold for maker)
4. Side invariants (buy yes / buy no mapping consistency)
5. Regression prevention (hardcoded-maker bug cannot reappear)

References:
- SEC memo on maker-taker fees: https://www.sec.gov/spotlight/emsac/memo-maker-taker-fees-on-equities-exchanges.pdf
- CME Group rulebook on audit trails: https://www.cmegroup.com/rulebook/files/RA1509-5.pdf
"""

import pytest
import os
from unittest.mock import patch, MagicMock


class TestEconomicsSelection:
    """Test that economics mode is correctly derived from aggressiveness."""
    
    def test_resting_order_uses_maker_economics(self):
        """Resting orders (aggressiveness=0.0) should use maker economics."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        
        # Mock dependencies at their actual location
        with patch('merid.event_venues.kalshi.spread_edge_analytics.compute_canonical_spreads') as mock_spreads, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_per_side_edges') as mock_edges:
            
            # Setup mock returns
            from merid.event_venues.kalshi.spread_edge_analytics import PerSideSpreadMetrics, PerSideEdgeMetrics
            
            mock_spreads.return_value = PerSideSpreadMetrics(
                yes_bid_cents=50, yes_ask_cents=51, yes_spread_cents=1,
                no_bid_cents=50, no_ask_cents=51, no_spread_cents=1
            )
            
            mock_edges.return_value = (
                PerSideEdgeMetrics(
                    side="yes",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                ),
                PerSideEdgeMetrics(
                    side="no",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                )
            )
            
            # Call with resting order (aggressiveness=0.0)
            passes, reason = check_market_microstructure_edge_aware(
                yes_bid_cents=50,
                no_bid_cents=50,
                p_hat_yes_cents=55.0,
                order_side="yes",
                order_price_cents=50,
                aggressiveness=0.0,  # Resting order
                ticker="KXBTC15M-26JUL281200-00"
            )
            
            # Verify compute_per_side_edges was called with use_maker_economics=True
            mock_edges.assert_called_once()
            call_kwargs = mock_edges.call_args[1]
            assert call_kwargs['use_maker_economics'] == True, \
                "Resting orders should use maker economics (use_maker_economics=True)"
    
    def test_marketable_order_uses_taker_economics(self):
        """Marketable orders (aggressiveness>0.0) should use taker economics."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        
        # Mock dependencies at their actual location
        with patch('merid.event_venues.kalshi.spread_edge_analytics.compute_canonical_spreads') as mock_spreads, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_per_side_edges') as mock_edges:
            
            # Setup mock returns
            from merid.event_venues.kalshi.spread_edge_analytics import PerSideSpreadMetrics, PerSideEdgeMetrics
            
            mock_spreads.return_value = PerSideSpreadMetrics(
                yes_bid_cents=50, yes_ask_cents=51, yes_spread_cents=1,
                no_bid_cents=50, no_ask_cents=51, no_spread_cents=1
            )
            
            mock_edges.return_value = (
                PerSideEdgeMetrics(
                    side="yes",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                ),
                PerSideEdgeMetrics(
                    side="no",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                )
            )
            
            # Call with marketable order (aggressiveness=0.5)
            passes, reason = check_market_microstructure_edge_aware(
                yes_bid_cents=50,
                no_bid_cents=50,
                p_hat_yes_cents=55.0,
                order_side="yes",
                order_price_cents=50,
                aggressiveness=0.5,  # Marketable order
                ticker="KXBTC15M-26JUL281200-00"
            )
            
            # Verify compute_per_side_edges was called with use_maker_economics=False
            mock_edges.assert_called_once()
            call_kwargs = mock_edges.call_args[1]
            assert call_kwargs['use_maker_economics'] == False, \
                "Marketable orders should use taker economics (use_maker_economics=False)"
    
    def test_aggressiveness_variations(self):
        """Test various aggressiveness values for correct economics selection."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        
        with patch('merid.event_venues.kalshi.spread_edge_analytics.compute_canonical_spreads') as mock_spreads, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_per_side_edges') as mock_edges:
            
            from merid.event_venues.kalshi.spread_edge_analytics import PerSideSpreadMetrics, PerSideEdgeMetrics
            
            mock_spreads.return_value = PerSideSpreadMetrics(
                yes_bid_cents=50, yes_ask_cents=51, yes_spread_cents=1,
                no_bid_cents=50, no_ask_cents=51, no_spread_cents=1
            )
            
            mock_edges.return_value = (
                PerSideEdgeMetrics(
                    side="yes",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                ),
                PerSideEdgeMetrics(
                    side="no",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                )
            )
            
            test_cases = [
                (0.0, True, "aggressiveness=0.0 should use maker economics"),
                (0.1, False, "aggressiveness=0.1 should use taker economics"),
                (0.5, False, "aggressiveness=0.5 should use taker economics"),
                (1.0, False, "aggressiveness=1.0 should use taker economics"),
            ]
            
            for aggressiveness, expected_maker, description in test_cases:
                mock_edges.reset_mock()
                
                check_market_microstructure_edge_aware(
                    yes_bid_cents=50,
                    no_bid_cents=50,
                    p_hat_yes_cents=55.0,
                    order_side="yes",
                    order_price_cents=50,
                    aggressiveness=aggressiveness,
                    ticker="KXBTC15M-26JUL281200-00"
                )
                
                call_kwargs = mock_edges.call_args[1]
                assert call_kwargs['use_maker_economics'] == expected_maker, description


class TestHedgeUniverseCoverage:
    """Test that hedge universe includes all 5 crypto assets by default."""
    
    def test_default_hedge_basket_includes_all_5_assets(self):
        """Default CRYPTO_BASKET_ASSETS should include BTC, ETH, SOL, XRP, DOGE."""
        from merid.hedging.exposure import CRYPTO_BASKET_ASSETS
        
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        actual_assets = set(CRYPTO_BASKET_ASSETS)
        
        assert actual_assets == expected_assets, \
            f"Default hedge basket should include all 5 assets. Expected {expected_assets}, got {actual_assets}"
    
    def test_hedge_basket_can_be_overridden_by_env(self):
        """Hedge basket can be overridden via MERID_HEDGE_CRYPTO_ASSETS environment variable."""
        from merid.hedging import exposure
        
        # Save original
        original_env = os.environ.get("MERID_HEDGE_CRYPTO_ASSETS")
        
        try:
            # Override with custom assets
            os.environ["MERID_HEDGE_CRYPTO_ASSETS"] = "BTC,ETH"
            
            # Reload the module to pick up new env var
            import importlib
            importlib.reload(exposure)
            
            from merid.hedging.exposure import CRYPTO_BASKET_ASSETS
            expected_assets = {"BTC", "ETH"}
            actual_assets = set(CRYPTO_BASKET_ASSETS)
            
            assert actual_assets == expected_assets, \
                f"Environment override should work. Expected {expected_assets}, got {actual_assets}"
        
        finally:
            # Restore original
            if original_env is not None:
                os.environ["MERID_HEDGE_CRYPTO_ASSETS"] = original_env
            else:
                os.environ.pop("MERID_HEDGE_CRYPTO_ASSETS", None)
            
            # Reload to restore default
            importlib.reload(exposure)
    
    def test_hedge_basket_whitespace_handling(self):
        """Hedge basket correctly handles whitespace in asset list."""
        from merid.hedging.exposure import CRYPTO_BASKET_ASSETS
        
        # All assets should be uppercase and no whitespace
        for asset in CRYPTO_BASKET_ASSETS:
            assert asset == asset.upper(), f"Asset should be uppercase: {asset}"
            assert asset == asset.strip(), f"Asset should have no whitespace: {asset}"
            assert len(asset) > 0, "Asset should not be empty"


class TestThresholdLogic:
    """Test that threshold logic is correctly applied based on economics mode."""
    
    def test_maker_orders_use_passive_threshold(self):
        """Maker orders should use maker-specific 2.5¢ minimum threshold."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        
        with patch('merid.event_venues.kalshi.spread_edge_analytics.compute_canonical_spreads') as mock_spreads, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_per_side_edges') as mock_edges, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_dynamic_threshold') as mock_dynamic:
            
            from merid.event_venues.kalshi.spread_edge_analytics import PerSideSpreadMetrics, PerSideEdgeMetrics
            
            mock_spreads.return_value = PerSideSpreadMetrics(
                yes_bid_cents=50, yes_ask_cents=51, yes_spread_cents=1,
                no_bid_cents=50, no_ask_cents=51, no_spread_cents=1
            )
            
            mock_edges.return_value = (
                PerSideEdgeMetrics(
                    side="yes",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                ),
                PerSideEdgeMetrics(
                    side="no",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                )
            )
            
            # Call with resting order (maker economics)
            check_market_microstructure_edge_aware(
                yes_bid_cents=50,
                no_bid_cents=50,
                p_hat_yes_cents=55.0,
                order_side="yes",
                order_price_cents=50,
                aggressiveness=0.0,  # Maker economics
                ticker="KXBTC15M-26JUL281200-00"
            )
            
            # Dynamic threshold should NOT be called for maker orders
            mock_dynamic.assert_not_called()
    
    def test_taker_orders_use_dynamic_threshold(self):
        """Taker orders should use dynamic threshold (spread + fee + volatility)."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        
        with patch('merid.event_venues.kalshi.spread_edge_analytics.compute_canonical_spreads') as mock_spreads, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_per_side_edges') as mock_edges, \
             patch('merid.event_venues.kalshi.spread_edge_analytics.compute_dynamic_threshold') as mock_dynamic:
            
            from merid.event_venues.kalshi.spread_edge_analytics import PerSideSpreadMetrics, PerSideEdgeMetrics, DynamicThresholdResult
            
            mock_spreads.return_value = PerSideSpreadMetrics(
                yes_bid_cents=50, yes_ask_cents=51, yes_spread_cents=1,
                no_bid_cents=50, no_ask_cents=51, no_spread_cents=1
            )
            
            mock_edges.return_value = (
                PerSideEdgeMetrics(
                    side="yes",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                ),
                PerSideEdgeMetrics(
                    side="no",
                    raw_edge_cents=5.0, executable_edge_cents=5.0,
                    spread_cents=1, spread_cost_cents=0.0, taker_fee_cents=0.0,
                    spread_to_edge_ratio=0.2, p_hat_yes_cents=55.0
                )
            )
            
            mock_dynamic.return_value = DynamicThresholdResult(
                threshold_cents=3.5,
                spread_component=1.0,
                volatility_component=1.0,
                fee_component=1.0,
                slippage_component=0.5,
                base_hurdle=0.0,
                asset_config_name="BTC"
            )
            
            # Call with marketable order (taker economics)
            check_market_microstructure_edge_aware(
                yes_bid_cents=50,
                no_bid_cents=50,
                p_hat_yes_cents=55.0,
                order_side="yes",
                order_price_cents=50,
                aggressiveness=0.5,  # Taker economics
                ticker="KXBTC15M-26JUL281200-00"
            )
            
            # Dynamic threshold SHOULD be called for taker orders
            mock_dynamic.assert_called_once()


class TestSideInvariants:
    """Test that side invariants are preserved across the trading pipeline."""
    
    def test_canonical_mapping_table_consistency(self):
        """Canonical mapping table should define correct semantic mappings."""
        from merid.validation.canonical_mapping_invariants import (
            CanonicalMappingTable, ThesisSide, ContractType, OrderAction
        )
        
        # Test bullish (UP) thesis
        assert CanonicalMappingTable.get_contract_type(ThesisSide.UP) == ContractType.YES
        assert CanonicalMappingTable.get_position_type(ThesisSide.UP).value == "long_yes"
        assert CanonicalMappingTable.get_enter_order(ThesisSide.UP) == OrderAction.BUY_YES
        assert CanonicalMappingTable.get_exit_order(ThesisSide.UP) == OrderAction.SELL_YES
        assert CanonicalMappingTable.get_hedge_order(ThesisSide.UP) == OrderAction.BUY_NO
        
        # Test bearish (DOWN) thesis
        assert CanonicalMappingTable.get_contract_type(ThesisSide.DOWN) == ContractType.NO
        assert CanonicalMappingTable.get_position_type(ThesisSide.DOWN).value == "long_no"
        assert CanonicalMappingTable.get_enter_order(ThesisSide.DOWN) == OrderAction.BUY_NO
        assert CanonicalMappingTable.get_exit_order(ThesisSide.DOWN) == OrderAction.SELL_NO
        assert CanonicalMappingTable.get_hedge_order(ThesisSide.DOWN) == OrderAction.BUY_YES
    
    def test_illegal_combinations_are_rejected(self):
        """Illegal semantic combinations should be detected."""
        from merid.validation.canonical_mapping_invariants import (
            CanonicalMappingTable, ThesisSide, OrderAction
        )
        
        # Bullish + BUY_NO is illegal
        assert CanonicalMappingTable.is_illegal_combination(ThesisSide.UP, OrderAction.BUY_NO)
        
        # Bearish + BUY_YES is illegal
        assert CanonicalMappingTable.is_illegal_combination(ThesisSide.DOWN, OrderAction.BUY_YES)
        
        # Valid combinations should not be flagged as illegal
        assert not CanonicalMappingTable.is_illegal_combination(ThesisSide.UP, OrderAction.BUY_YES)
        assert not CanonicalMappingTable.is_illegal_combination(ThesisSide.DOWN, OrderAction.BUY_NO)


class TestRegressionPrevention:
    """Test that the hardcoded-maker bug cannot reappear."""
    
    def test_no_hardcoded_maker_economics_in_router(self):
        """Router should not have hardcoded use_maker_economics=True."""
        from merid.event_venues.kalshi import order_router
        import inspect
        
        # Get the source code of check_market_microstructure_edge_aware
        source = inspect.getsource(order_router.check_market_microstructure_edge_aware)
        
        # Check for the old hardcoded pattern
        assert "use_maker_economics = True" not in source, \
            "Found hardcoded use_maker_economics=True - this is the regression bug"
        
        # Check for the new aggressiveness-based pattern
        assert "aggressiveness == 0.0" in source, \
            "Missing aggressiveness-based economics selection logic"
    
    def test_aggressiveness_parameter_exists(self):
        """check_market_microstructure_edge_aware should have aggressiveness parameter."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure_edge_aware
        import inspect
        
        sig = inspect.signature(check_market_microstructure_edge_aware)
        assert 'aggressiveness' in sig.parameters, \
            "Missing aggressiveness parameter in check_market_microstructure_edge_aware"
    
    def test_hedge_basket_default_is_complete(self):
        """Default hedge basket should include all 5 assets (not just 3)."""
        from merid.hedging.exposure import CRYPTO_BASKET_ASSETS
        
        # Should have exactly 5 assets
        assert len(CRYPTO_BASKET_ASSETS) == 5, \
            f"Expected 5 assets in hedge basket, got {len(CRYPTO_BASKET_ASSETS)}"
        
        # Should include XRP and DOGE (the ones that were missing)
        assert "XRP" in CRYPTO_BASKET_ASSETS, "XRP missing from hedge basket"
        assert "DOGE" in CRYPTO_BASKET_ASSETS, "DOGE missing from hedge basket"


class TestNOOrderEdgeCalculation:
    """Test that NO orders use correct edge calculation (fix for negative edge bug)."""
    
    def test_no_order_uses_order_price_not_market_bid(self):
        """NO orders should use order_price_cents for NO side, not market bid."""
        from merid.event_venues.kalshi.spread_edge_analytics import compute_per_side_edges, PerSideSpreadMetrics
        
        # Setup: model says 40% probability (p_hat_yes_cents=40)
        # Market: YES bid=35c, NO bid=65c (sum=100c, correct)
        # Order: BUY_NO at 60c (below market bid, good price)
        p_hat_yes_cents = 40.0  # Model says 40% YES, 60% NO
        spread_metrics = PerSideSpreadMetrics(
            yes_bid_cents=35, yes_ask_cents=36, yes_spread_cents=1,
            no_bid_cents=65, no_ask_cents=66, no_spread_cents=1
        )
        order_price_cents = 60.0  # Buying NO at 60c
        order_side = "buy_no"
        
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side=order_side,
            use_maker_economics=True
        )
        
        # Expected edge calculation:
        # NO raw edge = (100 - p_hat_yes_cents) - order_price_cents
        # NO raw edge = (100 - 40) - 60 = 60 - 60 = 0c
        # With maker economics: executable_edge = raw_edge = 0c
        
        assert no_edge.raw_edge_cents == 0.0, \
            f"NO raw edge should be 0c, got {no_edge.raw_edge_cents}c"
        assert no_edge.executable_edge_cents == 0.0, \
            f"NO executable edge should be 0c with maker economics, got {no_edge.executable_edge_cents}c"
    
    def test_no_order_positive_edge_case(self):
        """NO order with positive edge should calculate correctly."""
        from merid.event_venues.kalshi.spread_edge_analytics import compute_per_side_edges, PerSideSpreadMetrics
        
        # Setup: model says 30% probability (p_hat_yes_cents=30)
        # Market: YES bid=40c, NO bid=60c
        # Order: BUY_NO at 50c (below market bid, good price)
        p_hat_yes_cents = 30.0  # Model says 30% YES, 70% NO
        spread_metrics = PerSideSpreadMetrics(
            yes_bid_cents=40, yes_ask_cents=41, yes_spread_cents=1,
            no_bid_cents=60, no_ask_cents=61, no_spread_cents=1
        )
        order_price_cents = 50.0  # Buying NO at 50c
        order_side = "buy_no"
        
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side=order_side,
            use_maker_economics=True
        )
        
        # Expected edge calculation:
        # NO raw edge = (100 - p_hat_yes_cents) - order_price_cents
        # NO raw edge = (100 - 30) - 50 = 70 - 50 = 20c
        # With maker economics: executable_edge = raw_edge = 20c
        
        assert no_edge.raw_edge_cents == 20.0, \
            f"NO raw edge should be 20c, got {no_edge.raw_edge_cents}c"
        assert no_edge.executable_edge_cents == 20.0, \
            f"NO executable edge should be 20c with maker economics, got {no_edge.executable_edge_cents}c"
    
    def test_no_order_taker_economics(self):
        """NO order with taker economics should subtract spread and fee."""
        from merid.event_venues.kalshi.spread_edge_analytics import compute_per_side_edges, PerSideSpreadMetrics
        
        p_hat_yes_cents = 30.0
        spread_metrics = PerSideSpreadMetrics(
            yes_bid_cents=40, yes_ask_cents=41, yes_spread_cents=1,
            no_bid_cents=60, no_ask_cents=61, no_spread_cents=1
        )
        order_price_cents = 50.0
        order_side = "buy_no"
        
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side=order_side,
            use_maker_economics=False  # Taker economics
        )
        
        # With taker economics: executable_edge = raw_edge - spread - fee
        # raw_edge = 20c, spread = 1c, fee ~0.35c (at 50c price)
        # executable_edge should be less than raw_edge
        assert no_edge.executable_edge_cents < no_edge.raw_edge_cents, \
            "Taker economics should reduce executable edge by spread and fee"
        assert no_edge.spread_cost_cents > 0, \
            "Taker economics should include spread cost"
        assert no_edge.taker_fee_cents > 0, \
            "Taker economics should include taker fee"
    
    def test_yes_order_still_works(self):
        """Ensure YES orders still work correctly after NO order fix."""
        from merid.event_venues.kalshi.spread_edge_analytics import compute_per_side_edges, PerSideSpreadMetrics
        
        p_hat_yes_cents = 70.0  # Model says 70% YES
        spread_metrics = PerSideSpreadMetrics(
            yes_bid_cents=60, yes_ask_cents=61, yes_spread_cents=1,
            no_bid_cents=40, no_ask_cents=41, no_spread_cents=1
        )
        order_price_cents = 65.0  # Buying YES at 65c
        order_side = "buy_yes"
        
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side=order_side,
            use_maker_economics=True
        )
        
        # YES raw edge = p_hat_yes_cents - order_price_cents
        # YES raw edge = 70 - 65 = 5c
        assert yes_edge.raw_edge_cents == 5.0, \
            f"YES raw edge should be 5c, got {yes_edge.raw_edge_cents}c"
        assert yes_edge.executable_edge_cents == 5.0, \
            f"YES executable edge should be 5c with maker economics, got {yes_edge.executable_edge_cents}c"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
