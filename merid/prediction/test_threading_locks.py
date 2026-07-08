"""Test that threading locks are properly enabled in the prediction layer.

CRITICAL FIX (2026-07-07): Previously disabled threading locks were causing race conditions
in production. This test verifies locks are enabled by inspecting the source code directly,
avoiding complex initialization that might hang during testing.

Files fixed:
- merid/prediction/sentiment_floor_tracker.py
- merid/prediction/risk/_prediction_risk.py (2 locks)
- merid/prediction/risk/sentiment_vol_service.py (2 locks)
- merid/prediction/kalshi_strike_calibrator.py
- merid/prediction/high_performance_calibration.py
- merid/prediction/dynamic_edge_calibrator.py
- merid/prediction/alerts.py
"""

import threading
import re

import pytest


def test_sentiment_floor_tracker_lock_enabled():
    """Test that SentimentFloorTracker has threading lock enabled in source."""
    with open("merid/prediction/sentiment_floor_tracker.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: Lock must be initialized as threading.Lock(), not None
    assert "_lock: threading.Lock = threading.Lock()" in content, \
        "SentimentFloorTracker._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "_lock = None" not in content, \
        "SentimentFloorTracker._lock must NOT be set to None"
    
    # CRITICAL: Must NOT have conditional lock checks
    assert "if self._lock is not None:" not in content, \
        "SentimentFloorTracker must NOT have conditional lock checks"


def test_prediction_risk_rate_lock_enabled():
    """Test that PredictionRisk rate lock is enabled in source."""
    with open("merid/prediction/risk/_prediction_risk.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: Rate lock must be initialized as threading.Lock()
    assert "self._rate_lock = threading.Lock()" in content, \
        "PredictionRisk._rate_lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "self._rate_lock = None" not in content, \
        "PredictionRisk._rate_lock must NOT be set to None"


def test_prediction_risk_cycle_cap_lock_enabled():
    """Test that CycleCapTracker lock is enabled in source."""
    with open("merid/prediction/risk/_prediction_risk.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: CycleCapTracker lock must be initialized as threading.Lock()
    assert "self._lock = threading.Lock()" in content, \
        "CycleCapTracker._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern for CycleCapTracker
    # Check that the line is not in the CycleCapTracker class
    lines = content.split('\n')
    in_cycle_cap = False
    for line in lines:
        if 'class CycleCapTracker' in line:
            in_cycle_cap = True
        elif in_cycle_cap and 'class ' in line and 'CycleCapTracker' not in line:
            in_cycle_cap = False
        elif in_cycle_cap and 'self._lock = None' in line:
            assert False, "CycleCapTracker._lock must NOT be set to None"


def test_sentiment_vol_service_locks_enabled():
    """Test that SentimentVolService has both locks enabled in source."""
    with open("merid/prediction/risk/sentiment_vol_service.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Filter out docstrings
    lines = content.split('\n')
    code_lines = []
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if '"""' in stripped or "'''" in stripped:
            in_docstring = not in_docstring
        elif not in_docstring and not stripped.startswith('#'):
            code_lines.append(line)
    code_content = '\n'.join(code_lines)
    
    # CRITICAL: Class lock must be initialized as threading.Lock()
    assert "_lock = threading.Lock()" in code_content, \
        "SentimentVolService._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Asset lock must be initialized as threading.RLock()
    assert "self._asset_lock = threading.RLock()" in code_content, \
        "SentimentVolService._asset_lock must be initialized as threading.RLock()"
    
    # CRITICAL: Must NOT have disabled lock patterns
    assert "_lock = None" not in code_content, \
        "SentimentVolService._lock must NOT be set to None"
    assert "_asset_lock = None" not in code_content, \
        "SentimentVolService._asset_lock must NOT be set to None"


def test_kalshi_strike_calibrator_lock_enabled():
    """Test that KalshiStrikeCalibrator has lock enabled in source."""
    with open("merid/prediction/kalshi_strike_calibrator.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: Lock must be initialized as threading.Lock()
    assert "self._lock = threading.Lock()" in content, \
        "KalshiStrikeCalibrator._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "self._lock = None" not in content, \
        "KalshiStrikeCalibrator._lock must NOT be set to None"


def test_high_performance_calibration_lock_enabled():
    """Test that HighPerformanceCalibration has lock enabled in source."""
    with open("merid/prediction/high_performance_calibration.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: Lock must be initialized as threading.Lock()
    assert "self._lock = threading.Lock()" in content, \
        "HighPerformanceCalibration._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "self._lock = None" not in content, \
        "HighPerformanceCalibration._lock must NOT be set to None"


def test_dynamic_edge_calibrator_lock_enabled():
    """Test that DynamicEdgeCalibrator has lock enabled in source."""
    with open("merid/prediction/dynamic_edge_calibrator.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # CRITICAL: Lock must be initialized as threading.Lock()
    assert "self._cache_lock = threading.Lock()" in content, \
        "DynamicEdgeCalibrator._cache_lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "_cache_lock = None" not in content, \
        "DynamicEdgeCalibrator._cache_lock must NOT be set to None"


def test_alerts_lock_enabled():
    """Test that AlertManager has lock enabled in source."""
    with open("merid/prediction/alerts.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Filter out docstrings
    lines = content.split('\n')
    code_lines = []
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if '"""' in stripped or "'''" in stripped:
            in_docstring = not in_docstring
        elif not in_docstring and not stripped.startswith('#'):
            code_lines.append(line)
    code_content = '\n'.join(code_lines)
    
    # CRITICAL: Lock must be initialized as threading.Lock()
    assert "self._lock = threading.Lock()" in code_content, \
        "AlertManager._lock must be initialized as threading.Lock()"
    
    # CRITICAL: Must NOT have disabled lock pattern
    assert "self._lock = None" not in code_content, \
        "AlertManager._lock must NOT be set to None"
    
    # CRITICAL: Must NOT have conditional lock checks in actual code
    assert "if self._lock is not None:" not in code_content, \
        "AlertManager must NOT have conditional lock checks in code"


def test_no_disabled_lock_patterns():
    """Test that no disabled lock patterns exist across all fixed files."""
    files_to_check = [
        "merid/prediction/sentiment_floor_tracker.py",
        "merid/prediction/risk/_prediction_risk.py",
        "merid/prediction/risk/sentiment_vol_service.py",
        "merid/prediction/kalshi_strike_calibrator.py",
        "merid/prediction/high_performance_calibration.py",
        "merid/prediction/dynamic_edge_calibrator.py",
        "merid/prediction/alerts.py",
    ]
    
    # Only check code patterns, not comments/docstrings
    disabled_patterns = [
        "TEMPORARILY DISABLED",
        "TODO: Re-enable lock",
        "= None  # Disabled",
    ]
    
    for filepath in files_to_check:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Filter out docstrings and comments
        lines = content.split('\n')
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if '"""' in stripped or "'''" in stripped:
                in_docstring = not in_docstring
            elif not in_docstring and not stripped.startswith('#'):
                code_lines.append(line)
        
        code_content = '\n'.join(code_lines)
        
        for pattern in disabled_patterns:
            assert pattern not in code_content, \
                f"{filepath} must NOT contain disabled lock pattern in code: {pattern}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
