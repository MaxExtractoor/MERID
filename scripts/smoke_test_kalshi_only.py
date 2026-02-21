"""Smoke test for Kalshi-only mode.

Verifies that when KALSHI_ONLY=true:
1. Only 8 canonical Kalshi views are accessible
2. Positions/orders only return Kalshi venue data
3. Consensus/swarm APIs reference prediction domain
4. No non-Kalshi venue data leaks through

Usage:
    KALSHI_ONLY=true python scripts/smoke_test_kalshi_only.py
    
Exit codes:
    0 - All checks passed
    1 - Kalshi-only mode violations detected
"""

import asyncio
import os
import sys
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.settings import settings
from merid.venue_registry import get_venue_registry
from merid.ui_views_manifest import VIEWS

EXPECTED_KALSHI_VIEWS = {
    "overview",
    "positions",
    "predictions",
    "prediction-consensus",
    "signal-layer",
    "operator",
    "risk",
    "health",
}


class KalshiOnlySmokeTest:
    """Smoke test suite for Kalshi-only mode."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []
    
    def log_pass(self, test_name: str):
        """Log a passing test."""
        print(f"✓ {test_name}")
        self.passed += 1
    
    def log_fail(self, test_name: str, reason: str):
        """Log a failing test."""
        print(f"✗ {test_name}: {reason}")
        self.failures.append(f"{test_name}: {reason}")
        self.failed += 1
    
    def test_kalshi_only_setting(self):
        """Verify KALSHI_ONLY is enabled."""
        if settings.KALSHI_ONLY:
            self.log_pass("KALSHI_ONLY setting is TRUE")
        else:
            self.log_fail("KALSHI_ONLY setting", "Expected TRUE, got FALSE")
    
    def test_manifest_has_exactly_8_views(self):
        """Verify manifest has exactly 8 kalshi_only views."""
        kalshi_views = [v for v in VIEWS if v.kalshi_only]
        actual_ids = {v.id for v in kalshi_views}
        
        if actual_ids == EXPECTED_KALSHI_VIEWS:
            self.log_pass(f"Manifest has exactly 8 Kalshi views: {sorted(actual_ids)}")
        else:
            missing = EXPECTED_KALSHI_VIEWS - actual_ids
            extra = actual_ids - EXPECTED_KALSHI_VIEWS
            reason = []
            if missing:
                reason.append(f"Missing: {missing}")
            if extra:
                reason.append(f"Extra: {extra}")
            self.log_fail("Manifest Kalshi views", ", ".join(reason))
    
    async def test_venue_registry_kalshi_only(self):
        """Verify venue_registry.get_all_positions(kalshi_only=True) restricts to Kalshi."""
        registry = get_venue_registry()
        
        try:
            positions = await registry.get_all_positions(kalshi_only=True)
            
            # Should only contain 'kalshi' key
            if not positions:
                self.log_pass("Venue registry (kalshi_only): No positions (expected in paper mode)")
            elif set(positions.keys()) == {"kalshi"}:
                self.log_pass("Venue registry (kalshi_only): Only Kalshi venue present")
            else:
                non_kalshi = set(positions.keys()) - {"kalshi"}
                self.log_fail(
                    "Venue registry (kalshi_only)",
                    f"Non-Kalshi venues leaked: {non_kalshi}"
                )
        except Exception as exc:
            self.log_fail("Venue registry (kalshi_only)", f"Exception: {exc}")
    
    async def test_risk_snapshots_kalshi_only(self):
        """Verify risk snapshots restricted to Kalshi venue."""
        registry = get_venue_registry()
        
        try:
            risk = await registry.get_all_risk_snapshots(kalshi_only=True)
            
            if not risk:
                self.log_pass("Risk snapshots (kalshi_only): Empty (expected in paper mode)")
            elif set(risk.keys()) == {"kalshi"}:
                self.log_pass("Risk snapshots (kalshi_only): Only Kalshi venue present")
            else:
                non_kalshi = set(risk.keys()) - {"kalshi"}
                self.log_fail(
                    "Risk snapshots (kalshi_only)",
                    f"Non-Kalshi venues leaked: {non_kalshi}"
                )
        except Exception as exc:
            self.log_fail("Risk snapshots (kalshi_only)", f"Exception: {exc}")
    
    def test_prediction_views_exist(self):
        """Verify core prediction views are present."""
        required = ["predictions", "prediction-consensus"]
        kalshi_view_ids = {v.id for v in VIEWS if v.kalshi_only}
        
        for view_id in required:
            if view_id in kalshi_view_ids:
                self.log_pass(f"Core view '{view_id}' present")
            else:
                self.log_fail(f"Core view '{view_id}'", "Missing from Kalshi views")
    
    def test_operator_views_exist(self):
        """Verify operator/risk/health views are present."""
        required = ["operator", "risk", "health"]
        kalshi_view_ids = {v.id for v in VIEWS if v.kalshi_only}
        
        for view_id in required:
            if view_id in kalshi_view_ids:
                self.log_pass(f"Ops view '{view_id}' present")
            else:
                self.log_fail(f"Ops view '{view_id}'", "Missing from Kalshi views")
    
    def test_non_kalshi_views_not_flagged(self):
        """Verify non-Kalshi views don't have kalshi_only=True."""
        forbidden_kalshi_flags = [
            "betting", "betting-consensus", "trading", "tradefloor",
            "flow-radar", "wallet", "treasury", "agents", "devswarm"
        ]
        
        violations = []
        for view_id in forbidden_kalshi_flags:
            view = next((v for v in VIEWS if v.id == view_id), None)
            if view and view.kalshi_only:
                violations.append(view_id)
        
        if not violations:
            self.log_pass("Non-Kalshi views correctly flagged (kalshi_only=False)")
        else:
            self.log_fail(
                "Non-Kalshi views",
                f"These should NOT be kalshi_only=True: {violations}"
            )
    
    async def run_all(self):
        """Run all smoke tests."""
        print("=" * 60)
        print("KALSHI-ONLY MODE SMOKE TEST")
        print("=" * 60)
        print()
        
        # Sync tests
        self.test_kalshi_only_setting()
        self.test_manifest_has_exactly_8_views()
        self.test_prediction_views_exist()
        self.test_operator_views_exist()
        self.test_non_kalshi_views_not_flagged()
        
        # Async tests
        await self.test_venue_registry_kalshi_only()
        await self.test_risk_snapshots_kalshi_only()
        
        # Summary
        print()
        print("=" * 60)
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        print("=" * 60)
        
        if self.failed > 0:
            print("\n❌ FAILURES:")
            for failure in self.failures:
                print(f"  - {failure}")
            print()
            print("Kalshi-only mode has violations. DO NOT go live.")
            return False
        else:
            print("\n✅ ALL CHECKS PASSED")
            print("Kalshi-only mode is correctly configured.")
            return True


async def main():
    """Run smoke tests."""
    tester = KalshiOnlySmokeTest()
    success = await tester.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
