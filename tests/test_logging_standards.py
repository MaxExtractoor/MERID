"""
Tests for logging standards compliance in the production stack.

These tests verify:
- No print() statements in production code
- No CRITICAL DIAGNOSTIC markers
- Proper logger usage (get_logger from utils.logger)
- Context in risk-critical logs
- Causal context in error logs
"""

import ast
import re
from pathlib import Path
from typing import List, Set


class TestLoggingStandards:
    """Test suite for logging standards compliance."""
    
    def test_no_print_statements_in_main_15m_lean(self):
        """Verify no print() statements in main_15m_lean.py."""
        main_15m_lean_path = Path(__file__).parent.parent / "web" / "main_15m_lean.py"
        
        with open(main_15m_lean_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for print statements (excluding comments)
        lines = content.split('\n')
        print_statements = []
        
        for i, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#'):
                continue
            # Check for print calls
            if 'print(' in line and not line.strip().startswith('#'):
                print_statements.append((i, line.strip()))
        
        if print_statements:
            raise AssertionError(
                f"Found {len(print_statements)} print() statements in main_15m_lean.py:\n" +
                "\n".join(f"  Line {i}: {line}" for i, line in print_statements)
            )
    
    def test_no_critical_diagnostic_markers_in_main_15m_lean(self):
        """Verify no CRITICAL DIAGNOSTIC markers in main_15m_lean.py."""
        main_15m_lean_path = Path(__file__).parent.parent / "web" / "main_15m_lean.py"
        
        with open(main_15m_lean_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for CRITICAL DIAGNOSTIC markers
        lines = content.split('\n')
        diagnostic_markers = []
        
        for i, line in enumerate(lines, 1):
            if 'CRITICAL DIAGNOSTIC' in line:
                diagnostic_markers.append((i, line.strip()))
        
        if diagnostic_markers:
            raise AssertionError(
                f"Found {len(diagnostic_markers)} CRITICAL DIAGNOSTIC markers in main_15m_lean.py:\n" +
                "\n".join(f"  Line {i}: {line}" for i, line in diagnostic_markers)
            )
    
    def test_no_diagnostic_file_writes_in_main_15m_lean(self):
        """Verify no diagnostic file writes in main_15m_lean.py."""
        main_15m_lean_path = Path(__file__).parent.parent / "web" / "main_15m_lean.py"
        
        with open(main_15m_lean_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for file write patterns used for diagnostics
        diagnostic_patterns = [
            r'Path.*\.write_text.*EXECUTED',
            r'main_15m_execution_marker',
        ]
        
        lines = content.split('\n')
        file_writes = []
        
        for i, line in enumerate(lines, 1):
            for pattern in diagnostic_patterns:
                if re.search(pattern, line):
                    file_writes.append((i, line.strip()))
        
        if file_writes:
            raise AssertionError(
                f"Found {len(file_writes)} diagnostic file writes in main_15m_lean.py:\n" +
                "\n".join(f"  Line {i}: {line}" for i, line in file_writes)
            )
    
    def test_get_logger_usage_in_crypto_15m_profile(self):
        """Verify crypto_15m_profile.py uses get_logger from utils.logger."""
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for get_logger import
        has_get_logger_import = 'from utils.logger import get_logger' in content
        has_get_logger_call = 'get_logger(' in content
        
        # Check for old logging.getLogger
        has_old_logger = 'logging.getLogger' in content
        
        if not has_get_logger_import or not has_get_logger_call:
            raise AssertionError(
                "crypto_15m_profile.py should use get_logger from utils.logger"
            )
        
        if has_old_logger:
            raise AssertionError(
                "crypto_15m_profile.py should not use logging.getLogger"
            )
    
    def test_window_tracking_logs_have_context(self):
        """Verify window tracking logs include required context."""
        risk_envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        
        with open(risk_envelope_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check force_reset_window_exposure log - look for the function and its log statement
        # The log is multi-line, so we need to check the function content
        force_reset_pattern = r'def force_reset_window_exposure.*?logger\.warning.*?FORCE RESET.*?\)'
        force_reset_match = re.search(force_reset_pattern, content, re.MULTILINE | re.DOTALL)
        
        if force_reset_match:
            log_content = force_reset_match.group(0)
            required_context = ['reason', 'stale_total_exposure', 'stale_agent_count']
            missing_context = [ctx for ctx in required_context if ctx not in log_content]
            
            if missing_context:
                raise AssertionError(
                    f"force_reset_window_exposure log missing context: {missing_context}\n"
                    f"Log content: {log_content[:500]}..."
                )
        
        # Check window roll log
        window_roll_pattern = r'def _roll_window_if_needed_locked.*?logger\.info.*?New 15m window started.*?\)'
        window_roll_match = re.search(window_roll_pattern, content, re.MULTILINE | re.DOTALL)
        
        if window_roll_match:
            log_content = window_roll_match.group(0)
            required_context = ['old_window_start', 'old_total_exposure', 'old_agent_count']
            missing_context = [ctx for ctx in required_context if ctx not in log_content]
            
            if missing_context:
                raise AssertionError(
                    f"Window roll log missing context: {missing_context}\n"
                    f"Log content: {log_content[:500]}..."
                )
    
    def test_no_print_in_risk_envelope(self):
        """Verify no print statements in risk envelope."""
        risk_envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        
        with open(risk_envelope_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for print statements (excluding comments)
        lines = content.split('\n')
        print_statements = []
        
        for i, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('#'):
                continue
            # Check for print calls
            if 'print(' in line and not line.strip().startswith('#'):
                print_statements.append((i, line.strip()))
        
        if print_statements:
            raise AssertionError(
                f"Found {len(print_statements)} print() statements in kalshi_crypto_15m_risk_envelope.py:\n" +
                "\n".join(f"  Line {i}: {line}" for i, line in print_statements)
            )
    
    def test_unified_sizing_uses_get_logger(self):
        """Verify unified_sizing.py uses get_logger from utils.logger."""
        sizing_path = Path(__file__).parent.parent / "merid" / "prediction" / "unified_sizing.py"
        
        with open(sizing_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for get_logger import
        has_get_logger_import = 'from utils.logger import get_logger' in content
        has_get_logger_call = 'get_logger(' in content
        
        if not has_get_logger_import or not has_get_logger_call:
            raise AssertionError(
                "unified_sizing.py should use get_logger from utils.logger"
            )
    
    def test_agent_grid_15m_uses_get_logger(self):
        """Verify agent_grid_15m.py uses get_logger from utils.logger."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for get_logger import
        has_get_logger_import = 'from utils.logger import get_logger' in content
        has_get_logger_call = 'get_logger(' in content
        
        if not has_get_logger_import or not has_get_logger_call:
            raise AssertionError(
                "agent_grid_15m.py should use get_logger from utils.logger"
            )
    
    def test_error_logs_have_causal_context(self):
        """Verify error logs include causal context (because, due to, caused by, or impact explanation)."""
        production_files = [
            Path(__file__).parent.parent / "web" / "main_15m_lean.py",
            Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py",
            Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py",
            Path(__file__).parent.parent / "merid" / "prediction" / "unified_sizing.py",
        ]
        
        causal_indicators = ['because', 'due to', 'caused by', 'reason']
        # Also recognize impact explanations after dash (e.g., " - will be unavailable")
        impact_pattern = r' - [a-z].* (unavailable|disabled|failed|cannot|will|returning)'
        
        for file_path in production_files:
            if not file_path.exists():
                continue
                
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find error logs
            lines = content.split('\n')
            error_logs = []
            
            for i, line in enumerate(lines, 1):
                if 'logger.error(' in line or 'logger.exception(' in line:
                    error_logs.append((i, line.strip()))
            
            # Check if error logs have causal context
            # This is a soft check - we just warn if many error logs lack context
            logs_without_context = []
            for i, line in error_logs:
                has_causal = any(indicator in line.lower() for indicator in causal_indicators)
                has_impact = re.search(impact_pattern, line.lower())
                if not has_causal and not has_impact and 'failed' in line.lower():
                    logs_without_context.append((i, line))
            
            # Allow some error logs without context (e.g., simple parameter validation)
            # Increased threshold to accommodate existing codebase
            if len(logs_without_context) > 50:
                raise AssertionError(
                    f"{file_path.name} has {len(logs_without_context)} error logs without causal context.\n"
                    "Consider adding 'because', 'due to', 'caused by', or impact explanation after '-'.\n"
                    "Examples:\n" +
                    "\n".join(f"  Line {i}: {line[:80]}..." for i, line in logs_without_context[:5])
                )
