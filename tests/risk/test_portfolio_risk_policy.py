"""Tests for PortfolioRiskAgent startup risk-limit policy check.

Covers:
- Policy check passes when limits match bankroll × fraction
- Policy check raises RuntimeError on mismatch
- MERID_RISK_LIMIT_OVERRIDE=1 suppresses the error and logs a critical warning
- Policy check is skipped when no policy fractions are configured
- start() calls the policy check before launching the loop
"""

from __future__ import annotations

import os
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.prediction.agent_grid_config import PortfolioRiskConfig
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent


def _make_agent(**kwargs) -> PortfolioRiskAgent:
    """Return a PortfolioRiskAgent wrapping a PortfolioRiskConfig built from kwargs."""
    cfg = PortfolioRiskConfig(**kwargs)
    return PortfolioRiskAgent(config=cfg)


class TestRiskLimitPolicyCheck:
    """_check_risk_limit_policy() unit tests."""

    def test_no_policy_fractions_passes(self):
        """When no policy fractions are set the check is a no-op."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("1234"),  # arbitrary — no fraction set
        )
        agent._check_risk_limit_policy()  # must not raise

    def test_matching_daily_loss_passes(self):
        """Exact match between actual and bankroll-derived expected passes silently."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("5000"),
            policy_daily_loss_pct=Decimal("0.05"),  # 100000 × 0.05 = 5000
        )
        agent._check_risk_limit_policy()  # must not raise

    def test_matching_per_asset_passes(self):
        """Exact match for per-asset cap passes silently."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_notional_per_asset_usd=Decimal("8000"),
            policy_per_asset_pct=Decimal("0.08"),  # 100000 × 0.08 = 8000
        )
        agent._check_risk_limit_policy()  # must not raise

    def test_mismatch_daily_loss_raises(self):
        """Mismatch on max_daily_loss raises RuntimeError."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),  # actual
            policy_daily_loss_pct=Decimal("0.05"),  # expected 5000
        )
        with pytest.raises(RuntimeError, match="RISK LIMIT POLICY VIOLATION"):
            agent._check_risk_limit_policy()

    def test_mismatch_per_asset_raises(self):
        """Mismatch on max_notional_per_asset raises RuntimeError."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_notional_per_asset_usd=Decimal("5000"),  # actual
            policy_per_asset_pct=Decimal("0.08"),  # expected 8000
        )
        with pytest.raises(RuntimeError, match="RISK LIMIT POLICY VIOLATION"):
            agent._check_risk_limit_policy()

    def test_mismatch_detail_in_error_message(self):
        """Error message includes actual vs expected values."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        with pytest.raises(RuntimeError) as exc_info:
            agent._check_risk_limit_policy()
        msg = str(exc_info.value)
        assert "2500" in msg
        assert "5000" in msg

    def test_override_env_suppresses_error(self, monkeypatch):
        """MERID_RISK_LIMIT_OVERRIDE=1 allows startup despite mismatch."""
        monkeypatch.setenv("MERID_RISK_LIMIT_OVERRIDE", "1")
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        agent._check_risk_limit_policy()  # must not raise

    def test_override_env_wrong_value_still_raises(self, monkeypatch):
        """MERID_RISK_LIMIT_OVERRIDE=true (not '1') does not suppress the error."""
        monkeypatch.setenv("MERID_RISK_LIMIT_OVERRIDE", "true")
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        with pytest.raises(RuntimeError, match="RISK LIMIT POLICY VIOLATION"):
            agent._check_risk_limit_policy()

    def test_override_logs_critical_with_reason(self, monkeypatch, caplog):
        """When override is active a CRITICAL log includes the operator reason."""
        monkeypatch.setenv("MERID_RISK_LIMIT_OVERRIDE", "1")
        monkeypatch.setenv("MERID_RISK_OVERRIDE_REASON", "intentional tightening pre-policy-update")
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        import logging
        with caplog.at_level(logging.CRITICAL):
            agent._check_risk_limit_policy()
        assert any("intentional tightening" in r.message for r in caplog.records)

    def test_both_mismatches_reported_together(self):
        """When both limits mismatch the error message names both."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            max_notional_per_asset_usd=Decimal("5000"),
            policy_daily_loss_pct=Decimal("0.05"),
            policy_per_asset_pct=Decimal("0.08"),
        )
        with pytest.raises(RuntimeError) as exc_info:
            agent._check_risk_limit_policy()
        msg = str(exc_info.value)
        assert "max_daily_loss" in msg
        assert "max_per_asset" in msg


class TestPortfolioRiskAgentInit:
    """Verify __init__ sets _halted/_halt_reason for agent_grid.py compatibility."""

    def test_halted_false_by_default(self):
        agent = _make_agent()
        assert agent._halted is False

    def test_halt_reason_empty_by_default(self):
        agent = _make_agent()
        assert agent._halt_reason == ""


class TestStartCallsPolicyCheck:
    """start() must run the policy check before spawning the monitoring loop."""

    @pytest.mark.asyncio
    async def test_start_raises_if_policy_violated(self):
        """start() propagates RuntimeError from policy check."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("2500"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        with pytest.raises(RuntimeError, match="RISK LIMIT POLICY VIOLATION"):
            await agent.start()

    @pytest.mark.asyncio
    async def test_start_succeeds_when_policy_matches(self):
        """start() proceeds when limits are in policy compliance."""
        agent = _make_agent(
            starting_bankroll_usd=Decimal("100000"),
            max_daily_loss_usd=Decimal("5000"),
            policy_daily_loss_pct=Decimal("0.05"),
        )
        with patch.object(agent, "_run_loop", new_callable=AsyncMock):
            import asyncio
            with patch("asyncio.create_task") as mock_ct:
                mock_ct.return_value = MagicMock()
                await agent.start()
        assert agent._running is True
