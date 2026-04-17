"""
Archive Import Guard — Enforcement Tests (2026-03-19)

Validates the policies defined in docs/KALSHI_WIRING_AUDIT.md §0:
  1. No KEEP/FUTURE module may import from archive/
  2. web/main.py must not import from archive/
  3. All files in archive/ must NOT be importable from the production path
  4. kalshi_shims.py must not grow beyond its known endpoint count
"""

from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT / "archive"
WEB_MAIN = ROOT / "web" / "main.py"
KALSHI_SHIMS = ROOT / "web" / "api" / "kalshi_shims.py"

# Directories that are part of the Kalshi production path
PROD_DIRS = [
    ROOT / "web",
    ROOT / "merid",
    ROOT / "core",
    ROOT / "agents",
    ROOT / "consensus",
    ROOT / "trading",
    ROOT / "notifications",
    ROOT / "monitoring",
    ROOT / "observability",
]

# Known archive subdirectories
ARCHIVE_SUBDIRS = [
    "archive",
    "archive.legacy_swarm",
    "archive.legacy_agents",
    "archive.legacy_web_services",
    "archive.deep_archive",
]

# Known endpoint count in kalshi_shims.py — all backed by real implementations:
#   POST /errors/report, GET /errors/recent, GET /errors/stats, GET /venues
KNOWN_SHIM_ENDPOINT_COUNT = 4

# Known legitimate archive imports (pre-existing, documented in audit).
# These are ALLOWED because:
#   - web/api/archive.py is the archive router — it needs to read archive/ data
#   - core/system_orchestrator.py references archive for recovery/restore ops
# New entries require a comment explaining WHY.
ALLOWED_ARCHIVE_IMPORTS: set[tuple[str, str]] = {
    ("web/api/archive.py", "archive.outcome_scoring"),
    ("web/api/archive.py", "archive.strategy_autopsy"),
    ("core/system_orchestrator.py", "archive"),
}


class TestNoArchiveImportsInProdModules(unittest.TestCase):
    """No production module may import from archive/ directories."""

    def _collect_python_files(self, directory: Path):
        """Collect all .py files in a directory, skipping __pycache__."""
        files = []
        if not directory.exists():
            return files
        for root, dirs, filenames in os.walk(directory):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in filenames:
                if f.endswith(".py"):
                    files.append(Path(root) / f)
        return files

    def _check_file_for_archive_imports(
        self, filepath: Path, *, use_allowlist: bool = True
    ) -> list[str]:
        """Check a single Python file for archive imports. Returns violations."""
        violations = []
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return violations

        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            return violations

        rel = str(filepath.relative_to(ROOT)).replace("\\", "/")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in ARCHIVE_SUBDIRS:
                        if alias.name and alias.name.startswith(prefix):
                            if use_allowlist and (rel, alias.name) in ALLOWED_ARCHIVE_IMPORTS:
                                continue
                            violations.append(
                                f"{rel}:{node.lineno} "
                                f"imports '{alias.name}'"
                            )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for prefix in ARCHIVE_SUBDIRS:
                        if node.module.startswith(prefix):
                            if use_allowlist and (rel, node.module) in ALLOWED_ARCHIVE_IMPORTS:
                                continue
                            violations.append(
                                f"{rel}:{node.lineno} "
                                f"imports from '{node.module}'"
                            )
        return violations

    def test_no_archive_imports_in_production_code(self):
        """No file in production directories may import from archive/."""
        all_violations = []
        for prod_dir in PROD_DIRS:
            for pyfile in self._collect_python_files(prod_dir):
                all_violations.extend(self._check_file_for_archive_imports(pyfile))

        if all_violations:
            msg = (
                f"Found {len(all_violations)} archive import(s) in production code:\n"
                + "\n".join(f"  - {v}" for v in all_violations[:20])
            )
            if len(all_violations) > 20:
                msg += f"\n  ... and {len(all_violations) - 20} more"
            self.fail(msg)

    def test_web_main_no_archive_imports(self):
        """web/main.py specifically must never import from archive/."""
        violations = self._check_file_for_archive_imports(WEB_MAIN)
        if violations:
            self.fail(
                f"web/main.py has archive imports:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )


class TestArchiveFilesPhysicallyMoved(unittest.TestCase):
    """Files classified as ARCHIVE in the audit must live under archive/."""

    # Known ARCHIVE files that must NOT exist in their original location
    MUST_NOT_EXIST_IN_SWARM = [
        "dev_swarm_orchestrator.py",
        "swarm_lab.py",
        "swarm_lab_orchestrator.py",
        "federated_learning.py",
        "marl_engine.py",
        "coma.py",
        "replicator.py",
        "rllib_wrapper.py",
        "sb3_wrapper.py",
        "pso_optimizer.py",
        "continuous_learning_pipeline.py",
        "sniper_scanner.py",
        "contract_scanner.py",
        "mev_rewards.py",
        "secure_yield_contracts.py",
        "zk_privacy_bridge.py",
        "gamification_swarm.py",
        "gamified_security.py",
    ]

    def test_swarm_archive_files_not_in_original_location(self):
        """ARCHIVE swarm files must not exist in swarm/ (should be in archive/legacy_swarm/)."""
        still_present = []
        swarm_dir = ROOT / "swarm"
        for filename in self.MUST_NOT_EXIST_IN_SWARM:
            if (swarm_dir / filename).exists():
                still_present.append(filename)

        if still_present:
            self.fail(
                f"{len(still_present)} ARCHIVE files still in swarm/ "
                f"(should be in archive/legacy_swarm/):\n"
                + "\n".join(f"  - swarm/{f}" for f in still_present)
            )

    def test_swarm_archive_files_exist_in_archive(self):
        """ARCHIVE swarm files must exist in archive/legacy_swarm/."""
        legacy_dir = ARCHIVE_DIR / "legacy_swarm"
        if not legacy_dir.exists():
            self.skipTest("archive/legacy_swarm/ not yet created")

        missing = []
        for filename in self.MUST_NOT_EXIST_IN_SWARM:
            if not (legacy_dir / filename).exists():
                missing.append(filename)

        if missing:
            self.fail(
                f"{len(missing)} ARCHIVE files missing from archive/legacy_swarm/:\n"
                + "\n".join(f"  - {f}" for f in missing)
            )


class TestAgentsArchiveFilesPhysicallyMoved(unittest.TestCase):
    """ARCHIVE agents/ files must live under archive/legacy_agents/."""

    MUST_NOT_EXIST_IN_AGENTS = [
        "agent_mesh.py",
        "mesh.py",
        "crypto_prediction_agent.py",
        "prediction_arbitrage_analyst.py",
        "fast_prediction_arbitrage_analyst.py",
        "governor_agent.py",
        "human_collaboration_ux.py",
        "llm_roles.py",
        "swarm_coordination.py",
        "swarm_mixin.py",
        "unified_decision_layer.py",
    ]

    def test_agents_archive_files_not_in_original_location(self):
        """ARCHIVE agent files must not exist in agents/."""
        agents_dir = ROOT / "agents"
        still_present = [f for f in self.MUST_NOT_EXIST_IN_AGENTS if (agents_dir / f).exists()]
        if still_present:
            self.fail(
                f"{len(still_present)} ARCHIVE files still in agents/ "
                f"(should be in archive/legacy_agents/):\n"
                + "\n".join(f"  - agents/{f}" for f in still_present)
            )

    def test_agents_archive_files_exist_in_archive(self):
        """ARCHIVE agent files must exist in archive/legacy_agents/."""
        legacy_dir = ARCHIVE_DIR / "legacy_agents"
        if not legacy_dir.exists():
            self.skipTest("archive/legacy_agents/ not yet created")
        missing = [f for f in self.MUST_NOT_EXIST_IN_AGENTS if not (legacy_dir / f).exists()]
        if missing:
            self.fail(
                f"{len(missing)} ARCHIVE files missing from archive/legacy_agents/:\n"
                + "\n".join(f"  - {f}" for f in missing)
            )


class TestWebServicesArchiveFilesPhysicallyMoved(unittest.TestCase):
    """ARCHIVE web/services/ files must live under archive/legacy_web_services/."""

    MUST_NOT_EXIST_IN_WEB_SERVICES = [
        "price_publisher.py",
        "portfolio_publisher.py",
    ]

    def test_web_services_archive_files_not_in_original_location(self):
        """ARCHIVE web/services files must not exist in web/services/."""
        ws_dir = ROOT / "web" / "services"
        still_present = [f for f in self.MUST_NOT_EXIST_IN_WEB_SERVICES if (ws_dir / f).exists()]
        if still_present:
            self.fail(
                f"{len(still_present)} ARCHIVE files still in web/services/ "
                f"(should be in archive/legacy_web_services/):\n"
                + "\n".join(f"  - web/services/{f}" for f in still_present)
            )

    def test_web_services_archive_files_exist_in_archive(self):
        """ARCHIVE web/services files must exist in archive/legacy_web_services/."""
        legacy_dir = ARCHIVE_DIR / "legacy_web_services"
        if not legacy_dir.exists():
            self.skipTest("archive/legacy_web_services/ not yet created")
        missing = [f for f in self.MUST_NOT_EXIST_IN_WEB_SERVICES if not (legacy_dir / f).exists()]
        if missing:
            self.fail(
                f"{len(missing)} ARCHIVE files missing from archive/legacy_web_services/:\n"
                + "\n".join(f"  - {f}" for f in missing)
            )


class TestKalshiOnlyRouterGating(unittest.TestCase):
    """FUTURE routers must be gated behind `not _kalshi_only` in web/main.py."""

    # Routers that must be inside a `not _kalshi_only` block
    MUST_BE_GATED = [
        "streams_router",
        "data_endpoints_router",
        "live_stream_router",
        "schemas_router",
        "offline_router",
        "notifications_router",
        "compliance_router",
        "backup_router",
        "recovery_router",
        "reflection_router",
        "governance_router",
        "ops_router",
        "archive_router",
        "live_data_router",
        "domain_priority_router",
        "predictions_router",
        "betting_consensus_router",
        "flow_router",
        "signal_layer_router",
        "unified_pipeline_router",
        "dev_swarm_router",
    ]

    def test_future_routers_are_gated(self):
        """All FUTURE routers must be registered inside `if not _kalshi_only:` blocks."""
        try:
            source = WEB_MAIN.read_text(encoding="utf-8", errors="replace")
        except Exception:
            self.skipTest("Could not read web/main.py")

        ungated = []
        lines = source.splitlines()

        for router_name in self.MUST_BE_GATED:
            # Find all lines that register this router
            pattern = re.compile(rf"_reg\(\s*{re.escape(router_name)}\s*[,)]")
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    # Check if it's indented (inside an if block)
                    stripped = line.lstrip()
                    indent = len(line) - len(stripped)
                    if indent < 8:  # less than 2 levels of indent (4+4)
                        ungated.append(f"  line {i}: {router_name}")

        if ungated:
            self.fail(
                f"{len(ungated)} FUTURE router(s) not gated behind "
                f"`not _kalshi_only`:\n" + "\n".join(ungated)
            )


class TestShimSurfaceNotGrowing(unittest.TestCase):
    """kalshi_shims.py must not grow beyond its known endpoint count."""

    def test_shim_endpoint_count(self):
        """kalshi_shims.py must have <= KNOWN_SHIM_ENDPOINT_COUNT endpoints."""
        try:
            source = KALSHI_SHIMS.read_text(encoding="utf-8", errors="replace")
        except Exception:
            self.skipTest("Could not read kalshi_shims.py")

        # Count @router.get/post/put/delete/patch decorators
        endpoint_pattern = re.compile(
            r"@router\.(get|post|put|delete|patch)\("
        )
        count = len(endpoint_pattern.findall(source))

        self.assertLessEqual(
            count,
            KNOWN_SHIM_ENDPOINT_COUNT,
            f"kalshi_shims.py has {count} endpoints (max allowed: "
            f"{KNOWN_SHIM_ENDPOINT_COUNT}). Policy: no new shims — add "
            f"endpoints to their owning router instead. If you promoted a "
            f"shim, decrease KNOWN_SHIM_ENDPOINT_COUNT in this test.",
        )


class TestNoArchiveInKalshiRouters(unittest.TestCase):
    """Kalshi-critical routers must not import from archive/."""

    KALSHI_ROUTERS = [
        ROOT / "web" / "api" / "kalshi_api.py",
        ROOT / "web" / "api" / "kalshi_grid_api.py",
        ROOT / "web" / "api" / "kalshi_ui.py",
        ROOT / "web" / "api" / "kalshi_shims.py",
        ROOT / "web" / "api" / "kalshi_agent_grid_api.py",
        ROOT / "web" / "api" / "kalshi_agent_performance_api.py",
        ROOT / "web" / "api" / "kalshi_deployment.py",
        ROOT / "web" / "api" / "kalshi_metrics_api.py",
    ]

    def test_kalshi_routers_clean(self):
        """Kalshi-critical router files must not import from archive/."""
        guard = TestNoArchiveImportsInProdModules()
        all_violations = []
        for router_file in self.KALSHI_ROUTERS:
            if router_file.exists():
                all_violations.extend(
                    guard._check_file_for_archive_imports(router_file)
                )

        if all_violations:
            self.fail(
                f"Kalshi router(s) import from archive/:\n"
                + "\n".join(f"  - {v}" for v in all_violations)
            )


if __name__ == "__main__":
    unittest.main()
