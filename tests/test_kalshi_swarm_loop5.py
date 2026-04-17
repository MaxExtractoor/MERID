"""Loop 5 tests — Kalshi Swarm Profile + Guardrails (isolated).

Covers:
  1. Profile tests (kalshi_swarm defaults, incentives toggle)
  2. Guardrail tests (paper-only enforcement)
"""

import os
import sys
import unittest
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.profiles import PROFILES, ProfileManager, get_profile_manager
from core.guardrails import GuardrailViolation, SwarmGuardrails, get_guardrail_status


class TestKalshiSwarmProfile(unittest.TestCase):
    """Test kalshi_swarm profile configuration."""

    def test_profile_exists(self):
        """kalshi_swarm profile should exist in PROFILES."""
        self.assertIn("kalshi_swarm", PROFILES)

    def test_social_advisory_defaults(self):
        """kalshi_swarm should have social advisory enabled with conservative weights."""
        profile = PROFILES["kalshi_swarm"]
        self.assertTrue(profile.social_advisory_enabled)
        self.assertEqual(profile.social_advisory_max_nudge, 0.05)
        self.assertEqual(profile.social_advisory_weights["twitter"], 0.1)

    def test_incentive_ledger_defaults(self):
        """kalshi_swarm should have incentive ledger enabled but dry-run by default."""
        profile = PROFILES["kalshi_swarm"]
        self.assertTrue(profile.incentive_ledger_enabled)
        self.assertFalse(profile.incentives_live)
        self.assertTrue(profile.feedback_scheduler_enabled)
        self.assertTrue(profile.feedback_scheduler_dry_run)

    def test_mode_restrictions(self):
        """kalshi_swarm should only allow mock/paper modes."""
        profile = PROFILES["kalshi_swarm"]
        self.assertEqual(profile.allowed_modes, ["mock", "paper"])
        self.assertFalse(profile.allow_live_trading)

    def test_legacy_routers_disabled(self):
        """kalshi_swarm should disable legacy routers."""
        profile = PROFILES["kalshi_swarm"]
        disabled = {"prediction", "betting", "mining"}
        self.assertTrue(disabled.issubset(profile.disabled_routers))

    def test_incentives_toggle_requires_env_var(self):
        """Incentives live mode should require ALLOW_LIVE_INCENTIVES."""
        pm = ProfileManager()
        pm.load_profile("kalshi_swarm")

        with self.assertRaises(PermissionError):
            pm.set_incentives_live(True)

        with patch.dict("os.environ", {"ALLOW_LIVE_INCENTIVES": "1"}):
            pm.set_incentives_live(True)
            self.assertTrue(pm.get_current().incentives_live)


class TestSwarmGuardrails(unittest.TestCase):
    """Test kalshi_swarm safety guardrails."""

    def test_live_mode_blocked_in_swarm(self):
        """Live mode should be blocked in kalshi_swarm without env var."""
        pm = get_profile_manager()
        pm.load_profile("kalshi_swarm")

        with self.assertRaises(GuardrailViolation):
            SwarmGuardrails.check_mode_allowed("live")

    def test_live_mode_allowed_with_env_var(self):
        """Live mode should be allowed with ALLOW_LIVE_SWARM=1."""
        pm = get_profile_manager()
        pm.load_profile("kalshi_swarm")

        with patch.dict("os.environ", {"ALLOW_LIVE_SWARM": "1"}):
            SwarmGuardrails.check_mode_allowed("live")

    def test_mock_paper_always_allowed(self):
        """Mock and paper should always be allowed in kalshi_swarm."""
        pm = get_profile_manager()
        pm.load_profile("kalshi_swarm")

        SwarmGuardrails.check_mode_allowed("mock")
        SwarmGuardrails.check_mode_allowed("paper")


class TestProfileIntegration(unittest.TestCase):
    """Integration tests for profile system."""

    def test_profile_status_format(self):
        """Profile status should return expected format."""
        pm = get_profile_manager()
        pm.load_profile("kalshi_swarm")

        status = pm.get_status()

        self.assertIn("profile", status)
        self.assertIn("social_advisory_enabled", status)
        self.assertIn("incentive_ledger_enabled", status)
        self.assertIn("incentives_live", status)

    def test_guardrail_status_format(self):
        """Guardrail status should return expected format."""
        status = get_guardrail_status()

        self.assertIn("replay_isolated", status)
        self.assertIn("replay_active", status)
        self.assertTrue(status["replay_isolated"])


class TestProfileRouterFiltering(unittest.TestCase):
    """Test router enablement/disablement in profiles."""

    def test_kalshi_swarm_disables_legacy(self):
        """kalshi_swarm should filter out legacy routers."""
        pm = ProfileManager()
        pm.load_profile("kalshi_swarm")

        self.assertFalse(pm.is_router_enabled("prediction"))
        self.assertFalse(pm.is_router_enabled("betting"))
        self.assertFalse(pm.is_router_enabled("mining"))

    def test_default_enables_all(self):
        """default profile should enable all routers."""
        pm = ProfileManager()
        pm.load_profile("default")

        self.assertTrue(pm.is_router_enabled("prediction"))
        self.assertTrue(pm.is_router_enabled("betting"))


if __name__ == "__main__":
    unittest.main()
