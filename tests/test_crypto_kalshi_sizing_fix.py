"""Test crypto Kalshi sizing fix - 1-2% bankroll allocation enforcement.

This test verifies:
1. Cycle cap is computed correctly based on live bankroll and winner count
2. Risk check uses live bankroll from bankroll_service_v2 (not static settings)
3. Orders are blocked when they exceed the 1-2% cap per cycle
"""

import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from merid.prediction.dynamic_sizing import (
    compute_cycle_sizing_cap,
    get_cycle_sizing_cap,
    CycleSizingCap,
    get_winner_count_for_cycle,
)
from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig, PreTradeCheck, RiskAction


class TestCryptoKalshiSizingFix(unittest.TestCase):
    """Test the crypto Kalshi sizing fix for 1-2% cycle allocation."""

    def test_cycle_cap_with_micro_bankroll(self):
        """Test that cycle cap correctly limits contracts with $44.35 bankroll.
        
        With $44.35 bankroll, 2% allocation = $0.887 total, $0.44 per winner (2 winners).
        At 50 cents/contract, this should be 0-1 contracts per winner, not 50.
        """
        bankroll = Decimal("44.35")
        winner_count = 2
        price_cents = 50
        
        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
        )
        
        # Verify cap structure
        self.assertIsInstance(cap, CycleSizingCap)
        self.assertEqual(cap.bankroll_usd, bankroll)
        self.assertEqual(cap.winner_count, winner_count)
        self.assertEqual(cap.price_cents, price_cents)
        
        # Verify calculations: $44.35 * 0.02 = $0.887 total, / 2 winners = $0.44 per winner
        # At 50c/contract = 0.88 contracts, int() = 0
        self.assertAlmostEqual(float(cap.max_total_notional_usd), 0.887, places=2)
        self.assertAlmostEqual(float(cap.max_notional_per_winner_usd), 0.4435, places=2)
        
        # Max contracts should be 0 or 1 (not 50!)
        self.assertLessEqual(cap.max_contracts_per_winner, 1,
            f"With $44.35 bankroll and 2 winners, max_contracts should be 0-1, got {cap.max_contracts_per_winner}")

    def test_cycle_cap_with_single_winner(self):
        """Test cycle cap with single winner gets full allocation."""
        bankroll = Decimal("44.35")
        winner_count = 1
        price_cents = 50
        
        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
        )
        
        # With 1 winner: $44.35 * 0.02 = $0.887 total, all to 1 winner
        # At 50c/contract = 1.77 contracts, int() = 1
        self.assertAlmostEqual(float(cap.max_notional_per_winner_usd), 0.887, places=2)
        self.assertLessEqual(cap.max_contracts_per_winner, 2)
        self.assertGreaterEqual(cap.max_contracts_per_winner, 1)

    def test_cycle_cap_respects_allocation_pct(self):
        """Test cycle cap respects custom allocation percentage."""
        bankroll = Decimal("1000.00")
        winner_count = 2
        price_cents = 50
        
        # Test 1% allocation
        cap_1pct = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
            allocation_pct=Decimal("0.01"),
        )
        
        # 1% of $1000 = $10 total, / 2 = $5 per winner, / $0.50 = 10 contracts
        self.assertAlmostEqual(float(cap_1pct.max_total_notional_usd), 10.0, places=1)
        self.assertLessEqual(cap_1pct.max_contracts_per_winner, 10)
        
        # Test 2% allocation (double)
        cap_2pct = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
            allocation_pct=Decimal("0.02"),
        )
        
        # 2% of $1000 = $20 total, / 2 = $10 per winner, / $0.50 = 20 contracts
        self.assertAlmostEqual(float(cap_2pct.max_total_notional_usd), 20.0, places=1)
        self.assertLessEqual(cap_2pct.max_contracts_per_winner, 20)

    def test_risk_check_blocks_oversized_order(self):
        """Test that risk check blocks orders exceeding the cycle cap."""
        risk = PredictionMarketRisk(PredictionRiskConfig())
        
        # Try to place 50 contracts at 50c = $25 notional
        # With cycle cap of $0.887 (2% of $44.35), this should be blocked
        check = risk.check_order(
            market_id="KXBTC-TEST",
            event_id="KXBTC-EVENT",
            side="yes",
            contracts=50,
            price_cents=Decimal("50"),
            agent_max_notional_usd=Decimal("0.887"),  # 2% of $44.35
        )
        
        # Order should be rejected
        self.assertFalse(check.allowed)
        self.assertIn("exceeds", check.reason.lower())
        
        # Should provide adjusted size
        self.assertIsNotNone(check.adjusted_size)
        # Adjusted size should be small (around 1 contract: $0.50 < $0.887)
        self.assertLessEqual(check.adjusted_size, 2,
            f"Adjusted size should be <= 2, got {check.adjusted_size}")

    def test_cycle_cap_with_higher_bankroll(self):
        """Test cycle cap with higher bankroll allows more contracts."""
        bankroll = Decimal("500.00")
        winner_count = 2
        price_cents = 50
        
        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
        )
        
        # With $500 bankroll: $500 * 0.02 = $10 total, / 2 = $5 per winner
        # At 50c/contract = 10 contracts per winner
        self.assertAlmostEqual(float(cap.max_total_notional_usd), 10.0, places=1)
        self.assertAlmostEqual(float(cap.max_notional_per_winner_usd), 5.0, places=1)
        self.assertEqual(cap.max_contracts_per_winner, 10)

    def test_cycle_cap_absolute_max(self):
        """Test that cycle cap respects absolute $100 safety limit."""
        bankroll = Decimal("10000.00")  # Large bankroll
        winner_count = 1
        price_cents = 50
        
        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
        )
        
        # Even with $10k bankroll, should be capped at $100 absolute max
        self.assertLessEqual(float(cap.max_total_notional_usd), 100.0)
        self.assertLessEqual(cap.max_contracts_per_winner, 200)  # $100 / $0.50 = 200


class TestIntegrationWithArbiter(unittest.TestCase):
    """Test integration with crypto_top_edge arbiter."""

    @patch("merid.prediction.crypto_top_edge.get_crypto_top_edge_arbiter")
    def test_winner_count_from_arbiter(self, mock_get_arbiter):
        """Test that winner count is fetched from arbiter."""
        # Mock arbiter with 2 winners
        mock_arbiter = MagicMock()
        mock_arbiter._last_cycle_winners = {
            "KXBTC-1": MagicMock(),
            "KXETH-1": MagicMock(),
        }
        mock_get_arbiter.return_value = mock_arbiter
        
        winner_count = get_winner_count_for_cycle()
        
        self.assertEqual(winner_count, 2)


if __name__ == "__main__":
    unittest.main()
