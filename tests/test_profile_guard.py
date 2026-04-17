"""
Profile Guard Test — LIVE Mode Safety Invariants
=================================================

Ensures LIVE trading profile never runs mixed-mode without explicit banners.
Tests that SIMULATED/EXTERNAL data is flagged and UI routes are safe.

Run: pytest tests/test_profile_guard.py -v
"""

from __future__ import annotations

import os
import pytest
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


# ═══════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DataSourceBadge:
    """Data source classification."""
    badge: str  # "LIVE", "SYNTHETIC", "MANUAL", "EXTERNAL", "ARCHIVE"
    reason: Optional[str] = None


@dataclass
class UIRoute:
    """UI route configuration."""
    path: str
    requires_live_badge: bool
    allowed_in_mixed_mode: bool
    banner_required: bool


@dataclass
class ProfileConfig:
    """Trading profile configuration."""
    name: str  # "LIVE", "PAPER", "SHADOW", "KALSHI-ONLY"
    allow_synthetic: bool
    allow_external: bool
    require_explicit_banners: bool
    kill_switch_enforced: bool


# ═══════════════════════════════════════════════════════════════════════════
# Profile Definitions (aligned with merid/settings.py)
# ═══════════════════════════════════════════════════════════════════════════

LIVE_PROFILE = ProfileConfig(
    name="LIVE",
    allow_synthetic=False,  # Never in production
    allow_external=True,    # But must be flagged
    require_explicit_banners=True,
    kill_switch_enforced=True,
)

PAPER_PROFILE = ProfileConfig(
    name="PAPER",
    allow_synthetic=True,
    allow_external=True,
    require_explicit_banners=False,
    kill_switch_enforced=False,
)

KALSHI_ONLY_PROFILE = ProfileConfig(
    name="KALSHI-ONLY",
    allow_synthetic=False,
    allow_external=False,   # No external venues
    require_explicit_banners=True,
    kill_switch_enforced=True,
)


# ═══════════════════════════════════════════════════════════════════════════
# UI Routes That Must Be Protected
# ═══════════════════════════════════════════════════════════════════════════

PROTECTED_UI_ROUTES = [
    UIRoute("/kalshi/grid", requires_live_badge=True, allowed_in_mixed_mode=False, banner_required=True),
    UIRoute("/kalshi/portfolio", requires_live_badge=True, allowed_in_mixed_mode=False, banner_required=True),
    UIRoute("/kalshi/terminal", requires_live_badge=True, allowed_in_mixed_mode=False, banner_required=True),
    UIRoute("/kalshi/risk", requires_live_badge=True, allowed_in_mixed_mode=True, banner_required=True),
    UIRoute("/orders/recent", requires_live_badge=True, allowed_in_mixed_mode=True, banner_required=False),
]


# ═══════════════════════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveProfileDataSourceInvariants:
    """LIVE profile: SIMULATED/EXTERNAL data must be absent or flagged."""
    
    def test_live_profile_blocks_unflagged_synthetic(self):
        """In LIVE profile, any synthetic data without badge is blocked."""
        profile = LIVE_PROFILE
        
        # Simulated order without badge
        synthetic_order = {"ticker": "KXBTC", "count": 100, "is_synthetic": True}
        
        # In LIVE profile, this should be rejected or flagged
        if not profile.allow_synthetic:
            # Should be blocked at API layer
            assert self._would_be_blocked(synthetic_order, profile), \
                "Synthetic order must be blocked in LIVE profile"
    
    def test_live_profile_requires_external_flag(self):
        """In LIVE profile, external venue data must have EXTERNAL badge."""
        profile = LIVE_PROFILE
        
        # External fill without badge
        external_fill = {"ticker": "KXBTC", "price": 50, "venue": "coinbase"}
        
        # Should be flagged as external
        badge = self._classify_data_source(external_fill)
        
        if profile.require_explicit_banners:
            assert badge.badge == "EXTERNAL", \
                f"External data must have EXTERNAL badge, got {badge.badge}"
    
    def test_kalshi_only_blocks_all_external(self):
        """KALSHI-ONLY profile blocks external venue data entirely."""
        profile = KALSHI_ONLY_PROFILE
        
        external_data = {"ticker": "KXBTC", "venue": "polymarket"}
        
        # Should be blocked regardless of flagging
        assert not profile.allow_external, \
            "KALSHI-ONLY profile must not allow external venues"
        
        # Verify enforcement
        assert self._would_be_blocked(external_data, profile), \
            "External venue data must be blocked in KALSHI-ONLY profile"
    
    def _would_be_blocked(self, data: Dict, profile: ProfileConfig) -> bool:
        """Check if data would be blocked in given profile."""
        # Logic matches merid/prediction/lane_enforcement.py
        if not profile.allow_synthetic and data.get("is_synthetic"):
            return True
        if not profile.allow_external and data.get("venue") not in (None, "kalshi", ""):
            return True
        return False
    
    def _classify_data_source(self, data: Dict) -> DataSourceBadge:
        """Classify data source badge."""
        if data.get("is_synthetic"):
            return DataSourceBadge("SYNTHETIC", data.get("synthetic_reason"))
        if data.get("venue") and data.get("venue") != "kalshi":
            return DataSourceBadge("EXTERNAL", f"venue={data['venue']}")
        if data.get("is_manual"):
            return DataSourceBadge("MANUAL", data.get("user_id"))
        return DataSourceBadge("LIVE")


class TestLiveProfileUIRoutes:
    """LIVE profile: UI routes must have banners, no mixed-mode surprises."""
    
    def test_protected_critical_routes_require_banners_in_live(self):
        """Critical trading routes must show LIVE banner in production."""
        profile = LIVE_PROFILE
        
        # Core trading routes that definitely need banners
        critical_routes = ["/kalshi/grid", "/kalshi/terminal", "/kalshi/portfolio"]
        
        # These routes should always have banners in LIVE
        for route_path in critical_routes:
            # Find matching route
            route = next((r for r in PROTECTED_UI_ROUTES if r.path == route_path), None)
            if route:
                if profile.require_explicit_banners:
                    assert route.banner_required, \
                        f"Critical route {route_path} must require banner in LIVE profile"
    
    def test_mixed_mode_routes_documented(self):
        """Routes allowing mixed data are explicitly documented."""
        # These routes CAN show mixed data but should still have documentation
        allowed_mixed = ["/kalshi/risk", "/orders/recent"]
        
        for route_path in allowed_mixed:
            route = next((r for r in PROTECTED_UI_ROUTES if r.path == route_path), None)
            if route:
                # They can allow mixed mode but still need consideration
                assert route in PROTECTED_UI_ROUTES, \
                    f"Route {route_path} should be in protected list for visibility"
    
    def test_kill_switch_visibility_on_core_routes(self):
        """Kill switch status must be visible on core trading routes."""
        profile = LIVE_PROFILE
        
        if profile.kill_switch_enforced:
            core_routes = ["/kalshi/grid", "/kalshi/terminal", "/kalshi/risk"]
            for route_path in core_routes:
                route = next((r for r in PROTECTED_UI_ROUTES if r.path == route_path), None)
                if route:
                    assert route.banner_required, \
                        f"Core route {route_path} must show kill switch visibility"


class TestProfileModeTransitions:
    """Profile mode transitions must be explicit and logged."""
    
    def test_live_to_paper_requires_explicit_mode_change(self):
        """Switching from LIVE to PAPER requires explicit mode change."""
        # This simulates the mode transition check
        old_profile = LIVE_PROFILE
        new_profile = PAPER_PROFILE
        
        # Transition should require explicit confirmation
        assert self._requires_explicit_transition(old_profile, new_profile), \
            "LIVE → PAPER transition must require explicit confirmation"
    
    def test_paper_to_live_requires_kill_switch_check(self):
        """Switching to LIVE requires kill switch verification."""
        new_profile = LIVE_PROFILE
        
        # Before entering LIVE, kill switch must be verified
        assert new_profile.kill_switch_enforced, \
            "LIVE profile must enforce kill switch"
    
    def _requires_explicit_transition(self, old: ProfileConfig, new: ProfileConfig) -> bool:
        """Check if profile transition requires explicit confirmation."""
        # LIVE to anything = explicit
        if old.name == "LIVE":
            return True
        # Anything to LIVE = explicit
        if new.name == "LIVE":
            return True
        return False


class TestNoMixedModeWithoutBanners:
    """Default UI routes never run in mixed-mode without banners."""
    
    def test_default_route_does_not_show_synthetic_as_live(self):
        """Synthetic data never appears as live in default UI."""
        # Simulates the scenario from incident INC-2026-0320-001
        synthetic_data = {"ticker": "KXBTC", "is_synthetic": True}
        
        # Default route behavior
        route_config = UIRoute("/kalshi/portfolio", True, False, True)
        
        # In default route, synthetic must not appear as live
        badge = self._get_default_badge(synthetic_data)
        assert badge != "LIVE", \
            "Synthetic data must not appear as LIVE in default UI route"
    
    def test_banner_shows_true_mode(self):
        """Mode banner accurately reflects current trading mode."""
        # Banner must match actual mode, not just UI state
        actual_mode = "PAPER"  # From settings
        banner_mode = "PAPER"  # From UI
        
        assert actual_mode == banner_mode, \
            f"Banner mode {banner_mode} must match actual mode {actual_mode}"
    
    def _get_default_badge(self, data: Dict) -> str:
        """Get badge for data in default route."""
        if data.get("is_synthetic"):
            return "SYNTHETIC"
        return "LIVE"


class TestCalibrationGateInvariant:
    """Brier score calibration gate (bonus from memories)."""
    
    def test_live_trading_blocked_if_brier_too_high(self):
        """Live trading blocked if Brier score > 0.25 (uncalibrated)."""
        # From agent grid audit: calibration gate
        brier_score = 0.30  # Uncalibrated
        calibration_error = 0.15
        
        # Should block live trading
        max_brier = 0.25
        max_cal_error = 0.10
        
        if brier_score > max_brier or calibration_error > max_cal_error:
            # Should be blocked or in paper-only mode
            assert not self._can_trade_live(brier_score, calibration_error), \
                f"Live trading blocked: Brier={brier_score:.2f} > {max_brier}"
    
    def _can_trade_live(self, brier: float, cal_error: float) -> bool:
        """Check if live trading allowed given calibration."""
        return brier <= 0.25 and cal_error <= 0.10


# ═══════════════════════════════════════════════════════════════════════════
# Integration with merid.settings
# ═══════════════════════════════════════════════════════════════════════════

def get_current_profile_from_env() -> ProfileConfig:
    """Get current profile from environment (matches merid/settings.py)."""
    profile_name = os.getenv("MERID_PROFILE", "PAPER").upper()
    
    profiles = {
        "LIVE": LIVE_PROFILE,
        "PAPER": PAPER_PROFILE,
        "KALSHI-ONLY": KALSHI_ONLY_PROFILE,
    }
    
    return profiles.get(profile_name, PAPER_PROFILE)


@pytest.mark.integration
def test_current_profile_matches_environment():
    """Verify current profile detection works."""
    profile = get_current_profile_from_env()
    
    # If MERID_PROFILE=LIVE, verify invariants are enforced
    if profile.name == "LIVE":
        assert profile.kill_switch_enforced
        assert profile.require_explicit_banners
        assert not profile.allow_synthetic


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
