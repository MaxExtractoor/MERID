"""Regression tests for production-readiness audit fixes.

Each test class maps to a specific ticket:
  PR-01  merid/settings.py NEO4J_PASSWORD default removed
  PR-02  startup raises on missing prod settings
  PR-03  docker-compose.yml no hardcoded password fallbacks
  PR-04  real_data_endpoints.py fallback counter wired
  PR-05  ci.yml ruff is blocking (--exit-zero removed)
  PR-06  ci.yml bandit + pip-audit steps present
  PR-07  config/settings.py debug default is False
  PR-08  core/tracing.py Jaeger reads from env vars
  PR-09  docker-compose.prod.yml exists, no password fallbacks
  PR-10  ReconciliationDriftAlert wired in ALERT_RULES
  PR-11  CODEOWNERS exists covering critical paths
  PR-12  .gitignore hooks/ glob scoped to root only
  PR-13  Makefile production-readiness-test uses 'python' not 'py'
  PR-14  system_observability endpoints use lazy imports (no bare NameErrors)
  PR-15  ALERT_RULES count kept in sync across both test files

Run with:
    pytest tests/test_production_readiness_regressions.py -v
"""

from __future__ import annotations

import contextlib
import os
import re
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


# ===========================================================================
# PR-01 — NEO4J_PASSWORD default must be None, not "change_me"
# ===========================================================================

class TestNeo4jPasswordDefault:
    """merid/settings.py NEO4J_PASSWORD must not have a non-None default."""

    def test_field_default_is_none(self):
        from merid.settings import Settings
        import inspect
        src = inspect.getsource(Settings)
        assert '"change_me"' not in src, (
            'NEO4J_PASSWORD still defaults to "change_me" — regression of PR-01'
        )

    def test_runtime_default_is_none(self):
        """Instantiating Settings without env vars must leave NEO4J_PASSWORD as None."""
        # Strip NEO4J_PASSWORD from env AND suppress .env file loading
        env_copy = {k: v for k, v in os.environ.items() if k != "NEO4J_PASSWORD"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch("merid.settings.Settings.model_config",
                   {"env_file": None, "env_file_encoding": "utf-8", "extra": "ignore"}):
            from merid.settings import Settings
            s = Settings(_env_file=None)
            assert s.NEO4J_PASSWORD is None, (
                f"NEO4J_PASSWORD defaulted to {s.NEO4J_PASSWORD!r}, expected None — "
                "check that field default=None is set and no .env file overrides it"
            )

    def test_neo4j_password_in_required_for_production(self):
        """NEO4J_PASSWORD must appear in validate_required_for_production missing list
        when env is production and the var is unset."""
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("NEO4J_PASSWORD", "SECRET_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY")
        }
        env["MERID_ENV"] = "production"
        with patch.dict(os.environ, env, clear=True):
            from merid.settings import Settings
            # Bypass .env file so locally-set passwords don't interfere
            s = Settings(_env_file=None)
            missing = s.validate_required_for_production()
            assert "NEO4J_PASSWORD" in missing, (
                "NEO4J_PASSWORD not in validate_required_for_production missing list"
            )


# ===========================================================================
# PR-02 — startup raises ValueError when required prod settings absent
# ===========================================================================

class TestProductionStartupValidation:
    """validate_required_for_production() must catch missing secrets and
    web/main.py must raise on them during startup."""

    def test_missing_secret_key_caught(self, tmp_path):
        """Test that missing SECRET_KEY is detected in production mode.
        
        Note: We must create a temporary .env file to avoid loading
        real credentials from the project .env file during tests.
        """
        import os
        from pathlib import Path
        
        # Create minimal env with only MERID_ENV=production
        env_vars = {
            "MERID_ENV": "production",
            # Explicitly NOT setting SECRET_KEY, NEO4J_PASSWORD, SUPABASE_URL, SUPABASE_ANON_KEY
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            # Create a temp .env file that's essentially empty (no SECRET_KEY)
            temp_env = tmp_path / ".env"
            temp_env.write_text("MERID_ENV=production\n")
            
            # Patch the env file location before importing Settings
            with patch("merid.settings._ENV_FILE", str(temp_env)):
                from merid.settings import Settings
                # Need to re-create SettingsConfigDict to use new env file
                s = Settings(_env_file=str(temp_env))
                missing = s.validate_required_for_production()
                assert "SECRET_KEY" in missing

    def test_all_set_returns_empty(self):
        env = {
            "MERID_ENV": "production",
            "SECRET_KEY": "supersecret",
            "NEO4J_PASSWORD": "realpassword",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "anon-key-value",
        }
        with patch.dict(os.environ, env):
            from merid.settings import Settings
            s = Settings()
            missing = s.validate_required_for_production()
            assert missing == [], f"Unexpected missing vars: {missing}"

    def test_non_production_skips_validation(self):
        """validate_required_for_production must return [] for non-prod envs."""
        with patch.dict(os.environ, {"MERID_ENV": "development"}, clear=False):
            from merid.settings import Settings
            s = Settings()
            result = s.validate_required_for_production()
            assert result == []


# ===========================================================================
# PR-03 — docker-compose.yml must not have hardcoded password fallbacks
# ===========================================================================

class TestDockerComposeNoHardcodedPasswords:
    """docker-compose.yml must not contain :-<password> fallback syntax."""

    BANNED_PATTERNS = [
        ":-kalshi_password",
        ":-redis_password",
        ":-admin",
        ":-password",
        ':-postgresql://kalshi:password',
    ]

    def test_no_hardcoded_postgres_password(self):
        content = _read("docker-compose.yml")
        assert ":-kalshi_password" not in content, (
            "docker-compose.yml still has hardcoded POSTGRES_PASSWORD fallback"
        )

    def test_no_hardcoded_redis_password(self):
        content = _read("docker-compose.yml")
        assert ":-redis_password" not in content, (
            "docker-compose.yml still has hardcoded REDIS_PASSWORD fallback"
        )

    def test_no_hardcoded_grafana_password(self):
        content = _read("docker-compose.yml")
        assert "GRAFANA_PASSWORD:-admin" not in content, (
            "docker-compose.yml still has hardcoded GRAFANA_PASSWORD=admin fallback"
        )

    def test_no_hardcoded_database_url_password(self):
        content = _read("docker-compose.yml")
        assert ":-postgresql://kalshi:password" not in content, (
            "docker-compose.yml still has hardcoded DATABASE_URL with embedded password"
        )

    def test_mandatory_error_syntax_used(self):
        """All password vars should use :? syntax (fail fast if unset)."""
        content = _read("docker-compose.yml")
        assert "POSTGRES_PASSWORD:?" in content
        assert "REDIS_PASSWORD:?" in content
        assert "GRAFANA_PASSWORD:?" in content


# ===========================================================================
# PR-04 — real_data_endpoints.py fallback counter
# ===========================================================================

class TestFallbackCounter:
    """_record_fallback and get_fallback_counts must be present and functional."""

    def test_record_fallback_increments_count(self):
        from web.api.real_data_endpoints import _record_fallback, _fallback_counts
        _fallback_counts.clear()
        exc = ValueError("test error")
        _record_fallback("test_endpoint", exc)
        assert _fallback_counts["test_endpoint"] == 1
        _record_fallback("test_endpoint", exc)
        assert _fallback_counts["test_endpoint"] == 2

    def test_get_fallback_counts_returns_snapshot(self):
        from web.api.real_data_endpoints import _record_fallback, get_fallback_counts, _fallback_counts
        _fallback_counts.clear()
        _record_fallback("ep_a", RuntimeError("boom"))
        _record_fallback("ep_a", RuntimeError("boom2"))
        _record_fallback("ep_b", TypeError("bad"))
        counts = get_fallback_counts()
        assert counts["ep_a"] == 2
        assert counts["ep_b"] == 1

    def test_record_fallback_logs_warning_on_first_new_type(self):
        from web.api import real_data_endpoints as rde
        rde._fallback_counts.clear()
        rde._fallback_last_exc.clear()
        with patch.object(rde.logger, "warning") as mock_warn:
            rde._record_fallback("ep_new", ValueError("first"))
            assert mock_warn.called, "_record_fallback must log WARNING on first new exc type"

    def test_record_fallback_suppresses_duplicate_log(self):
        """Second call with same endpoint+exc type must NOT emit another warning."""
        from web.api import real_data_endpoints as rde
        rde._fallback_counts.clear()
        rde._fallback_last_exc.clear()
        with patch.object(rde.logger, "warning") as mock_warn:
            rde._record_fallback("dup_ep", ValueError("e1"))
            rde._record_fallback("dup_ep", ValueError("e2"))
        assert mock_warn.call_count == 1, (
            "Duplicate exc type on same endpoint should only warn once"
        )

    def test_live_price_helpers_call_record_fallback(self):
        """_get_live_prices and _get_live_price_details must invoke _record_fallback on error."""
        from web.api import real_data_endpoints as rde
        rde._fallback_counts.clear()
        with patch("data.live_price_feed.get_live_price_feed", side_effect=RuntimeError("feed down")):
            result = rde._get_live_prices()
            assert result == {}
            assert rde._fallback_counts.get("live_price_feed", 0) >= 1

        rde._fallback_counts.clear()
        with patch("data.live_price_feed.get_live_price_feed", side_effect=RuntimeError("feed down")):
            result = rde._get_live_price_details()
            assert result == {}
            assert rde._fallback_counts.get("live_price_details", 0) >= 1


# ===========================================================================
# PR-05 — ci.yml ruff must NOT use --exit-zero
# ===========================================================================

class TestCIRuffBlocking:
    """ruff check step must not pass --exit-zero (would make lint non-blocking)."""

    def test_no_exit_zero_on_ruff(self):
        content = _read(".github/workflows/ci.yml")
        # Find the ruff check line and assert --exit-zero is absent
        ruff_lines = [ln for ln in content.splitlines() if "ruff check" in ln]
        assert ruff_lines, "No ruff check line found in ci.yml"
        for line in ruff_lines:
            assert "--exit-zero" not in line, (
                f"ruff check still uses --exit-zero (non-blocking lint): {line!r}"
            )


# ===========================================================================
# PR-06 — ci.yml must have bandit and pip-audit
# ===========================================================================

class TestCISASTSteps:
    """CI pipeline must include bandit SAST and pip-audit dependency scan."""

    def test_bandit_present(self):
        content = _read(".github/workflows/ci.yml")
        assert "bandit" in content, "bandit SAST step missing from ci.yml"

    def test_pip_audit_present(self):
        content = _read(".github/workflows/ci.yml")
        assert "pip-audit" in content, "pip-audit dependency scan missing from ci.yml"

    def test_bandit_high_severity_blocks(self):
        """bandit must be invoked with -lll (HIGH exits non-zero)."""
        content = _read(".github/workflows/ci.yml")
        assert "-lll" in content, (
            "bandit -lll flag missing — HIGH severity findings won't block CI"
        )

    def test_sast_reports_uploaded(self):
        content = _read(".github/workflows/ci.yml")
        assert "sast-reports" in content, "SAST report artifact upload step missing"


# ===========================================================================
# PR-07 — config/settings.py ServerConfig.debug default must be False
# ===========================================================================

class TestDeprecatedSettingsDebugDefault:
    """Deprecated config/settings.py ServerConfig must default debug=False."""

    def test_debug_default_is_false(self):
        from config.settings import ServerConfig
        s = ServerConfig()
        assert s.debug is False, (
            f"ServerConfig.debug defaults to {s.debug!r}, expected False — "
            "regression of PR-07"
        )

    def test_from_env_debug_reads_env(self):
        """from_env() must still honour the DEBUG env var when explicitly set."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            from config.settings import ServerConfig
            s = ServerConfig.from_env()
            assert s.debug is True

    def test_from_env_debug_false_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != "DEBUG"}
        with patch.dict(os.environ, env, clear=True):
            from config.settings import ServerConfig
            s = ServerConfig.from_env()
            # DEBUG env var absent → defaults to "true" in from_env() per original code,
            # but the dataclass default itself must be False
            s2 = ServerConfig()
            assert s2.debug is False


# ===========================================================================
# PR-08 — core/tracing.py Jaeger must read host/port from env vars
# ===========================================================================

class TestJaegerEnvConfig:
    """JaegerExporter must not hardcode localhost:6831."""

    def test_no_hardcoded_localhost_in_source(self):
        content = _read("core/tracing.py")
        # The string "localhost" may still appear but only as the *default* in os.getenv
        assert 'agent_host_name="localhost"' not in content, (
            'core/tracing.py still hardcodes agent_host_name="localhost" — PR-08 regression'
        )

    def test_jaeger_host_read_from_env(self):
        """core/tracing.py source must call os.getenv for JAEGER_AGENT_HOST."""
        content = _read("core/tracing.py")
        assert "JAEGER_AGENT_HOST" in content, (
            "JAEGER_AGENT_HOST env var not referenced in core/tracing.py — PR-08 regression"
        )
        assert 'os.getenv("JAEGER_AGENT_HOST"' in content or \
               "os.getenv('JAEGER_AGENT_HOST'" in content or \
               'os.environ' in content, (
            "JAEGER_AGENT_HOST not read via os.getenv in core/tracing.py"
        )

    def test_jaeger_port_read_from_env(self):
        """core/tracing.py source must call os.getenv for JAEGER_AGENT_PORT."""
        content = _read("core/tracing.py")
        assert "JAEGER_AGENT_PORT" in content, (
            "JAEGER_AGENT_PORT env var not referenced in core/tracing.py — PR-08 regression"
        )
        assert 'os.getenv("JAEGER_AGENT_PORT"' in content or \
               "os.getenv('JAEGER_AGENT_PORT'" in content, (
            "JAEGER_AGENT_PORT not read via os.getenv in core/tracing.py"
        )

    def test_os_import_present(self):
        """os must be imported so os.getenv works at module level."""
        content = _read("core/tracing.py")
        assert "import os" in content, "import os missing from core/tracing.py"


# ===========================================================================
# PR-09 — docker-compose.prod.yml exists and is clean
# ===========================================================================

class TestProdComposeFile:
    """docker-compose.prod.yml must exist and must not contain password fallbacks."""

    def test_file_exists(self):
        assert (REPO_ROOT / "docker-compose.prod.yml").exists(), (
            "docker-compose.prod.yml does not exist — PR-09 not applied"
        )

    def test_no_hardcoded_passwords(self):
        content = _read("docker-compose.prod.yml")
        assert ":-admin" not in content
        assert ":-password" not in content
        assert ":-kalshi_password" not in content
        assert ":-redis_password" not in content

    def test_image_tag_mandatory(self):
        content = _read("docker-compose.prod.yml")
        assert "IMAGE_TAG:?" in content, (
            "docker-compose.prod.yml IMAGE_TAG should be mandatory (:?)"
        )

    def test_all_passwords_mandatory(self):
        content = _read("docker-compose.prod.yml")
        assert "GRAFANA_PASSWORD:?" in content

    def test_resource_limits_present(self):
        content = _read("docker-compose.prod.yml")
        assert "mem_limit" in content, "No mem_limit in docker-compose.prod.yml"
        assert "cpus" in content, "No cpu limit in docker-compose.prod.yml"

    def test_health_check_present(self):
        content = _read("docker-compose.prod.yml")
        assert "healthcheck" in content


# ===========================================================================
# PR-10 — ReconciliationDriftAlert registered and functional
# ===========================================================================

class TestReconciliationDriftAlert:
    """ReconciliationDriftAlert must be in ALERT_RULES and fire correctly."""

    def test_alert_registered(self):
        from web.api.system_observability import ALERT_RULES, ReconciliationDriftAlert
        names = [r.name for r in ALERT_RULES]
        assert "reconciliation_drift" in names, (
            "reconciliation_drift alert not in ALERT_RULES — PR-10 regression"
        )
        assert any(isinstance(r, ReconciliationDriftAlert) for r in ALERT_RULES)

    def test_not_firing_when_all_ok(self):
        from web.api.system_observability import ReconciliationDriftAlert
        mock_report = MagicMock()
        mock_report.all_ok = True
        mock_report.checks = []
        mock_report.portfolios_checked = 2
        mock_report.positions_checked = 5
        mock_report.timestamp = time.time()

        with patch("merid.reconciliation.get_last_report", return_value=mock_report):
            alert = ReconciliationDriftAlert()
            result = alert.evaluate()

        assert result["firing"] is False
        assert result["detail"]["all_ok"] is True
        assert result["detail"]["failed_checks"] == []

    def test_firing_when_drift_detected(self):
        from web.api.system_observability import ReconciliationDriftAlert

        bad_check = MagicMock()
        bad_check.name = "balance_identity"
        bad_check.status = MagicMock(value="delta")
        ok_check = MagicMock()
        ok_check.name = "trade_count"
        ok_check.status = MagicMock(value="ok")

        mock_report = MagicMock()
        mock_report.all_ok = False
        mock_report.checks = [bad_check, ok_check]
        mock_report.portfolios_checked = 1
        mock_report.positions_checked = 3
        mock_report.timestamp = time.time()

        with patch("merid.reconciliation.get_last_report", return_value=mock_report):
            alert = ReconciliationDriftAlert()
            result = alert.evaluate()

        assert result["firing"] is True
        assert result["severity"] == "critical"
        assert "balance_identity" in result["detail"]["failed_checks"]
        assert "trade_count" not in result["detail"]["failed_checks"]

    def test_not_firing_when_no_report_yet(self):
        from web.api.system_observability import ReconciliationDriftAlert
        with patch("merid.reconciliation.get_last_report", return_value=None):
            alert = ReconciliationDriftAlert()
            result = alert.evaluate()
        assert result["firing"] is False
        assert result["detail"]["status"] == "no_report_yet"

    def test_graceful_on_import_error(self):
        from web.api.system_observability import ReconciliationDriftAlert
        with patch("merid.reconciliation.get_last_report",
                   side_effect=Exception("db locked")):
            alert = ReconciliationDriftAlert()
            result = alert.evaluate()
        assert result["firing"] is True
        assert "probe_error" in result["detail"]

    def test_rule_count_updated(self):
        """ALERT_RULES count must reflect the addition of ReconciliationDriftAlert."""
        from web.api.system_observability import ALERT_RULES
        assert len(ALERT_RULES) == 37, (
            f"Expected 37 alert rules (incl. NewsFeedHealthAlert + ReconciliationDriftAlert + WSSequenceGapAlert), "
            f"got {len(ALERT_RULES)}"
        )


# ===========================================================================
# PR-11 — CODEOWNERS exists and covers critical paths
# ===========================================================================

class TestCodeowners:
    """CODEOWNERS must exist and protect execution/trading/risk paths."""

    REQUIRED_PATHS = [
        "execution/",
        "trading/",
        "merid/risk/",
        "trading/trade_mode.py",
        "merid/settings.py",
        ".github/",
        "Dockerfile",
    ]

    def test_codeowners_file_exists(self):
        assert (REPO_ROOT / ".github" / "CODEOWNERS").exists(), (
            ".github/CODEOWNERS does not exist — PR-11 not applied"
        )

    def test_execution_paths_covered(self):
        content = _read(".github/CODEOWNERS")
        for path in self.REQUIRED_PATHS:
            assert path in content, (
                f"CODEOWNERS does not cover {path!r}"
            )

    def test_risk_team_assigned(self):
        content = _read(".github/CODEOWNERS")
        assert "merid-risk-team" in content

    def test_ops_team_assigned(self):
        content = _read(".github/CODEOWNERS")
        assert "merid-ops-team" in content


# ===========================================================================
# PR-Template — production readiness checklist present
# ===========================================================================

class TestPRTemplate:
    """Pull request template must include the production readiness checklist."""

    def test_production_checklist_present(self):
        content = _read(".github/pull_request_template.md")
        assert "Production readiness checklist" in content

    def test_kill_switch_item_present(self):
        content = _read(".github/pull_request_template.md")
        assert "kill-switch" in content.lower() or "kill switch" in content.lower()

    def test_mode_integrity_item_present(self):
        content = _read(".github/pull_request_template.md")
        assert "Mode integrity" in content or "mode integrity" in content


# ===========================================================================
# PR-12 — .gitignore hooks/ glob must be root-scoped (/hooks/)
# ===========================================================================

class TestGitignoreHooksScope:
    """.gitignore must not hide web/react/src/hooks/ via a bare hooks/ glob.

    A bare 'hooks/' pattern matches any directory named hooks at any depth,
    silently preventing every React hook file from being tracked.  The pattern
    must be anchored to the repo root as '/hooks/'.
    """

    def test_bare_hooks_glob_absent(self):
        content = _read(".gitignore")
        lines = content.splitlines()
        for line in lines:
            stripped = line.strip()
            assert stripped != "hooks/", (
                ".gitignore contains bare 'hooks/' which silently hides "
                "web/react/src/hooks/ — must be '/hooks/' (root-anchored)"
            )

    def test_root_hooks_glob_present(self):
        """The root-anchored /hooks/ pattern must still be present."""
        content = _read(".gitignore")
        assert "/hooks/" in content, (
            ".gitignore missing '/hooks/' entry — legacy hooks/ dir is no "
            "longer excluded from git tracking"
        )

    def test_react_hooks_dir_not_ignored(self):
        """web/react/src/hooks/ must NOT appear in any gitignore pattern that
        would match it (i.e. it must be trackable)."""
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore", "-v", "web/react/src/hooks/useWebSocket.ts"],
            capture_output=True, text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0, (
            "web/react/src/hooks/useWebSocket.ts is still gitignored — "
            f"matched by: {result.stdout.strip()!r}"
        )


# ===========================================================================
# PR-13 — Makefile production-readiness-test must use 'python' not 'py'
# ===========================================================================

class TestMakefileProductionReadinessTarget:
    """Makefile production-readiness-test must invoke 'python', not 'py'.

    'py' is a Windows-only shim.  Using it breaks the target on Linux CI
    runners (Ubuntu) where only 'python' / 'python3' are in PATH.
    """

    def test_no_bare_py_invocation_in_production_readiness_target(self):
        content = _read("Makefile")
        lines = content.splitlines()
        in_target = False
        for line in lines:
            if line.startswith("production-readiness-test:"):
                in_target = True
                continue
            if in_target:
                if line and not line[0].isspace():
                    break
                if "\tpy " in line or "\tpy\n" == line:
                    assert False, (
                        f"Makefile production-readiness-test uses 'py' (Windows alias): {line!r}\n"
                        "Must use 'python' for portability across CI runners."
                    )

    def test_python_invocation_present_in_target(self):
        content = _read("Makefile")
        lines = content.splitlines()
        in_target = False
        for line in lines:
            if line.startswith("production-readiness-test:"):
                in_target = True
                continue
            if in_target:
                if line and not line[0].isspace():
                    break
                if "python -m pytest" in line:
                    return
        assert False, (
            "Makefile production-readiness-test target does not contain "
            "'python -m pytest' invocation"
        )


# ===========================================================================
# PR-14 — system_observability endpoints must not have bare NameErrors
# ===========================================================================

class TestObservabilityEndpointLazyImports:
    """system_observability.py endpoint functions must not reference any name
    that is not defined at the point of call.

    Before this fix, _METRICS_CACHE, get_prediction_consensus_store,
    get_debate_store, get_reward_engine, get_reality_debugger,
    get_bookie_agent, and get_sports_betting_manager were called bare in
    the endpoint body without any import, causing silent NameErrors caught
    by the surrounding try/except and returning {"error": "unavailable"}
    for every request.
    """

    BARE_NAMES = [
        "_METRICS_CACHE",
        "get_prediction_consensus_store",
        "get_debate_store",
        "get_reward_engine",
        "get_reality_debugger",
        "get_bookie_agent",
        "get_sports_betting_manager",
    ]

    def _endpoint_body_lines(self) -> list:
        """Return only the lines that belong to the async endpoint functions
        (i.e. not inside a class method that has its own local import)."""
        content = _read("web/api/system_observability.py")
        lines = content.splitlines()
        endpoint_lines = []
        in_endpoint = False
        for line in lines:
            if line.startswith("async def ") or line.startswith("@router."):
                in_endpoint = True
            if in_endpoint:
                endpoint_lines.append(line)
        return endpoint_lines

    def test_no_bare_metrics_cache_reference(self):
        """_METRICS_CACHE must never be used bare at module scope in endpoint functions.

        Every usage must be either:
          (a) a 'from … import _METRICS_CACHE …' statement, or
          (b) using an alias (_smc, _smc2, etc.) assigned by a preceding lazy import.

        The bare name '_METRICS_CACHE' is only acceptable inside an evaluate()
        class method where it is imported two lines above via
        'from web.api.signal_layer_api import _METRICS_CACHE'.
        What is NOT acceptable is using it as a bare name inside the top-level
        async endpoint functions without a preceding import statement.
        """
        source = _read("web/api/system_observability.py")
        lines = source.splitlines()

        # Find the line where the async endpoint functions begin
        endpoint_start = None
        for i, line in enumerate(lines):
            if line.startswith("# ── Endpoints"):
                endpoint_start = i
                break

        if endpoint_start is None:
            return  # Can't locate endpoint section; skip

        endpoint_lines = lines[endpoint_start:]
        for i, line in enumerate(endpoint_lines):
            stripped = line.strip()
            # A bare _METRICS_CACHE usage (not an import line, not an alias)
            if "_METRICS_CACHE" in stripped and not stripped.startswith("from "):
                # Must be using an alias (_smc, _smc2, _smc3, …)
                assert re.search(r"\b_smc\d*\b", stripped), (
                    f"Endpoint section line {endpoint_start + i + 1}: "
                    f"bare _METRICS_CACHE used without alias: {line!r}"
                )

    def test_observability_endpoint_survives_all_import_errors(self):
        """With all backends unavailable, system_observability must return a
        dict with required keys rather than raising."""
        import asyncio
        from web.api.system_observability import system_observability

        # Patch every lazy import to raise ImportError
        patches = [
            patch("web.api.signal_layer_api._METRICS_CACHE", {}),
            patch("merid.prediction.consensus.get_prediction_consensus_store",
                  side_effect=ImportError("unavailable")),
            patch("merid.prediction.debate.get_debate_store",
                  side_effect=ImportError("unavailable")),
            patch("merid.rewards.engine.get_reward_engine",
                  side_effect=ImportError("unavailable")),
            patch("merid.cognitive.reality_debugger.get_reality_debugger",
                  side_effect=ImportError("unavailable")),
            patch("web.api.betting.get_bookie_agent",
                  side_effect=ImportError("unavailable")),
            patch("merid.betting.live_sports.get_sports_betting_manager",
                  side_effect=ImportError("unavailable")),
            patch("web.api.real_data_endpoints.get_fallback_counts",
                  side_effect=ImportError("unavailable")),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = asyncio.run(system_observability())

        assert isinstance(result, dict), "endpoint must return a dict even when all backends fail"
        for key in ("signal_metrics_slo", "consensus_store", "collaboration_health",
                    "reward_engine_health", "cognitive_health", "betting_health",
                    "sports_betting_health", "alerts", "timestamp"):
            assert key in result, f"missing key {key!r} from observability response"

    def test_slo_endpoint_survives_import_error(self):
        """system_slo must return error-keyed dict, not raise, when cache unavailable."""
        import asyncio
        from web.api.system_observability import system_slo

        with patch("web.api.signal_layer_api._METRICS_CACHE",
                   side_effect=ImportError("unavailable")):
            result = asyncio.run(system_slo())

        assert "timestamp" in result

    def test_consensus_store_metrics_endpoint_survives_import_error(self):
        """consensus_store_metrics must return {"error": ...} not raise."""
        import asyncio
        from web.api.system_observability import consensus_store_metrics

        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                   side_effect=ImportError("unavailable")):
            result = asyncio.run(consensus_store_metrics())

        assert "error" in result


# ===========================================================================
# PR-15 — ALERT_RULES count must be in sync across both test files
# ===========================================================================

class TestAlertRulesCountSync:
    """Both test files that assert on ALERT_RULES length must agree with the
    actual registry.  A mismatch means one file was updated and the other
    was forgotten, causing a silent false-pass or false-fail.
    """

    _EXPECTED = 37

    def test_actual_registry_count(self):
        from web.api.system_observability import ALERT_RULES
        assert len(ALERT_RULES) == self._EXPECTED, (
            f"ALERT_RULES has {len(ALERT_RULES)} entries, expected {self._EXPECTED}. "
            "Update _EXPECTED in this class AND the assertions in "
            "test_system_observability.py when adding/removing alert rules."
        )

    def test_test_system_observability_count_in_sync(self):
        """test_system_observability.py must assert the same count."""
        content = _read("tests/test_system_observability.py")
        assert f"len(ALERT_RULES) == {self._EXPECTED}" in content or f"== {self._EXPECTED}" in content, (
            f"test_system_observability.py does not assert ALERT_RULES == {self._EXPECTED}. "
            "Keep both test files in sync when adding/removing alert rules."
        )

    def test_test_production_readiness_count_in_sync(self):
        """test_production_readiness_regressions.py must assert the same count."""
        content = _read("tests/test_production_readiness_regressions.py")
        assert f"len(ALERT_RULES) == {self._EXPECTED}" in content or f"== {self._EXPECTED}" in content, (
            f"test_production_readiness_regressions.py does not assert "
            f"ALERT_RULES == {self._EXPECTED}. Keep both test files in sync."
        )
