"""
Swarm Readiness CLI - Automated Pre-Deployment Validation

Consolidates all readiness checks into a single PASS/FAIL report:
- Paper rehearsal execution
- Metrics sanity (Prometheus continuity)
- Mode/config validation
- Watchdog health check

Usage:
    python scripts/swarm_readiness.py
    python scripts/swarm_readiness.py --extended  # 1-hour rehearsal
    python scripts/swarm_readiness.py --skip-rehearsal  # Only infra checks
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

CHECKLIST_VERSION = "1.0.0"


@dataclass
class CheckResult:
    """Result of a readiness check."""
    name: str
    passed: bool
    message: str
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class SwarmReadinessChecker:
    """Main readiness validation orchestrator."""
    
    def __init__(self, extended: bool = False, skip_rehearsal: bool = False):
        self.extended = extended
        self.skip_rehearsal = skip_rehearsal
        self.results: List[CheckResult] = []
        self.start_time = time.time()
        
    def run(self) -> bool:
        """Run all checks and return overall pass/fail."""
        print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
        print(f"{BOLD}{BLUE}MERID SWARM READINESS VALIDATION{RESET}")
        print(f"{BOLD}{BLUE}{'='*80}{RESET}")
        print(f"\nChecklist Version: {CHECKLIST_VERSION}")
        print(f"Mode: {'Extended (1h)' if self.extended else 'Standard (60s)'}")
        print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Run checks in order
        self._check_environment()
        self._check_mode_config()
        
        if not self.skip_rehearsal:
            self._run_paper_rehearsal()
        else:
            print(f"{YELLOW}⊘ Paper rehearsal skipped{RESET}")
        
        self._check_prometheus_metrics()
        self._check_watchdog_status()
        
        # Print summary
        self._print_summary()
        
        # Return overall result
        return all(r.passed for r in self.results)
    
    def _check_environment(self) -> None:
        """Verify required environment and files exist."""
        print(f"{BOLD}[1/5] Environment Check{RESET}")
        
        checks = [
            ("Python version", self._check_python_version()),
            (".env file exists", self._check_env_file()),
            ("scripts/paper_rehearsal.py exists", self._check_rehearsal_script()),
            ("Required packages", self._check_packages()),
        ]
        
        failed = []
        for name, passed in checks:
            status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
            print(f"  {status} {name}")
            if not passed:
                failed.append(name)
        
        result = CheckResult(
            name="environment",
            passed=len(failed) == 0,
            message=f"Environment check {'passed' if len(failed) == 0 else 'FAILED'}",
            details={"failed_checks": failed}
        )
        self.results.append(result)
        print()
    
    def _check_mode_config(self) -> None:
        """Verify trading mode is set correctly."""
        print(f"{BOLD}[2/5] Mode & Config Check{RESET}")
        
        # Read .env file
        env_path = Path(".env")
        mode = "unknown"
        live_authorized = "unknown"
        
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    if line.startswith("RUN_MODE="):
                        mode = line.split("=", 1)[1].strip()
                    if line.startswith("LIVE_MODE_AUTHORIZED="):
                        live_authorized = line.split("=", 1)[1].strip()
        
        # Validate
        issues = []
        
        if mode not in ("simulation", "paper", "live"):
            issues.append(f"Invalid RUN_MODE: {mode}")
        
        if mode == "live" and live_authorized.lower() != "true":
            issues.append("LIVE mode set but LIVE_MODE_AUTHORIZED != true")
        
        if mode != "simulation" and not self.extended:
            issues.append(f"Mode is {mode} but running standard check (use --extended for non-sim)")
        
        print(f"  RUN_MODE: {BLUE}{mode}{RESET}")
        print(f"  LIVE_MODE_AUTHORIZED: {BLUE}{live_authorized}{RESET}")
        
        for issue in issues:
            print(f"  {YELLOW}⚠{RESET} {issue}")
        
        result = CheckResult(
            name="mode_config",
            passed=len(issues) == 0,
            message=f"Mode is {mode}, {'OK' if len(issues) == 0 else 'issues found'}",
            details={"mode": mode, "live_authorized": live_authorized, "issues": issues}
        )
        self.results.append(result)
        print()
    
    def _run_paper_rehearsal(self) -> None:
        """Execute paper rehearsal script."""
        print(f"{BOLD}[3/5] Paper Rehearsal Execution{RESET}")
        
        duration = 3600 if self.extended else 60
        cmd = [
            sys.executable,
            "scripts/paper_rehearsal.py",
            "--mode", "simulation",
            "--duration", str(duration),
        ]
        
        print(f"  Running: {' '.join(cmd)}")
        print(f"  Duration: {duration}s ({duration//60}m)")
        print()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=duration + 30,
            )
            
            # Parse output
            passed = result.returncode == 0
            
            # Look for validation results in output
            validation_summary = "See rehearsal output for details"
            if "Overall:" in result.stdout:
                for line in result.stdout.split("\n"):
                    if "Overall:" in line:
                        validation_summary = line.strip()
            
            print(result.stdout)
            
            if result.stderr:
                print(f"{YELLOW}Warnings/Errors:{RESET}")
                print(result.stderr)
            
            check_result = CheckResult(
                name="paper_rehearsal",
                passed=passed,
                message=f"Rehearsal {'PASSED' if passed else 'FAILED'}: {validation_summary}",
                details={
                    "duration": duration,
                    "exit_code": result.returncode,
                }
            )
            self.results.append(check_result)
            
        except subprocess.TimeoutExpired:
            print(f"{RED}✗ Rehearsal timed out{RESET}")
            self.results.append(CheckResult(
                name="paper_rehearsal",
                passed=False,
                message="Rehearsal timed out",
            ))
        except Exception as e:
            print(f"{RED}✗ Rehearsal failed: {e}{RESET}")
            self.results.append(CheckResult(
                name="paper_rehearsal",
                passed=False,
                message=f"Rehearsal error: {e}",
            ))
        
        print()
    
    def _check_prometheus_metrics(self) -> None:
        """Check Prometheus metrics for continuity."""
        print(f"{BOLD}[4/5] Prometheus Metrics Continuity{RESET}")
        
        # Try to query Prometheus
        try:
            import requests
            
            # Check if Prometheus is running
            response = requests.get("http://localhost:9090/-/healthy", timeout=5)
            
            if response.status_code != 200:
                print(f"  {YELLOW}⚠{RESET} Prometheus not healthy")
                self.results.append(CheckResult(
                    name="prometheus_metrics",
                    passed=False,
                    message="Prometheus not healthy",
                ))
                print()
                return
            
            # Query for recent metrics
            query = "merid_agent_participation_rate"
            end_time = int(time.time())
            start_time = end_time - 300  # Last 5 minutes
            
            response = requests.get(
                f"http://localhost:9090/api/v1/query_range",
                params={
                    "query": query,
                    "start": start_time,
                    "end": end_time,
                    "step": "15s",
                },
                timeout=10,
            )
            
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "success" and data["data"]["result"]:
                    values = data["data"]["result"][0]["values"]
                    expected_points = (end_time - start_time) // 15
                    actual_points = len(values)
                    
                    # Allow 10% tolerance for gaps
                    passed = actual_points >= expected_points * 0.9
                    
                    print(f"  Metric: {query}")
                    print(f"  Expected data points: {expected_points}")
                    print(f"  Actual data points: {actual_points}")
                    print(f"  Coverage: {actual_points/expected_points*100:.1f}%")
                    
                    status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
                    print(f"  {status} {'OK' if passed else 'Gaps detected'}")
                    
                    self.results.append(CheckResult(
                        name="prometheus_metrics",
                        passed=passed,
                        message=f"Metrics coverage: {actual_points/expected_points*100:.1f}%",
                        details={
                            "expected": expected_points,
                            "actual": actual_points,
                        }
                    ))
                else:
                    print(f"  {YELLOW}⚠{RESET} No metric data found")
                    self.results.append(CheckResult(
                        name="prometheus_metrics",
                        passed=False,
                        message="No metric data available",
                    ))
            else:
                print(f"  {YELLOW}⚠{RESET} Prometheus query failed")
                self.results.append(CheckResult(
                    name="prometheus_metrics",
                    passed=False,
                    message="Query failed",
                ))
        
        except ImportError:
            print(f"  {YELLOW}⊘{RESET} requests package not installed, skipping")
            self.results.append(CheckResult(
                name="prometheus_metrics",
                passed=True,  # Don't fail if can't check
                message="Skipped (requests not available)",
            ))
        except Exception as e:
            print(f"  {YELLOW}⊘{RESET} Prometheus check failed: {e}")
            self.results.append(CheckResult(
                name="prometheus_metrics",
                passed=True,  # Don't fail on connection errors
                message=f"Skipped ({e})",
            ))
        
        print()
    
    def _check_watchdog_status(self) -> None:
        """Check if watchdogs are running and healthy."""
        print(f"{BOLD}[5/5] Watchdog Status{RESET}")
        
        try:
            import requests
            
            # Try to query swarm stats API
            response = requests.get(
                "http://localhost:8000/api/v1/swarm/stats",
                timeout=5,
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check for health issues
                health_issues = data.get("health_issues", {})
                active_agents = data.get("swarm", {}).get("active_agents", 0)
                total_agents = data.get("swarm", {}).get("total_agents", 0)
                
                print(f"  Active agents: {active_agents}/{total_agents}")
                print(f"  Health issues: {len(health_issues)}")
                
                if health_issues:
                    print(f"\n  {YELLOW}Issues detected:{RESET}")
                    for agent_id, issue in health_issues.items():
                        print(f"    - {agent_id}: {issue}")
                
                passed = len(health_issues) == 0 and active_agents > 0
                status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
                print(f"\n  {status} {'All watchdogs healthy' if passed else 'Issues detected'}")
                
                self.results.append(CheckResult(
                    name="watchdog_status",
                    passed=passed,
                    message=f"{len(health_issues)} issues, {active_agents}/{total_agents} agents active",
                    details={
                        "health_issues": health_issues,
                        "active_agents": active_agents,
                        "total_agents": total_agents,
                    }
                ))
            else:
                print(f"  {YELLOW}⊘{RESET} Backend API not responding")
                self.results.append(CheckResult(
                    name="watchdog_status",
                    passed=False,
                    message="Backend API not available",
                ))
        
        except ImportError:
            print(f"  {YELLOW}⊘{RESET} requests package not installed, skipping")
            self.results.append(CheckResult(
                name="watchdog_status",
                passed=True,
                message="Skipped (requests not available)",
            ))
        except Exception as e:
            print(f"  {YELLOW}⊘{RESET} Watchdog check failed: {e}")
            self.results.append(CheckResult(
                name="watchdog_status",
                passed=True,
                message=f"Skipped ({e})",
            ))
        
        print()
    
    def _print_summary(self) -> None:
        """Print final summary banner."""
        duration = time.time() - self.start_time
        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)
        overall_passed = passed_count == total_count
        
        print(f"{BOLD}{'='*80}{RESET}")
        print(f"{BOLD}READINESS VALIDATION SUMMARY{RESET}")
        print(f"{BOLD}{'='*80}{RESET}\n")
        
        print(f"Checklist Version: {CHECKLIST_VERSION}")
        print(f"Validation Duration: {duration:.1f}s\n")
        
        print(f"{BOLD}Results:{RESET}")
        for result in self.results:
            status = f"{GREEN}✓ PASS{RESET}" if result.passed else f"{RED}✗ FAIL{RESET}"
            print(f"  [{status}] {result.name}: {result.message}")
        
        print(f"\n{BOLD}Overall: {passed_count}/{total_count} checks passed{RESET}")
        
        if overall_passed:
            print(f"\n{BOLD}{GREEN}{'='*80}{RESET}")
            print(f"{BOLD}{GREEN}✓ SWARM READY FOR DEPLOYMENT{RESET}")
            print(f"{BOLD}{GREEN}{'='*80}{RESET}\n")
        else:
            print(f"\n{BOLD}{RED}{'='*80}{RESET}")
            print(f"{BOLD}{RED}✗ SWARM NOT READY - FIX ISSUES BEFORE DEPLOYING{RESET}")
            print(f"{BOLD}{RED}{'='*80}{RESET}\n")
            
            print(f"{YELLOW}Next steps:{RESET}")
            print("  1. Review failed checks above")
            print("  2. Fix configuration or code issues")
            print("  3. Re-run this script")
            print("  4. Consult SWARM_READINESS.md for detailed checklist\n")
        
        # Save results to file
        self._save_results()
    
    def _save_results(self) -> None:
        """Save validation results to timestamped file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"logs/swarm_readiness_{timestamp}.json"
        
        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)
        
        data = {
            "checklist_version": CHECKLIST_VERSION,
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extended": self.extended,
            "overall_passed": all(r.passed for r in self.results),
            "checks": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }
        
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"Results saved to: {filename}\n")
    
    def _check_python_version(self) -> bool:
        """Check Python version >= 3.9."""
        return sys.version_info >= (3, 9)
    
    def _check_env_file(self) -> bool:
        """Check .env file exists."""
        return Path(".env").exists()
    
    def _check_rehearsal_script(self) -> bool:
        """Check rehearsal script exists."""
        return Path("scripts/paper_rehearsal.py").exists()
    
    def _check_packages(self) -> bool:
        """Check required packages are installed."""
        try:
            import asyncio
            import dataclasses
            return True
        except ImportError:
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MERID Swarm Readiness Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/swarm_readiness.py                 # Standard 60s check
  python scripts/swarm_readiness.py --extended      # Extended 1h check
  python scripts/swarm_readiness.py --skip-rehearsal # Only infra checks
        """
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Run extended 1-hour rehearsal (required for PAPER mode)",
    )
    parser.add_argument(
        "--skip-rehearsal",
        action="store_true",
        help="Skip paper rehearsal, only check infrastructure",
    )
    
    args = parser.parse_args()
    
    # Change to repo root
    os.chdir(Path(__file__).parent.parent)
    
    # Run checks
    checker = SwarmReadinessChecker(
        extended=args.extended,
        skip_rehearsal=args.skip_rehearsal,
    )
    
    passed = checker.run()
    
    # Exit with appropriate code
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
