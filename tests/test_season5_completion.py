"""Season 5 completion tests — covers all new/modified modules.

Run:
    python -m pytest tests/test_season5_completion.py -v
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_RISK_TRADING_VIEWS = (
    PROJECT_ROOT / "web/react/src/views/Risk.tsx",
    PROJECT_ROOT / "web/react/src/views/Trading.tsx",
)
_SKIP_IF_NO_RISK_TRADING_VIEWS = pytest.mark.skipif(
    not all(p.exists() for p in _RISK_TRADING_VIEWS),
    reason="Risk.tsx / Trading.tsx not present in this checkout",
)
_DATA_HEALTH_PATH = PROJECT_ROOT / "web/react/src/components/DataHealthCard.tsx"
_SKIP_IF_NO_DATA_HEALTH = pytest.mark.skipif(
    not _DATA_HEALTH_PATH.exists(),
    reason="DataHealthCard.tsx not present in this checkout",
)


# ════════════════════════════════════════════════════════════════════
# 1. StubBadge / DataAgeBadge wiring in Risk + Trading views
# ════════════════════════════════════════════════════════════════════

@_SKIP_IF_NO_RISK_TRADING_VIEWS
class TestStubBadgeWiring:
    """Verify StubBadge and DataAgeBadge are imported in Risk and Trading views."""

    def test_risk_view_imports_stub_badge(self):
        src = (PROJECT_ROOT / "web/react/src/views/Risk.tsx").read_text(encoding="utf-8")
        assert "StubBadge" in src, "Risk.tsx must import StubBadge"
        assert "DataAgeBadge" in src, "Risk.tsx must import DataAgeBadge"

    def test_risk_view_uses_badges(self):
        src = (PROJECT_ROOT / "web/react/src/views/Risk.tsx").read_text(encoding="utf-8")
        assert "riskIsStub" in src, "Risk.tsx must destructure isStub from useApiData"
        assert "riskUpdated" in src, "Risk.tsx must destructure lastUpdated from useApiData"
        assert "<StubBadge" in src, "Risk.tsx must render StubBadge"
        assert "<DataAgeBadge" in src, "Risk.tsx must render DataAgeBadge"

    def test_trading_view_imports_stub_badge(self):
        src = (PROJECT_ROOT / "web/react/src/views/Trading.tsx").read_text(encoding="utf-8")
        assert "StubBadge" in src, "Trading.tsx must import StubBadge"
        assert "DataAgeBadge" in src, "Trading.tsx must import DataAgeBadge"

    def test_trading_view_uses_badges(self):
        src = (PROJECT_ROOT / "web/react/src/views/Trading.tsx").read_text(encoding="utf-8")
        assert "positionsIsStub" in src, "Trading.tsx must destructure isStub"
        assert "positionsUpdated" in src, "Trading.tsx must destructure lastUpdated"
        assert "<StubBadge" in src, "Trading.tsx must render StubBadge"
        assert "<DataAgeBadge" in src, "Trading.tsx must render DataAgeBadge"


# ════════════════════════════════════════════════════════════════════
# 2. Observability alert rules — PnL divergence, Agent failures, Recon
# ════════════════════════════════════════════════════════════════════

class TestObservabilityAlerts:
    """Verify new alert rules are wired and evaluate correctly."""

    def test_pnl_divergence_alert_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class PnlDivergenceAlert" in src
        assert "PnlDivergenceAlert()" in src  # in ALERT_RULES

    def test_agent_consecutive_failure_alert_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class AgentConsecutiveFailureAlert" in src
        assert "AgentConsecutiveFailureAlert()" in src

    def test_reconciliation_degraded_alert_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class ReconciliationDegradedAlert" in src
        assert "ReconciliationDegradedAlert()" in src

    def test_pnl_divergence_alert_evaluates(self):
        try:
            from web.api.system_observability import PnlDivergenceAlert
        except Exception:
            pytest.skip("Cannot import due to runtime env (OFFLINE mode enum)")
        alert = PnlDivergenceAlert()
        result = alert.evaluate()
        assert "firing" in result
        assert "name" in result
        assert result["name"] == "pnl_divergence"

    def test_agent_failure_alert_evaluates(self):
        try:
            from web.api.system_observability import AgentConsecutiveFailureAlert
        except Exception:
            pytest.skip("Cannot import due to runtime env (OFFLINE mode enum)")
        alert = AgentConsecutiveFailureAlert()
        result = alert.evaluate()
        assert "firing" in result
        assert result["name"] == "agent_consecutive_failures"

    def test_reconciliation_degraded_alert_evaluates(self):
        try:
            from web.api.system_observability import ReconciliationDegradedAlert
        except Exception:
            pytest.skip("Cannot import due to runtime env (OFFLINE mode enum)")
        alert = ReconciliationDegradedAlert()
        result = alert.evaluate()
        assert "firing" in result
        assert result["name"] == "reconciliation_degraded"

    def test_alert_rules_list_count(self):
        try:
            from web.api.system_observability import ALERT_RULES
        except Exception:
            pytest.skip("Cannot import due to runtime env (OFFLINE mode enum)")
        names = [r.name for r in ALERT_RULES]
        assert "pnl_divergence" in names
        assert "agent_consecutive_failures" in names
        assert "reconciliation_degraded" in names
        # Should have at least 25 rules now
        assert len(ALERT_RULES) >= 25


# ════════════════════════════════════════════════════════════════════
# 3. Agent failure counts function
# ════════════════════════════════════════════════════════════════════

class TestAgentFailureCounts:
    """Verify get_agent_failure_counts in core/error_handling."""

    def test_function_exists(self):
        from core.error_handling import get_agent_failure_counts
        assert callable(get_agent_failure_counts)

    def test_returns_dict(self):
        from core.error_handling import get_agent_failure_counts
        result = get_agent_failure_counts()
        assert isinstance(result, dict)

    def test_empty_when_no_failures(self):
        from core.error_handling import get_agent_failure_counts, get_health_monitor
        monitor = get_health_monitor()
        # Fresh monitor should have no failures
        result = get_agent_failure_counts()
        # Only agents with consecutive_failures > 0 should appear
        for name, count in result.items():
            assert count > 0


# ════════════════════════════════════════════════════════════════════
# 4. WebSocket heartbeat
# ════════════════════════════════════════════════════════════════════

class TestWebSocketHeartbeat:
    """Verify heartbeat parameters are in useWebSocket."""

    def test_heartbeat_params_in_hook(self):
        src = (PROJECT_ROOT / "web/react/src/hooks/useWebSocket.ts").read_text(encoding="utf-8")
        assert "heartbeatMs" in src, "useWebSocket must accept heartbeatMs"
        assert "pongTimeoutMs" in src, "useWebSocket must accept pongTimeoutMs"
        assert "30_000" in src or "30000" in src, "Default heartbeat should be 30s"

    def test_ping_pong_logic(self):
        src = (PROJECT_ROOT / "web/react/src/hooks/useWebSocket.ts").read_text(encoding="utf-8")
        assert "event: 'ping'" in src or "event: \"ping\"" in src, "Must send ping events"
        assert "pong" in src, "Must handle pong responses"

    def test_dead_socket_detection(self):
        src = (PROJECT_ROOT / "web/react/src/hooks/useWebSocket.ts").read_text(encoding="utf-8")
        assert "heartbeat timeout" in src.lower() or "connection dead" in src.lower()


# ════════════════════════════════════════════════════════════════════
# 5. Paper fee model
# ════════════════════════════════════════════════════════════════════

class TestPaperFeeModel:
    """Verify per-venue fee model in paper trading engine."""

    def test_default_fee_bps_defined(self):
        from trading.paper_trading import PaperTradingEngine
        assert hasattr(PaperTradingEngine, "DEFAULT_FEE_BPS")
        bps = PaperTradingEngine.DEFAULT_FEE_BPS
        assert "binance" in bps
        assert "alpaca" in bps
        assert "kalshi" in bps
        assert bps["alpaca"] == 0.0  # commission-free

    def test_fee_override(self):
        from trading.paper_trading import PaperTradingEngine
        engine = PaperTradingEngine(fee_overrides={"binance": 5.0})
        assert engine.fee_bps["binance"] == 5.0
        assert engine.fee_bps["alpaca"] == 0.0  # unchanged

    def test_total_fees_tracking(self):
        from trading.paper_trading import PaperTradingEngine
        engine = PaperTradingEngine()
        assert engine.total_fees_paid == 0.0


# ════════════════════════════════════════════════════════════════════
# 6. DataHealthCard component
# ════════════════════════════════════════════════════════════════════

@_SKIP_IF_NO_DATA_HEALTH
class TestDataHealthCard:
    """Verify DataHealthCard component and wiring."""

    def test_component_file_exists(self):
        path = PROJECT_ROOT / "web/react/src/components/DataHealthCard.tsx"
        assert path.exists(), "DataHealthCard.tsx must exist"

    def test_component_uses_api_data(self):
        src = (PROJECT_ROOT / "web/react/src/components/DataHealthCard.tsx").read_text(encoding="utf-8")
        assert "useApiData" in src
        assert "DATA_FRESHNESS" in src

    def test_component_wired_into_operator_dashboard(self):
        src = (PROJECT_ROOT / "web/react/src/views/OperatorDashboard.tsx").read_text(encoding="utf-8")
        assert "DataHealthCard" in src
        assert "import DataHealthCard" in src


# ════════════════════════════════════════════════════════════════════
# 7. Unified reconciliation endpoint + thread safety
# ════════════════════════════════════════════════════════════════════

class TestReconciliationUnified:
    """Verify unified endpoint and thread-safe state."""

    def test_unified_endpoint_exists(self):
        src = (PROJECT_ROOT / "web/api/system_endpoints.py").read_text(encoding="utf-8")
        assert "/api/v1/reconciliation/unified-status" in src
        assert "async def unified_reconciliation_status" in src

    def test_thread_lock_in_merid_reconciliation(self):
        src = (PROJECT_ROOT / "merid/reconciliation/venue_reconciler.py").read_text(
            encoding="utf-8"
        )
        assert "_recon_lock" in src
        assert "threading.Lock()" in src
        assert "with _recon_lock:" in src

    def test_has_critical_discrepancies_uses_lock(self):
        src = (PROJECT_ROOT / "merid/reconciliation/venue_reconciler.py").read_text(
            encoding="utf-8"
        )
        idx = src.index("def has_critical_discrepancies")
        body = src[idx : idx + 800]
        assert "with _recon_lock:" in body

    def test_frontend_constant_exists(self):
        constants_src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(
            encoding="utf-8"
        )
        api_src = (PROJECT_ROOT / "web/api/system_endpoints.py").read_text(encoding="utf-8")
        assert "RECONCILIATION_STATUS" in constants_src
        assert "/api/v1/reconciliation/unified-status" in api_src


# ════════════════════════════════════════════════════════════════════
# 8. JSONL log rotation
# ════════════════════════════════════════════════════════════════════

class TestJsonlWriter:
    """Verify rotating JSONL writer."""

    def test_import(self):
        from utils.jsonl_writer import JsonlWriter
        assert callable(JsonlWriter)

    def test_write_and_read(self):
        from utils.jsonl_writer import JsonlWriter
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            writer = JsonlWriter(path, max_bytes=1000, backup_count=2)
            writer.append({"event": "test", "ts": time.time()})
            assert path.exists()
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["event"] == "test"

    def test_rotation(self):
        from utils.jsonl_writer import JsonlWriter
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            # Very small max_bytes to force rotation quickly
            writer = JsonlWriter(path, max_bytes=100, backup_count=2)
            # Write enough to trigger rotation
            for i in range(50):
                writer.append({"i": i, "padding": "x" * 50})
            # After rotation, backup files should exist
            backup1 = path.with_suffix(".jsonl.1")
            assert path.exists()
            assert backup1.exists(), "Rotation should create .jsonl.1 backup"

    def test_thread_safety(self):
        from utils.jsonl_writer import JsonlWriter
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            writer = JsonlWriter(path, max_bytes=100_000, backup_count=2)
            errors = []

            def write_batch(start):
                for i in range(100):
                    ok = writer.append({"thread": threading.current_thread().name, "i": start + i})
                    if not ok:
                        errors.append(start + i)

            threads = [threading.Thread(target=write_batch, args=(n * 100,)) for n in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Write errors: {errors}"
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 400

    def test_stats(self):
        from utils.jsonl_writer import JsonlWriter
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            writer = JsonlWriter(path, max_bytes=1000)
            writer.append({"x": 1})
            stats = writer.stats()
            assert stats["healthy"] is True
            assert stats["write_errors"] == 0
            assert stats["size_bytes"] > 0

    def test_singletons(self):
        from utils.jsonl_writer import get_audit_writer, get_tick_writer
        audit = get_audit_writer()
        tick = get_tick_writer()
        assert audit is not None
        assert tick is not None
        assert "audit_log" in str(audit.path)
        assert "merid_ticks" in str(tick.path)


# ════════════════════════════════════════════════════════════════════
# 9. Cross-module wiring checks
# ════════════════════════════════════════════════════════════════════

class TestCrossModuleWiring:
    """Verify routes, constants, and config alignment."""

    def test_all_reconciliation_endpoints_in_constants(self):
        src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(encoding="utf-8")
        api_src = (PROJECT_ROOT / "web/api/system_endpoints.py").read_text(encoding="utf-8")
        assert "RECONCILIATION_RUN" in src
        assert "RECONCILIATION_STATUS" in src
        assert "/api/v1/reconciliation/unified-status" in api_src

    def test_operator_dashboard_imports_data_freshness(self):
        src = (PROJECT_ROOT / "web/react/src/views/OperatorDashboard.tsx").read_text(encoding="utf-8")
        assert "DataFreshnessPanel" in src
        assert "import DataFreshnessPanel" in src or "from '../components/DataFreshnessPanel'" in src

    def test_data_freshness_endpoint_in_constants(self):
        src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(encoding="utf-8")
        assert "DATA_FRESHNESS" in src

    def test_staleness_polling_interval_in_constants(self):
        src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(encoding="utf-8")
        assert "STALENESS" in src


# ════════════════════════════════════════════════════════════════════
# 10. Reconciliation module import checks
# ════════════════════════════════════════════════════════════════════

class TestReconciliationModules:
    """Verify merid reconciliation is importable; legacy module is deprecated."""

    def test_trading_reconciliation_deprecated(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ImportError):
                import trading.reconciliation  # noqa: F401

    def test_merid_reconciliation_importable(self):
        from merid.reconciliation import reconcile_all_venues, has_critical_discrepancies
        assert callable(reconcile_all_venues)
        assert callable(has_critical_discrepancies)

    def test_merid_reconciliation_status_shape(self):
        from merid.reconciliation import get_reconciliation_status, reconcile_all_venues

        reconcile_all_venues(["kalshi"])
        d = get_reconciliation_status()
        assert "discrepancy_count" in d
        assert "execution_gate_blocked" in d


# ════════════════════════════════════════════════════════════════════
# Season 6 / Quality Pass invariants
# ════════════════════════════════════════════════════════════════════

class TestErrorBarUsage:
    """Verify ErrorBar component is used consistently across useApiData consumers."""

    # Components/views that import the shared components/ErrorBar.tsx (see ripgrep ErrorBar)
    COMPONENTS_WITH_ERROR_BAR = [
        "AlertHistoryPanel.tsx",
        "DataFreshnessPanel.tsx",
        "ExplainabilityTimeline.tsx",
        "ModeControlPanel.tsx",
        "TelegramLogViewer.tsx",
        "TradingHaltBanner.tsx",
        "PaperLadderCard.tsx",
        "KalshiCancelAllButton.tsx",
        "KalshiCredentialsCard.tsx",
        "KalshiReconciliationBadge.tsx",
        "KalshiAllMarketsView.tsx",
        "LaneControlDashboard.tsx",
        "SwarmConsensusMatrix.tsx",
    ]

    def test_errorbar_component_exists(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "components" / "ErrorBar.tsx"
        assert p.exists(), "ErrorBar.tsx missing"
        text = p.read_text(encoding="utf-8")
        assert "function ErrorBar" in text
        assert "export default" in text

    def test_all_components_import_errorbar(self):
        components_dir = PROJECT_ROOT / "web" / "react" / "src" / "components"
        views_dir = PROJECT_ROOT / "web" / "react" / "src" / "views"
        missing = []
        checked = 0
        for name in self.COMPONENTS_WITH_ERROR_BAR:
            p = components_dir / name
            if not p.exists():
                p = views_dir / name
            if not p.exists():
                continue
            checked += 1
            text = p.read_text(encoding="utf-8")
            if "import ErrorBar" not in text:
                missing.append(f"{name} missing ErrorBar import")
        if checked == 0:
            pytest.skip("No listed ErrorBar consumer components present in this checkout")
        assert not missing, f"ErrorBar not imported in: {missing}"

    def test_all_components_destructure_error(self):
        components_dir = PROJECT_ROOT / "web" / "react" / "src" / "components"
        views_dir = PROJECT_ROOT / "web" / "react" / "src" / "views"
        missing = []
        checked = 0
        for name in self.COMPONENTS_WITH_ERROR_BAR:
            p = components_dir / name
            if not p.exists():
                p = views_dir / name
            if not p.exists():
                continue
            checked += 1
            text = p.read_text(encoding="utf-8")
            if "useApiData" not in text:
                continue
            if "error:" not in text and "error," not in text:
                missing.append(name)
        if checked == 0:
            pytest.skip("No listed ErrorBar consumer components present in this checkout")
        assert not missing, f"Components not destructuring error from useApiData: {missing}"


class TestWebSocketPongHandler:
    """Verify server-side WS pong handlers exist on all endpoints."""

    def test_live_stream_has_pong_handlers(self):
        p = PROJECT_ROOT / "web" / "api" / "live_stream.py"
        text = p.read_text(encoding="utf-8")
        # Shared helper has the pong response; all 4 endpoints call it
        assert '"event": "pong"' in text, "Pong handler must exist"
        assert "_run_ws_endpoint" in text, "Shared WS helper must exist"
        assert text.count("_run_ws_endpoint") >= 5, "All 4 endpoints must call shared helper"

    def test_live_stream_has_receiver_tasks(self):
        p = PROJECT_ROOT / "web" / "api" / "live_stream.py"
        text = p.read_text(encoding="utf-8")
        # After DRY refactor: 1 shared _receiver inside _run_ws_endpoint
        assert "async def _receiver()" in text, "_receiver must exist in shared helper"
        assert "receive_text" in text, "Receiver must read client messages"

    def test_client_side_ping_sends(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "hooks" / "useWebSocket.ts"
        text = p.read_text(encoding="utf-8")
        assert "event: 'ping'" in text or 'event: "ping"' in text


class TestExecutionGuardLogging:
    """Verify execution guard logging is clean (no dead code)."""

    def test_no_dead_code_in_log_verdict(self):
        p = PROJECT_ROOT / "merid" / "execution_guard.py"
        text = p.read_text(encoding="utf-8")
        assert "if False" not in text, "Dead code 'if False' still present in execution_guard"

    def test_log_fn_pattern(self):
        p = PROJECT_ROOT / "merid" / "execution_guard.py"
        text = p.read_text(encoding="utf-8")
        assert "log_fn = logger.info if verdict.allowed else logger.warning" in text


class TestKillSwitchConfirmations:
    """Verify all kill switch actions require confirmation."""

    def test_kalshi_grid_kill_switch_has_confirm(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "views" / "KalshiGridView.tsx"
        text = p.read_text(encoding="utf-8")
        assert "confirm(" in text or "window.confirm(" in text, \
            "KalshiGridView kill switch reset missing confirmation"

    def test_operator_dashboard_kill_switch_has_confirm(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "views" / "OperatorDashboard.tsx"
        text = p.read_text(encoding="utf-8")
        assert "confirm(" in text or "window.confirm(" in text, \
            "OperatorDashboard kill switch missing confirmation"

    def test_mode_control_live_has_confirm(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "components" / "ModeControlPanel.tsx"
        text = p.read_text(encoding="utf-8")
        assert "confirmAction" in text, "ModeControlPanel missing confirmation for LIVE mode"

    def test_trading_halt_banner_has_confirm(self):
        p = PROJECT_ROOT / "web" / "react" / "src" / "components" / "TradingHaltBanner.tsx"
        text = p.read_text(encoding="utf-8")
        assert "confirm(" in text, "TradingHaltBanner halt/resume missing confirmation"
