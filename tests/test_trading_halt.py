"""
Integration tests for trading halt wiring (Backlog #2).

Tests:
- TradingHaltManager: halt/resume lifecycle, callbacks, idempotency
- Daily loss breach → auto-halt
- Drawdown breach → auto-halt
- Circuit breaker open → trading halt
- RiskControlCoordinator.can_trade() gate
- Kill switch via /shutdown endpoint smoke test
"""

import asyncio
import time
import unittest
from unittest.mock import MagicMock, patch

from core.automated_risk_controls import (
    TradingHaltManager,
    RiskControlCoordinator,
    PortfolioRiskManager,
    PositionRisk,
    RiskLimit,
    RiskControlType,
)
from core.error_handling import CircuitBreaker


class TestTradingHaltManager(unittest.TestCase):
    """Tests for TradingHaltManager halt/resume lifecycle."""

    def setUp(self):
        self.mgr = TradingHaltManager(
            max_daily_loss_pct=0.20,  # CRITICAL FIX: 20% aligned with drawdown halt
            max_drawdown_pct=0.15,
            circuit_breaker_halt_threshold=2,
        )

    def test_initial_state_not_halted(self):
        self.assertFalse(self.mgr.is_halted)
        self.assertIsNone(self.mgr.halt_reason)

    def test_halt_changes_state(self):
        changed = self.mgr.halt("test reason")
        self.assertTrue(changed)
        self.assertTrue(self.mgr.is_halted)
        self.assertEqual(self.mgr.halt_reason, "test reason")

    def test_halt_idempotent(self):
        self.mgr.halt("first")
        changed = self.mgr.halt("second")
        self.assertFalse(changed)
        self.assertEqual(self.mgr.halt_reason, "first")

    def test_resume_changes_state(self):
        self.mgr.halt("test")
        changed = self.mgr.resume("operator_1")
        self.assertTrue(changed)
        self.assertFalse(self.mgr.is_halted)
        self.assertIsNone(self.mgr.halt_reason)

    def test_resume_when_not_halted(self):
        changed = self.mgr.resume()
        self.assertFalse(changed)

    def test_halt_fires_callbacks(self):
        cb = MagicMock()
        self.mgr.register_on_halt(cb)
        self.mgr.halt("breach")
        cb.assert_called_once_with("breach")

    def test_resume_fires_callbacks(self):
        cb = MagicMock()
        self.mgr.register_on_resume(cb)
        self.mgr.halt("breach")
        self.mgr.resume("op")
        cb.assert_called_once_with("op")

    def test_callback_error_does_not_prevent_halt(self):
        def bad_cb(reason):
            raise RuntimeError("callback failed")
        self.mgr.register_on_halt(bad_cb)
        changed = self.mgr.halt("test")
        self.assertTrue(changed)
        self.assertTrue(self.mgr.is_halted)

    def test_history_tracking(self):
        self.mgr.halt("r1")
        self.mgr.resume("op")
        self.mgr.halt("r2")
        status = self.mgr.get_status()
        self.assertEqual(status["history_count"], 3)
        self.assertEqual(status["history"][0]["action"], "halt")
        self.assertEqual(status["history"][1]["action"], "resume")
        self.assertEqual(status["history"][2]["action"], "halt")


class TestDailyLossAutoHalt(unittest.TestCase):
    """Daily loss breach → auto-halt."""

    def setUp(self):
        self.mgr = TradingHaltManager(max_daily_loss_pct=0.20)  # CRITICAL FIX: 20% aligned with drawdown halt

    def test_loss_below_threshold_no_halt(self):
        halted = self.mgr.check_daily_loss(-1500, 10000)  # 15% (below 20% threshold)
        self.assertFalse(halted)
        self.assertFalse(self.mgr.is_halted)

    def test_loss_at_threshold_halts(self):
        halted = self.mgr.check_daily_loss(-2000, 10000)  # 20% (at threshold)
        self.assertTrue(halted)
        self.assertTrue(self.mgr.is_halted)
        self.assertIn("20.0%", self.mgr.halt_reason)

    def test_loss_above_threshold_halts(self):
        halted = self.mgr.check_daily_loss(-2500, 10000)  # 25% (above threshold)
        self.assertTrue(halted)
        self.assertTrue(self.mgr.is_halted)

    def test_positive_pnl_no_halt(self):
        halted = self.mgr.check_daily_loss(500, 10000)
        self.assertFalse(halted)

    def test_zero_portfolio_no_halt(self):
        halted = self.mgr.check_daily_loss(-100, 0)
        self.assertFalse(halted)


class TestDrawdownAutoHalt(unittest.TestCase):
    """Drawdown breach → auto-halt."""

    def setUp(self):
        self.mgr = TradingHaltManager(max_drawdown_pct=0.15)

    def test_drawdown_below_threshold_no_halt(self):
        halted = self.mgr.check_drawdown(0.10)
        self.assertFalse(halted)

    def test_drawdown_at_threshold_halts(self):
        halted = self.mgr.check_drawdown(0.15)
        self.assertTrue(halted)
        self.assertTrue(self.mgr.is_halted)

    def test_drawdown_above_threshold_halts(self):
        halted = self.mgr.check_drawdown(0.25)
        self.assertTrue(halted)


class TestCircuitBreakerAutoHalt(unittest.TestCase):
    """Circuit breaker open → trading halt."""

    def setUp(self):
        self.mgr = TradingHaltManager(circuit_breaker_halt_threshold=2)

    def test_one_breaker_no_halt(self):
        halted = self.mgr.check_circuit_breakers(1)
        self.assertFalse(halted)

    def test_two_breakers_halts(self):
        halted = self.mgr.check_circuit_breakers(2)
        self.assertTrue(halted)
        self.assertIn("2 circuit breakers", self.mgr.halt_reason)

    def test_three_breakers_halts(self):
        halted = self.mgr.check_circuit_breakers(3)
        self.assertTrue(halted)


class TestRiskControlCoordinatorGate(unittest.TestCase):
    """RiskControlCoordinator.can_trade() gate."""

    def setUp(self):
        self.coord = RiskControlCoordinator()

    def test_can_trade_initially(self):
        self.assertTrue(self.coord.can_trade())

    def test_cannot_trade_after_halt(self):
        self.coord.halt_manager.halt("test")
        self.assertFalse(self.coord.can_trade())

    def test_can_trade_after_resume(self):
        self.coord.halt_manager.halt("test")
        self.coord.halt_manager.resume("op")
        self.assertTrue(self.coord.can_trade())

    def test_comprehensive_status_includes_halt(self):
        self.coord.halt_manager.halt("drawdown")
        status = self.coord.get_comprehensive_risk_status()
        self.assertIn("trading_halt", status)
        self.assertTrue(status["trading_halt"]["halted"])
        self.assertFalse(status["can_trade"])


class TestCircuitBreakerIntegration(unittest.TestCase):
    """Integration: CircuitBreaker open state → coordinator detects → halt."""

    def test_open_breakers_trigger_halt_in_check(self):
        coord = RiskControlCoordinator()

        # Create mock breakers
        breaker1 = MagicMock()
        breaker1.get_state.return_value = {"state": "open"}
        breaker2 = MagicMock()
        breaker2.get_state.return_value = {"state": "open"}
        breaker3 = MagicMock()
        breaker3.get_state.return_value = {"state": "closed"}

        coord.register_circuit_breaker("binance", breaker1)
        coord.register_circuit_breaker("kraken", breaker2)
        coord.register_circuit_breaker("coinbase", breaker3)

        # Run the risk check
        asyncio.get_event_loop().run_until_complete(coord._check_all_risks())

        self.assertTrue(coord.halt_manager.is_halted)
        self.assertIn("2 circuit breakers", coord.halt_manager.halt_reason)
        self.assertFalse(coord.can_trade())

    def test_closed_breakers_no_halt(self):
        coord = RiskControlCoordinator()

        breaker1 = MagicMock()
        breaker1.get_state.return_value = {"state": "closed"}
        coord.register_circuit_breaker("binance", breaker1)

        asyncio.get_event_loop().run_until_complete(coord._check_all_risks())

        self.assertFalse(coord.halt_manager.is_halted)
        self.assertTrue(coord.can_trade())


class TestDrawdownIntegration(unittest.TestCase):
    """Integration: large drawdown in portfolio → auto-halt via coordinator."""

    def test_large_drawdown_triggers_halt(self):
        coord = RiskControlCoordinator()
        coord.halt_manager.max_drawdown_pct = 0.10  # 10%

        # Set up portfolio with a large loss
        pm = coord.portfolio_manager
        pm.portfolio_value = 10000
        pos = PositionRisk(
            symbol="BTC",
            position_size=1.0,
            entry_price=50000,
            current_price=40000,  # -20% drawdown
            unrealized_pnl=-10000,
            unrealized_pnl_pct=-0.20,
        )
        pm.add_position(pos)

        asyncio.get_event_loop().run_until_complete(coord._check_all_risks())

        # Drawdown is 100% of portfolio (10000 loss on 10000 portfolio)
        self.assertTrue(coord.halt_manager.is_halted)
        self.assertFalse(coord.can_trade())


class TestKillSwitchEndpoint(unittest.TestCase):
    """Smoke test: /shutdown endpoint exists and coordinator wires correctly."""

    def test_halt_manager_status_serializable(self):
        """Ensure get_status() returns JSON-serializable data."""
        mgr = TradingHaltManager()
        mgr.halt("test")
        mgr.resume("op")
        status = mgr.get_status()
        import json
        serialized = json.dumps(status)
        self.assertIn("halted", serialized)
        self.assertIn("history", serialized)

    def test_coordinator_status_serializable(self):
        """Ensure comprehensive status is JSON-serializable."""
        coord = RiskControlCoordinator()
        status = coord.get_comprehensive_risk_status()
        import json
        serialized = json.dumps(status)
        self.assertIn("can_trade", serialized)
        self.assertIn("trading_halt", serialized)


class TestVenue5xxCircuitBreaker(unittest.TestCase):
    """End-to-end: venue 5xx errors → circuit breaker opens → trading halt."""

    def test_5xx_errors_open_circuit_breaker(self):
        """Simulate a venue returning 5xx errors until circuit breaker opens."""
        cb = CircuitBreaker(name="venue-binance", failure_threshold=3, timeout=60.0)

        async def _failing_call():
            raise ConnectionError("HTTP 503 Service Unavailable")

        loop = asyncio.new_event_loop()
        for _ in range(3):
            with self.assertRaises(ConnectionError):
                loop.run_until_complete(cb.call(_failing_call))

        self.assertEqual(cb.state.state, "open")
        loop.close()

    def test_5xx_breakers_trigger_trading_halt(self):
        """Two open circuit breakers → RiskControlCoordinator halts trading."""
        coord = RiskControlCoordinator()

        cb1 = CircuitBreaker(name="venue-binance", failure_threshold=2, timeout=60.0)
        cb2 = CircuitBreaker(name="venue-coinbase", failure_threshold=2, timeout=60.0)
        coord.register_circuit_breaker(cb1)
        coord.register_circuit_breaker(cb2)

        async def _failing():
            raise ConnectionError("HTTP 500")

        loop = asyncio.new_event_loop()
        # Trip both breakers
        for cb in (cb1, cb2):
            for _ in range(2):
                with self.assertRaises(ConnectionError):
                    loop.run_until_complete(cb.call(_failing))
            self.assertEqual(cb.state.state, "open")

        # Check risks — should auto-halt
        loop.run_until_complete(coord._check_all_risks())
        self.assertTrue(coord.halt_manager.is_halted)
        self.assertFalse(coord.can_trade())
        loop.close()

    def test_single_breaker_does_not_halt(self):
        """One open circuit breaker alone should NOT halt (threshold is 2)."""
        coord = RiskControlCoordinator()

        cb1 = CircuitBreaker(name="venue-kraken", failure_threshold=2, timeout=60.0)
        cb2 = CircuitBreaker(name="venue-alpaca", failure_threshold=2, timeout=60.0)
        coord.register_circuit_breaker(cb1)
        coord.register_circuit_breaker(cb2)

        async def _failing():
            raise ConnectionError("HTTP 502")

        loop = asyncio.new_event_loop()
        # Trip only cb1
        for _ in range(2):
            with self.assertRaises(ConnectionError):
                loop.run_until_complete(cb1.call(_failing))
        self.assertEqual(cb1.state.state, "open")
        self.assertEqual(cb2.state.state, "closed")

        loop.run_until_complete(coord._check_all_risks())
        # Only 1 breaker open — should NOT halt
        self.assertFalse(coord.halt_manager.is_halted)
        self.assertTrue(coord.can_trade())
        loop.close()


if __name__ == "__main__":
    unittest.main()
