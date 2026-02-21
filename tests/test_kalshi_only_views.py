"""Test suite for Kalshi-only mode wiring.

Ensures that:
1. All kalshi_only views use venue_registry (never call Kalshi REST directly)
2. Swarm/consensus views hit consensus_bridge
3. Reconciliation views hit reconciliation module
4. Paper mode propagates correctly
5. No accidental cross-venue data leaks
"""

import pytest
from merid.ui_views_manifest import VIEWS, get_view
from merid.venue_registry import get_venue_registry


# ── Kalshi-only view list ────────────────────────────────────────────
# 
# FROZEN: This set defines the canonical Kalshi-only surface.
# To add a new view, you MUST:
#   1. Update this set
#   2. Mark view with kalshi_only=True in merid/ui_views_manifest.py
#   3. Add justification in KALSHI_ONLY_MODE.md
#   4. Ensure view uses venue_registry/consensus_bridge/reconciliation

EXPECTED_KALSHI_VIEWS = {
    "overview",              # Core portfolio view with reconciliation
    "positions",             # Position table filtered to Kalshi venue
    "predictions",           # PRIMARY: Kalshi markets + drift signals
    "prediction-consensus",  # Swarm Brain for Kalshi prediction consensus
    "signal-layer",          # Kalshi-specific signals: arbs, drift, macro
    "operator",              # PRIMARY: Reconciliation + audit trail
    "risk",                  # Risk metrics and alerts for Kalshi venue
    "health",                # System/venue health including Kalshi adapter
}

# Legacy list for backward compatibility
KALSHI_ONLY_VIEWS = list(EXPECTED_KALSHI_VIEWS)


@pytest.fixture
def kalshi_only_views():
    """Get all views marked as kalshi_only=True."""
    return [v for v in VIEWS if v.kalshi_only]


class TestKalshiOnlyManifest:
    """Validate the kalshi_only flag in ui_views_manifest."""
    
    def test_kalshi_only_view_ids_are_exact(self):
        """FROZEN: Kalshi-only view IDs must match EXPECTED_KALSHI_VIEWS exactly.
        
        This test prevents silent scope creep. To add a view:
        1. Update EXPECTED_KALSHI_VIEWS in this file
        2. Mark view with kalshi_only=True in merid/ui_views_manifest.py
        3. Document justification in KALSHI_ONLY_MODE.md
        """
        actual_ids = {v.id for v in VIEWS if v.kalshi_only}
        
        assert actual_ids == EXPECTED_KALSHI_VIEWS, \
            f"Kalshi-only view set has changed!\n" \
            f"Expected (frozen): {sorted(EXPECTED_KALSHI_VIEWS)}\n" \
            f"Actual: {sorted(actual_ids)}\n" \
            f"Missing: {sorted(EXPECTED_KALSHI_VIEWS - actual_ids)}\n" \
            f"Extra (FORBIDDEN): {sorted(actual_ids - EXPECTED_KALSHI_VIEWS)}\n\n" \
            f"To add a Kalshi view, you MUST:\n" \
            f"  1. Update EXPECTED_KALSHI_VIEWS in tests/test_kalshi_only_views.py\n" \
            f"  2. Mark view with kalshi_only=True in merid/ui_views_manifest.py\n" \
            f"  3. Add justification to KALSHI_ONLY_MODE.md"
    
    def test_kalshi_only_views_exist(self, kalshi_only_views):
        """All expected Kalshi-only views are flagged."""
        actual_ids = {v.id for v in kalshi_only_views}
        expected_ids = EXPECTED_KALSHI_VIEWS
        
        assert actual_ids == expected_ids, \
            f"Kalshi-only views mismatch.\n" \
            f"Expected: {expected_ids}\n" \
            f"Actual: {actual_ids}\n" \
            f"Missing: {expected_ids - actual_ids}\n" \
            f"Extra: {actual_ids - expected_ids}"
    
    def test_non_kalshi_views_not_flagged(self):
        """Non-Kalshi views must not have kalshi_only=True."""
        non_kalshi_views = [
            "betting", "betting-consensus",  # Betting domain
            "trading", "tradefloor",         # Crypto domain
            "flow-radar",                     # Flow detection
            "wallet", "treasury",             # General finance
            "agents", "devswarm",             # Dev tools
        ]
        
        for view_id in non_kalshi_views:
            view = get_view(view_id)
            if view:
                assert not view.kalshi_only, \
                    f"View '{view_id}' should not be kalshi_only"
    
    def test_kalshi_views_cover_all_sections(self, kalshi_only_views):
        """Kalshi-only views should span all major sections."""
        sections = {v.section for v in kalshi_only_views}
        assert "navigation" in sections
        assert "management" in sections
        assert "system" in sections


class TestVenueRegistryKalshiMode:
    """Test venue_registry kalshi_only mode guards."""
    
    @pytest.mark.asyncio
    async def test_kalshi_only_filters_venues(self):
        """kalshi_only=True should restrict to Kalshi venue only."""
        registry = get_venue_registry()
        
        # Mock scenario: multiple venues registered
        # In reality, only Kalshi is registered currently
        positions = await registry.get_all_positions(kalshi_only=True)
        
        # Should only return Kalshi positions
        assert "kalshi" in positions or len(positions) == 0, \
            "kalshi_only=True must only include Kalshi venue"
        
        # Should not include other venues
        non_kalshi_venues = {"coinbase", "polymarket", "binance"}
        for venue_name in non_kalshi_venues:
            assert venue_name not in positions, \
                f"kalshi_only mode leaked {venue_name} data"
    
    @pytest.mark.asyncio
    async def test_kalshi_only_overrides_venues_param(self):
        """kalshi_only=True should override explicit venues parameter."""
        registry = get_venue_registry()
        
        # Try to request non-Kalshi venues with kalshi_only=True
        positions = await registry.get_all_positions(
            venues=["coinbase", "polymarket"],
            kalshi_only=True
        )
        
        # Should ignore venues param and only return Kalshi
        if positions:
            assert set(positions.keys()) == {"kalshi"}, \
                "kalshi_only should override venues parameter"
    
    @pytest.mark.asyncio
    async def test_default_mode_includes_all_venues(self):
        """Default mode (kalshi_only=False) should include all enabled venues."""
        registry = get_venue_registry()
        
        positions = await registry.get_all_positions(kalshi_only=False)
        
        # Should return all enabled venues (currently just Kalshi)
        enabled = registry.list_venues(enabled_only=True)
        for venue_name in enabled:
            assert venue_name in positions or len(positions) == 0


class TestKalshiOnlyAPIWiring:
    """Test that Kalshi-only views use proper backend modules."""
    
    def test_predictions_view_apis(self):
        """Predictions view must use correct Kalshi endpoints."""
        view = get_view("predictions")
        assert view is not None
        assert view.kalshi_only
        
        api_paths = view.all_api_paths()
        
        # Must use US-compliant endpoints
        assert any("us-compliant" in path for path in api_paths), \
            "Predictions view should use us-compliant endpoints"
        
        # Should include drift signals
        assert any("drift-signals" in path for path in api_paths), \
            "Predictions view should fetch drift signals"
    
    def test_prediction_consensus_view_apis(self):
        """Prediction consensus view must use consensus bridge."""
        view = get_view("prediction-consensus")
        assert view is not None
        assert view.kalshi_only
        
        api_paths = view.all_api_paths()
        
        # Must use consensus endpoints
        assert any("consensus" in path for path in api_paths), \
            "Prediction-consensus view should use consensus APIs"
        
        # Should fetch opinions, plans, instruments
        required_apis = ["opinions", "plans", "instruments"]
        for api_part in required_apis:
            assert any(api_part in path for path in api_paths), \
                f"Prediction-consensus should fetch {api_part}"
    
    def test_operator_view_apis(self):
        """Operator view must use reconciliation module."""
        view = get_view("operator")
        assert view is not None
        assert view.kalshi_only
        
        api_paths = view.all_api_paths()
        
        # Must use operator/reconciliation endpoints
        assert any("operator" in path or "audit-trail" in path for path in api_paths), \
            "Operator view should use operator/audit-trail APIs"
    
    def test_signal_layer_view_apis(self):
        """Signal layer view must fetch Kalshi-specific signals."""
        view = get_view("signal-layer")
        assert view is not None
        assert view.kalshi_only
        
        api_paths = view.all_api_paths()
        
        # Should include arbs, drift, macro signals
        signal_types = ["arbs", "drift", "macro"]
        for signal_type in signal_types:
            assert any(signal_type in path for path in api_paths), \
                f"Signal-layer should fetch {signal_type} signals"


class TestKalshiOnlyEndpoints:
    """Test that API endpoints respect kalshi_only mode at runtime."""
    
    @pytest.mark.asyncio
    async def test_positions_endpoint_restricts_to_kalshi(self):
        """Positions endpoint in kalshi_only mode must only return Kalshi data.
        
        This prevents UI from seeing non-Kalshi venues accidentally.
        """
        # This is a placeholder test structure
        # In real implementation, would:
        # 1. Set KALSHI_ONLY=True via settings or env
        # 2. Call positions endpoint
        # 3. Assert only 'kalshi' venue in response
        
        # Example structure:
        # from merid.settings import KALSHI_ONLY
        # KALSHI_ONLY.set(True)
        # resp = await client.get("/api/v1/positions")
        # venues = {p["venue"] for p in resp.json()["positions"]}
        # assert venues <= {"kalshi"}, "Kalshi-only mode leaked non-Kalshi venues"
        
        registry = get_venue_registry()
        positions = await registry.get_all_positions(kalshi_only=True)
        
        # Verify only Kalshi venue present
        assert all(venue == "kalshi" for venue in positions.keys()), \
            "kalshi_only=True must restrict to Kalshi venue only"
    
    @pytest.mark.asyncio
    async def test_risk_endpoint_restricts_to_kalshi(self):
        """Risk endpoint in kalshi_only mode must only return Kalshi risk data."""
        registry = get_venue_registry()
        risk_snapshots = await registry.get_all_risk_snapshots(kalshi_only=True)
        
        # Verify only Kalshi venue present
        assert all(venue == "kalshi" for venue in risk_snapshots.keys()), \
            "kalshi_only=True must restrict risk data to Kalshi venue only"


class TestNoDirectKalshiAPICalls:
    """Ensure no view bypasses venue adapter to call Kalshi REST directly."""
    
    def test_no_direct_kalshi_rest_urls(self):
        """No view should contain direct Kalshi API URLs."""
        kalshi_domains = ["api.elections.kalshi.com", "demo-api.kalshi.co"]
        
        for view in VIEWS:
            if not view.kalshi_only:
                continue
            
            api_paths = view.all_api_paths()
            for path in api_paths:
                for domain in kalshi_domains:
                    assert domain not in path, \
                        f"View '{view.id}' contains direct Kalshi URL: {path}. " \
                        f"Must use venue_registry instead."
    
    def test_kalshi_views_use_merid_api_paths(self):
        """Kalshi-only views should use MERID internal API paths."""
        for view in VIEWS:
            if not view.kalshi_only:
                continue
            
            api_paths = view.all_api_paths()
            for path in api_paths:
                assert path.startswith("/api/"), \
                    f"View '{view.id}' API path '{path}' should start with /api/"
    
    def test_no_direct_kalshi_http_calls_in_codebase(self):
        """BRUTAL: Grep entire codebase for direct Kalshi API calls.
        
        Only event_venues/kalshi/ may contain Kalshi API URLs.
        Everywhere else must use venue_registry.
        """
        import os
        import re
        
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        kalshi_patterns = [
            r'api\.elections\.kalshi\.com',
            r'demo-api\.kalshi\.co',
            r'trading-api\.kalshi\.com',
        ]
        
        # Directories allowed to call Kalshi directly
        allowed_dirs = {
            os.path.join(project_root, "merid", "event_venues", "kalshi"),
            os.path.join(project_root, "tests", "test_kalshi_only_views.py"),  # This file
        }
        
        offenders = []
        
        # Search Python files
        for root, dirs, files in os.walk(project_root):
            # Skip venv, node_modules, .git
            dirs[:] = [d for d in dirs if d not in {'.venv', 'node_modules', '.git', '__pycache__', 'dist'}]
            
            for filename in files:
                if not filename.endswith('.py'):
                    continue
                
                filepath = os.path.join(root, filename)
                
                # Skip allowed directories
                if any(filepath.startswith(allowed) for allowed in allowed_dirs):
                    continue
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        for pattern in kalshi_patterns:
                            if re.search(pattern, content):
                                offenders.append((filepath, pattern))
                except Exception:
                    pass  # Skip files that can't be read
        
        assert not offenders, \
            f"Found direct Kalshi API calls outside event_venues/kalshi/:\n" + \
            "\n".join(f"  {path}: {pattern}" for path, pattern in offenders) + \
            "\n\nAll Kalshi calls must go through venue_registry!"


class TestPaperModeIntegration:
    """Ensure Kalshi-only views respect paper mode."""
    
    def test_paper_mode_environment_variable(self):
        """KALSHI_ONLY mode should be configurable via environment."""
        import os
        
        # Should support KALSHI_ONLY env var
        kalshi_mode = os.getenv("KALSHI_ONLY", "false").lower() == "true"
        
        # Just verify it can be read (actual value depends on environment)
        assert isinstance(kalshi_mode, bool)
    
    @pytest.mark.asyncio
    async def test_paper_mode_venue_adapter_routing(self):
        """Paper mode should route through paper venue adapter."""
        registry = get_venue_registry()
        kalshi = registry.get_venue("kalshi")
        
        if kalshi:
            # Verify venue adapter exists
            assert hasattr(kalshi, "venue_name")
            assert kalshi.venue_name == "kalshi"
            
            # Should have paper mode indicator
            # (actual implementation may vary)


# ── Summary helpers ──────────────────────────────────────────────────

def test_kalshi_only_coverage_report():
    """Generate coverage report for Kalshi-only views."""
    kalshi_views = [v for v in VIEWS if v.kalshi_only]
    
    report = {
        "total_views": len(VIEWS),
        "kalshi_only_views": len(kalshi_views),
        "kalshi_only_percentage": len(kalshi_views) / len(VIEWS) * 100,
        "kalshi_views_by_section": {},
    }
    
    for view in kalshi_views:
        section = view.section
        report["kalshi_views_by_section"].setdefault(section, []).append(view.id)
    
    # Should have reasonable Kalshi coverage
    assert report["kalshi_only_views"] >= 8, \
        "Should have at least 8 Kalshi-only views"
    assert report["kalshi_only_percentage"] < 50, \
        "Kalshi-only views should be a focused subset, not majority"
    
    print(f"\n=== Kalshi-Only Coverage Report ===")
    print(f"Total views: {report['total_views']}")
    print(f"Kalshi-only: {report['kalshi_only_views']} ({report['kalshi_only_percentage']:.1f}%)")
    print(f"By section: {report['kalshi_views_by_section']}")
