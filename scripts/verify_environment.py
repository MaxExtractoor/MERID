#!/usr/bin/env python3
"""
Phase 3: Environment Verification Script

Run this script to verify that the Python environment is correctly configured
for the kalshi_crypto_15m_v2 production profile.

Usage:
    py scripts/verify_environment.py
"""

import sys
import os
from pathlib import Path

def check_sys_path():
    """Check sys.path for multiple merid installations."""
    print("=" * 80)
    print("SYS.PATH ANALYSIS")
    print("=" * 80)
    
    merid_paths = []
    for i, path in enumerate(sys.path):
        if "merid" in path.lower():
            merid_paths.append((i, path))
            print(f"[{i}] {path}")
    
    if len(merid_paths) > 1:
        print(f"\n⚠️  WARNING: Multiple merid paths found ({len(merid_paths)})")
        print("This could cause module shadowing issues.")
    elif len(merid_paths) == 1:
        print(f"\n✓ Single merid path found")
    else:
        print(f"\n⚠️  No merid path found in sys.path")
    
    return merid_paths


def check_installed_packages():
    """Check for merid in site-packages."""
    print("\n" + "=" * 80)
    print("INSTALLED PACKAGES CHECK")
    print("=" * 80)
    
    try:
        import importlib.metadata
        try:
            dist = importlib.metadata.distribution("merid")
            print(f"⚠️  merid package found in site-packages:")
            print(f"   Location: {dist._path}")
            print(f"   Version: {dist.version}")
            return True
        except importlib.metadata.PackageNotFoundError:
            print("✓ No merid package in site-packages (good - using local source)")
            return False
    except Exception as e:
        print(f"Could not check installed packages: {e}")
        return None


def check_module_sources():
    """Check where critical modules are loaded from."""
    print("\n" + "=" * 80)
    print("MODULE SOURCE VERIFICATION")
    print("=" * 80)
    
    critical_modules = [
        ("merid", "Expected: local source"),
        ("merid.prediction.agent_grid_15m", "Expected: local source"),
        ("merid.loop_15m", "Expected: local source"),
        ("merid.event_venues.kalshi.market_catalog", "Expected: local source"),
        ("merid.event_venues.kalshi.bankroll_service_v2", "Expected: local source"),
        ("merid.event_venues.kalshi.client_v2", "Expected: local source"),
    ]
    
    issues = []
    for module_name, expectation in critical_modules:
        try:
            mod = __import__(module_name, fromlist=[""])
            mod_file = getattr(mod, "__file__", None)
            
            if mod_file:
                # Check if it's from site-packages
                if "site-packages" in mod_file.lower():
                    status = "⚠️  SHADOWED by site-packages"
                    issues.append((module_name, mod_file))
                elif "dist-packages" in mod_file.lower():
                    status = "⚠️  SHADOWED by dist-packages"
                    issues.append((module_name, mod_file))
                else:
                    status = "✓ Local source"
                
                print(f"{module_name}")
                print(f"  {status}")
                print(f"  Path: {mod_file}")
                print(f"  {expectation}")
            else:
                status = "⚠️  No __file__ attribute"
                print(f"{module_name}: {status}")
                issues.append((module_name, "No __file__"))
        except ImportError as e:
            status = "⚠️  Not importable"
            print(f"{module_name}: {status} - {e}")
            issues.append((module_name, str(e)))
        print()
    
    return issues


def check_environment_variables():
    """Check critical environment variables."""
    print("=" * 80)
    print("ENVIRONMENT VARIABLES")
    print("=" * 80)
    
    env_vars = {
        "MERID_PROFILE": "Required for production",
        "MERID_ALLOW_LIVE_TRADES": "Required for live trading",
        "KALSHI_ENV": "Required for Kalshi configuration",
        "PYTHONPATH": "Optional but affects imports",
    }
    
    for var, description in env_vars.items():
        value = os.environ.get(var, "<not set>")
        print(f"{var}={value}")
        print(f"  {description}")
    
    # Check profile
    profile = os.environ.get("MERID_PROFILE")
    if profile == "kalshi_crypto_15m_v2":
        print(f"\n✓ Profile is correctly set to kalshi_crypto_15m_v2")
    elif profile:
        print(f"\n⚠️  Profile is set to '{profile}' instead of 'kalshi_crypto_15m_v2'")
    else:
        print(f"\n⚠️  MERID_PROFILE is not set")


def check_working_directory():
    """Check current working directory."""
    print("\n" + "=" * 80)
    print("WORKING DIRECTORY")
    print("=" * 80)
    
    cwd = os.getcwd()
    print(f"Current directory: {cwd}")
    
    # Check if we're in the MERID repo
    if "MERID" in cwd or "merid" in cwd.lower():
        print("✓ Working directory appears to be MERID repo")
    else:
        print("⚠️  Working directory may not be MERID repo")


def check_git_root():
    """Check if we're in a git repository."""
    print("\n" + "=" * 80)
    print("GIT REPOSITORY CHECK")
    print("=" * 80)
    
    cwd = Path(os.getcwd())
    git_dir = cwd / ".git"
    
    if git_dir.exists():
        print("✓ .git directory found - in a git repository")
        print(f"   Git root: {cwd}")
    else:
        # Search up for .git
        for parent in cwd.parents:
            if (parent / ".git").exists():
                print(f"✓ .git directory found at {parent}")
                print(f"   Current dir: {cwd}")
                print(f"   Git root: {parent}")
                break
        else:
            print("⚠️  .git directory not found - may not be in git repository")


def main():
    print("\n" + "=" * 80)
    print("MERID ENVIRONMENT VERIFICATION")
    print("Phase 3: Profile & Environment Verification")
    print("=" * 80 + "\n")
    
    check_working_directory()
    check_git_root()
    check_environment_variables()
    merid_paths = check_sys_path()
    has_site_packages = check_installed_packages()
    module_issues = check_module_sources()
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    if len(merid_paths) > 1:
        print("⚠️  Multiple merid paths in sys.path - potential shadowing")
    
    if has_site_packages:
        print("⚠️  merid installed in site-packages - may shadow local source")
    
    if module_issues:
        print(f"⚠️  {len(module_issues)} module source issues detected")
        for module, issue in module_issues:
            print(f"   - {module}: {issue}")
    else:
        print("✓ All critical modules loaded from local source")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    if has_site_packages:
        print("1. Uninstall merid from site-packages:")
        print("   pip uninstall merid")
        print("2. Install local source in editable mode:")
        print("   pip install -e .")
    
    if len(merid_paths) > 1:
        print("3. Review sys.path and remove duplicate merid entries")
    
    if module_issues:
        print("4. Investigate module loading issues - check PYTHONPATH and installation")


if __name__ == "__main__":
    main()
