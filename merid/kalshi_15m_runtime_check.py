"""
Kalshi 15m Production Runtime Check

This module provides production invariants validation for the kalshi_crypto_15m_v2 profile.
It ensures the system is in a valid state for live trading by checking:
- Correct profile and environment configuration
- No legacy subsystems are imported
- Startup state is healthy
- Required components are initialized

Usage:
    from merid.kalshi_15m_runtime_check import check_15m_production_invariants
    check_15m_production_invariants()
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

# Ensure project root is on sys.path when this file is run as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from typing import Dict, Any

# Load .env / settings first so standalone runs see MERID_PROFILE and other env vars.
try:
    from merid import settings as merid_settings
except Exception:
    merid_settings = None


def check_profile_and_env() -> tuple[bool, str]:
    """Verify correct profile and Kalshi base URL configuration."""
    if merid_settings is not None:
        profile = merid_settings.settings.MERID_PROFILE
    else:
        profile = os.getenv("MERID_PROFILE", "")
    if profile != "kalshi_crypto_15m_v2":
        return False, f"Invalid profile '{profile}'. Expected 'kalshi_crypto_15m_v2'"
    
    # Check Kalshi base URL matches expectation
    try:
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url
        base_url = get_kalshi_base_url()
        is_demo = "demo" in base_url.lower()
        
        # For production, we expect live URL (not demo)
        # For paper trading, demo is acceptable
        trade_mode = os.getenv("MERID_TRADE_MODE", "paper")
        if trade_mode == "live" and is_demo:
            return False, f"Live trade mode requires live Kalshi URL, got demo: {base_url}"
        
        return True, f"Profile OK: {profile}, Mode: {trade_mode}, Kalshi: {'demo' if is_demo else 'live'}"
    except Exception as e:
        return False, f"Failed to check Kalshi base URL: {e}"


def check_no_legacy_subsystems() -> tuple[bool, str]:
    """Verify legacy subsystems are not imported for this profile."""
    # Check that known legacy modules are not in sys.modules
    legacy_modules = [
        "merid.prediction.paper_session",
        "merid.agents.reflection.integration",
        "merid.agents.base.CanonicalAgentRegistry",
    ]
    
    imported_legacy = []
    for module in legacy_modules:
        if module in sys.modules:
            imported_legacy.append(module)
    
    if imported_legacy:
        return False, f"Legacy modules imported: {imported_legacy}"
    
    return True, "No legacy subsystems imported"


def check_startup_state() -> tuple[bool, str]:
    """Verify startup state is healthy (only when called from the running server)."""
    if "web.startup_state" not in sys.modules:
        return True, "Startup state check skipped (standalone run)"

    try:
        from web.startup_state import startup_state

        if not startup_state.started:
            return False, "Startup not started"

        if startup_state.failed:
            return False, f"Startup failed: {startup_state.error}"

        if not startup_state.completed:
            return False, "Startup not completed"

        return True, "Startup state healthy"
    except Exception as e:
        return False, f"Failed to check startup state: {e}"


def check_app_state_components() -> tuple[bool, str]:
    """Verify required app.state components are initialized (only when called from the running server)."""
    if "web.main_15m_lean" not in sys.modules:
        return True, "App state check skipped (standalone run)"

    try:
        from web.main_15m_lean import app

        grid = getattr(app.state, "agent_grid_15m", None)
        loop = getattr(app.state, "loop_15m", None)

        if grid is None:
            return False, "agent_grid_15m not initialized"

        if loop is None:
            return False, "loop_15m not initialized"

        # Check loop status
        is_running = getattr(loop, "is_running", False)
        if not is_running:
            return False, "loop_15m not running"

        return True, f"App state OK: grid={type(grid).__name__}, loop_running={is_running}"
    except Exception as e:
        return False, f"Failed to check app state: {e}"


def check_unified_edge_config() -> tuple[bool, str]:
    """Verify unified edge configuration is valid (only when called from the running server)."""
    if "web.main_15m_lean" not in sys.modules:
        return True, "Unified edge config check skipped (standalone run)"

    try:
        from web.main_15m_lean import UnifiedEdgeConfig

        config = UnifiedEdgeConfig.from_env()
        is_valid, error_msg = config.validate()

        if not is_valid:
            return False, f"Unified edge config invalid: {error_msg}"

        return True, f"Unified edge config OK: enabled={config.enabled}, calibration_version={config.calibration_version}, shadow_mode={config.shadow_mode}"
    except Exception as e:
        return False, f"Failed to check unified edge config: {e}"


def check_agent_config_consistency() -> tuple[bool, str]:
    """Verify agent grid configuration matches expected 5 agents."""
    try:
        import yaml
        
        # Load kalshi_agent_grid.yaml
        config_path = "config/kalshi_agent_grid.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        
        # Extract agent names
        agents = config.get("agents", [])
        agent_names = [a.get("name") for a in agents if a.get("enabled", False)]
        
        # Expected agents for kalshi_crypto_15m_v2
        expected_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        actual_agents = set(agent_names)
        
        if actual_agents != expected_agents:
            return False, f"Agent config mismatch: expected {expected_agents}, got {actual_agents}"
        
        if len(agent_names) != 5:
            return False, f"Expected exactly 5 enabled agents, got {len(agent_names)}"
        
        return True, f"Agent config OK: {sorted(agent_names)}"
    except Exception as e:
        return False, f"Failed to check agent config consistency: {e}"


def check_15m_production_invariants() -> Dict[str, Any]:
    """
    Run all production invariants checks for kalshi_crypto_15m_v2.
    
    Returns a dictionary with check results:
    {
        "all_passed": bool,
        "checks": {
            "profile_and_env": {"passed": bool, "message": str},
            "no_legacy_subsystems": {"passed": bool, "message": str},
            "startup_state": {"passed": bool, "message": str},
            "app_state_components": {"passed": bool, "message": str},
        }
    }
    """
    results = {
        "all_passed": True,
        "checks": {}
    }
    
    checks = [
        ("profile_and_env", check_profile_and_env),
        ("no_legacy_subsystems", check_no_legacy_subsystems),
        ("startup_state", check_startup_state),
        ("app_state_components", check_app_state_components),
        ("unified_edge_config", check_unified_edge_config),
        ("agent_config_consistency", check_agent_config_consistency),
    ]
    
    for check_name, check_func in checks:
        passed, message = check_func()
        results["checks"][check_name] = {
            "passed": passed,
            "message": message
        }
        if not passed:
            results["all_passed"] = False
    
    return results


def print_15m_production_check() -> None:
    """Print production invariants check results to stdout."""
    results = check_15m_production_invariants()
    
    print("=" * 60)
    print("Kalshi 15m Production Invariants Check")
    print("=" * 60)
    
    for check_name, check_result in results["checks"].items():
        status = "✓ PASS" if check_result["passed"] else "✗ FAIL"
        print(f"{status:8} {check_name:25} - {check_result['message']}")
    
    print("=" * 60)
    if results["all_passed"]:
        print("All checks passed - system is production-ready")
    else:
        print("Some checks failed - system is NOT production-ready")
    print("=" * 60)


if __name__ == "__main__":
    print_15m_production_check()
