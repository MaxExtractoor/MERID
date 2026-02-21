"""
Dev Swarm Integration Validation Script

Verifies that Dev Swarm is fully integrated and operational.
Run this after deployment to ensure everything works.

Usage:
    python scripts/validate_dev_swarm.py
    python scripts/validate_dev_swarm.py --quick  # Skip long-running tests
"""

import asyncio
import sys
import time
import argparse
from typing import List, Tuple
import httpx

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

API_BASE = "http://localhost:8000/api/dev-swarm"
TIMEOUT = 10.0


class ValidationResult:
    """Result of a validation check."""
    def __init__(self, name: str, passed: bool, message: str = ""):
        self.name = name
        self.passed = passed
        self.message = message


async def check_api_health() -> ValidationResult:
    """Check if Dev Swarm API is responding."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{API_BASE}/health")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["healthy", "degraded"]:
                    return ValidationResult("API Health Check", True, f"Status: {data['status']}")
                else:
                    return ValidationResult("API Health Check", False, f"Unexpected status: {data.get('status')}")
            else:
                return ValidationResult("API Health Check", False, f"HTTP {response.status_code}")
    except Exception as e:
        return ValidationResult("API Health Check", False, f"Connection failed: {e}")


async def check_agents_registered() -> ValidationResult:
    """Check if agents are registered."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{API_BASE}/agents")
            
            if response.status_code == 200:
                agents = response.json()
                if len(agents) >= 4:  # Expecting Planner, Coder, Tester, Reviewer
                    agent_names = [a['name'] for a in agents]
                    return ValidationResult(
                        "Agent Registration",
                        True,
                        f"Found {len(agents)} agents: {', '.join(agent_names)}"
                    )
                else:
                    return ValidationResult(
                        "Agent Registration",
                        False,
                        f"Only {len(agents)} agents registered (expected ≥4)"
                    )
            else:
                return ValidationResult("Agent Registration", False, f"HTTP {response.status_code}")
    except Exception as e:
        return ValidationResult("Agent Registration", False, f"Error: {e}")


async def check_stats_endpoint() -> ValidationResult:
    """Check if stats endpoint works."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{API_BASE}/stats")
            
            if response.status_code == 200:
                stats = response.json()
                required_fields = [
                    "active_tasks", "total_tasks", "completed", "failed",
                    "success_rate", "avg_duration_seconds", "daily_cost_usd"
                ]
                
                if all(field in stats for field in required_fields):
                    return ValidationResult(
                        "Stats Endpoint",
                        True,
                        f"Active: {stats['active_tasks']}, Total: {stats['total_tasks']}"
                    )
                else:
                    missing = [f for f in required_fields if f not in stats]
                    return ValidationResult(
                        "Stats Endpoint",
                        False,
                        f"Missing fields: {', '.join(missing)}"
                    )
            else:
                return ValidationResult("Stats Endpoint", False, f"HTTP {response.status_code}")
    except Exception as e:
        return ValidationResult("Stats Endpoint", False, f"Error: {e}")


async def check_task_creation() -> ValidationResult:
    """Check if task creation works."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Create a minimal test task
            task_data = {
                "description": "Validation test task - safe to ignore",
                "target_files": ["scripts/validate_dev_swarm.py"],
                "success_criteria": "Validation test passes",
                "priority": 5,
                "estimated_effort": "small",
                "timeout_seconds": 60,
                "max_cost_usd": 0.1
            }
            
            response = await client.post(f"{API_BASE}/tasks", json=task_data)
            
            if response.status_code == 201:
                task = response.json()
                task_id = task.get("task_id")
                
                if task_id:
                    return ValidationResult(
                        "Task Creation",
                        True,
                        f"Created task {task_id}"
                    )
                else:
                    return ValidationResult("Task Creation", False, "No task_id in response")
            else:
                error = response.json().get("detail", "Unknown error")
                return ValidationResult("Task Creation", False, f"HTTP {response.status_code}: {error}")
    except Exception as e:
        return ValidationResult("Task Creation", False, f"Error: {e}")


async def check_task_listing() -> ValidationResult:
    """Check if task listing works."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{API_BASE}/tasks")
            
            if response.status_code == 200:
                data = response.json()
                if "tasks" in data and "total" in data:
                    return ValidationResult(
                        "Task Listing",
                        True,
                        f"Found {data['total']} tasks"
                    )
                else:
                    return ValidationResult("Task Listing", False, "Invalid response format")
            else:
                return ValidationResult("Task Listing", False, f"HTTP {response.status_code}")
    except Exception as e:
        return ValidationResult("Task Listing", False, f"Error: {e}")


async def check_config_endpoint() -> ValidationResult:
    """Check if config endpoint works."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Try to update config (no-op)
            response = await client.post(f"{API_BASE}/config")
            
            if response.status_code == 200:
                return ValidationResult("Config Endpoint", True, "Endpoint responding")
            else:
                return ValidationResult("Config Endpoint", False, f"HTTP {response.status_code}")
    except Exception as e:
        return ValidationResult("Config Endpoint", False, f"Error: {e}")


async def check_safety_limits() -> ValidationResult:
    """Check if safety limits are enforced."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            stats = await client.get(f"{API_BASE}/stats")
            
            if stats.status_code == 200:
                data = stats.json()
                
                # Check if cost tracking is present
                if "daily_cost_usd" in data and "cost_budget_remaining" in data:
                    return ValidationResult(
                        "Safety Limits",
                        True,
                        f"Cost tracking: ${data['daily_cost_usd']:.2f} / budget"
                    )
                else:
                    return ValidationResult("Safety Limits", False, "Cost tracking not found")
            else:
                return ValidationResult("Safety Limits", False, "Could not verify")
    except Exception as e:
        return ValidationResult("Safety Limits", False, f"Error: {e}")


async def run_validation(quick: bool = False) -> Tuple[int, int]:
    """Run all validation checks."""
    print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
    print(f"{BOLD}{BLUE}MERID Dev Swarm Validation{RESET}")
    print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")
    
    checks = [
        check_api_health(),
        check_agents_registered(),
        check_stats_endpoint(),
        check_task_listing(),
        check_config_endpoint(),
        check_safety_limits(),
    ]
    
    # Add task creation check if not quick mode
    if not quick:
        checks.append(check_task_creation())
    
    results: List[ValidationResult] = []
    
    for i, check_coro in enumerate(checks, 1):
        print(f"[{i}/{len(checks)}] Running check...", end="\r")
        result = await check_coro
        results.append(result)
        
        # Print result
        status_icon = f"{GREEN}✓{RESET}" if result.passed else f"{RED}✗{RESET}"
        status_text = f"{GREEN}PASS{RESET}" if result.passed else f"{RED}FAIL{RESET}"
        
        print(f"[{i}/{len(checks)}] {status_icon} {result.name:<30} {status_text}")
        if result.message:
            print(f"      {result.message}")
    
    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    
    print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
    print(f"{BOLD}Summary: {passed}/{total} checks passed{RESET}")
    
    if passed == total:
        print(f"{BOLD}{GREEN}✓ ALL CHECKS PASSED - Dev Swarm is operational!{RESET}")
    else:
        print(f"{BOLD}{RED}✗ SOME CHECKS FAILED - Review errors above{RESET}")
        
        failed = [r for r in results if not r.passed]
        print(f"\n{BOLD}Failed checks:{RESET}")
        for r in failed:
            print(f"  - {r.name}: {r.message}")
    
    print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")
    
    return passed, total


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate Dev Swarm Integration")
    parser.add_argument("--quick", action="store_true", help="Skip long-running checks")
    args = parser.parse_args()
    
    print(f"{YELLOW}Starting validation...{RESET}")
    print(f"{YELLOW}Target: {API_BASE}{RESET}")
    
    if args.quick:
        print(f"{YELLOW}Quick mode: Skipping task creation test{RESET}")
    
    passed, total = await run_validation(quick=args.quick)
    
    # Exit code
    if passed == total:
        print(f"{GREEN}✓ Validation successful!{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}✗ Validation failed ({total - passed} errors){RESET}")
        print(f"\n{YELLOW}Troubleshooting:{RESET}")
        print(f"  1. Ensure backend is running: python -m uvicorn web.main:app --reload")
        print(f"  2. Check logs: tail -f logs/merid.log")
        print(f"  3. Verify port 8000 is not blocked")
        print(f"  4. Check DEV_SWARM_INTEGRATION_SUMMARY.md for setup instructions")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
