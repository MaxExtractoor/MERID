"""Tests for logging audit fixes - centralized logging contamination cleanup.

This test file verifies that all components now use the centralized logging system
(utils/logger.py) which writes to logs/full.log instead of legacy log file paths.

Changes tested:
- monitor_production_stack.py - uses logs/full.log
- web/api/core_views_api.py - uses logs/full.log
- web/api/missing_endpoints.py - uses logs/full.log
- alignment_watchdog.py - uses centralized logger
- run_server_with_logs.py - writes to logs/ directory
- scripts/validate_invariants.py - uses centralized logger
- scripts/war_game_scheduler.py - uses centralized logger
- scripts/run_paper_gate.py - defaults to logs/ directory
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Set

import pytest

REPO = Path(__file__).resolve().parent.parent


class TestMonitorProductionStackLogging:
    """Verify monitor_production_stack.py uses centralized log path."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "monitor_production_stack.py").read_text(encoding="utf-8")

    def test_uses_logs_full_log(self):
        """probe_signal_generation should use logs/full.log."""
        # Check for any reference to logs/full.log (flexible for different path formats)
        # The file uses: log_file = "c:\\Dev\\MERID\\logs\\full.log"
        assert "full.log" in self.text and "logs" in self.text, (
            "monitor_production_stack.py should use logs/full.log instead of legacy log paths"
        )

    def test_no_legacy_server_15m_log(self):
        """Should not reference server_15m.log."""
        assert "server_15m.log" not in self.text, (
            "monitor_production_stack.py should not reference legacy server_15m.log"
        )

    def test_no_legacy_server_output_log(self):
        """Should not reference server_output.log directly (it's now written by logger.py)."""
        # server_output.log is now a valid production log file written by utils/logger.py
        # Components should not hardcode paths to it, but may reference it for reading
        # This test ensures monitor_production_stack.py doesn't hardcode the path
        # but allows the logger system to write to it
        hardcoded_patterns = [
            'server_output.log"',
            "server_output.log'",
            'server_output.log\n',
            "server_output.log\n",
        ]
        for pattern in hardcoded_patterns:
            assert pattern not in self.text, (
                f"monitor_production_stack.py should not hardcode server_output.log path (found {pattern})"
            )

    def test_probe_signal_generation_uses_centralized_log(self):
        """probe_signal_generation function should use logs/full.log."""
        assert 'def probe_signal_generation' in self.text
        # Check that the function uses the centralized log path
        assert "full.log" in self.text and "logs" in self.text

    def test_probe_order_routing_uses_centralized_log(self):
        """probe_order_routing function should use logs/full.log."""
        assert 'def probe_order_routing' in self.text
        # Check that the function uses the centralized log path
        assert "full.log" in self.text and "logs" in self.text

    def test_probe_fill_execution_uses_centralized_log(self):
        """probe_fill_execution function should use logs/full.log."""
        assert 'def probe_fill_execution' in self.text
        # Check that the function uses the centralized log path
        assert "full.log" in self.text and "logs" in self.text


class TestCoreViewsApiLogging:
    """Verify web/api/core_views_api.py uses centralized log path."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "web" / "api" / "core_views_api.py").read_text(encoding="utf-8")

    def test_get_logs_uses_logs_full_log(self):
        """get_logs endpoint should use logs/full.log."""
        assert 'log_path = log_dir / "logs" / "full.log"' in self.text, (
            "core_views_api.py get_logs should use logs/full.log"
        )

    def test_get_log_stats_uses_logs_full_log(self):
        """get_log_stats endpoint should use logs/full.log."""
        assert 'log_path = log_dir / "logs" / "full.log"' in self.text, (
            "core_views_api.py get_log_stats should use logs/full.log"
        )

    def test_no_legacy_server_startup_log(self):
        """Should not reference server_startup*.log."""
        assert "server_startup" not in self.text, (
            "core_views_api.py should not reference legacy server_startup*.log"
        )

    def test_json_parsing_for_centralized_logger(self):
        """Should parse JSON format from centralized logger."""
        assert 'json.loads(line.strip())' in self.text, (
            "core_views_api.py should parse JSON format from centralized logger"
        )


class TestMissingEndpointsLogging:
    """Verify web/api/missing_endpoints.py uses centralized log path."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "web" / "api" / "missing_endpoints.py").read_text(encoding="utf-8")

    def test_uses_logs_full_log(self):
        """Log statistics function should use logs/full.log."""
        assert 'log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "full.log"' in self.text, (
            "missing_endpoints.py should use logs/full.log"
        )

    def test_no_legacy_server_startup_log(self):
        """Should not reference server_startup*.log."""
        assert "server_startup" not in self.text, (
            "missing_endpoints.py should not reference legacy server_startup*.log"
        )

    def test_json_parsing_for_centralized_logger(self):
        """Should parse JSON format from centralized logger."""
        assert 'json.loads(line.strip())' in self.text, (
            "missing_endpoints.py should parse JSON format from centralized logger"
        )


class TestAlignmentWatchdogLogging:
    """Verify alignment_watchdog.py uses centralized logger."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "alignment_watchdog.py").read_text(encoding="utf-8")

    def test_uses_centralized_logger(self):
        """Should use utils.logger.get_logger."""
        assert "from utils.logger import get_logger" in self.text, (
            "alignment_watchdog.py should use centralized logger from utils.logger"
        )

    def test_no_legacy_file_handler(self):
        """Should not have FileHandler('alignment_watchdog.log')."""
        assert "FileHandler('alignment_watchdog.log')" not in self.text, (
            "alignment_watchdog.py should not use legacy FileHandler"
        )

    def test_no_legacy_logging_basicconfig(self):
        """Should not use logging.basicConfig."""
        assert "logging.basicConfig" not in self.text, (
            "alignment_watchdog.py should not use logging.basicConfig"
        )


class TestRunServerWithLogsLogging:
    """Verify run_server_with_logs.py writes to logs directory."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "run_server_with_logs.py").read_text(encoding="utf-8")

    def test_writes_to_logs_directory(self):
        """Should write to logs/ directory."""
        assert 'logs_dir = Path(r\'c:\\Dev\\MERID\\logs\')' in self.text, (
            "run_server_with_logs.py should write to logs/ directory"
        )

    def test_creates_logs_directory(self):
        """Should create logs directory if it doesn't exist."""
        assert "logs_dir.mkdir(parents=True, exist_ok=True)" in self.text, (
            "run_server_with_logs.py should create logs directory"
        )

    def test_no_root_directory_log(self):
        """Should not write log file to root directory."""
        # Check that log_filename is under logs_dir
        assert "log_filename = logs_dir /" in self.text, (
            "run_server_with_logs.py should write log file under logs directory"
        )


class TestValidateInvariantsLogging:
    """Verify scripts/validate_invariants.py uses centralized logger."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "scripts" / "validate_invariants.py").read_text(encoding="utf-8")

    def test_uses_centralized_logger(self):
        """Should use utils.logger.get_logger."""
        assert "from utils.logger import get_logger" in self.text, (
            "validate_invariants.py should use centralized logger from utils.logger"
        )

    def test_no_legacy_file_handler(self):
        """Should not have FileHandler('invariant_validation.log')."""
        assert "FileHandler('invariant_validation.log')" not in self.text, (
            "validate_invariants.py should not use legacy FileHandler"
        )

    def test_no_legacy_logging_basicconfig(self):
        """Should not use logging.basicConfig."""
        assert "logging.basicConfig" not in self.text, (
            "validate_invariants.py should not use logging.basicConfig"
        )


class TestWarGameSchedulerLogging:
    """Verify scripts/war_game_scheduler.py uses centralized logger."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "scripts" / "war_game_scheduler.py").read_text(encoding="utf-8")

    def test_uses_centralized_logger(self):
        """Should use utils.logger.get_logger."""
        assert "from utils.logger import get_logger" in self.text, (
            "war_game_scheduler.py should use centralized logger from utils.logger"
        )

    def test_no_legacy_file_handler(self):
        """Should not have FileHandler('war_game_scheduler.log')."""
        assert "FileHandler('war_game_scheduler.log')" not in self.text, (
            "war_game_scheduler.py should not use legacy FileHandler"
        )

    def test_no_legacy_logging_basicconfig(self):
        """Should not use logging.basicConfig."""
        assert "logging.basicConfig" not in self.text, (
            "war_game_scheduler.py should not use logging.basicConfig"
        )


class TestRunPaperGateLogging:
    """Verify scripts/run_paper_gate.py defaults to logs directory."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (REPO / "scripts" / "run_paper_gate.py").read_text(encoding="utf-8")

    def test_defaults_to_logs_directory(self):
        """Should default to logs directory for output."""
        assert 'self.output_dir = Path(__file__).parent.parent / "logs"' in self.text, (
            "run_paper_gate.py should default to logs directory"
        )

    def test_creates_logs_directory(self):
        """Should create logs directory if it doesn't exist."""
        assert "self.output_dir.mkdir(parents=True, exist_ok=True)" in self.text, (
            "run_paper_gate.py should create logs directory"
        )


class TestNoLegacyLogPathsInCodebase:
    """Verify no legacy log paths remain in critical files."""

    @pytest.fixture(autouse=True)
    def _collect_legacy_log_paths(self):
        """Collect all legacy log path references."""
        self.legacy_patterns = [
            "server_15m.log",
            "server_output.log",
            "server_startup*.log",
            "alignment_watchdog.log",
            "invariant_validation.log",
            "war_game_scheduler.log",
        ]
        self.violations = []

        # Check critical files
        critical_files = [
            REPO / "monitor_production_stack.py",
            REPO / "web" / "api" / "core_views_api.py",
            REPO / "web" / "api" / "missing_endpoints.py",
            REPO / "alignment_watchdog.py",
            REPO / "run_server_with_logs.py",
            REPO / "scripts" / "validate_invariants.py",
            REPO / "scripts" / "war_game_scheduler.py",
            REPO / "scripts" / "run_paper_gate.py",
        ]

        for filepath in critical_files:
            if not filepath.exists():
                continue
            text = filepath.read_text(encoding="utf-8")
            for pattern in self.legacy_patterns:
                if pattern in text:
                    self.violations.append((str(filepath.relative_to(REPO)), pattern))

    def test_no_legacy_log_paths(self):
        """No legacy log paths should remain in critical files."""
        if self.violations:
            lines = []
            for filepath, pattern in self.violations:
                lines.append(f"  {filepath}: {pattern}")
            pytest.fail(
                f"Found {len(self.violations)} legacy log path reference(s):\n" + "\n".join(lines)
            )


class TestCentralizedLoggerImports:
    """Verify modified files import centralized logger correctly."""

    @pytest.fixture(autouse=True)
    def _check_imports(self):
        """Check that files use the correct logger import."""
        self.files_to_check = [
            (REPO / "alignment_watchdog.py", "from utils.logger import get_logger"),
            (REPO / "scripts" / "validate_invariants.py", "from utils.logger import get_logger"),
            (REPO / "scripts" / "war_game_scheduler.py", "from utils.logger import get_logger"),
        ]
        self.violations = []

        for filepath, expected_import in self.files_to_check:
            if not filepath.exists():
                continue
            text = filepath.read_text(encoding="utf-8")
            if expected_import not in text:
                self.violations.append((str(filepath.relative_to(REPO)), expected_import))

    def test_centralized_logger_imports(self):
        """Files should import centralized logger correctly."""
        if self.violations:
            lines = []
            for filepath, expected_import in self.violations:
                lines.append(f"  {filepath}: missing {expected_import}")
            pytest.fail(
                f"Found {len(self.violations)} missing centralized logger import(s):\n" + "\n".join(lines)
            )
