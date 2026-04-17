"""
Mode-gate tests (S3-02 gap: SIMULATION mode cannot call live venue adapters).

Verifies that the ModeManager feature gates correctly block live trading
execution in SIMULATION and PAPER modes, and allow it in LIVE/HYBRID.
"""

import unittest

from core.mode_manager import ModeManager, TradingMode


class TestSimulationModeBlocking(unittest.TestCase):
    """SIMULATION mode must block live trading execution."""

    def setUp(self):
        self.mm = ModeManager()

    def test_simulation_blocks_trading_execution(self):
        self.mm.change_mode(TradingMode.SIMULATION)
        self.assertFalse(self.mm.can_execute_trading())

    def test_simulation_allows_paper_trading(self):
        self.mm.change_mode(TradingMode.SIMULATION)
        self.assertTrue(self.mm.can_execute_paper_trading())

    def test_simulation_blocks_execution_engine(self):
        self.mm.change_mode(TradingMode.SIMULATION)
        self.assertFalse(self.mm.is_feature_enabled("execution_engine"))

    def test_simulation_enabled_features(self):
        self.mm.change_mode(TradingMode.SIMULATION)
        enabled = self.mm.get_enabled_features()
        self.assertIn("paper_trading", enabled)
        self.assertNotIn("trading_execution", enabled)
        self.assertNotIn("execution_engine", enabled)


class TestPaperModeGating(unittest.TestCase):
    """PAPER mode allows paper trading but blocks live execution."""

    def setUp(self):
        self.mm = ModeManager()

    def test_paper_blocks_live_trading(self):
        self.mm.change_mode(TradingMode.PAPER)
        self.assertFalse(self.mm.can_execute_trading())

    def test_paper_allows_paper_trading(self):
        self.mm.change_mode(TradingMode.PAPER)
        self.assertTrue(self.mm.can_execute_paper_trading())

    def test_paper_allows_execution_engine(self):
        self.mm.change_mode(TradingMode.PAPER)
        self.assertTrue(self.mm.is_feature_enabled("execution_engine"))


class TestLiveModeGating(unittest.TestCase):
    """LIVE mode allows live trading execution."""

    def setUp(self):
        self.mm = ModeManager()

    def test_live_allows_trading_execution(self):
        self.mm.change_mode(TradingMode.LIVE, changed_by="admin")
        self.assertTrue(self.mm.can_execute_trading())

    def test_live_allows_execution_engine(self):
        self.mm.change_mode(TradingMode.LIVE, changed_by="admin")
        self.assertTrue(self.mm.is_feature_enabled("execution_engine"))

    def test_live_blocks_paper_trading(self):
        self.mm.change_mode(TradingMode.LIVE, changed_by="admin")
        self.assertFalse(self.mm.can_execute_paper_trading())


class TestOfflineModeBlocking(unittest.TestCase):
    """OFFLINE mode blocks all trading."""

    def setUp(self):
        self.mm = ModeManager()

    def test_offline_blocks_all_trading(self):
        self.mm.change_mode(TradingMode.OFFLINE)
        self.assertFalse(self.mm.can_execute_trading())
        self.assertFalse(self.mm.can_execute_paper_trading())
        self.assertFalse(self.mm.is_feature_enabled("execution_engine"))


class TestMaintenanceModeBlocking(unittest.TestCase):
    """MAINTENANCE mode blocks all trading."""

    def setUp(self):
        self.mm = ModeManager()

    def test_maintenance_blocks_all_trading(self):
        self.mm.change_mode(TradingMode.MAINTENANCE, changed_by="admin")
        self.assertFalse(self.mm.can_execute_trading())
        self.assertFalse(self.mm.can_execute_paper_trading())
        self.assertFalse(self.mm.is_feature_enabled("execution_engine"))


class TestModeChangeAuthorization(unittest.TestCase):
    """Non-admin users cannot switch to privileged modes."""

    def setUp(self):
        self.mm = ModeManager()

    def test_non_admin_cannot_switch_to_live(self):
        result = self.mm.change_mode(TradingMode.LIVE, changed_by="user")
        self.assertFalse(result)

    def test_admin_can_switch_to_live(self):
        result = self.mm.change_mode(TradingMode.LIVE, changed_by="admin")
        self.assertTrue(result)

    def test_non_admin_can_switch_to_simulation(self):
        result = self.mm.change_mode(TradingMode.SIMULATION, changed_by="user")
        self.assertTrue(result)


class TestVenueGateModeIntegration(unittest.TestCase):
    """VenueGate blocks live orders in SIM/MOCK mode."""

    def test_sim_mode_blocks_live_orders(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode

        gate = VenueGate(mode=TradingMode.MOCK)
        with self.assertRaises(gate.ModeBlockedError):
            gate.check_can_trade()

    def test_sim_mode_should_simulate_fill(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode

        gate = VenueGate(mode=TradingMode.MOCK)
        self.assertTrue(gate.should_simulate_fill())


if __name__ == "__main__":
    unittest.main()
