"""Guard Promotion Enforcement Tests — validates that the ExecutionGuard
blocks live execution for non-promoted domains and allows paper trades.

Run with:
  pytest tests/test_guard_promotion.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from merid.execution_guard import ExecutionGuard, TradeVerdict


# ═══════════════════════════════════════════════════════════════════════
# 1. Promotion state management
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionState:
    """Verify promotion state tracking on the guard."""

    def test_default_enforcement_enabled(self):
        guard = ExecutionGuard()
        assert guard.enforce_promotion is True

    def test_no_report_is_fail_open(self):
        guard = ExecutionGuard()
        # No report synced yet → fail-open (allow)
        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_agent_promoted("any-agent") is True

    def test_manual_eligible_domains(self):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"crypto", "equity"}
        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("equity") is True
        assert guard.is_domain_promoted("prediction") is False
        assert guard.is_domain_promoted("sports") is False

    def test_manual_blocked_agents(self):
        guard = ExecutionGuard()
        guard._promotion_blocked_agents = {"bad-agent-01"}
        assert guard.is_agent_promoted("good-agent-01") is True
        assert guard.is_agent_promoted("bad-agent-01") is False

    def test_enforcement_can_be_disabled(self):
        guard = ExecutionGuard()
        guard.enforce_promotion = False
        guard._promotion_eligible_domains = set()  # empty = nothing eligible
        # Even with no eligible domains, enforcement off → passes
        verdict = guard.pre_trade_check(
            plan_id="test", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        # Should not fail on promotion_eligibility
        assert "promotion_eligibility" not in (verdict.checks_failed or [])

    def test_summary_includes_promotion(self):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"crypto"}
        guard._promotion_blocked_agents = {"bad-01"}
        guard._promotion_report_ts = 1000.0
        s = guard.summary()
        assert "promotion_enforcement" in s
        pe = s["promotion_enforcement"]
        assert pe["enabled"] is True
        assert "crypto" in pe["eligible_domains"]
        assert "bad-01" in pe["blocked_agents"]
        assert pe["report_ts"] == 1000.0


# ═══════════════════════════════════════════════════════════════════════
# 2. Live execution blocking
# ═══════════════════════════════════════════════════════════════════════

class TestLiveBlocking:
    """Verify that non-promoted domains are blocked in live mode."""

    def _make_guard_with_eligible(self, eligible_domains):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = set(eligible_domains)
        guard._cooldown_seconds = 0  # disable cooldown for tests
        guard._last_execution_at = 0
        return guard

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_live_blocked_domain_rejected(self, mock_ctrl_fn):
        """In live mode, a non-promoted domain should be blocked."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = self._make_guard_with_eligible(["equity"])
        verdict = guard.pre_trade_check(
            plan_id="live-test", symbol="BTC/USDT",
            domain="crypto", size_usd=500.0,
        )
        assert verdict.allowed is False
        assert "promotion_eligibility" in verdict.checks_failed
        assert "not eligible" in verdict.reason

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_live_eligible_domain_allowed(self, mock_ctrl_fn):
        """In live mode, a promoted domain should pass the promotion check."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = self._make_guard_with_eligible(["crypto", "equity"])
        verdict = guard.pre_trade_check(
            plan_id="live-ok", symbol="BTC/USDT",
            domain="crypto", size_usd=500.0,
        )
        # Should pass promotion check (may still be blocked by other checks)
        assert "promotion_eligibility" in verdict.checks_passed

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_live_multiple_domains_mixed(self, mock_ctrl_fn):
        """Only eligible domains pass; others blocked."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = self._make_guard_with_eligible(["crypto"])
        guard._cooldown_seconds = 0
        guard._last_execution_at = 0

        v_crypto = guard.pre_trade_check(
            plan_id="t1", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        assert "promotion_eligibility" in v_crypto.checks_passed

        guard._last_execution_at = 0  # reset cooldown
        v_equity = guard.pre_trade_check(
            plan_id="t2", symbol="AAPL",
            domain="equity", size_usd=100.0,
        )
        assert v_equity.allowed is False
        assert "promotion_eligibility" in v_equity.checks_failed


# ═══════════════════════════════════════════════════════════════════════
# 3. Paper mode pass-through
# ═══════════════════════════════════════════════════════════════════════

class TestPaperPassthrough:
    """Verify that paper mode is never blocked by promotion enforcement."""

    def _make_guard_with_nothing_eligible(self):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = set()  # nothing eligible
        guard._cooldown_seconds = 0
        guard._last_execution_at = 0
        return guard

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_paper_mode_allows_non_promoted(self, mock_ctrl_fn):
        """In paper mode, even non-promoted domains should pass promotion check."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = False
        mock_ctrl_fn.return_value = mock_ctrl

        guard = self._make_guard_with_nothing_eligible()
        verdict = guard.pre_trade_check(
            plan_id="paper-test", symbol="BTC/USDT",
            domain="crypto", size_usd=500.0,
        )
        # Promotion check should pass (paper mode)
        assert "promotion_eligibility" in verdict.checks_passed

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_paper_mode_all_domains_pass(self, mock_ctrl_fn):
        """All domains pass promotion in paper mode."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = False
        mock_ctrl_fn.return_value = mock_ctrl

        guard = self._make_guard_with_nothing_eligible()
        for domain in ["crypto", "prediction", "equity", "sports"]:
            guard._last_execution_at = 0
            verdict = guard.pre_trade_check(
                plan_id=f"paper-{domain}", symbol="TEST",
                domain=domain, size_usd=100.0,
            )
            assert "promotion_eligibility" in verdict.checks_passed, (
                f"Domain {domain} should pass promotion in paper mode"
            )

    def test_no_mode_controller_fails_open(self):
        """If mode controller import fails, promotion check passes (fail-open)."""
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = set()  # nothing eligible
        guard._cooldown_seconds = 0
        guard._last_execution_at = 0

        # Don't mock — let the import fail naturally in test context
        # The guard should catch the exception and treat as non-live
        verdict = guard.pre_trade_check(
            plan_id="no-ctrl", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        assert "promotion_eligibility" in verdict.checks_passed


# ═══════════════════════════════════════════════════════════════════════
# 4. Sync from promotion report
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionSync:
    """Verify sync_promotion_report pulls data correctly."""

    def test_sync_populates_state(self):
        guard = ExecutionGuard()
        assert guard._promotion_eligible_domains is None

        guard.sync_promotion_report()

        # After sync, should have some state (even if empty)
        assert guard._promotion_eligible_domains is not None
        assert guard._promotion_blocked_agents is not None
        assert guard._promotion_report_ts > 0

    def test_sync_failure_preserves_state(self):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"crypto"}
        guard._promotion_report_ts = 999.0

        # Patch the lazy import target to make sync fail
        with patch("merid.promotion_report.get_cached_promotion_report", side_effect=RuntimeError("boom")):
            guard.sync_promotion_report()

        # State should be preserved (sync failed gracefully)
        assert guard._promotion_eligible_domains == {"crypto"}
        assert guard._promotion_report_ts == 999.0


# ═══════════════════════════════════════════════════════════════════════
# 5. Verdict check ordering
# ═══════════════════════════════════════════════════════════════════════

class TestCheckOrdering:
    """Verify promotion check is in the right position in the check chain."""

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_kill_switch_takes_precedence(self, mock_ctrl_fn):
        """Kill switch should block before promotion check runs."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"crypto"}
        guard.activate_kill_switch("test")

        verdict = guard.pre_trade_check(
            plan_id="ks-test", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        assert verdict.allowed is False
        assert "global_kill_switch" in verdict.checks_failed
        # Promotion check should NOT appear (short-circuited)
        assert "promotion_eligibility" not in verdict.checks_passed
        assert "promotion_eligibility" not in verdict.checks_failed

        guard.deactivate_kill_switch()

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_domain_kill_takes_precedence(self, mock_ctrl_fn):
        """Domain kill switch should block before promotion check."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"crypto"}
        guard.activate_domain_kill_switch("crypto", "test")

        verdict = guard.pre_trade_check(
            plan_id="dk-test", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        assert verdict.allowed is False
        assert "domain_kill_switch" in verdict.checks_failed
        assert "promotion_eligibility" not in verdict.checks_passed

        guard.deactivate_domain_kill_switch("crypto")

    @patch("trading.mode_controller.get_trading_mode_controller")
    def test_promotion_before_cqi(self, mock_ctrl_fn):
        """Promotion check should run before CQI throttle."""
        mock_ctrl = MagicMock()
        mock_ctrl.is_live = True
        mock_ctrl_fn.return_value = mock_ctrl

        guard = ExecutionGuard()
        guard._promotion_eligible_domains = set()  # nothing eligible
        guard._cooldown_seconds = 0
        guard._last_execution_at = 0
        guard.update_cqi("crypto", 0.1)  # Very low CQI

        verdict = guard.pre_trade_check(
            plan_id="order-test", symbol="BTC/USDT",
            domain="crypto", size_usd=100.0,
        )
        assert verdict.allowed is False
        # Should fail on promotion, not CQI (promotion comes first)
        assert "promotion_eligibility" in verdict.checks_failed
        assert "cqi_throttle" not in verdict.checks_failed
