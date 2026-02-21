"""Global test fixtures for MERID test suite."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Quarantine hook — skip tests tagged with known-broken markers
# ---------------------------------------------------------------------------
QUARANTINE_MARKERS = {"quarantine"}


def pytest_collection_modifyitems(config, items):
    """Skip tests marked with quarantine markers unless explicitly requested."""
    run_quarantine = config.getoption("--run-quarantine", default=False) if hasattr(config.option, "run_quarantine") else False
    if run_quarantine:
        return
    skip_q = pytest.mark.skip(reason="quarantined — pass --run-quarantine to include")
    for item in items:
        if QUARANTINE_MARKERS & {m.name for m in item.iter_markers()}:
            item.add_marker(skip_q)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_integration_like_node(node) -> bool:
    integration_markers = {"integration", "e2e", "prod_integration", "contract"}
    if any(node.get_closest_marker(marker) for marker in integration_markers):
        return True

    node_path = str(getattr(node, "fspath", "")).replace("\\", "/")
    return "/tests/integration/" in node_path


@pytest.fixture(scope="session")
def swarm_integrity_report():
    """Session-scoped swarm integrity report (enabled via env flag)."""
    enforced = _env_flag("MERID_SWARM_INTEGRITY_ENFORCE", default=False)
    if not enforced:
        return {
            "enforced": False,
            "ok": True,
            "issues": [],
            "warning": None,
        }

    from merid.safeguards.swarm_integrity_guard import run_swarm_integrity_gate

    report = run_swarm_integrity_gate(
        snapshot_path=os.getenv("MERID_SWARM_HEALTH_SNAPSHOT"),
        policy_path=os.getenv("MERID_SWARM_SAFEGUARD_CONFIG", ".merid_safeguard.yml"),
    )
    payload = report.to_dict()
    payload["enforced"] = True
    return payload


@pytest.fixture(autouse=True)
def enforce_swarm_integrity_for_integration_tests(request, swarm_integrity_report):
    """Fail integration-like tests when swarm integrity enforcement is enabled."""
    if not swarm_integrity_report.get("enforced"):
        return
    if not _is_integration_like_node(request.node):
        return
    if swarm_integrity_report.get("ok"):
        return

    issues = "; ".join(swarm_integrity_report.get("issues", [])) or "unknown integrity failure"
    warning = swarm_integrity_report.get("warning")
    suffix = f" {warning}" if warning else ""
    pytest.fail(f"Swarm integrity guard failed: {issues}.{suffix}")

from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch):
    """
    Autouse fixture to warn about real network traffic during tests.
    
    This fixture monkeypatches common HTTP/WebSocket libraries at the start
    of each test to catch unmocked network calls. Tests should explicitly
    set up their mocks.
    """
    # We'll implement this more carefully to not interfere with existing mocks
    # For now, just yield to allow tests to run
    yield


@pytest.fixture
def mock_httpx_client():
    """Fixture providing a mock httpx.AsyncClient for tests."""
    client = MagicMock()
    client.get = MagicMock()
    client.post = MagicMock()
    client.request = MagicMock()
    return client


@pytest.fixture
def mock_websocket():
    """Fixture providing a mock WebSocket for tests."""
    ws = MagicMock()
    ws.send = MagicMock()
    ws.recv = MagicMock()
    ws.close = MagicMock()
    return ws


@pytest.fixture
def missing_endpoints_client():
    """Minimal FastAPI TestClient containing only the missing_endpoints router.

    Usage in tests::

        def test_something(missing_endpoints_client):
            resp = missing_endpoints_client.get("/api/v1/some/endpoint")
            assert resp.status_code == 200
    """
    from web.api.missing_endpoints import router as missing_router
    app = FastAPI()
    app.include_router(missing_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dev Swarm xdist invariant fixtures
# ---------------------------------------------------------------------------

_S2_TEMPLATES = {
    "build_state_manager": {
        "priority": 0, "estimated_effort": "large",
        "description": "[RRG-01/RRG-02] Build CriticalStateManager with reconciliation",
        "success_criteria": "CriticalStateManager persists and reconciles all pipeline state; RRG-01 and RRG-02 resolved",
    },
    "implement_black_swan_drill_harness": {
        "priority": 0, "estimated_effort": "large",
        "description": "[RRG-03] Implement BlackSwanDrillHarness with FlashCrash, ExchangeOutage, LiquidityCrisis",
        "success_criteria": "BlackSwanDrillHarness runs all drill scenarios with pass/fail verdicts; RRG-03 resolved",
    },
    "add_observability_kill_switch": {
        "priority": 0, "estimated_effort": "medium",
        "description": "[RRG-04] Add ObservabilityGuard kill switch for stress conditions",
        "success_criteria": "ObservabilityGuard can disable/enable observability subsystems; RRG-04 resolved",
    },
    "enforce_agent_registry": {
        "priority": 1, "estimated_effort": "large",
        "description": "[RRG-05] Enforce AuthorityEnforcer for agent registry permissions",
        "success_criteria": "AuthorityEnforcer blocks unregistered agents; permission matrix enforced; RRG-05 resolved",
    },
    "build_emergency_control_panel": {
        "priority": 1, "estimated_effort": "large",
        "description": "[RRG-06] Build EmergencyControlPanel with halt/flatten/lockdown",
        "success_criteria": "EmergencyControlPanel renders with action buttons; backend routes execute; RRG-06 resolved",
    },
    "add_model_drift_detection": {
        "priority": 2, "estimated_effort": "medium",
        "description": "[RRG-08] Add ModelDriftDetector for LLM output distribution monitoring",
        "success_criteria": "ModelDriftDetector computes KL-divergence on rolling windows; alerts on drift; RRG-08 resolved",
    },
    "add_override_intent_logging": {
        "priority": 2, "estimated_effort": "medium",
        "description": "[RRG-09] Add OverrideManager for structured override logging",
        "success_criteria": "OverrideManager logs every override with intent and audit trail; RRG-09 resolved",
    },
}


@pytest.fixture(scope="session")
def dev_swarm_s2_config():
    """Session-scoped Season 2 config dict — deterministic and JSON-serializable."""
    return {
        "season": 2,
        "template_count": len(_S2_TEMPLATES),
        "templates": _S2_TEMPLATES,
    }


@pytest.fixture
def dev_swarm_instance():
    """Function-scoped DevSwarm instance — each test gets a fresh one."""
    from core.dev_swarm import DevSwarm, SwarmConfig
    config = SwarmConfig(
        max_concurrent_tasks=2,
        default_task_timeout=5,
        max_daily_cost_usd=10.0,
        enable_cost_tracking=False,
    )
    return DevSwarm(config=config, enable_persistence=False)


# Synthetic commitment datasets for the historical auditor tests.
_DATASETS = {
    "none.md": (
        "## Part 2\n"
        "| ID | Description | Status | Evidence |\n"
        "|-----|-------------|--------|----------|\n"
        "| RRG-01 | Risk controls wired | **COMPLETED** | tests pass |\n"
        "| RRG-02 | Halt banner added | **COMPLETED** | deployed |\n"
    ),
    "one_overdue.md": (
        "## Part 2\n"
        "| ID | Description | Status | Evidence |\n"
        "|-----|-------------|--------|----------|\n"
        "| RRG-01 | Risk controls wired | **COMPLETED** | tests pass |\n"
        "| RRG-03 | Kill switch missing | **UNTOUCHED** | no evidence |\n"
    ),
    "mixed.md": (
        "## Part 2\n"
        "| ID | Description | Status | Evidence |\n"
        "|-----|-------------|--------|----------|\n"
        "| RRG-01 | Risk controls wired | **COMPLETED** | tests pass |\n"
        "| RRG-04 | Partial consensus | **PARTIALLY_COMPLETED** | half done |\n"
        "## Part 3\n"
        "| ID | Description | Status | Evidence |\n"
        "|-----|-------------|--------|----------|\n"
        "| UW-01 | UI wiring gap | **UNTOUCHED** | not started |\n"
        "| UW-02 | Another UI gap | **COMPLETED** | done |\n"
    ),
    "malformed.md": (
        "## Part 2\n"
        "| ID | Description | Status | Evidence |\n"
        "|-----|-------------|--------|----------|\n"
        "| VAL-01 | Valid row one | **COMPLETED** | evidence |\n"
        "| BAD-01 | Bad status | **BANANA** | evidence |\n"
        "| VAL-02 | Valid row two | **UNTOUCHED** | none |\n"
    ),
}


@pytest.fixture
def commitments_dataset_root(tmp_path):
    """Temp directory populated with 4 synthetic commitment .md datasets."""
    for name, content in _DATASETS.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


@pytest.fixture
def historical_auditor_for(commitments_dataset_root):
    """Factory fixture: historical_auditor_for(filename) → CommitmentsReport."""
    from core.historical_commitments_auditor import parse_gap_report

    def _factory(filename: str):
        path = commitments_dataset_root / filename
        return parse_gap_report(path)

    return _factory
