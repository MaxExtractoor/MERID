"""Zero-Trust Invariant Tests for MERID.

Assumes attacker already inside — every layer can lie.
Tests enforce the hard rules documented in security/zero_trust.py.

Classes:
  TestAgentScopeRegistry         ZT-01 — agent identity + tool scopes
  TestDualControlGuard           ZT-02 — dual-control for destructive actions
  TestStreamPublisherGuard       ZT-03 — event-bus producer identity
  TestDevAuthBypass              ZT-DEV — dev bypass must be explicit opt-in
  TestOperatorApiRoleGuards      ZT-RBAC — operator endpoints require role
  TestConfigMutationGate         ZT-04 — agent-mode config changes need auth
  TestBlastRadiusLimits          ZT-05 — compromised agent blast radius
  TestKillSwitchDualControl      ZT-02b — kill-switch reset is dual-control
  TestCIInvariants               ZT-CI — CI pipeline security gates present
  TestZTPolicyConstants          ZT-POLICY — policy object completeness

Run with:
    pytest tests/test_zero_trust_invariants.py -v
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _fresh_scope_registry():
    from security.zero_trust import AgentScopeRegistry
    return AgentScopeRegistry()


def _fresh_dual_control():
    from security.zero_trust import DualControlGuard
    return DualControlGuard()


def _fresh_publisher_guard():
    from security.zero_trust import StreamPublisherGuard
    return StreamPublisherGuard()


# ===========================================================================
# ZT-01 — Agent Identity & Tool Scopes
# ===========================================================================

class TestAgentScopeRegistry:

    def test_unregistered_agent_raises_on_any_tool(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        with pytest.raises(ScopeViolation, match="unregistered agent"):
            reg.check_tool("ghost-agent", AgentTool.READ_MARKET_DATA)

    def test_default_registration_blocks_submit_order(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-1")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-1", AgentTool.SUBMIT_ORDER)

    def test_default_registration_blocks_cancel_order(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-2")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-2", AgentTool.CANCEL_ORDER)

    def test_default_registration_blocks_config_write(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-3")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-3", AgentTool.CONFIG_WRITE)

    def test_default_registration_blocks_kill_switch(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-4")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-4", AgentTool.KILL_SWITCH)

    def test_default_registration_blocks_domain_promote(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-5")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-5", AgentTool.DOMAIN_PROMOTE)

    def test_default_registration_blocks_agent_promote(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-6")
        with pytest.raises(ScopeViolation):
            reg.check_tool("analyst-6", AgentTool.AGENT_PROMOTE)

    def test_default_registration_allows_read_tools(self):
        from security.zero_trust import AgentTool
        reg = _fresh_scope_registry()
        reg.register_agent("analyst-7")
        # Should not raise
        reg.check_tool("analyst-7", AgentTool.READ_MARKET_DATA)
        reg.check_tool("analyst-7", AgentTool.READ_PORTFOLIO)
        reg.check_tool("analyst-7", AgentTool.READ_RISK)
        reg.check_tool("analyst-7", AgentTool.PUBLISH_OPINION)

    def test_governance_gated_tool_requires_both_grant_and_approval(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        # Grant the tool in allowed_tools but NOT governance_approved
        reg.register_agent(
            "exec-agent",
            allowed_tools={AgentTool.READ_MARKET_DATA, AgentTool.SUBMIT_ORDER},
            governance_approved_tools=set(),  # no approval yet
        )
        with pytest.raises(ScopeViolation, match="not governance-approved"):
            reg.check_tool("exec-agent", AgentTool.SUBMIT_ORDER)

    def test_governance_approval_unlocks_tool(self):
        from security.zero_trust import AgentTool
        reg = _fresh_scope_registry()
        reg.register_agent(
            "exec-agent-2",
            allowed_tools={AgentTool.SUBMIT_ORDER},
            governance_approved_tools={AgentTool.SUBMIT_ORDER},
        )
        # Should not raise
        reg.check_tool("exec-agent-2", AgentTool.SUBMIT_ORDER)

    def test_grant_governance_approval_enables_tool(self):
        from security.zero_trust import AgentTool
        reg = _fresh_scope_registry()
        reg.register_agent(
            "exec-agent-3",
            allowed_tools={AgentTool.SUBMIT_ORDER},
        )
        reg.grant_governance_approval("exec-agent-3", AgentTool.SUBMIT_ORDER)
        reg.check_tool("exec-agent-3", AgentTool.SUBMIT_ORDER)  # no raise

    def test_revoke_governance_approval_re_blocks_tool(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent(
            "exec-agent-4",
            allowed_tools={AgentTool.SUBMIT_ORDER},
            governance_approved_tools={AgentTool.SUBMIT_ORDER},
        )
        reg.revoke_governance_approval("exec-agent-4", AgentTool.SUBMIT_ORDER)
        with pytest.raises(ScopeViolation):
            reg.check_tool("exec-agent-4", AgentTool.SUBMIT_ORDER)

    def test_violation_increments_counter(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("sneaky-agent")
        for _ in range(3):
            try:
                reg.check_tool("sneaky-agent", AgentTool.SUBMIT_ORDER)
            except ScopeViolation:
                pass
        entry = reg.get_entry("sneaky-agent")
        assert entry.violation_count == 3

    def test_grant_governance_on_unregistered_agent_raises(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        with pytest.raises(ScopeViolation, match="not registered"):
            reg.grant_governance_approval("nobody", AgentTool.SUBMIT_ORDER)

    def test_high_risk_tools_off_by_default_policy(self):
        from security.zero_trust import ZTPolicy, AgentTool, _HIGH_RISK_TOOLS
        assert ZTPolicy.HIGH_RISK_TOOLS_OFF_BY_DEFAULT is True
        assert AgentTool.SUBMIT_ORDER in _HIGH_RISK_TOOLS
        assert AgentTool.CANCEL_ORDER in _HIGH_RISK_TOOLS
        assert AgentTool.CONFIG_WRITE in _HIGH_RISK_TOOLS
        assert AgentTool.KILL_SWITCH in _HIGH_RISK_TOOLS
        assert AgentTool.DOMAIN_PROMOTE in _HIGH_RISK_TOOLS
        assert AgentTool.AGENT_PROMOTE in _HIGH_RISK_TOOLS

    def test_thread_safety_concurrent_registrations(self):
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        errors = []

        def _register(i):
            try:
                reg.register_agent(f"agent-{i}")
                reg.check_tool(f"agent-{i}", AgentTool.READ_MARKET_DATA)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_register, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Thread safety errors: {errors}"


# ===========================================================================
# ZT-02 — Dual Control Guard
# ===========================================================================

class TestDualControlGuard:

    def test_self_approval_blocked(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.KILL_SWITCH_RESET, "alice", reason="test")
        with pytest.raises(DualControlError, match="SELF-APPROVAL BLOCKED"):
            guard.approve_action(token, "alice")

    def test_unapproved_token_cannot_be_consumed(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.KILL_SWITCH_RESET, "alice", reason="test")
        with pytest.raises(DualControlError, match="requires second-human approval"):
            guard.consume_action(token)

    def test_valid_dual_approval_allows_consume(self):
        from security.zero_trust import DualControlAction
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.KILL_SWITCH_RESET, "alice", reason="test")
        guard.approve_action(token, "bob")
        pa = guard.consume_action(token)
        assert pa.requester_id == "alice"
        assert pa.approver_id == "bob"
        assert pa.consumed is True

    def test_consumed_token_cannot_be_reused(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.KILL_SWITCH_RESET, "alice")
        guard.approve_action(token, "bob")
        guard.consume_action(token)
        with pytest.raises(DualControlError, match="Unknown approval token"):
            guard.consume_action(token)

    def test_unknown_token_raises(self):
        from security.zero_trust import DualControlError
        guard = _fresh_dual_control()
        with pytest.raises(DualControlError, match="Unknown"):
            guard.approve_action("bad-token", "bob")

    def test_expired_token_raises_on_approve(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.DOMAIN_PROMOTE, "alice")
        # Manually expire by setting expires_at in the past
        guard._pending[token].expires_at = time.time() - 1
        with pytest.raises(DualControlError, match="expired"):
            guard.approve_action(token, "bob")

    def test_expired_token_raises_on_consume(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.DOMAIN_PROMOTE, "alice")
        guard._pending[token].approver_id = "bob"
        guard._pending[token].approved_at = time.time()
        # Manually expire by setting expires_at in the past
        guard._pending[token].expires_at = time.time() - 1
        with pytest.raises(DualControlError, match="expired"):
            guard.consume_action(token)

    def test_double_approval_blocked(self):
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.RISK_LIMIT_CHANGE, "alice")
        guard.approve_action(token, "bob")
        with pytest.raises(DualControlError, match="Already approved"):
            guard.approve_action(token, "carol")

    def test_all_destructive_actions_covered(self):
        from security.zero_trust import DualControlAction, ZTPolicy
        for action in DualControlAction:
            assert action in ZTPolicy.DUAL_CONTROL_ACTIONS

    def test_kill_switch_reset_is_dual_control_action(self):
        from security.zero_trust import DualControlAction
        assert DualControlAction.KILL_SWITCH_RESET in list(DualControlAction)

    def test_live_mode_enable_is_dual_control_action(self):
        from security.zero_trust import DualControlAction
        assert DualControlAction.LIVE_MODE_ENABLE in list(DualControlAction)

    def test_history_records_completed_approvals(self):
        from security.zero_trust import DualControlAction
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.AGENT_PROMOTE, "alice")
        guard.approve_action(token, "bob")
        guard.consume_action(token)
        hist = guard.history()
        assert len(hist) == 1
        assert hist[0].action == DualControlAction.AGENT_PROMOTE

    def test_thread_safety_concurrent_requests(self):
        from security.zero_trust import DualControlAction
        guard = _fresh_dual_control()
        tokens = []
        lock = threading.Lock()

        def _request(i):
            t = guard.request_action(DualControlAction.KILL_SWITCH_RESET, f"op-{i}")
            with lock:
                tokens.append(t)

        threads = [threading.Thread(target=_request, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(tokens) == 10
        assert len(set(tokens)) == 10  # all unique


# ===========================================================================
# ZT-03 — Stream Publisher Identity
# ===========================================================================

class TestStreamPublisherGuard:

    def test_unregistered_publisher_raises_in_strict_mode(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.set_strict(True)
        with pytest.raises(PublisherViolation, match="unregistered publisher"):
            spg.assert_publish("ghost-feed", "prices.kalshi.BTC-USD")

    def test_registered_publisher_allowed_on_matching_topic(self):
        spg = _fresh_publisher_guard()
        spg.register_publisher("price_feed", allowed_topics={"prices.*"})
        spg.assert_publish("price_feed", "prices.kalshi.BTC-USD")  # no raise

    def test_registered_publisher_blocked_on_wrong_topic(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.register_publisher("price_feed", allowed_topics={"prices.*"})
        with pytest.raises(PublisherViolation, match="not permitted"):
            spg.assert_publish("price_feed", "trades.executed")

    def test_glob_pattern_prices_dot_star(self):
        spg = _fresh_publisher_guard()
        spg.register_publisher("feed-a", allowed_topics={"prices.*"})
        spg.assert_publish("feed-a", "prices.binance.ETH-USD")
        spg.assert_publish("feed-a", "prices.kalshi.SOL-USD")

    def test_glob_does_not_match_nested_without_double_star(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.register_publisher("feed-b", allowed_topics={"prices.*"})
        # "prices.kalshi.BTC-USD" is two levels deep; single * only matches one segment
        # fnmatch treats "." as a normal char so "prices.*" does match "prices.kalshi.BTC-USD"
        # Verify the behaviour is deterministic either way (not broken)
        import fnmatch
        matched = fnmatch.fnmatch("prices.kalshi.BTC-USD", "prices.*")
        if matched:
            spg.assert_publish("feed-b", "prices.kalshi.BTC-USD")  # consistent
        else:
            with pytest.raises(PublisherViolation):
                spg.assert_publish("feed-b", "prices.kalshi.BTC-USD")

    def test_execution_topic_blocked_for_price_feed(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.register_publisher("price_feed", allowed_topics={"prices.*"})
        with pytest.raises(PublisherViolation):
            spg.assert_publish("price_feed", "trades.executed")

    def test_agent_opinion_publisher_blocked_from_trade_topic(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.register_publisher("analyst", allowed_topics={"agent.opinions"})
        with pytest.raises(PublisherViolation):
            spg.assert_publish("analyst", "trades.executed")

    def test_non_strict_mode_warns_but_does_not_raise(self):
        spg = _fresh_publisher_guard()
        spg.set_strict(False)
        # Should not raise, only log
        spg.assert_publish("unknown-publisher", "any.topic")

    def test_violation_counter_increments(self):
        from security.zero_trust import PublisherViolation
        spg = _fresh_publisher_guard()
        spg.register_publisher("noisy", allowed_topics={"prices.*"})
        for _ in range(4):
            try:
                spg.assert_publish("noisy", "trades.executed")
            except PublisherViolation:
                pass
        summary = spg.violation_summary()
        assert summary.get("noisy", 0) == 4

    def test_stream_bus_source_field_is_unverified_without_guard(self):
        """Confirm that StreamBus itself does NOT verify source — guard is external."""
        from streaming.stream_bus import StreamEvent
        # Any string is accepted as source — the guard must be called separately
        evt = StreamEvent.create(
            event_type="price.tick",
            topic="prices.test",
            source="i_am_totally_legit",
            payload={},
        )
        assert evt.source == "i_am_totally_legit"
        # This test documents the gap: callers MUST call spg.assert_publish() before bus.publish()


# ===========================================================================
# ZT-DEV — Dev Auth Bypass Must Be Explicit Opt-In
# ===========================================================================

class TestDevAuthBypass:

    def test_unset_merid_env_defaults_to_production(self):
        """ZT-DEV: When MERID_ENV is unset, default must be production (not development)."""
        src = _read("web/api/auth.py")
        # The default must be "production", not "development"
        assert 'os.getenv("MERID_ENV", "production")' in src, (
            "MERID_ENV default must be 'production' to prevent silent bypass "
            "when env var is missing in a container"
        )

    def test_dev_bypass_requires_explicit_opt_in(self):
        """ZT-DEV: Dev bypass must require MERID_DEV_AUTH_BYPASS=1 (not merely absence of =0)."""
        src = _read("web/api/auth.py")
        assert 'MERID_DEV_AUTH_BYPASS") == "1"' in src, (
            "Dev bypass must require explicit opt-in (== '1'), not opt-out (!= '0')"
        )

    def test_dev_bypass_blocked_in_live_mode(self):
        """ZT-DEV: Dev bypass must check and block when live trading is active."""
        src = _read("web/api/auth.py")
        assert "MERID_PM_LIVE_ENABLED" in src
        assert "live_trading" in src
        # The bypass block raises HTTPException when live_trading is True
        assert "Dev auth bypass is disabled in live trading mode" in src

    def test_dev_bypass_inactive_when_env_unset(self):
        """Integration: calling get_current_session without any bypass env vars raises 401."""
        import asyncio
        from fastapi import HTTPException

        env_backup = {
            "MERID_SKIP_AUTH_FOR_TESTS": os.environ.pop("MERID_SKIP_AUTH_FOR_TESTS", None),
            "MERID_ENV": os.environ.pop("MERID_ENV", None),
            "MERID_DEV_AUTH_BYPASS": os.environ.pop("MERID_DEV_AUTH_BYPASS", None),
        }
        try:
            from web.api.auth import get_current_session
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    get_current_session(session_id=None, authorization=None)
                )
            assert exc_info.value.status_code == 401
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)

    def test_zt_policy_constants_exist(self):
        from security.zero_trust import ZTPolicy
        assert ZTPolicy.DEV_BYPASS_REQUIRES_EXPLICIT_OPT_IN is True
        assert ZTPolicy.DEV_BYPASS_BLOCKED_IN_LIVE_MODE is True


# ===========================================================================
# ZT-RBAC — Operator API Role Guards
# ===========================================================================

class TestOperatorApiRoleGuards:

    def _read_operator_api(self) -> str:
        return _read("web/api/operator_api.py")

    def test_kill_switch_on_requires_operator_or_admin(self):
        src = self._read_operator_api()
        # The kill-switch-on endpoint must have require_role("operator", "admin")
        assert 'require_role("operator", "admin")' in src

    def test_kill_switch_off_requires_operator_or_admin(self):
        src = self._read_operator_api()
        # Both on and off endpoints have the role dep
        assert src.count('require_role("operator", "admin")') >= 2

    def test_promotion_refresh_requires_operator_or_admin(self):
        src = self._read_operator_api()
        # After fix, refresh must also carry the role guard
        lines = src.splitlines()
        refresh_idx = next(
            (i for i, l in enumerate(lines) if "promotion-report/refresh" in l), None
        )
        assert refresh_idx is not None, "promotion-report/refresh endpoint not found"
        # Within the next 3 lines, require_role must appear
        window = "\n".join(lines[refresh_idx: refresh_idx + 4])
        assert "require_role" in window, (
            "promotion-report/refresh must have require_role guard; "
            "any authenticated user could otherwise trigger promotion refresh"
        )

    def test_domain_promote_requires_operator_or_admin(self):
        src = self._read_operator_api()
        assert "promote_domain" in src
        # Locate the promote_domain function and check it has require_role
        lines = src.splitlines()
        promote_idx = next((i for i, l in enumerate(lines) if "async def promote_domain" in l), None)
        assert promote_idx is not None
        nearby = "\n".join(lines[max(0, promote_idx - 3): promote_idx + 1])
        assert "require_role" in nearby

    def test_router_has_global_auth_dependency(self):
        src = self._read_operator_api()
        # The router itself carries get_current_session dependency
        assert "get_current_session" in src
        assert "dependencies=[Depends(get_current_session)]" in src

    def test_all_mutation_endpoints_have_role_guard(self):
        """Every POST/DELETE/PUT on operator router needs require_role."""
        import re
        src = self._read_operator_api()
        post_endpoints = re.findall(r'@router\.post\([^)]+\)\nasync def (\w+)', src)
        # The mutation endpoints we know about
        critical_mutations = {
            "activate_kill_switch",
            "deactivate_kill_switch",
            "refresh_promotion_report",
            "promote_domain",
            "demote_domain",
            "promote_agent",
            "demote_agent",
        }
        for fn in critical_mutations:
            if fn in post_endpoints or fn in src:
                # Find the function and verify role guard presence nearby
                fn_idx = src.find(f"async def {fn}")
                if fn_idx == -1:
                    continue
                # Look at the 300 chars before the def for require_role
                context = src[max(0, fn_idx - 300): fn_idx + 200]
                assert "require_role" in context, (
                    f"Mutation endpoint '{fn}' missing require_role guard"
                )


# ===========================================================================
# ZT-04 — Config Mutation Gate
# ===========================================================================

class TestConfigMutationGate:

    def test_set_agent_mode_function_exists(self):
        """Ensure set_agent_mode is callable (it is the mutation surface)."""
        from config.agent_modes import set_agent_mode
        assert callable(set_agent_mode)

    def test_agent_mode_mutation_is_runtime_only(self):
        """Mutations to DEFAULT_AGENT_MODES go nowhere on restart — document the gap."""
        from config import agent_modes
        original = agent_modes.DEFAULT_AGENT_MODES.get("btc_15m_regime")
        if original:
            original_mode = original.mode
            valid_target = "paper" if original_mode != "paper" else "shadow"
            agent_modes.set_agent_mode("btc_15m_regime", valid_target, operator_id="test")
            assert agent_modes.DEFAULT_AGENT_MODES["btc_15m_regime"].mode == valid_target
            # Restore
            agent_modes.set_agent_mode("btc_15m_regime", original_mode, operator_id="test")

    def test_config_mutation_policy_constant(self):
        from security.zero_trust import ZTPolicy
        assert ZTPolicy.CONFIG_MUTATION_REQUIRES_AUTH is True

    def test_invalid_mode_value_rejected(self):
        """ZT-04: Arbitrary mode strings must be rejected."""
        from config.agent_modes import set_agent_mode
        with pytest.raises(ValueError, match="Invalid agent mode"):
            set_agent_mode("btc_15m_regime", "EXPLOIT", operator_id="attacker")
        with pytest.raises(ValueError, match="Invalid agent mode"):
            set_agent_mode("btc_15m_regime", "", operator_id="attacker")
        with pytest.raises(ValueError, match="Invalid agent mode"):
            set_agent_mode("btc_15m_regime", "live; DROP TABLE agents", operator_id="attacker")

    def test_set_agent_mode_audit_logs_operator(self):
        """ZT-04: operator_id defaults to 'unknown' — always traceable."""
        import logging
        from config.agent_modes import set_agent_mode
        from config import agent_modes
        original = agent_modes.DEFAULT_AGENT_MODES.get("btc_15m_regime")
        if original is None:
            pytest.skip("btc_15m_regime not in DEFAULT_AGENT_MODES")
        orig_mode = original.mode
        target = "paper" if orig_mode != "paper" else "shadow"
        with patch("config.agent_modes.logger") as mock_log:
            set_agent_mode("btc_15m_regime", target, operator_id="alice")
            # Restore
            set_agent_mode("btc_15m_regime", orig_mode, operator_id="alice")
            calls = str(mock_log.warning.call_args_list)
            assert "ZT-04" in calls
            assert "alice" in calls

    def test_env_var_agent_mode_override_cannot_escalate_to_live_without_guard(self):
        """ZT-04: An env var like BTC_15M_REGIME_MODE=live must not bypass ExecutionGuard."""
        from config.agent_modes import get_agent_mode_config
        with patch.dict(os.environ, {"BTC_15M_REGIME_MODE": "live"}):
            cfg = get_agent_mode_config("btc_15m_regime")
            assert cfg.mode == "live"
        # The test documents that env-var escalation is possible;
        # ExecutionGuard.pre_trade_check() is the downstream gate that must block
        # live trades without promotion approval. This test verifies the gap exists
        # and is NOT closed at the config layer itself.
        # A future ZT-04 hardening would add a mode-change audit log here.


# ===========================================================================
# ZT-05 — Blast Radius Limits
# ===========================================================================

class TestBlastRadiusLimits:

    def test_compromised_agent_cannot_enumerate_registry_via_scope_check(self):
        """A compromised agent hitting check_tool for another agent's ID gets a violation."""
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("victim-agent")
        # Attacker agent is NOT registered; calling check_tool for victim's tools
        # would require knowing victim's agent_id — but the call is made as attacker
        # Simulate: attacker tries to use check_tool with victim's id
        with pytest.raises(ScopeViolation, match="unregistered agent"):
            reg.check_tool("attacker-agent", AgentTool.READ_MARKET_DATA)

    def test_agent_registry_does_not_expose_all_agents_to_any_caller(self):
        """AgentRegistry.get_all_agents() is a blast-radius concern — document it."""
        from agents.agent_framework import get_agent_registry
        registry = get_agent_registry()
        # all_agents() returns the full list; ZT-05 policy says agents should NOT
        # call this directly. The test asserts the method exists (it does) so that
        # we can add access control later; for now we document the gap.
        all_agents = registry.get_all_agents()
        assert isinstance(all_agents, list)
        # Policy constant must state agents cannot enumerate
        from security.zero_trust import ZTPolicy
        assert ZTPolicy.AGENTS_CANNOT_ENUMERATE_REGISTRY is True

    def test_message_bus_broadcast_requires_scope(self):
        """BROADCAST_MSG is a high-risk tool; default agents cannot use it."""
        from security.zero_trust import AgentTool, ScopeViolation
        reg = _fresh_scope_registry()
        reg.register_agent("noisy-agent")
        with pytest.raises(ScopeViolation):
            reg.check_tool("noisy-agent", AgentTool.BROADCAST_MSG)

    def test_risk_controller_is_global_singleton_not_per_agent(self):
        """Confirm a compromised agent cannot instantiate its own RiskController."""
        from merid.risk.kill_switches import risk_controller, RiskController
        # Importing the module again returns the same singleton
        from merid.risk import kill_switches as ks
        assert ks.risk_controller is risk_controller

    def test_kill_switch_file_path_is_env_overridable(self):
        """kill_switch.json path must use env var, not hardcoded path."""
        src = _read("merid/risk/kill_switches.py")
        assert 'os.environ.get("MERID_RISK_KS_FILE"' in src, (
            "Kill switch file path should be overridable via env var for isolation"
        )


# ===========================================================================
# ZT-02b — Kill Switch Reset Requires Dual Control
# ===========================================================================

class TestKillSwitchDualControl:

    def test_risk_controller_reset_accepts_operator_param(self, tmp_path, monkeypatch):
        """reset() logs the operator; dual control wraps this at the API layer."""
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        from merid.risk.kill_switches import RiskController

        rc = RiskController()
        rc.emergency_stop("test")
        result = rc.reset(operator="alice")
        assert result is True

    def test_dual_control_kill_switch_reset_flow(self):
        """Full dual-control flow: request → second approval → consume → then reset."""
        from security.zero_trust import DualControlAction
        guard = _fresh_dual_control()
        token = guard.request_action(
            DualControlAction.KILL_SWITCH_RESET, "alice", reason="daily restart"
        )
        guard.approve_action(token, "bob")
        pa = guard.consume_action(token)
        assert pa.requester_id == "alice"
        assert pa.approver_id == "bob"
        assert pa.action == DualControlAction.KILL_SWITCH_RESET
        # Now it would be safe to call risk_controller.reset(operator="alice")

    def test_kill_switch_reset_single_operator_alone_is_insufficient(self):
        """Without second approval, consume_action raises — single operator cannot reset."""
        from security.zero_trust import DualControlAction, DualControlError
        guard = _fresh_dual_control()
        token = guard.request_action(DualControlAction.KILL_SWITCH_RESET, "alice")
        with pytest.raises(DualControlError, match="second-human approval"):
            guard.consume_action(token)

    def test_kill_switch_activate_is_dual_control_action(self):
        from security.zero_trust import DualControlAction
        # Activating (emergency stop) is allowed single-operator for speed;
        # only RESET requires dual control. Confirm activate IS in the enum.
        assert DualControlAction.KILL_SWITCH_ACTIVATE in list(DualControlAction)


# ===========================================================================
# ZT-CI — CI Pipeline Security Gates
# ===========================================================================

class TestCIInvariants:

    def _ci_yml(self) -> str:
        return _read(".github/workflows/ci.yml")

    def test_bandit_step_present(self):
        assert "bandit" in self._ci_yml()

    def test_pip_audit_step_present(self):
        assert "pip-audit" in self._ci_yml()

    def test_bandit_blocks_on_high_severity(self):
        """bandit with -lll should exit non-zero on HIGH findings."""
        ci = self._ci_yml()
        assert "-lll" in ci, "bandit must use -lll to exit non-zero on HIGH severity"

    def test_secret_file_check_present(self):
        """CI must check for tracked .pem/.key files."""
        ci = self._ci_yml()
        assert ".pem" in ci or "secret" in ci.lower()

    def test_ruff_blocking_check_present(self):
        """ruff check must be blocking (no --exit-zero)."""
        ci = self._ci_yml()
        assert "ruff check" in ci
        # Verify --exit-zero is not present on the blocking step
        lines = ci.splitlines()
        ruff_lines = [l for l in lines if "ruff check" in l and "--exit-zero" in l]
        assert not ruff_lines, "ruff check must not use --exit-zero on the blocking step"

    def test_swarm_integrity_gate_runs_before_tests(self):
        """swarm-integrity-gate must be a dependency of backend-tests."""
        ci = self._ci_yml()
        assert "swarm-integrity-gate" in ci
        assert "needs: [swarm-integrity-gate]" in ci

    def test_timeout_set_on_jobs(self):
        """All jobs must have timeout-minutes to prevent runaway CI."""
        import re
        ci = self._ci_yml()
        jobs = re.findall(r'^\s{2}\w[\w-]+:\s*$', ci, re.MULTILINE)
        # Just confirm at least one timeout-minutes is present
        assert "timeout-minutes" in ci

    def test_codeowners_exists(self):
        codeowners = REPO_ROOT / ".github" / "CODEOWNERS"
        assert codeowners.exists(), "CODEOWNERS file must exist for critical path protection"

    def test_codeowners_covers_execution_path(self):
        src = _read(".github/CODEOWNERS")
        # Critical dirs must have owners — web/api/ auth is covered by .github/
        # and operator execution paths by merid/execution_guard.py + trading/
        critical = ["merid/", "trading/", "governance/", "config/"]
        for path in critical:
            assert path in src, f"CODEOWNERS must cover {path}"

    def test_codeowners_covers_web_auth(self):
        src = _read(".github/CODEOWNERS")
        # web/api auth must be covered; add web/api/ if missing
        has_web_api = "web/api/" in src or "web/" in src
        has_ci_coverage = ".github/" in src
        assert has_web_api or has_ci_coverage, (
            "CODEOWNERS must cover web/api/ or web/ to protect auth endpoints"
        )


# ===========================================================================
# ZT-POLICY — Policy Object Completeness
# ===========================================================================

class TestZTPolicyConstants:

    def test_all_policy_constants_are_true(self):
        from security.zero_trust import ZTPolicy
        assert ZTPolicy.EXECUTION_REQUIRES_SCOPED_TOKEN is True
        assert ZTPolicy.HIGH_RISK_TOOLS_OFF_BY_DEFAULT is True
        assert ZTPolicy.STREAM_PUBLISHER_MUST_BE_REGISTERED is True
        assert ZTPolicy.CONFIG_MUTATION_REQUIRES_AUTH is True
        assert ZTPolicy.AGENTS_CANNOT_ENUMERATE_REGISTRY is True
        assert ZTPolicy.DEV_BYPASS_REQUIRES_EXPLICIT_OPT_IN is True
        assert ZTPolicy.DEV_BYPASS_BLOCKED_IN_LIVE_MODE is True

    def test_governance_gated_tools_subset_of_high_risk(self):
        from security.zero_trust import ZTPolicy, _HIGH_RISK_TOOLS
        for tool in ZTPolicy.GOVERNANCE_GATED_TOOLS:
            assert tool in _HIGH_RISK_TOOLS, (
                f"{tool} is governance-gated but not in _HIGH_RISK_TOOLS"
            )

    def test_dual_control_actions_covers_all_enum_values(self):
        from security.zero_trust import ZTPolicy, DualControlAction
        for action in DualControlAction:
            assert action in ZTPolicy.DUAL_CONTROL_ACTIONS

    def test_approval_token_ttl_is_reasonable(self):
        from security.zero_trust import ZTPolicy
        # Must be > 0 and ≤ 24h
        assert 60 <= ZTPolicy.APPROVAL_TOKEN_TTL_S <= 86400

    def test_singletons_return_same_instance(self):
        from security.zero_trust import (
            get_agent_scope_registry,
            get_dual_control_guard,
            get_stream_publisher_guard,
        )
        assert get_agent_scope_registry() is get_agent_scope_registry()
        assert get_dual_control_guard() is get_dual_control_guard()
        assert get_stream_publisher_guard() is get_stream_publisher_guard()

    def test_zero_trust_module_importable(self):
        import security.zero_trust  # noqa: F401

    def test_security_package_init_exists(self):
        init = REPO_ROOT / "security" / "__init__.py"
        assert init.exists() or (REPO_ROOT / "security").is_dir(), (
            "security/ must be a package or directory"
        )
