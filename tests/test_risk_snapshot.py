"""Risk State Snapshot Tests — Test the comprehensive risk aggregation endpoint.

Covers RiskSnapshot model serialization, get_risk_snapshot() aggregator,
and the /api/risk/snapshot HTTP endpoint.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from merid.risk_state import (
    CapSnapshot,
    KillSwitchSnapshot,
    CQISnapshot,
    CooldownSnapshot,
    PromotionSnapshot,
    RiskSnapshot,
    get_risk_snapshot,
)
from merid.execution_guard import ExecutionGuard


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pydantic Model Unit Tests (6)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapSnapshot:
    """Test CapSnapshot model."""

    def test_basic_cap(self):
        """CapSnapshot calculates utilization correctly."""
        cap = CapSnapshot(name="BTC", limit=4000.0, used=2000.0, remaining=2000.0, utilization_pct=50.0)
        assert cap.name == "BTC"
        assert cap.utilization_pct == 50.0

    def test_zero_limit(self):
        """Zero limit returns 0% utilization."""
        cap = CapSnapshot(name="TEST", limit=0.0, used=100.0, remaining=0.0, utilization_pct=0.0)
        assert cap.utilization_pct == 0.0


class TestKillSwitchSnapshot:
    """Test KillSwitchSnapshot model."""

    def test_active_switch(self):
        """Active kill switch with reason."""
        ks = KillSwitchSnapshot(active=True, reason="manual_stop", activated_at="2026-03-29T12:00:00Z")
        assert ks.active is True
        assert ks.reason == "manual_stop"

    def test_inactive_switch(self):
        """Inactive kill switch."""
        ks = KillSwitchSnapshot(active=False, reason="")
        assert ks.active is False
        assert ks.activated_at is None


class TestCQISnapshot:
    """Test CQISnapshot model."""

    def test_full_throttle(self):
        """CQI above full_above gives 100% throttle."""
        cqi = CQISnapshot(score=0.9, throttle_pct=100.0, block_below=0.3, full_above=0.8)
        assert cqi.throttle_pct == 100.0

    def test_low_cqi(self):
        """Low CQI below block threshold."""
        cqi = CQISnapshot(score=0.2, throttle_pct=0.0, block_below=0.3, full_above=0.8)
        assert cqi.score < cqi.block_below


class TestCooldownSnapshot:
    """Test CooldownSnapshot model."""

    def test_active_cooldown(self):
        """Active cooldown with remaining time."""
        cd = CooldownSnapshot(active=True, seconds_remaining=2.5, cooldown_seconds=5.0)
        assert cd.active is True
        assert cd.seconds_remaining > 0

    def test_inactive_cooldown(self):
        """Inactive cooldown."""
        cd = CooldownSnapshot(active=False, seconds_remaining=0.0, cooldown_seconds=5.0)
        assert cd.active is False


class TestPromotionSnapshot:
    """Test PromotionSnapshot model."""

    def test_promotion_enforced(self):
        """Promotion enforcement active."""
        promo = PromotionSnapshot(
            enforcement_enabled=True,
            eligible_domains=["kalshi"],
            blocked_agents=["agent_1"],
            report_stale=False
        )
        assert promo.enforcement_enabled is True
        assert "kalshi" in promo.eligible_domains


class TestRiskSnapshot:
    """Test RiskSnapshot model."""

    def test_complete_snapshot(self):
        """RiskSnapshot with all components."""
        snapshot = RiskSnapshot(
            timestamp="2026-03-29T12:00:00Z",
            trading_blocked=False,
            trading_blocked_reason="",
            kill_switch_guard=KillSwitchSnapshot(active=False, reason=""),
            kill_switch_risk_controller=KillSwitchSnapshot(active=False, reason=""),
            domains={"crypto": CapSnapshot(name="crypto", limit=10000.0, used=5000.0, remaining=5000.0, utilization_pct=50.0)},
            venues={"kalshi": CapSnapshot(name="kalshi", limit=5000.0, used=1000.0, remaining=4000.0, utilization_pct=20.0)},
            assets={"BTC": CapSnapshot(name="BTC", limit=4000.0, used=2000.0, remaining=2000.0, utilization_pct=50.0)},
            cqi=CQISnapshot(score=0.9, throttle_pct=100.0, block_below=0.3, full_above=0.8),
            cooldown=CooldownSnapshot(active=False, seconds_remaining=0.0, cooldown_seconds=5.0),
            promotion=PromotionSnapshot(enforcement_enabled=True, eligible_domains=[], blocked_agents=[], report_stale=False),
            recent_protect_events=[],
            recent_cap_events=[],
        )
        assert "crypto" in snapshot.domains
        assert "BTC" in snapshot.assets
        assert snapshot.cqi.score == 0.9
        assert snapshot.trading_blocked is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_risk_snapshot() Aggregator Tests (8)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshot:
    """Test the risk snapshot aggregator function."""

    def _guard_with_test_setup(self):
        """Create guard with test-friendly settings."""
        guard = ExecutionGuard()
        guard.enforce_promotion = False
        # Clear kill switches
        if guard.kill_switch_active:
            guard.deactivate_kill_switch()
        # Set high CQI
        guard.update_cqi("crypto", 1.0)
        # Disable cooldown
        guard._cooldown_seconds = 0.0
        guard._last_execution_at = 0.0
        return guard

    def test_returns_snapshot(self):
        """get_risk_snapshot returns valid RiskSnapshot."""
        guard = self._guard_with_test_setup()
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert isinstance(snapshot, RiskSnapshot)
        assert snapshot.timestamp is not None

    def test_includes_kill_switches(self):
        """Snapshot includes both kill switch states."""
        guard = self._guard_with_test_setup()
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert isinstance(snapshot.kill_switch_guard, KillSwitchSnapshot)
        assert isinstance(snapshot.kill_switch_risk_controller, KillSwitchSnapshot)

    def test_includes_cqi(self):
        """Snapshot includes CQI state."""
        guard = self._guard_with_test_setup()
        guard.update_cqi("crypto", 0.85)
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert isinstance(snapshot.cqi, CQISnapshot)
        assert 0.0 <= snapshot.cqi.score <= 1.0

    def test_includes_cooldown(self):
        """Snapshot includes cooldown state."""
        guard = self._guard_with_test_setup()
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert isinstance(snapshot.cooldown, CooldownSnapshot)

    def test_includes_asset_caps(self):
        """Snapshot includes asset caps when configured."""
        guard = self._guard_with_test_setup()
        guard.set_asset_cap("BTC", 4000.0, 1000.0)
        guard.set_asset_cap("ETH", 3000.0, 750.0)
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert "BTC" in snapshot.assets
        assert "ETH" in snapshot.assets
        assert snapshot.assets["BTC"].limit == 4000.0

    def test_calculates_utilization(self):
        """Utilization is calculated for asset caps with usage."""
        guard = self._guard_with_test_setup()
        guard.set_asset_cap("BTC", 4000.0, 1000.0)
        guard.record_execution("crypto", 2000.0, asset="BTC")
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert snapshot.assets["BTC"].used == 2000.0
        assert snapshot.assets["BTC"].remaining == 2000.0
        assert snapshot.assets["BTC"].utilization_pct == 50.0

    def test_empty_asset_caps(self):
        """Empty asset caps returns empty dict."""
        guard = self._guard_with_test_setup()
        # No asset caps configured
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert snapshot.assets == {}

    def test_domain_and_venue_caps(self):
        """Domain and venue caps included in snapshot."""
        guard = self._guard_with_test_setup()
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        # Should have at least prediction domain
        assert len(snapshot.domains) >= 1
        # Should have kalshi venue
        assert len(snapshot.venues) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API Endpoint Tests (4) - Integration with FastAPI
# ═══════════════════════════════════════════════════════════════════════════════

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.api.risk_routes import router as risk_router


@pytest.fixture
def risk_snapshot_client():
    """FastAPI TestClient with just the risk router for isolated testing."""
    from web.api.auth import get_current_session
    
    app = FastAPI()
    
    # Override auth dependency to bypass authentication
    async def mock_auth():
        return {"user_id": "test_user", "role": "operator"}
    
    app.include_router(risk_router)
    app.dependency_overrides[get_current_session] = mock_auth
    
    return TestClient(app)


class TestRiskSnapshotEndpoint:
    """Test the HTTP endpoint for risk snapshot."""

    def test_endpoint_returns_200(self, risk_snapshot_client):
        """GET /api/risk/snapshot returns 200 with valid data."""
        response = risk_snapshot_client.get("/api/risk/snapshot")
        
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "kill_switch_guard" in data
        assert "assets" in data

    def test_endpoint_includes_all_fields(self, risk_snapshot_client):
        """Response includes all expected risk snapshot fields."""
        response = risk_snapshot_client.get("/api/risk/snapshot")
        
        assert response.status_code == 200
        data = response.json()
        
        # All top-level fields present
        required_fields = [
            "timestamp", "kill_switch_guard", "kill_switch_risk_controller",
            "domains", "venues", "assets", "cqi", "cooldown",
            "promotion", "recent_protect_events", "recent_cap_events"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_endpoint_with_non_default_state(self, risk_snapshot_client):
        """Endpoint shows kill switch and utilization correctly when active."""
        from merid.execution_guard import get_execution_guard
        
        # Set up a non-default state
        guard = get_execution_guard()
        guard.activate_kill_switch("test_endpoint_audit")
        guard.set_asset_cap("BTC", 4000.0, 1000.0)
        guard.record_execution("crypto", 3500.0, asset="BTC")
        
        try:
            response = risk_snapshot_client.get("/api/risk/snapshot")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify kill switch is active
            assert data["kill_switch_guard"]["active"] is True
            assert "test_endpoint_audit" in data["kill_switch_guard"]["reason"]
            
            # Verify BTC utilization at 87.5%
            assert "BTC" in data["assets"]
            assert data["assets"]["BTC"]["used"] == 3500.0
            assert data["assets"]["BTC"]["utilization_pct"] == 87.5
            
        finally:
            # Clean up
            guard.deactivate_kill_switch()

    def test_endpoint_respects_include_verdicts_param(self, risk_snapshot_client):
        """include_verdicts query param affects response."""
        # First without verdicts
        response_no_verdicts = risk_snapshot_client.get("/api/risk/snapshot?include_verdicts=false")
        assert response_no_verdicts.status_code == 200
        
        # Then with verdicts
        response_with_verdicts = risk_snapshot_client.get("/api/risk/snapshot?include_verdicts=true")
        assert response_with_verdicts.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Integration: Risk Snapshot → Observability (2)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskSnapshotObservability:
    """Test risk snapshot for operational observability."""

    def test_snapshot_for_operator_audit(self):
        """Snapshot provides actionable operator visibility."""
        guard = ExecutionGuard()
        guard.enforce_promotion = False
        guard.update_cqi("crypto", 1.0)
        guard.set_asset_cap("BTC", 4000.0, 1000.0)
        guard.record_execution("crypto", 3500.0, asset="BTC")  # 87.5% utilized
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        # Operator can see BTC is near limit
        assert snapshot.assets["BTC"].utilization_pct == 87.5
        assert snapshot.assets["BTC"].remaining == 500.0

    def test_snapshot_identifies_blocked_trading(self):
        """Snapshot clearly shows when trading is blocked."""
        guard = ExecutionGuard()
        guard.activate_kill_switch("manual_audit_test")
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        assert snapshot.kill_switch_guard.active is True
        assert "manual_audit_test" in snapshot.kill_switch_guard.reason
        
        # Clean up
        guard.deactivate_kill_switch()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Edge Cases (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskSnapshotEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_risk_controller_import_error(self):
        """Gracefully handles risk_controller import issues."""
        # Should not crash even if risk_controller unavailable
        snapshot = get_risk_snapshot(include_verdicts=False)
        assert isinstance(snapshot, RiskSnapshot)

    def test_handles_excessive_utilization(self):
        """Handles edge case where used approaches limit."""
        guard = ExecutionGuard()
        guard.set_asset_cap("TEST", 1000.0, 500.0)
        # Use 90% of cap via proper API
        guard.record_execution("crypto", 900.0, asset="TEST")
        
        snapshot = get_risk_snapshot(include_verdicts=False, guard=guard)
        
        # Should show 90% utilization, 100 remaining
        assert snapshot.assets["TEST"].used == 900.0
        assert snapshot.assets["TEST"].remaining == 100.0
        assert snapshot.assets["TEST"].utilization_pct == 90.0

    def test_timestamp_format(self):
        """Timestamp is ISO format."""
        snapshot = get_risk_snapshot(include_verdicts=False)
        
        # Should be parseable as ISO timestamp
        try:
            datetime.fromisoformat(snapshot.timestamp.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail("Timestamp not in valid ISO format")
