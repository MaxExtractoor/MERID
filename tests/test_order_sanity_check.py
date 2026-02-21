"""
Tests for OrderSanityChecker (S9-02 hardening).

Validates:
- Max order as % of portfolio
- Max absolute notional
- Min order notional
- Daily order count limit
- Per-symbol daily notional limit
- Zero/negative quantity and price
- Daily counter reset
- Metrics tracking
- Config customization
"""

import unittest

from core.order_sanity_check import (
    OrderSanityChecker,
    OrderSanityConfig,
    SanityCheckResult,
)


class TestMaxOrderPctOfPortfolio(unittest.TestCase):
    """Orders exceeding portfolio % limit are rejected."""

    def setUp(self):
        self.checker = OrderSanityChecker(OrderSanityConfig(
            max_order_pct_of_portfolio=0.10,
            max_order_notional_usd=100_000,
        ))

    def test_within_limit_passes(self):
        result = self.checker.check("BTC/USDT", 0.01, 50000, portfolio_value=100_000)
        # 0.01 * 50000 = 500, which is 0.5% of 100K
        self.assertTrue(result.passed)

    def test_at_limit_passes(self):
        result = self.checker.check("BTC/USDT", 0.2, 50000, portfolio_value=100_000)
        # 0.2 * 50000 = 10000, which is 10% of 100K
        self.assertTrue(result.passed)

    def test_over_limit_rejected(self):
        result = self.checker.check("BTC/USDT", 0.5, 50000, portfolio_value=100_000)
        # 0.5 * 50000 = 25000, which is 25% of 100K
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "max_order_pct_of_portfolio" for v in result.violations))

    def test_zero_portfolio_rejected(self):
        result = self.checker.check("BTC/USDT", 0.01, 50000, portfolio_value=0)
        self.assertFalse(result.passed)


class TestMaxAbsoluteNotional(unittest.TestCase):
    """Orders exceeding absolute notional limit are rejected."""

    def setUp(self):
        self.checker = OrderSanityChecker(OrderSanityConfig(
            max_order_notional_usd=10_000,
            max_order_pct_of_portfolio=1.0,  # disable pct check
        ))

    def test_within_limit_passes(self):
        result = self.checker.check("ETH/USDT", 1.0, 3000, portfolio_value=1_000_000)
        self.assertTrue(result.passed)

    def test_over_limit_rejected(self):
        result = self.checker.check("ETH/USDT", 5.0, 3000, portfolio_value=1_000_000)
        # 5 * 3000 = 15000 > 10000
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "max_order_notional_usd" for v in result.violations))

    def test_exact_limit_passes(self):
        result = self.checker.check("ETH/USDT", 2.0, 5000, portfolio_value=1_000_000)
        # 2 * 5000 = 10000 == limit
        self.assertTrue(result.passed)


class TestMinOrderNotional(unittest.TestCase):
    """Orders below minimum notional are rejected."""

    def setUp(self):
        self.checker = OrderSanityChecker(OrderSanityConfig(
            min_order_notional_usd=10.0,
            max_order_pct_of_portfolio=1.0,
            max_order_notional_usd=1_000_000,
        ))

    def test_above_min_passes(self):
        result = self.checker.check("SOL/USDT", 1.0, 100, portfolio_value=100_000)
        self.assertTrue(result.passed)

    def test_below_min_rejected(self):
        result = self.checker.check("SOL/USDT", 0.001, 1.0, portfolio_value=100_000)
        # 0.001 * 1.0 = 0.001 < 10
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "min_order_notional_usd" for v in result.violations))


class TestDailyOrderCount(unittest.TestCase):
    """Daily order count limit is enforced."""

    def setUp(self):
        self.checker = OrderSanityChecker(OrderSanityConfig(
            max_daily_order_count=5,
            max_order_pct_of_portfolio=1.0,
            max_order_notional_usd=1_000_000,
            max_order_notional_per_symbol_usd=1_000_000,
        ))

    def test_within_count_passes(self):
        for i in range(5):
            result = self.checker.check(f"SYM-{i}", 1.0, 100, portfolio_value=100_000)
            self.assertTrue(result.passed, f"Order {i} should pass")

    def test_over_count_rejected(self):
        for i in range(5):
            self.checker.check(f"SYM-{i}", 1.0, 100, portfolio_value=100_000)
        result = self.checker.check("SYM-X", 1.0, 100, portfolio_value=100_000)
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "max_daily_order_count" for v in result.violations))


class TestPerSymbolDailyNotional(unittest.TestCase):
    """Per-symbol daily notional limit is enforced."""

    def setUp(self):
        self.checker = OrderSanityChecker(OrderSanityConfig(
            max_order_notional_per_symbol_usd=5_000,
            max_order_pct_of_portfolio=1.0,
            max_order_notional_usd=1_000_000,
            max_daily_order_count=1000,
        ))

    def test_single_order_within_limit(self):
        result = self.checker.check("BTC/USDT", 0.05, 50000, portfolio_value=1_000_000)
        # 0.05 * 50000 = 2500 < 5000
        self.assertTrue(result.passed)

    def test_cumulative_exceeds_limit(self):
        # First order: 2500
        r1 = self.checker.check("BTC/USDT", 0.05, 50000, portfolio_value=1_000_000)
        self.assertTrue(r1.passed)
        # Second order: 2500 more → total 5000 (at limit, passes)
        r2 = self.checker.check("BTC/USDT", 0.05, 50000, portfolio_value=1_000_000)
        self.assertTrue(r2.passed)
        # Third order: 2500 more → total 7500 > 5000
        r3 = self.checker.check("BTC/USDT", 0.05, 50000, portfolio_value=1_000_000)
        self.assertFalse(r3.passed)
        self.assertTrue(any(v["check"] == "max_order_notional_per_symbol_usd" for v in r3.violations))

    def test_different_symbols_independent(self):
        r1 = self.checker.check("BTC/USDT", 0.08, 50000, portfolio_value=1_000_000)
        self.assertTrue(r1.passed)  # 4000 < 5000
        r2 = self.checker.check("ETH/USDT", 1.0, 4000, portfolio_value=1_000_000)
        self.assertTrue(r2.passed)  # 4000 < 5000 (different symbol)


class TestZeroNegativeInputs(unittest.TestCase):
    """Zero or negative quantity/price are rejected."""

    def setUp(self):
        self.checker = OrderSanityChecker()

    def test_zero_quantity_rejected(self):
        result = self.checker.check("BTC/USDT", 0, 50000, portfolio_value=100_000)
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "positive_quantity" for v in result.violations))

    def test_negative_quantity_rejected(self):
        result = self.checker.check("BTC/USDT", -1.0, 50000, portfolio_value=100_000)
        self.assertFalse(result.passed)

    def test_zero_price_rejected(self):
        result = self.checker.check("BTC/USDT", 1.0, 0, portfolio_value=100_000)
        self.assertFalse(result.passed)
        self.assertTrue(any(v["check"] == "positive_price" for v in result.violations))

    def test_negative_price_rejected(self):
        result = self.checker.check("BTC/USDT", 1.0, -100, portfolio_value=100_000)
        self.assertFalse(result.passed)


class TestMetrics(unittest.TestCase):
    """Metrics tracking works correctly."""

    def test_initial_metrics(self):
        checker = OrderSanityChecker()
        m = checker.get_metrics()
        self.assertEqual(m["total_checks"], 0)
        self.assertEqual(m["total_rejects"], 0)
        self.assertEqual(m["daily_order_count"], 0)

    def test_metrics_after_checks(self):
        checker = OrderSanityChecker(OrderSanityConfig(
            max_order_notional_usd=1000,
            max_order_pct_of_portfolio=1.0,
        ))
        # Pass
        checker.check("BTC/USDT", 0.01, 50000, portfolio_value=1_000_000)
        # Reject (notional 5000 > 1000)
        checker.check("BTC/USDT", 0.1, 50000, portfolio_value=1_000_000)

        m = checker.get_metrics()
        self.assertEqual(m["total_checks"], 2)
        self.assertEqual(m["total_rejects"], 1)
        self.assertEqual(m["daily_order_count"], 1)

    def test_reject_rate(self):
        checker = OrderSanityChecker(OrderSanityConfig(
            max_order_notional_usd=100,
            max_order_pct_of_portfolio=1.0,
        ))
        checker.check("X", 1, 50, portfolio_value=1_000_000)  # pass
        checker.check("X", 1, 200, portfolio_value=1_000_000)  # reject
        m = checker.get_metrics()
        self.assertAlmostEqual(m["reject_rate"], 0.5)


class TestSanityCheckResultSerialization(unittest.TestCase):
    """SanityCheckResult.to_dict() is well-formed."""

    def test_passed_result(self):
        r = SanityCheckResult(passed=True, order_notional_usd=500, order_pct_of_portfolio=0.005)
        d = r.to_dict()
        self.assertTrue(d["passed"])
        self.assertEqual(d["order_notional_usd"], 500.0)
        self.assertEqual(len(d["violations"]), 0)

    def test_failed_result(self):
        r = SanityCheckResult(
            passed=False,
            violations=[{"check": "test", "message": "fail"}],
            order_notional_usd=50000,
            order_pct_of_portfolio=0.5,
        )
        d = r.to_dict()
        self.assertFalse(d["passed"])
        self.assertEqual(len(d["violations"]), 1)


class TestMultipleViolations(unittest.TestCase):
    """Multiple violations can fire simultaneously."""

    def test_pct_and_notional_both_violated(self):
        checker = OrderSanityChecker(OrderSanityConfig(
            max_order_pct_of_portfolio=0.05,
            max_order_notional_usd=1000,
        ))
        result = checker.check("BTC/USDT", 1.0, 50000, portfolio_value=100_000)
        # 50000 is 50% of portfolio AND > $1000
        self.assertFalse(result.passed)
        checks = {v["check"] for v in result.violations}
        self.assertIn("max_order_pct_of_portfolio", checks)
        self.assertIn("max_order_notional_usd", checks)


if __name__ == "__main__":
    unittest.main()
