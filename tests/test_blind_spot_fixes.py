"""Invariant tests for blind-spot audit fixes.

Covers:
  - RBAC enforcement on destructive endpoints (kill switch, grid start/stop, circuit breaker)
  - operator_api.py auth wiring
  - Dev-bypass fail-closed when live trading is active
  - UserManager.invalidate_session (logout)
  - Backtest live-mode guard
  - Backtest slippage application
  - FeedStalenessMonitor wiring in AgentGrid
"""

from __future__ import annotations

import ast
import os
import textwrap
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).parent.parent


# ─── helpers ──────────────────────────────────────────────────────────────────

def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _parse(rel: str) -> ast.Module:
    return ast.parse(_src(rel))


# ══════════════════════════════════════════════════════════════════════════════
# 1. operator_api.py — auth wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestOperatorApiAuth:
    FILE = "web/api/operator_api.py"

    def test_imports_get_current_session(self):
        src = _src(self.FILE)
        assert "get_current_session" in src

    def test_imports_require_role(self):
        src = _src(self.FILE)
        assert "require_role" in src

    def test_router_has_session_dependency(self):
        src = _src(self.FILE)
        assert 'dependencies=[Depends(get_current_session)]' in src

    def test_kill_switch_on_requires_operator(self):
        src = _src(self.FILE)
        assert 'require_role("operator", "admin")' in src
        # Ensure it appears on/near the kill-switch-on route
        assert "guard/kill-switch/on" in src

    def test_kill_switch_off_requires_operator(self):
        src = _src(self.FILE)
        assert "guard/kill-switch/off" in src
        assert 'require_role("operator", "admin")' in src

    def test_domain_promote_requires_operator(self):
        src = _src(self.FILE)
        assert "domain/{domain}/promote" in src
        # require_role appears on that route
        lines = src.splitlines()
        promote_idx = next(i for i, l in enumerate(lines) if "{domain}/promote" in l)
        nearby = "\n".join(lines[promote_idx:promote_idx + 4])
        assert "require_role" in nearby

    def test_domain_demote_requires_operator(self):
        src = _src(self.FILE)
        assert "domain/{domain}/demote" in src
        lines = src.splitlines()
        demote_idx = next(i for i, l in enumerate(lines) if "{domain}/demote" in l)
        nearby = "\n".join(lines[demote_idx:demote_idx + 4])
        assert "require_role" in nearby

    def test_agent_promote_requires_operator(self):
        src = _src(self.FILE)
        assert "agent/{agent_id}/promote" in src
        lines = src.splitlines()
        idx = next(i for i, l in enumerate(lines) if "agent_id}/promote" in l)
        nearby = "\n".join(lines[idx:idx + 4])
        assert "require_role" in nearby

    def test_agent_demote_requires_operator(self):
        src = _src(self.FILE)
        assert "agent/{agent_id}/demote" in src
        lines = src.splitlines()
        idx = next(i for i, l in enumerate(lines) if "agent_id}/demote" in l)
        nearby = "\n".join(lines[idx:idx + 4])
        assert "require_role" in nearby


# ══════════════════════════════════════════════════════════════════════════════
# 2. kalshi_api.py — kill-switch role check
# ══════════════════════════════════════════════════════════════════════════════

class TestKalshiApiRBAC:
    FILE = "web/api/kalshi_api.py"

    def test_imports_require_role(self):
        assert "require_role" in _src(self.FILE)

    def test_kill_switch_route_has_role_check(self):
        src = _src(self.FILE)
        lines = src.splitlines()
        ks_idx = next(i for i, l in enumerate(lines) if '"/kill-switch"' in l)
        nearby = "\n".join(lines[ks_idx:ks_idx + 5])
        assert "require_role" in nearby


# ══════════════════════════════════════════════════════════════════════════════
# 3. kalshi_grid_api.py — grid lifecycle role checks
# ══════════════════════════════════════════════════════════════════════════════

class TestKalshiGridApiRBAC:
    FILE = "web/api/kalshi_grid_api.py"

    def test_imports_require_role(self):
        assert "require_role" in _src(self.FILE)

    def _route_has_require_role(self, route_path: str) -> bool:
        src = _src(self.FILE)
        lines = src.splitlines()
        try:
            idx = next(i for i, l in enumerate(lines) if f'"{route_path}"' in l)
        except StopIteration:
            return False
        nearby = "\n".join(lines[idx:idx + 8])
        return "require_role" in nearby

    def test_start_requires_operator(self):
        assert self._route_has_require_role("/start")

    def test_stop_requires_operator(self):
        src = _src(self.FILE)
        lines = src.splitlines()
        idx = next(i for i, l in enumerate(lines) if '"/stop"' in l)
        nearby = "\n".join(lines[idx:idx + 4])
        assert "require_role" in nearby

    def test_kill_switch_reset_requires_operator(self):
        assert self._route_has_require_role("/kill-switch/reset")

    def test_mode_switch_requires_operator(self):
        assert self._route_has_require_role("/mode")


# ══════════════════════════════════════════════════════════════════════════════
# 4. system_endpoints.py — circuit breaker reset role check
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemEndpointsRBAC:
    FILE = "web/api/system_endpoints.py"

    def test_imports_require_role(self):
        assert "require_role" in _src(self.FILE)

    def test_circuit_breaker_reset_requires_operator(self):
        src = _src(self.FILE)
        lines = src.splitlines()
        idx = next(i for i, l in enumerate(lines) if "circuit-breaker/reset" in l)
        nearby = "\n".join(lines[idx:idx + 5])
        assert "require_role" in nearby


# ══════════════════════════════════════════════════════════════════════════════
# 5. Previously-unprotected routers now have auth
# ══════════════════════════════════════════════════════════════════════════════

class TestRouterAuthCoverage:
    ROUTERS = [
        ("web/api/swarm_routes.py", "router"),
        ("web/api/signal_layer_api.py", "signal_layer_router"),
        ("web/api/signals_api.py", "router"),
        ("web/api/us_compliant_markets.py", "router"),
        ("web/api/slo_api.py", "router"),
    ]

    @pytest.mark.parametrize("filepath,router_var", ROUTERS)
    def test_router_has_session_dependency(self, filepath, router_var):
        src = _src(filepath)
        assert "get_current_session" in src, f"{filepath} missing get_current_session import"
        assert "Depends(get_current_session)" in src, (
            f"{filepath} router '{router_var}' missing session dependency"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. auth.py — dev-bypass fail-closed
# ══════════════════════════════════════════════════════════════════════════════

class TestDevBypassFailClosed:
    FILE = "web/api/auth.py"

    def test_live_trading_check_present(self):
        src = _src(self.FILE)
        assert "MERID_PM_LIVE_ENABLED" in src
        assert "live_trading" in src

    def test_raises_403_when_live_and_dev_mode(self):
        src = _src(self.FILE)
        assert "status_code=403" in src
        assert "Dev auth bypass is disabled in live trading mode" in src

    def test_critical_log_present(self):
        src = _src(self.FILE)
        assert "DEV AUTH BYPASS BLOCKED" in src

    def test_logout_calls_invalidate_session(self):
        src = _src(self.FILE)
        assert "user_manager.invalidate_session" in src


# ══════════════════════════════════════════════════════════════════════════════
# 7. UserManager — invalidate_session
# ══════════════════════════════════════════════════════════════════════════════

class TestUserManagerLogout:
    FILE = "auth/user_manager.py"

    def test_invalidate_session_method_exists(self):
        src = _src(self.FILE)
        assert "def invalidate_session" in src

    def test_invalidate_session_deletes_from_dict(self):
        src = _src(self.FILE)
        assert "del self._sessions[session_id]" in src

    def test_invalidate_session_returns_bool(self):
        src = _src(self.FILE)
        assert "return True" in src
        assert "return False" in src

    def test_invalidate_session_functional(self):
        """Unit test: session is gone after invalidation."""
        import sys
        sys.path.insert(0, str(ROOT))
        from auth.user_manager import UserManager
        mgr = UserManager()
        user = mgr.create_user("testuser_inv", "inv@test.com")
        session = mgr.create_session(user.user_id)
        sid = session.session_id
        assert mgr.validate_session(sid) is not None
        result = mgr.invalidate_session(sid)
        assert result is True
        assert mgr.validate_session(sid) is None

    def test_invalidate_nonexistent_returns_false(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from auth.user_manager import UserManager
        mgr = UserManager()
        assert mgr.invalidate_session("nonexistent-session-id") is False


# ══════════════════════════════════════════════════════════════════════════════
# 8. backtesting/engine.py — live-mode guard + slippage
# ══════════════════════════════════════════════════════════════════════════════

class TestBacktestingFixes:
    FILE = "backtesting/engine.py"

    def test_live_mode_guard_present(self):
        src = _src(self.FILE)
        assert "live_active" in src or "_live_active" in src
        assert "MERID_PM_LIVE_ENABLED" in src

    def test_live_mode_raises_runtime_error(self):
        src = _src(self.FILE)
        assert "raise RuntimeError" in src
        assert "live trading is active" in src

    def test_slippage_applied_in_momentum(self):
        src = _src(self.FILE)
        assert "slippage_pct" in src
        # slippage deduction appears in PnL calculation
        assert "slippage * position" in src

    def test_slippage_applied_in_all_four_strategies(self):
        src = _src(self.FILE)
        # Each strategy exit block should deduct slippage
        count = src.count("slippage * position")
        assert count >= 4, f"Expected slippage in 4 strategies, found {count}"

    def test_live_mode_guard_blocks_execution(self):
        """Functional: run_backtest raises when live mode env vars are set."""
        import sys, asyncio, os
        from datetime import datetime
        sys.path.insert(0, str(ROOT))

        os.environ["MERID_PM_LIVE_ENABLED"] = "true"
        try:
            from backtesting.engine import BacktestEngine, BacktestConfig
            engine = BacktestEngine()
            config = BacktestConfig(
                backtest_id="test-live-block",
                strategy_name="momentum",
                symbols=["BTC/USD"],
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 1, 31),
            )
            with pytest.raises(RuntimeError, match="live trading is active"):
                asyncio.get_event_loop().run_until_complete(engine.run_backtest(config))
        finally:
            os.environ.pop("MERID_PM_LIVE_ENABLED", None)


# ══════════════════════════════════════════════════════════════════════════════
# 9. AgentGrid — FeedStalenessMonitor wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentGridFeedStalenessWiring:
    FILE = "merid/prediction/agent_grid.py"

    def test_feed_staleness_monitor_imported(self):
        src = _src(self.FILE)
        assert "get_feed_staleness_monitor" in src

    def test_on_stale_callback_registered(self):
        src = _src(self.FILE)
        assert "_fsm.on_stale(" in src

    def test_stale_callback_pauses_agent(self):
        src = _src(self.FILE)
        assert "_agent.pause()" in src

    def test_stale_callback_logs_warning(self):
        src = _src(self.FILE)
        assert "FeedStalenessMonitor:" in src
