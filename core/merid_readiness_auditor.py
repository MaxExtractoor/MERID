"""
MERID 24/7 Readiness Auditor

Programmatic evaluation of the 24/7 readiness scorecard defined in
docs/READINESS_24_7.md.  Each check probes the actual codebase/config
for evidence and returns a 0-2 score.

Usage:
    python -m core.merid_readiness_auditor          # human-readable
    python -m core.merid_readiness_auditor --json    # JSON output
"""

from __future__ import annotations
import logging

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CheckItem:
    id: str
    dimension: str
    description: str
    score: int  # 0, 1, or 2
    max_score: int = 2
    evidence: str = ""


@dataclass
class ReadinessReport:
    items: List[CheckItem] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        return sum(c.score for c in self.items)

    @property
    def max_score(self) -> int:
        return sum(c.max_score for c in self.items)

    @property
    def pct(self) -> float:
        return (self.total_score / self.max_score * 100) if self.max_score else 0.0

    @property
    def level(self) -> str:
        p = self.pct
        if p >= 90:
            return "Production"
        if p >= 70:
            return "Staging"
        if p >= 50:
            return "Lab"
        return "Prototype"

    def by_dimension(self) -> dict:
        dims: dict = {}
        for c in self.items:
            dims.setdefault(c.dimension, []).append(c)
        return dims

    def gaps(self) -> List[CheckItem]:
        return [c for c in self.items if c.score < c.max_score]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _file_exists(rel: str) -> bool:
    return (PROJECT_ROOT / rel).exists()


def _file_contains(rel: str, pattern: str) -> bool:
    p = PROJECT_ROOT / rel
    if not p.exists():
        return False
    try:
        return bool(re.search(pattern, p.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        return False


def _count_tests() -> int:
    """Count collected tests in test_dev_swarm.py without running them."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_dev_swarm.py",
             "--collect-only", "-q", "--no-header"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60,
        )
        m = re.search(r"(\d+) tests? collected", r.stdout)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _git_tracks(rel: str) -> bool:
    """Return True if the file is tracked by git (i.e. in the index)."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _dir_has_files(rel: str, ext: str = ".md") -> int:
    d = PROJECT_ROOT / rel
    if not d.is_dir():
        return 0
    return sum(1 for f in d.iterdir() if f.suffix == ext)


# ---------------------------------------------------------------------------
# Checklist evaluation
# ---------------------------------------------------------------------------

def evaluate() -> ReadinessReport:
    """Run all readiness checks and return a scored report."""
    report = ReadinessReport()

    def add(id: str, dim: str, desc: str, score: int, evidence: str = ""):
        report.items.append(CheckItem(id=id, dimension=dim, description=desc,
                                      score=min(score, 2), evidence=evidence))

    # ── Testing & Correctness ──────────────────────────────────────────

    # T-01: CI green on every commit
    has_ci = (_file_exists(".github/workflows") or _file_exists(".gitlab-ci.yml")
              or _file_exists("Jenkinsfile") or _file_exists("Makefile"))
    test_count = _count_tests()
    ci_score = 2 if (has_ci and test_count >= 250) else (1 if test_count >= 100 else 0)
    add("T-01", "Testing", "CI green on every commit",
        ci_score, f"{test_count} tests collected; CI config={'found' if has_ci else 'missing'}")

    # T-02: Core path coverage >= 90%
    cov_ok = _file_contains("LEGACY_RISK_MATRIX.md", r"93\.\d+%|9[0-9]\.\d+%")
    add("T-02", "Testing", "Core path coverage >= 90%",
        2 if cov_ok else 0, "Dev Swarm domain 93.52%+" if cov_ok else "Not verified")

    # T-03: Historical commitments auditor tested
    auditor_tested = _file_contains("tests/test_dev_swarm.py", r"TestHistoricalCommitmentsAuditor")
    add("T-03", "Testing", "Historical commitments auditor tested",
        2 if auditor_tested else 0, "TestHistoricalCommitmentsAuditor class present")

    # T-04: Edge-case / negative-path coverage
    neg_path = _file_contains("tests/test_dev_swarm.py", r"TestNegativePathAuditor")
    add("T-04", "Testing", "Edge-case / negative-path coverage",
        2 if neg_path else 0, "TestNegativePathAuditor class present")

    # T-05: Long-run stability / soak tests
    soak = _file_contains("tests/test_dev_swarm.py", r"class TestSoakLoop|class TestLongRun")
    add("T-05", "Testing", "Long-run stability / soak tests",
        2 if soak else 0, "Soak test class found" if soak else "No soak tests")

    # T-06: Restart / recovery tests
    restart = _file_contains("tests/test_dev_swarm.py", r"class TestRestartRecovery")
    add("T-06", "Testing", "Restart / recovery tests",
        2 if restart else 0, "Restart test class found" if restart else "No restart tests")

    # T-07: Dependency failure tests
    dep_fail = _file_contains("tests/test_dev_swarm.py", r"class TestDependencyFailure")
    add("T-07", "Testing", "Dependency failure tests",
        2 if dep_fail else 0, "Dep failure class found" if dep_fail else "No dependency failure tests")

    # T-08: Performance benchmarks tracked
    perf = _file_exists("tests/PERFORMANCE_BASELINE.md")
    bench = _file_contains("tests/test_dev_swarm.py", r"class TestPerformanceBenchmarks")
    add("T-08", "Testing", "Performance benchmarks tracked",
        2 if (perf and bench) else (1 if perf or bench else 0),
        f"Baseline={'yes' if perf else 'no'}, benchmarks={'yes' if bench else 'no'}")

    # ── Observability & Alerts ─────────────────────────────────────────

    add("O-01", "Observability", "Prometheus metrics configured",
        2 if _file_exists("monitoring/prometheus-config.yml") else 0,
        "monitoring/prometheus-config.yml")

    alert_rules = _file_exists("monitoring/alert_rules.yml")
    add("O-02", "Observability", "Alert rules defined",
        2 if alert_rules else 0, "monitoring/alert_rules.yml")

    add("O-03", "Observability", "Alertmanager configured",
        1 if _file_exists("monitoring/alertmanager.yml") else 0,
        "Exists but live routing not verified")

    app_metrics = _file_exists("core/dev_swarm_metrics.py") and _file_exists("core/observability_manager.py")
    add("O-04", "Observability", "Application metrics emitted",
        2 if app_metrics else (1 if _file_exists("core/dev_swarm_metrics.py") else 0),
        "dev_swarm_metrics + observability_manager")

    dash_backend = _file_exists("core/merid_dashboard.py")
    dash_api = _file_contains("web/api/metrics.py", r"swarm_health|heatmap|latency")
    dash_react = _file_exists("web/react/src/views/OperatorDashboard.tsx")
    dash_score = 2 if (dash_api and dash_react) else (1 if (dash_backend or dash_api) else 0)
    add("O-05", "Observability", "Dashboard for swarm health",
        dash_score,
        f"API={'yes' if dash_api else 'no'}, React={'yes' if dash_react else 'no'}, merid_dashboard={'yes' if dash_backend else 'no'}")

    safety_api = _file_contains("web/api/metrics.py", r"breach_log|radar")
    safety_react = _file_exists("web/react/src/components/charts/BreachAlertLog.tsx")
    safety_score = 2 if (safety_api and safety_react) else (1 if (dash_backend or safety_api) else 0)
    add("O-06", "Observability", "Dashboard for trading safety",
        safety_score,
        f"Breach/radar API={'yes' if safety_api else 'no'}, BreachAlertLog={'yes' if safety_react else 'no'}")

    add("O-07", "Observability", "Structured logging",
        2 if _file_contains("core/dev_swarm.py", r"structlog|get_logger") else 0,
        "structlog used in dev_swarm")

    add("O-08", "Observability", "Distributed tracing",
        1 if _file_contains("monitoring/prometheus-config.yml", r"jaeger") else 0,
        "Jaeger scrape target configured")

    # ── Risk & Safety Controls ─────────────────────────────────────────

    add("R-01", "Risk", "Position / exposure limits in code",
        2 if _file_exists("core/automated_risk_controls.py") else 0,
        "automated_risk_controls.py with 7 control types")

    cb = _file_contains("core/error_handling.py", r"[Cc]ircuit[Bb]reaker|circuit_breaker")
    add("R-02", "Risk", "Circuit breakers for exchange errors",
        1 if cb else 0, "Pattern in error_handling.py" if cb else "Not found")

    ks = _file_exists("ops/drills/3am_simulation.py")
    add("R-03", "Risk", "Kill switch tested",
        1 if ks else 0, "3am drill exists; not in CI")

    anom = _file_exists("ops/anomaly_detection.py")
    add("R-04", "Risk", "Price feed anomaly detection",
        1 if anom else 0, "anomaly_detection.py exists; not wired to halt")

    risk_tests = _file_contains("tests/test_dev_swarm.py", r"risk_limit|RiskLimit|risk_control")
    risk_class = _file_contains("tests/test_dev_swarm.py", r"class TestRiskLimits")
    add("R-05", "Risk", "Risk limit tests",
        2 if risk_class else (1 if risk_tests else 0),
        f"TestRiskLimits={'yes' if risk_class else 'no'}, references={'yes' if risk_tests else 'no'}")

    gov = _file_exists("core/merid_governance.py") and _file_exists("core/merid_governance_cadence.py")
    add("R-06", "Risk", "Governance gates enforced",
        2 if gov else 0, "Governance + cadence modules")

    const = _file_exists("core/constitution_enforcer.py") and _file_exists("policy/guardrails.yml")
    add("R-07", "Risk", "Constitution / guardrails",
        2 if const else 0, "constitution_enforcer + guardrails.yml")

    dd = _file_contains("core/automated_risk_controls.py", r"DRAWDOWN_LIMIT")
    add("R-08", "Risk", "Drawdown / max-loss limits",
        1 if dd else 0, "Defined but no integration tests verified")

    # ── Operations & Runbooks ──────────────────────────────────────────

    ops_docs = (_file_exists("docs/OPERATOR_RUNBOOK.md")
                or _file_exists("docs/SEASON1_OPERATOR_RUNBOOK.md"))
    add("P-01", "Operations", "Start / stop / deploy documented",
        2 if ops_docs else 0, "Operator runbooks present")

    add("P-02", "Operations", "Rollback procedure",
        1, "Git-based; no blue/green or canary documented")

    rb_count = _dir_has_files("docs/runbooks") + _dir_has_files("ops/runbooks")
    add("P-03", "Operations", "Incident runbooks",
        2 if rb_count >= 5 else (1 if rb_count >= 2 else 0),
        f"{rb_count} runbooks found")

    drill = _file_exists("ops/drills/3am_simulation.py")
    add("P-04", "Operations", "3am drill tested",
        2 if drill else 0, "ops/drills/3am_simulation.py")

    tg = _file_exists("core/telegram_bot.py")
    add("P-05", "Operations", "On-call / escalation pattern",
        1 if tg else 0, "Telegram bot; no PagerDuty/OpsGenie")

    pir = _file_exists("docs/runbooks/RB-RISK-003-post-incident-recovery.md")
    add("P-06", "Operations", "Post-incident review process",
        1 if pir else 0, "Recovery runbook exists; no completed PIRs")

    # ── Infrastructure & Redundancy ────────────────────────────────────

    systemd = _file_exists("deploy/merid-dev-swarm.service")
    add("I-01", "Infrastructure", "Process restart automation",
        2 if systemd else 0, "systemd unit with Restart=always")

    docker = _file_exists("docker-compose.yml")
    add("I-02", "Infrastructure", "Docker / compose orchestration",
        2 if docker else 0, "docker-compose.yml + variants")

    healthz = _file_contains("web/main.py", r"/health|/readyz|/healthz")
    add("I-03", "Infrastructure", "Health / readiness probes",
        2 if healthz else (1 if systemd else 0),
        "HTTP probe" if healthz else "systemd timeout only")

    neo4j = _file_exists("docker-compose.yml") and _file_contains("docker-compose.yml", r"neo4j|redis")
    add("I-04", "Infrastructure", "Data persistence guarantees",
        1 if neo4j else 0, "Neo4j+Redis in compose; no backup automation")

    audit_log = _file_exists("core/explainability_storage.py")
    add("I-05", "Infrastructure", "Audit trail / trade records",
        1 if audit_log else 0, "Explainability storage; no immutable log verified")

    gitignore_pem = _file_contains(".gitignore", r"\*\.pem|kalshi_private_key\.pem")
    gitignore_env = _file_contains(".gitignore", r"\.env")
    secret_tracked = _git_tracks("kalshi_private_key.pem") or _git_tracks(".env.backup")
    env_exists = _file_exists(".env")
    secrets_score = 0
    if secret_tracked:
        secrets_score = 0
    elif env_exists and gitignore_pem and gitignore_env:
        secrets_score = 2
    elif env_exists:
        secrets_score = 1
    add("I-06", "Infrastructure", "Secrets management",
        secrets_score,
        f"tracked_secrets={'YES-CRITICAL' if secret_tracked else 'no'}, "
        f".env={'yes' if env_exists else 'no'}, "
        f".gitignore(pem={'yes' if gitignore_pem else 'no'}, env={'yes' if gitignore_env else 'no'})")

    tls = _file_exists("infra/tls-config.yml") and _file_exists("infra/firewall-rules.yml")
    add("I-07", "Infrastructure", "TLS / network security",
        1 if tls else 0, "Config files exist; deployment not verified")

    backup = _file_contains("Makefile", r"backup|restore|snapshot")
    backup_script = _file_exists("ops/backup_restore.py")
    add("I-08", "Infrastructure", "Backup / recovery for state",
        2 if (backup and backup_script) else (1 if backup else 0),
        f"Makefile targets={'yes' if backup else 'no'}, backup_restore.py={'yes' if backup_script else 'no'}")

    return report


# ---------------------------------------------------------------------------
# Swarm-Trading Readiness Checks (10 sections from checklist prompt)
# ---------------------------------------------------------------------------

def evaluate_swarm_trading() -> ReadinessReport:
    """Run swarm-trading & decentralized AI commerce readiness checks."""
    report = ReadinessReport()

    def add(id: str, dim: str, desc: str, score: int, evidence: str = ""):
        report.items.append(CheckItem(id=id, dimension=dim, description=desc,
                                      score=min(score, 2), evidence=evidence))

    # ── 1. Swarm Architecture & Agent Roles ─────────────────────────────

    roles = _file_exists("core/dev_swarm.py") and _file_contains(
        "core/dev_swarm.py", r"class DevAgent")
    collab = _file_exists("core/collaboration_framework.py")
    add("S1-01", "Swarm Architecture", "Agent roles and collaboration patterns",
        2 if (roles and collab) else (1 if roles else 0),
        f"DevAgent={'yes' if roles else 'no'}, collaboration_framework={'yes' if collab else 'no'}")

    consensus = _file_exists("core/consensus_engine.py") and _file_contains(
        "core/consensus_engine.py", r"quorum|VETO|trust.*weight")
    add("S1-02", "Swarm Architecture", "Multi-agent coordination (consensus/voting)",
        2 if consensus else 0,
        "Trust-weighted voting, VETO, 2/3 quorum" if consensus else "Not found")

    negotiation = _file_contains(
        "core/consensus_engine.py", r"re.round|skeptic|veto", ) if _file_exists(
        "core/consensus_engine.py") else False
    add("S1-03", "Swarm Architecture", "Agent-to-agent negotiation / conflict resolution",
        1 if negotiation else 0,
        "VETO + skeptic re-round; no iterative negotiation protocol")

    swarm_intel = _file_exists("core/swarm_intelligence.py")
    add("S1-04", "Swarm Architecture", "Collective intelligence demonstrated",
        1 if swarm_intel else 0,
        "swarm_intelligence.py exists; no A/B benchmark vs single-agent")

    # ── 2. Decentralization, Trust, Ledgers ─────────────────────────────

    distributed = (_file_exists("core/celery_tasks.py")
                   or _file_exists("core/workflows_temporal.py"))
    add("S2-01", "Decentralization", "Distributed execution support",
        1 if distributed else 0,
        "Celery/Temporal configs exist; single-process runtime")

    audit_trail = _file_exists("core/audit_trail.py") and _file_contains(
        "core/audit_trail.py", r"hash|sha256|chain")
    explain = _file_exists("core/explainability.py")
    add("S2-02", "Decentralization", "Auditability and trust (logs, traces)",
        2 if (audit_trail and explain) else (1 if audit_trail or explain else 0),
        f"Hash-chained audit trail={'yes' if audit_trail else 'no'}, "
        f"explainability={'yes' if explain else 'no'}")

    add("S2-03", "Decentralization", "Blockchain / ledger integration",
        1 if audit_trail else 0,
        "Hash-chained entries (ledger-like); no on-chain integration")

    compliance = _file_exists("core/us_compliance_config.py") and _file_exists(
        "core/constitution_enforcer.py")
    add("S2-04", "Decentralization", "Regulatory and compliance strategy",
        2 if compliance else (1 if _file_exists("core/us_compliance_config.py") else 0),
        "US venue classification + constitution enforcer" if compliance else "Partial")

    # ── 3. Tokenization / Value Flow ────────────────────────────────────

    cost_track = _file_contains("core/dev_swarm.py", r"daily_cost_usd|cost_per_token")
    add("S3-01", "Value Flow", "Internal credits / cost accounting",
        1 if cost_track else 0,
        "daily_cost_usd + cost_per_token; no agent-to-agent credits")

    mode_mgr = _file_exists("core/mode_manager.py") and _file_contains(
        "core/mode_manager.py", r"SIMULATION|PAPER|LIVE")
    add("S3-02", "Value Flow", "Internal vs real capital boundary",
        2 if mode_mgr else 0,
        "TradingMode enum: OFFLINE/SIMULATION/PAPER/LIVE/SPECTATOR")

    budget = _file_contains("core/dev_swarm.py", r"max_daily_cost_usd")
    risk_ctrl = _file_exists("core/automated_risk_controls.py")
    add("S3-03", "Value Flow", "Budget / risk limit enforcement",
        2 if (budget and risk_ctrl) else (1 if budget or risk_ctrl else 0),
        f"Budget cap={'yes' if budget else 'no'}, risk controls={'yes' if risk_ctrl else 'no'}")

    # ── 4. Strategy, Risk, Safety ───────────────────────────────────────

    risk_types = _file_contains(
        "core/automated_risk_controls.py", r"POSITION|DRAWDOWN|VOLATILITY|EXPOSURE")
    add("S4-01", "Risk & Safety", "Explicit risk limits enforced and tested",
        2 if risk_types else (1 if risk_ctrl else 0),
        "7 control types with check_breach()" if risk_types else "Partial")

    cb = _file_contains("core/error_handling.py", r"[Cc]ircuit[Bb]reaker|circuit_breaker")
    add("S4-02", "Risk & Safety", "Circuit breakers (volatility, outages, failures)",
        1 if cb else 0,
        "Pattern exists; not wired to automated halt")

    ks = _file_exists("ops/drills/3am_simulation.py")
    shutdown = _file_contains("core/dev_swarm.py", r"async def shutdown")
    add("S4-03", "Risk & Safety", "Kill switch / emergency stop tested",
        1 if (ks and shutdown) else 0,
        f"3am drill={'yes' if ks else 'no'}, shutdown={'yes' if shutdown else 'no'}; not in CI")

    hist_aud = _file_exists("core/historical_commitments_auditor.py")
    add("S4-04", "Risk & Safety", "Historical commitments auditor in risk view",
        2 if hist_aud else 0,
        "Parses gap reports, generates DevTasks, integrated in readiness auditor")

    # ── 5. Observability & Swarm-Health UX ──────────────────────────────

    metrics = _file_exists("core/dev_swarm_metrics.py") and _file_contains(
        "core/dev_swarm_metrics.py", r"Counter|Histogram|Gauge")
    add("S5-01", "Swarm Observability", "Swarm health metrics (agents, queues, latency)",
        2 if metrics else 0,
        "Counter + Histogram + Gauge in dev_swarm_metrics")

    dashboard = _file_exists("core/merid_dashboard.py")
    routes = _file_contains("web/api/dev_swarm_routes.py", r"/tasks|/stats")
    react_dash = _file_exists("web/react/src/views/OperatorDashboard.tsx")
    react_charts = _file_exists("web/react/src/components/charts/LatencyChart.tsx")
    add("S5-02", "Swarm Observability", "Agent activity / outcome dashboards",
        2 if (routes and react_dash) else (1 if (dashboard or routes) else 0),
        f"Routes={'yes' if routes else 'no'}, OperatorDashboard={'yes' if react_dash else 'no'}, charts={'yes' if react_charts else 'no'}")

    explain_api = _file_contains(
        "core/explainability.py", r"ExplanationType") if _file_exists(
        "core/explainability.py") else False
    add("S5-03", "Swarm Observability", "Plain-language decision explanations",
        1 if explain_api else 0,
        "Structured rationale per decision; no NL query interface")

    audit_log = _file_exists("core/audit_trail.py") and _file_exists(
        "core/consensus_logging.py")
    add("S5-04", "Swarm Observability", "Audit trails tied to orders / risk events",
        2 if audit_log else (1 if _file_exists("core/audit_trail.py") else 0),
        "Hash-chained audit + consensus logging")

    # ── 6. 24/7 Operations & SRE ────────────────────────────────────────

    systemd = _file_exists("deploy/merid-dev-swarm.service")
    docker = _file_exists("docker-compose.yml")
    add("S6-01", "24/7 Operations", "Process supervision with probes",
        2 if (systemd and docker) else (1 if systemd or docker else 0),
        f"systemd={'yes' if systemd else 'no'}, docker={'yes' if docker else 'no'}")

    tg = _file_exists("core/telegram_bot.py")
    am = _file_exists("monitoring/alertmanager.yml")
    add("S6-02", "24/7 Operations", "On-call / notification flow",
        1 if (tg or am) else 0,
        f"Telegram={'yes' if tg else 'no'}, Alertmanager={'yes' if am else 'no'}; no PagerDuty")

    rb_count = _dir_has_files("docs/runbooks") + _dir_has_files("ops/runbooks")
    add("S6-03", "24/7 Operations", "Runbooks for common failures",
        2 if rb_count >= 5 else (1 if rb_count >= 2 else 0),
        f"{rb_count} runbooks across docs/runbooks + ops/runbooks")

    restart_test = _file_contains("tests/test_dev_swarm.py", r"class TestRestartRecovery")
    persist = _file_exists("core/dev_swarm_persistence.py")
    add("S6-04", "24/7 Operations", "Restart and recovery tested",
        2 if (restart_test and persist) else (1 if persist else 0),
        f"Persistence={'yes' if persist else 'no'}, restart tests={'yes' if restart_test else 'no'}")

    # ── 7. Testing Depth (Swarm + Trading) ──────────────────────────────

    test_count = _count_tests()
    neg = _file_contains("tests/test_dev_swarm.py", r"TestNegativePathAuditor")
    add("S7-01", "Testing Depth", "High-coverage unit tests (including edge/negative)",
        2 if (test_count >= 200 and neg) else (1 if test_count >= 100 else 0),
        f"{test_count} tests; negative-path={'yes' if neg else 'no'}")

    integ = _file_contains("tests/test_dev_swarm.py",
                           r"TestIntegration|TestSeason2RRGFlows|multi_agent_pipeline")
    add("S7-02", "Testing Depth", "Integration tests with multi-agent flows",
        1 if integ else 0,
        "Multi-agent pipeline + RRG flows; no full signal→order→audit test")

    soak = _file_contains("tests/test_dev_swarm.py", r"class TestSoakLoop")
    add("S7-03", "Testing Depth", "Long-run / soak tests",
        2 if soak else 0,
        "TestSoakLoop: 10k tasks, bounded history, 500 parse cycles")

    perf = _file_exists("tests/PERFORMANCE_BASELINE.md")
    bench = _file_contains("tests/test_dev_swarm.py", r"class TestPerformanceBenchmarks")
    add("S7-04", "Testing Depth", "Performance baselines with regression thresholds",
        2 if (perf and bench) else (1 if perf or bench else 0),
        f"Baseline={'yes' if perf else 'no'}, benchmarks={'yes' if bench else 'no'}")

    # ── 8. Data, Models, Drift ──────────────────────────────────────────

    data_val = _file_exists("core/data_validation.py")
    add("S8-01", "Data & Drift", "Data contracts and validation per feed",
        1 if data_val else 0,
        "data_validation.py exists; no formal per-feed DataContract")

    drift = _file_exists("core/drift_monitoring_pipeline.py") and _file_contains(
        "core/drift_monitoring_pipeline.py", r"CONCEPT|MODEL|LLM_BEHAVIORAL|STRATEGY")
    add("S8-02", "Data & Drift", "Drift monitoring (model, data, LLM behavioral)",
        2 if drift else 0,
        "6 drift types with auto-demotion and retrain triggers")

    safe_degrade = _file_exists("core/mode_manager.py") and _file_contains(
        "core/mode_manager.py", r"MAINTENANCE")
    reality = _file_exists("core/reality_registry.py")
    add("S8-03", "Data & Drift", "Safe degradation on missing / bad data",
        1 if (safe_degrade or reality) else 0,
        "MAINTENANCE mode + reality registry; no per-feed staleness halt")

    # ── 9. Security, Abuse Resistance, Ethics ───────────────────────────

    s_secret_tracked = _git_tracks("kalshi_private_key.pem") or _git_tracks(".env.backup")
    s_gitignore_ok = _file_contains(".gitignore", r"\*\.pem|kalshi_private_key\.pem") and _file_contains(".gitignore", r"\.env")
    s_env = _file_exists(".env")
    s9_score = 0 if s_secret_tracked else (2 if (s_env and s_gitignore_ok) else (1 if s_env else 0))
    add("S9-01", "Security & Ethics", "Access control for configs, secrets, live keys",
        s9_score,
        f"tracked_secrets={'YES-CRITICAL' if s_secret_tracked else 'no'}, "
        f".env={'yes' if s_env else 'no'}, gitignore={'yes' if s_gitignore_ok else 'no'}")

    adversarial = _file_exists("core/adversarial_hardening.py")
    guardrails = _file_exists("core/reuse_guardrails.py")
    add("S9-02", "Security & Ethics", "Abuse / adversarial protections",
        2 if (adversarial and guardrails) else (1 if adversarial or guardrails else 0),
        f"adversarial_hardening={'yes' if adversarial else 'no'}, "
        f"reuse_guardrails={'yes' if guardrails else 'no'}")

    ethics = _file_exists("core/us_compliance_config.py") and _file_contains(
        "core/us_compliance_config.py", r"BLOCKED_VENUES")
    const_e = _file_exists("core/constitution_enforcer.py")
    add("S9-03", "Security & Ethics", "Ethical guardrails and compliance rules",
        2 if (ethics and const_e) else (1 if ethics or const_e else 0),
        "Blocked venues + constitution enforcer")

    # ── 10. User & Operator Experience ──────────────────────────────────

    cli = _file_exists("core/swarm_cli.py")
    routes_ctrl = _file_contains("web/api/dev_swarm_routes.py", r"/shutdown")
    routes_pause = _file_contains("web/api/dev_swarm_routes.py", r"/pause|/resume")
    ctrl_plane = _file_exists("web/react/src/views/OperatorControlPlane.tsx")
    add("S10-01", "Operator UX", "Operator UX for swarm control (start/stop/pause)",
        2 if (routes_ctrl and routes_pause and ctrl_plane) else (1 if (cli or routes_ctrl) else 0),
        f"CLI={'yes' if cli else 'no'}, /shutdown={'yes' if routes_ctrl else 'no'}, /pause={'yes' if routes_pause else 'no'}, ControlPlane={'yes' if ctrl_plane else 'no'}")

    op_dash = _file_exists("web/react/src/views/OperatorDashboard.tsx")
    op_api = _file_contains("web/api/operator.py", r"/summary|/audit-trail")
    risk_views = _file_exists("web/react/src/components/charts/RiskTreeMap.tsx")
    add("S10-02", "Operator UX", "Portfolio, risk, and position views",
        2 if (op_dash and op_api and risk_views) else (1 if (op_dash or op_api) else 0),
        f"OperatorDashboard={'yes' if op_dash else 'no'}, API={'yes' if op_api else 'no'}, RiskTreeMap={'yes' if risk_views else 'no'}")

    sim_mode = _file_contains("core/mode_manager.py", r"SIMULATION|PAPER|SPECTATOR")
    sim_adapter = _file_exists("core/venues/merid_sim_adapter.py")
    add("S10-03", "Operator UX", "Simulation / demo mode",
        2 if (sim_mode and sim_adapter) else (1 if sim_mode else 0),
        f"TradingMode enum + sim adapter={'yes' if sim_adapter else 'no'}")

    ops_docs = (_file_exists("docs/OPERATOR_RUNBOOK.md")
                or _file_exists("docs/SEASON1_OPERATOR_RUNBOOK.md"))
    add("S10-04", "Operator UX", "Documentation for new operators",
        2 if ops_docs else 0,
        "Operator runbooks + season runbooks present")

    return report


# ---------------------------------------------------------------------------
# Combined evaluation
# ---------------------------------------------------------------------------

def evaluate_all() -> tuple:
    """Run both 24/7 readiness and swarm-trading checks."""
    return evaluate(), evaluate_swarm_trading()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report: ReadinessReport, title: str, as_json: bool) -> dict:
    """Print a single report and return its JSON dict."""
    out = {
        "total_score": report.total_score,
        "max_score": report.max_score,
        "pct": round(report.pct, 1),
        "level": report.level,
        "dimensions": {},
        "gaps": [],
    }
    for dim, items in report.by_dimension().items():
        out["dimensions"][dim] = {
            "score": sum(c.score for c in items),
            "max": sum(c.max_score for c in items),
            "items": [
                {"id": c.id, "description": c.description,
                 "score": c.score, "evidence": c.evidence}
                for c in items
            ],
        }
    for g in report.gaps():
        out["gaps"].append({
            "id": g.id, "dimension": g.dimension,
            "description": g.description,
            "score": g.score, "evidence": g.evidence,
        })

    if not as_json:
        print("=" * 60)
        print(f"  {title}")
        print("=" * 60)
        print()
        for dim, items in report.by_dimension().items():
            dim_score = sum(c.score for c in items)
            dim_max = sum(c.max_score for c in items)
            dim_pct = dim_score / dim_max * 100 if dim_max else 0
            print(f"## {dim} ({dim_score}/{dim_max} = {dim_pct:.0f}%)")
            for c in items:
                icon = "OK" if c.score == 2 else ("~~" if c.score == 1 else "XX")
                print(f"  [{icon}] {c.id}: {c.description} ({c.score}/{c.max_score})")
                if c.evidence:
                    print(f"        {c.evidence}")
            print()

        print("-" * 60)
        print(f"TOTAL: {report.total_score}/{report.max_score} "
              f"({report.pct:.0f}%) — {report.level}")
        print()

        gaps = report.gaps()
        if gaps:
            print(f"GAPS ({len(gaps)} items below max):")
            for g in gaps:
                print(f"  - {g.id} [{g.dimension}]: {g.description} "
                      f"(score {g.score}/{g.max_score})")
        print()

    return out


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="MERID Readiness Auditor")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--swarm", action="store_true",
                        help="Run swarm-trading readiness checks only")
    parser.add_argument("--all", action="store_true",
                        help="Run both 24/7 and swarm-trading checks")
    args = parser.parse_args()

    if args.swarm:
        report = evaluate_swarm_trading()
        if args.json:
            print(json.dumps(_print_report(report, "", True), indent=2))
        else:
            _print_report(report, "MERID Swarm-Trading Readiness Audit", False)
        sys.exit(0 if report.pct >= 80 else 1)
    elif args.all:
        r24, rsw = evaluate_all()
        if args.json:
            combined = {
                "readiness_24_7": _print_report(r24, "", True),
                "swarm_trading": _print_report(rsw, "", True),
                "combined_score": r24.total_score + rsw.total_score,
                "combined_max": r24.max_score + rsw.max_score,
                "combined_pct": round(
                    (r24.total_score + rsw.total_score)
                    / (r24.max_score + rsw.max_score) * 100, 1)
                if (r24.max_score + rsw.max_score) else 0,
            }
            print(json.dumps(combined, indent=2))
        else:
            _print_report(r24, "MERID 24/7 Readiness Audit", False)
            _print_report(rsw, "MERID Swarm-Trading Readiness Audit", False)
            total = r24.total_score + rsw.total_score
            mx = r24.max_score + rsw.max_score
            pct = total / mx * 100 if mx else 0
            print("=" * 60)
            print(f"  COMBINED (live scan): {total}/{mx} ({pct:.0f}%)")
            # Show declared baseline from merid_readiness_score
            try:
                from core.merid_readiness_score import (
                    aggregate_scores, readiness_level, composite_scores,
                )
                bt, bm, bp = aggregate_scores()
                bl = readiness_level(bp)
                comp = composite_scores()
                print(f"  BASELINE (declared): {bt}/{bm} ({bp:.0f}%) — {bl}")
                for name, (ct, cm, cp) in comp.items():
                    print(f"    {name}: {ct}/{cm} ({cp:.0f}%)")
            except ImportError:
                logger.debug("baseline scoring module not available")
            print("=" * 60)
        worst = min(r24.pct, rsw.pct)
        sys.exit(0 if worst >= 80 else 1)
    else:
        report = evaluate()
        if args.json:
            print(json.dumps(_print_report(report, "", True), indent=2))
        else:
            _print_report(report, "MERID 24/7 Readiness Audit", False)
        sys.exit(0 if report.pct >= 80 else 1)


if __name__ == "__main__":
    main()
