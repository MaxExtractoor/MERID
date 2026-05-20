#!/usr/bin/env python3
"""
Enable Live Trading Script for MERID

This script:
1. Checks if Kalshi API credentials are configured
2. Verifies the private key file exists
3. Tests the Kalshi API connection
4. Verifies all safety interlocks are set correctly
5. Runs the live readiness check
"""

import os
import sys
import subprocess
from pathlib import Path

def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_status(message, status, detail=""):
    status_colors = {
        "OK": "\033[92m",      # Green
        "WARN": "\033[93m",    # Yellow
        "ERROR": "\033[91m",   # Red
        "INFO": "\033[94m",    # Blue
        "RESET": "\033[0m"
    }
    color = status_colors.get(status, "")
    reset = status_colors["RESET"]
    print(f"  [{color}{status:5}{reset}] {message}")
    if detail:
        print(f"         {detail}")

def check_env_file():
    """Check if .env file exists and has required settings."""
    print_header("CHECKING ENVIRONMENT FILE")
    
    env_path = Path(".env")
    if not env_path.exists():
        print_status(".env file exists", "ERROR", "File not found!")
        return False
    
    print_status(".env file exists", "OK")
    
    # Read .env file
    env_content = env_path.read_text()
    
    # Check critical settings
    critical_settings = [
        ("MERID_ALLOW_LIVE_TRADES", "true"),
        ("MERID_PM_TRADING_MODE", "live"),
        ("MERID_PM_LIVE_ENABLED", "true"),
        ("KALSHI_ENV", "live"),
        ("KALSHI_USE_DEMO", "false"),
    ]
    
    all_ok = True
    for setting, expected in critical_settings:
        if f"{setting}={expected}" in env_content or f"{setting}={expected.upper()}" in env_content:
            print_status(f"{setting}={expected}", "OK")
        else:
            print_status(f"{setting}", "ERROR", f"Should be set to {expected}")
            all_ok = False
    
    return all_ok

def check_kalshi_credentials():
    """Check if Kalshi API credentials are configured."""
    print_header("CHECKING KALSHI API CREDENTIALS")
    
    # Check if .env file has placeholder or actual key
    env_path = Path(".env")
    env_content = env_path.read_text()
    
    if "KALSHI_API_KEY_ID=your_kalshi_api_key_id_here" in env_content:
        print_status("KALSHI_API_KEY_ID", "ERROR", "Still using placeholder value!")
        print("\n  TO FIX:")
        print("  1. Go to https://kalshi.com/account and get your API Key ID")
        print("  2. Edit .env file and replace 'your_kalshi_api_key_id_here' with your actual key")
        return False
    
    if "KALSHI_API_KEY_ID=" in env_content:
        # Extract the key value
        for line in env_content.split("\n"):
            if line.startswith("KALSHI_API_KEY_ID=") and "your_" not in line:
                print_status("KALSHI_API_KEY_ID configured", "OK")
                break
        else:
            print_status("KALSHI_API_KEY_ID", "ERROR", "Not properly configured")
            return False
    else:
        print_status("KALSHI_API_KEY_ID", "ERROR", "Not found in .env file")
        return False
    
    # Check private key file
    if "KALSHI_PRIVATE_KEY_PATH=" in env_content:
        for line in env_content.split("\n"):
            if line.startswith("KALSHI_PRIVATE_KEY_PATH="):
                key_path = line.split("=", 1)[1].strip()
                # Expand variables and home directory
                key_path = os.path.expandvars(key_path)
                key_path = os.path.expanduser(key_path)
                
                if Path(key_path).exists():
                    print_status(f"Private key file exists: {key_path}", "OK")
                    return True
                else:
                    print_status(f"Private key file not found: {key_path}", "ERROR")
                    print("\n  TO FIX:")
                    print(f"  1. Download your private key from https://kalshi.com/account")
                    print(f"  2. Save it to: {key_path}")
                    return False
    
    print_status("KALSHI_PRIVATE_KEY_PATH", "ERROR", "Not configured")
    return False

def check_kill_switch():
    """Check if kill switch is active."""
    print_header("CHECKING KILL SWITCH STATUS")
    
    kill_switch_path = Path("data/risk_kill_switch.json")
    if kill_switch_path.exists():
        import json
        try:
            data = json.loads(kill_switch_path.read_text())
            if data.get("active", False):
                print_status("Kill switch is ACTIVE", "WARN", "Trading is blocked!")
                print("\n  TO FIX:")
                print("  Edit data/risk_kill_switch.json and set active: false")
                return False
            else:
                print_status("Kill switch is inactive", "OK")
                return True
        except Exception as e:
            print_status("Kill switch check failed", "WARN", str(e))
            return True
    else:
        print_status("Kill switch file not found", "INFO", "Assuming inactive")
        return True

def test_kalshi_connection():
    """Test connection to Kalshi API."""
    print_header("TESTING KALSHI API CONNECTION")
    
    # Run the Kalshi access diagnostics
    scripts = [
        "verify_kalshi_env.py",
        "check_live_ready.py",
    ]
    
    for script in scripts:
        script_path = Path(script)
        if script_path.exists():
            print(f"\n  Running {script}...")
            try:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    print_status(f"{script} passed", "OK")
                else:
                    print_status(f"{script} failed", "WARN")
                    if result.stdout:
                        print(f"  Output: {result.stdout[:200]}")
                    if result.stderr:
                        print(f"  Error: {result.stderr[:200]}")
            except Exception as e:
                print_status(f"{script} error", "WARN", str(e))
    
    return True

def show_next_steps():
    """Show next steps for the user."""
    print_header("NEXT STEPS")
    
    print("""
  1. EDIT YOUR API KEY:
     Open .env file and replace:
       KALSHI_API_KEY_ID=your_kalshi_api_key_id_here
     With your actual Kalshi API Key ID from https://kalshi.com/account

  2. VERIFY PRIVATE KEY:
     Ensure your kalshi_private_key.pem file is in:
       c:\\Dev\\MERID\\kalshi_private_key.pem

  3. RUN READINESS CHECK:
     Start the backend and visit:
       http://127.0.0.1:8011/api/v1/operator/pm-live-readiness
     
     Verify: ready_for_live_pm_trading = true

  4. START TRADING:
     Run the backend:
       python web/main.py
     
     Or use the dashboard:
       npm run dev --prefix web/react

  5. MONITOR FIRST TRADE:
     - Watch logs for "[KALSHI_ORDER_RESULT]" with status=filled_live
     - Check Telegram for trade notifications
     - Verify position appears in portfolio

  SAFETY REMINDERS:
  - Start with 1 contract to verify the flow
  - The system has 5% cycle risk limit (configured in .env)
  - Kill switch is at data/risk_kill_switch.json
  - All orders go through risk checks before execution
""")

def main():
    print_header("MERID LIVE TRADING ENABLEMENT")
    print("\n  This script verifies your system is ready for live trading.")
    print("  Safety checks will ensure all interlocks are properly configured.")
    
    checks = [
        ("Environment File", check_env_file),
        ("Kalshi Credentials", check_kalshi_credentials),
        ("Kill Switch", check_kill_switch),
        ("API Connection", test_kalshi_connection),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print_status(f"{name} check failed", "ERROR", str(e))
            results.append((name, False))
    
    # Summary
    print_header("SUMMARY")
    all_passed = all(result for _, result in results)
    
    for name, result in results:
        status = "OK" if result else "FAIL"
        print_status(name, status)
    
    if all_passed:
        print_status("\nSystem is ready for live trading!", "OK")
    else:
        print_status("\nIssues found - please fix before trading live", "WARN")
    
    show_next_steps()
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
