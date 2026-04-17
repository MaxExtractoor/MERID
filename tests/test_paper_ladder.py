"""Tests for the Paper Trading Ladder system."""

import os
import sys
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestLadderTierDefinitions(unittest.TestCase):
    """Verify tier structure and progression."""

    def test_default_tiers_exist(self):
        from merid.paper_ladder import DEFAULT_TIERS
        self.assertEqual(len(DEFAULT_TIERS), 5)

    def test_tiers_ascending_seed(self):
        from merid.paper_ladder import DEFAULT_TIERS
        seeds = [t.seed_usd for t in DEFAULT_TIERS]
        self.assertEqual(seeds, sorted(seeds))

    def test_tier_names(self):
        from merid.paper_ladder import DEFAULT_TIERS
        names = [t.name for t in DEFAULT_TIERS]
        self.assertEqual(names, ["Sandbox", "Rookie", "Contender", "Pro", "Live-Ready"])

    def test_tier_levels_sequential(self):
        from merid.paper_ladder import DEFAULT_TIERS
        levels = [t.level for t in DEFAULT_TIERS]
        self.assertEqual(levels, [0, 1, 2, 3, 4])

    def test_sandbox_seed_1000(self):
        from merid.paper_ladder import DEFAULT_TIERS
        self.assertEqual(DEFAULT_TIERS[0].seed_usd, 1000)

    def test_live_ready_seed_100k(self):
        from merid.paper_ladder import DEFAULT_TIERS
        self.assertEqual(DEFAULT_TIERS[4].seed_usd, 100_000)

    def test_drawdown_limits_tighten(self):
        from merid.paper_ladder import DEFAULT_TIERS
        dds = [t.max_drawdown_pct for t in DEFAULT_TIERS]
        # Each tier should have same or tighter drawdown than previous
        for i in range(1, len(dds)):
            self.assertLessEqual(dds[i], dds[i - 1])


class TestLadderProgress(unittest.TestCase):
    """Test LadderProgress dataclass properties."""

    def test_win_rate_empty(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test")
        self.assertEqual(p.win_rate_pct, 0.0)

    def test_win_rate_calculation(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test", winning_trades=6, losing_trades=4)
        self.assertAlmostEqual(p.win_rate_pct, 60.0)

    def test_roi_calculation(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test", seed_balance=1000, current_equity=1100)
        self.assertAlmostEqual(p.roi_pct, 10.0)

    def test_roi_zero_seed(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test", seed_balance=0, current_equity=100)
        self.assertEqual(p.roi_pct, 0.0)

    def test_drawdown_calculation(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test", high_water_mark=1000, current_equity=900)
        self.assertAlmostEqual(p.drawdown_pct, 10.0)

    def test_to_dict_has_computed_fields(self):
        from merid.paper_ladder import LadderProgress
        p = LadderProgress(portfolio_id="test", seed_balance=1000, current_equity=1050,
                           high_water_mark=1050, winning_trades=3, losing_trades=2)
        d = p.to_dict()
        self.assertIn("win_rate_pct", d)
        self.assertIn("roi_pct", d)
        self.assertIn("drawdown_pct", d)


class TestPaperLadderEngine(unittest.TestCase):
    """Test the PaperLadder engine logic."""

    def _make_ladder(self):
        from merid.paper_ladder import PaperLadder
        # Use in-memory (no persistence) by patching the persist file
        with patch("merid.paper_ladder._PERSIST_FILE", Path("/tmp/test_ladder_nonexistent.json")):
            ladder = PaperLadder()
        ladder._save_state = MagicMock()  # Don't write to disk
        ladder._apply_to_paper_engine = MagicMock()  # Don't touch real engine
        return ladder

    def test_seed_portfolio_creates_progress(self):
        ladder = self._make_ladder()
        p = ladder.seed_portfolio("agent-1")
        self.assertEqual(p.portfolio_id, "agent-1")
        self.assertEqual(p.current_tier, 0)
        self.assertEqual(p.seed_balance, 1000)
        self.assertEqual(p.current_equity, 1000)

    def test_seed_with_tier_override(self):
        ladder = self._make_ladder()
        p = ladder.seed_portfolio("agent-2", tier_override=2)
        self.assertEqual(p.current_tier, 2)
        self.assertEqual(p.seed_balance, 15_000)

    def test_promotion_on_profit_target(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-3")
        # Simulate hitting Sandbox targets: 10% ROI, 10 trades, 0% win rate min
        result = ladder.update_equity("agent-3", equity=1100, trades=10, wins=6, losses=4)
        self.assertEqual(result, "promoted")
        p = ladder.get_progress("agent-3")
        self.assertEqual(p.current_tier, 1)
        self.assertEqual(p.seed_balance, 5000)

    def test_demotion_on_drawdown(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-4", tier_override=1)
        # Tier 1 max drawdown is 10%
        # First update to set HWM
        ladder.update_equity("agent-4", equity=5000)
        # Now drop below 10% drawdown
        result = ladder.update_equity("agent-4", equity=4400)
        self.assertEqual(result, "demoted")
        p = ladder.get_progress("agent-4")
        self.assertEqual(p.current_tier, 0)

    def test_no_demotion_below_tier_0(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-5")
        # Drop 25% at tier 0 (max dd 20%)
        result = ladder.update_equity("agent-5", equity=750)
        self.assertEqual(result, "demoted")
        p = ladder.get_progress("agent-5")
        self.assertEqual(p.current_tier, 0)  # stays at 0

    def test_no_promotion_without_min_trades(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-6")
        # 10% ROI but only 5 trades (need 10)
        result = ladder.update_equity("agent-6", equity=1100, trades=5, wins=3, losses=2)
        self.assertIsNone(result)

    def test_no_promotion_at_max_tier(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-7", tier_override=4)
        # Can't promote past tier 4
        result = ladder.update_equity("agent-7", equity=200_000, trades=100, wins=60, losses=40)
        self.assertIsNone(result)

    def test_summary_structure(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-8")
        s = ladder.summary()
        self.assertIn("tiers", s)
        self.assertIn("portfolios", s)
        self.assertIn("total_portfolios", s)
        self.assertEqual(s["total_portfolios"], 1)
        self.assertIn("agent-8", s["portfolios"])

    def test_next_goal_in_progress(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-9")
        p = ladder.get_progress("agent-9")
        goal = ladder._next_goal(p)
        self.assertEqual(goal["status"], "in_progress")
        self.assertIn("remaining", goal)
        self.assertEqual(goal["next_tier"], "Rookie")

    def test_next_goal_max_tier(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-10", tier_override=4)
        p = ladder.get_progress("agent-10")
        goal = ladder._next_goal(p)
        self.assertEqual(goal["status"], "max_tier")

    def test_tier_history_recorded(self):
        ladder = self._make_ladder()
        ladder.seed_portfolio("agent-11")
        ladder.update_equity("agent-11", equity=1100, trades=10, wins=6, losses=4)
        p = ladder.get_progress("agent-11")
        # Should have: seeded + promoted
        events = [h["event"] for h in p.tier_history]
        self.assertIn("seeded", events)
        self.assertIn("promoted", events)


class TestPaperLadderAPI(unittest.TestCase):
    """Test API file structure and wiring."""

    def test_api_file_exists(self):
        path = Path("web/api/paper_ladder_api.py")
        self.assertTrue(path.exists(), f"{path} not found")

    def test_api_has_router(self):
        import web.api.paper_ladder_api as api
        self.assertTrue(hasattr(api, "router"))

    def test_api_endpoints(self):
        import web.api.paper_ladder_api as api
        routes = [r.path for r in api.router.routes]
        self.assertIn("/api/v1/paper-ladder/status", routes)
        self.assertIn("/api/v1/paper-ladder/seed", routes)
        self.assertIn("/api/v1/paper-ladder/seed-all", routes)
        self.assertIn("/api/v1/paper-ladder/tiers", routes)

    def test_wired_in_main(self):
        source = Path("web/main.py").read_text(encoding="utf-8")
        self.assertIn("paper_ladder_router", source)


class TestPaperLadderFrontend(unittest.TestCase):
    """Test frontend component and constants."""

    def test_component_exists(self):
        path = Path("web/react/src/components/PaperLadderCard.tsx")
        self.assertTrue(path.exists())

    def test_component_imports_useApiData(self):
        source = Path("web/react/src/components/PaperLadderCard.tsx").read_text()
        self.assertIn("useApiData", source)

    def test_component_uses_endpoint(self):
        source = Path("web/react/src/components/PaperLadderCard.tsx").read_text()
        self.assertIn("PAPER_LADDER_STATUS", source)

    def test_constants_defined(self):
        source = Path("web/react/src/config/constants.ts").read_text()
        self.assertIn("PAPER_LADDER_STATUS", source)
        self.assertIn("PAPER_LADDER_SEED", source)
        self.assertIn("PAPER_LADDER_SEED_ALL", source)

    def test_wired_in_kalshi_grid(self):
        source = Path("web/react/src/views/KalshiGridView.tsx").read_text(encoding="utf-8")
        self.assertIn("PaperLadderCard", source)


if __name__ == "__main__":
    unittest.main()
