#!/usr/bin/env python3
"""
Phase 1: Inventory and Duplication Scan
Run this script to generate a comprehensive inventory of all critical components.
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, List
import re

def run_ripgrep(pattern: str, path: str = "c:\\Dev\\MERID", file_type: str = "py") -> List[str]:
    """Run ripgrep and return matching lines."""
    cmd = ["rg", pattern, path, "-t", file_type, "--no-heading", "--line-number"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip().split("\n") if result.stdout.strip() else []

def classify_path(file_path: str) -> str:
    """Classify a file path as production, legacy, test, or script."""
    path_lower = file_path.lower()
    
    # Production paths
    if any(x in path_lower for x in [
        "merid/prediction/agent_grid_15m.py",
        "merid/event_venues/kalshi/market_catalog.py",
        "merid/event_venues/kalshi/crypto_catalog.py",
        "merid/event_venues/kalshi/bankroll_service_v2.py",
        "merid/event_venues/kalshi/client_v2.py",
        "merid/event_venues/kalshi/crypto_15m_scheduler.py",
        "merid/loop_15m.py",
        "web/main_15m_lean.py",
    ]):
        return "PRODUCTION"
    
    # Legacy paths
    if any(x in path_lower for x in [
        "archive/legacy",
        "legacy/",
        "merid/prediction/agent_grid.py",  # Legacy grid
        "merid/event_venues/kalshi/bankroll_service.py",  # Deprecated
        "merid/event_venues/kalshi/client.py",  # Old venue client
        "merid/loop.py",  # Legacy loop
    ]):
        return "LEGACY"
    
    # Test paths
    if "tests/" in path_lower or "test_" in path_lower:
        return "TEST"
    
    # Script paths
    if "scripts/" in path_lower:
        return "SCRIPT"
    
    return "UNKNOWN"

def main():
    repo_root = Path("c:\\Dev\\MERID")
    
    # Search patterns for critical components
    searches = {
        "agent_grid_classes": r"class.*AgentGrid15m",
        "agent_grid_instantiations": r"LeanAgentGrid15m\(",
        "scheduler_classes": r"class.*Scheduler.*15m|class.*15m.*Scheduler",
        "scheduler_refs": r"crypto15mscheduler|Kalshi15mScheduler",
        "catalog_classes": r"class.*MarketCatalog|class.*CryptoCatalog",
        "catalog_refs": r"KalshiMarketCatalog|KalshiCryptoCatalog",
        "bankroll_classes": r"KalshiBankrollService|BankrollServiceV2",
        "client_classes": r"class.*Kalshi.*Client",
        "run_cycle_methods": r"def run_cycle",
        "legacy_imports": r"from merid\.prediction\.agent_grid import",
        "production_imports": r"from merid\.prediction\.agent_grid_15m import",
    }
    
    inventory = {}
    
    for category, pattern in searches.items():
        print(f"Searching: {category} with pattern: {pattern}")
        matches = run_ripgrep(pattern)
        classified = {"PRODUCTION": [], "LEGACY": [], "TEST": [], "SCRIPT": [], "UNKNOWN": []}
        
        for match in matches:
            if not match:
                continue
            # Extract file path from match (format: "file:line:content")
            parts = match.split(":", 2)
            if len(parts) >= 2:
                file_path = parts[0]
                classification = classify_path(file_path)
                classified[classification].append(match)
        
        inventory[category] = classified
    
    # Output results
    output_file = repo_root / "output" / "phase1_inventory.json"
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, "w") as f:
        json.dump(inventory, f, indent=2)
    
    print(f"\n✓ Inventory written to {output_file}")
    
    # Print summary
    print("\n=== SUMMARY ===")
    for category, classified in inventory.items():
        total = sum(len(v) for v in classified.values())
        prod_count = len(classified["PRODUCTION"])
        legacy_count = len(classified["LEGACY"])
        print(f"{category}: {total} total (PROD: {prod_count}, LEGACY: {legacy_count})")

if __name__ == "__main__":
    main()
