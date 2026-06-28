"""Test Decimal type safety across trading system.

Validates fixes for TypeError: unsupported operand type(s) for float and Decimal
"""

import unittest
from decimal import Decimal, InvalidOperation
from merid.utils.decimal_encoder import DecimalEncoder, safe_decimal


class TestDecimalEncoder(unittest.TestCase):
    """Test DecimalEncoder utility."""

    def test_to_decimal_with_float(self):
        """Float must be converted via str to avoid FP errors."""
        result = DecimalEncoder.to_decimal(123.45)
        # Should be Decimal('123.45') not Decimal(123.45) which has FP errors
        self.assertEqual(result, Decimal("123.45"))

    def test_to_decimal_with_str(self):
        """String input preserved exactly."""
        result = DecimalEncoder.to_decimal("123.45")
        self.assertEqual(result, Decimal("123.45"))

    def test_to_decimal_with_int(self):
        """Integer input converted correctly."""
        result = DecimalEncoder.to_decimal(100)
        self.assertEqual(result, Decimal("100"))

    def test_to_decimal_with_decimal(self):
        """Decimal input passed through unchanged."""
        original = Decimal("123.45")
        result = DecimalEncoder.to_decimal(original)
        self.assertEqual(result, original)

    def test_to_decimal_with_none(self):
        """None returns Decimal('0')."""
        result = DecimalEncoder.to_decimal(None)
        self.assertEqual(result, Decimal("0"))

    def test_to_decimal_safe_with_invalid(self):
        """Safe version returns default on invalid input."""
        result = DecimalEncoder.to_decimal_safe("invalid", Decimal("99"))
        self.assertEqual(result, Decimal("99"))

    def test_to_decimal_avoids_float_errors(self):
        """Critical: float -> str -> Decimal avoids binary FP representation."""
        # This is the bug we're preventing
        float_val = 0.1 + 0.2  # 0.30000000000000004 in binary FP
        
        # Wrong way (creates Decimal with FP error)
        wrong = Decimal(float_val)  # noqa
        
        # Right way (our method)
        right = DecimalEncoder.to_decimal(float_val)
        
        # The string representation should be clean
        self.assertEqual(str(right), "0.30000000000000004")
        # But it should match the float's *literal* value, not add extra errors
        self.assertEqual(right, Decimal(str(float_val)))

    def test_coerce_for_calculation(self):
        """Multiple values coerced to Decimal for safe arithmetic."""
        price, contracts, edge = DecimalEncoder.coerce_for_calculation(
            "50.5", 10, "0.02"
        )
        
        # All should be Decimal
        self.assertIsInstance(price, Decimal)
        self.assertIsInstance(contracts, Decimal)
        self.assertIsInstance(edge, Decimal)
        
        # Safe arithmetic
        notional = price * contracts  # No TypeError
        self.assertEqual(notional, Decimal("505.0"))

    def test_parse_market_data(self):
        """Market data parsed with Decimal conversion."""
        api_response = {
            "last_price": 50.5,
            "best_bid": 49.0,
            "best_ask": 51.0,
            "volume": 1000,
            "open_interest": 500,
        }
        
        result = DecimalEncoder.parse_market_data(api_response)
        
        # Price fields should be Decimal
        self.assertIsInstance(result["last_price"], Decimal)
        self.assertEqual(result["last_price"], Decimal("50.5"))
        
        # Volume should be int
        self.assertIsInstance(result["volume"], int)
        self.assertEqual(result["volume"], 1000)

    def test_module_level_safe_decimal(self):
        """Convenience function works."""
        result = safe_decimal("123.45")
        self.assertEqual(result, Decimal("123.45"))
        
        # Test with string default
        result = safe_decimal(None, "99.99")
        self.assertEqual(result, Decimal("99.99"))
        
        # Test with float default  
        result = safe_decimal(None, 99.99)
        self.assertEqual(result, Decimal("99.99"))
        
        # Test with Decimal default
        result = safe_decimal(None, Decimal("99.99"))
        self.assertEqual(result, Decimal("99.99"))


class TestRiskCheckOrderTypes(unittest.TestCase):
    """Test that check_order handles type coercion."""

    def test_check_order_accepts_float_price_cents(self):
        """check_order should coerce float price_cents to Decimal."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        
        risk = PredictionMarketRisk(PredictionRiskConfig())
        
        # Should not raise TypeError when passing float
        result = risk.check_order(
            market_id="TEST-123",
            event_id="EVT-456",
            side="yes",
            contracts=10,
            price_cents=50.0,  # Float instead of Decimal
            best_bid_cents=49.0,  # Float
            best_ask_cents=51.0,  # Float
        )
        
        # Should be allowed or rejected gracefully, not crash with TypeError
        self.assertIsNotNone(result)
        self.assertIn(result.allowed, [True, False])

    def test_check_order_accepts_string_price_cents(self):
        """check_order should coerce string price_cents to Decimal."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        
        risk = PredictionMarketRisk(PredictionRiskConfig())
        
        # Should not raise TypeError when passing string
        result = risk.check_order(
            market_id="TEST-123",
            event_id="EVT-456",
            side="yes",
            contracts=10,
            price_cents="50",  # String instead of Decimal
        )
        
        self.assertIsNotNone(result)


class TestPositionCachePnL(unittest.TestCase):
    """Test that position cache PnL calculations use Decimal properly."""

    def test_pnl_calculation_no_float_intermediate(self):
        """PnL should use Decimal arithmetic, not float intermediate."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        pos = CachedPosition(
            market_id="TEST-123",
            contracts=10,
            side="yes",
            avg_price_cents=50,
        )
        
        # Apply a closing fill
        pos.apply_fill(
            contracts=10,
            price_cents=55,  # Profit: 5 cents per contract
            fee_cents=20,
            side="no"  # Closing
        )
        
        # PnL should be calculated correctly using Decimal
        # 10 contracts * 5 cents = 50 cents = $0.50
        # Minus fee: $0.20
        # Net: $0.30
        expected_pnl = Decimal("0.30")
        self.assertEqual(pos.realized_pnl_usd, expected_pnl)
        
        # Verify it's actually a Decimal
        self.assertIsInstance(pos.realized_pnl_usd, Decimal)


class TestRiskEngineEdgeCalculation(unittest.TestCase):
    """Test risk engine uses Decimal throughout edge calculations."""

    def test_min_edge_for_price_decimal_arithmetic(self):
        """Edge calculations should not cast Decimal to float."""
        # P2: Use venue config instead of deprecated PM config
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskEngine, KalshiRiskConfig

        engine = KalshiRiskEngine(KalshiRiskConfig())
        
        # Should not raise TypeError or lose precision
        result = engine.min_edge_for_price(5)  # Penny contract
        
        # Should be Decimal
        self.assertIsInstance(result, Decimal)
        
        # Verify calculation is reasonable (should be higher due to penny multiplier)
        base = KalshiRiskConfig().min_edge
        self.assertGreaterEqual(result, base)


if __name__ == "__main__":
    unittest.main()
