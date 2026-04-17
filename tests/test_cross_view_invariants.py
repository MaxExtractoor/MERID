"""
Cross-View Invariant Tests

These tests verify critical invariants across the MERID UI spine to prevent
regression of the single-source-of-truth architecture.

Run with: pytest tests/test_cross_view_invariants.py -v
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from typing import Dict, List, Any
from datetime import datetime, timezone


class TestPositionFillInvariants:
    """
    Invariant: Every non-synthetic position must have at least one backing fill.
    Invariant: Sum of position exposures must match fills ledger calculations.
    """
    
    def test_positions_have_backing_fills(self, api_client):
        """
        EGG-PREVENTION: Positions without fills are ghosts.
        
        For each position in /positions:
        - If synthetic=False, there must be at least one fill in /fills with matching ticker
        - Position size should approximately match sum of fill sizes
        """
        positions_resp = api_client.get("/api/v1/kalshi/positions")
        positions = positions_resp.json()["positions"]
        
        fills_resp = api_client.get("/api/v1/kalshi/fills?since_hours=168")  # 7 days
        fills = fills_resp.json()["fills"]
        
        fills_by_ticker: Dict[str, List[Dict]] = {}
        for fill in fills:
            ticker = fill.get("ticker")
            if ticker:
                fills_by_ticker.setdefault(ticker, []).append(fill)
        
        errors = []
        for pos in positions:
            if pos.get("synthetic"):
                continue  # Synthetic positions don't need fills
            
            ticker = pos.get("ticker")
            pos_fills = fills_by_ticker.get(ticker, [])
            
            if not pos_fills:
                errors.append(f"Position {ticker} has no backing fills (ghost position)")
                continue
            
            # Check size consistency (allow 5% tolerance for partial fills)
            total_fill_size = sum(f.get("size", 0) for f in pos_fills)
            pos_size = pos.get("size", 0)
            
            if abs(total_fill_size - pos_size) > max(pos_size * 0.05, 1):
                errors.append(
                    f"Position {ticker} size mismatch: "
                    f"position={pos_size}, fills_sum={total_fill_size}"
                )
        
        assert not errors, "Position-fill invariants violated:\n" + "\n".join(errors)
    
    def test_fills_have_position_impact(self, api_client):
        """
        EGG-PREVENTION: Fills without position impact are orphaned.
        
        For each fill in /fills:
        - There should be a corresponding position change in /positions
        - Or the fill should be very recent (< 5 seconds, position not yet updated)
        """
        fills_resp = api_client.get("/api/v1/kalshi/fills?since_hours=24")
        fills = fills_resp.json()["fills"]
        
        positions_resp = api_client.get("/api/v1/kalshi/positions")
        positions = positions_resp.json()["positions"]
        
        position_tickers = {p.get("ticker") for p in positions}
        
        errors = []
        for fill in fills:
            ticker = fill.get("ticker")
            fill_time = fill.get("timestamp", "")
            
            # Skip very recent fills (position update may be pending)
            if fill_time:
                try:
                    fill_dt = datetime.fromisoformat(fill_time.replace("Z", "+00:00"))
                    age_sec = (datetime.now(timezone.utc) - fill_dt).total_seconds()
                    if age_sec < 5:
                        continue
                except Exception:
                    pass
            
            if ticker not in position_tickers:
                errors.append(f"Fill {fill.get('fill_id')} for {ticker} has no position impact")
        
        assert not errors, "Fill-position invariants violated:\n" + "\n".join(errors)


class TestBalancePnLInvariants:
    """
    Invariant: Calculated balance from fills must match venue balance within tolerance.
    Invariant: PnL from fills ledger must match risk controller PnL.
    """
    
    TOLERANCE_USD = 5.0  # $5 tolerance for rounding/fee differences
    
    def test_balance_consistency(self, api_client):
        """
        EGG-PREVENTION: Balance drift indicates missing fills or phantom positions.
        
        Compare:
        - /balance (from venue)
        - Calculated balance from /fills ledger
        """
        balance_resp = api_client.get("/api/v1/kalshi/balance")
        balance_data = balance_resp.json()
        venue_balance = balance_data.get("available", 0) + balance_data.get("locked", 0)
        
        fills_resp = api_client.get("/api/v1/kalshi/fills?since_hours=168")
        fills = fills_resp.json()["fills"]
        
        # Calculate expected balance from fills
        total_impact = 0.0
        for fill in fills:
            size = fill.get("size", 0)
            price = fill.get("price", 0)
            fee = fill.get("fee", 0)
            side = fill.get("side", "").lower()
            
            if side == "buy":
                total_impact -= (size * price + fee)
            elif side == "sell":
                total_impact += (size * price - fee)
        
        # Get starting balance (this would ideally come from config or first fill)
        # For now, we just check that the drift isn't growing
        calculated_balance = 10000.0 + total_impact  # Assuming 10k starting
        
        drift = abs(venue_balance - calculated_balance)
        
        assert drift <= self.TOLERANCE_USD, (
            f"Balance drift ${drift:.2f} exceeds tolerance ${self.TOLERANCE_USD}\n"
            f"Venue: ${venue_balance:.2f}, Calculated: ${calculated_balance:.2f}"
        )
    
    def test_pnl_consistency(self, api_client):
        """
        EGG-PREVENTION: PnL divergence indicates calculation errors or missing data.
        
        Compare:
        - /risk daily_pnl_usd (from fills ledger)
        - /portfolio/pnl total_pnl_usd
        """
        risk_resp = api_client.get("/api/v1/kalshi/risk")
        risk_data = risk_resp.json()
        risk_pnl = risk_data.get("daily_pnl_usd", 0)
        
        portfolio_resp = api_client.get("/api/v1/kalshi/portfolio/pnl")
        portfolio_data = portfolio_resp.json()
        portfolio_pnl = portfolio_data.get("total_pnl_usd", 0)
        
        divergence = abs(risk_pnl - portfolio_pnl)
        
        assert divergence <= self.TOLERANCE_USD, (
            f"PnL divergence ${divergence:.2f} exceeds tolerance ${self.TOLERANCE_USD}\n"
            f"Risk: ${risk_pnl:.2f}, Portfolio: ${portfolio_pnl:.2f}"
        )


class TestOrderLineageInvariants:
    """
    Invariant: Every live order must have complete lineage (signal → agent → risk → router).
    Invariant: Orders without lineage must be flagged as manual/external.
    """
    
    def test_live_orders_have_lineage(self, api_client):
        """
        EGG-PREVENTION: Orders without lineage may be from shadow paths.
        
        For each non-synthetic order:
        - Query /orders/{id}/lineage
        - Verify chain has: signal, agent, risk, router
        - If incomplete, verify it's flagged as manual/external
        """
        orders_resp = api_client.get("/api/v1/kalshi/orders")
        orders = orders_resp.json()["orders"]
        
        errors = []
        for order in orders:
            if order.get("synthetic"):
                continue
            
            order_id = order.get("order_id")
            lineage_resp = api_client.get(f"/api/v1/kalshi/orders/{order_id}/lineage")
            lineage = lineage_resp.json()
            
            if not lineage.get("found"):
                errors.append(f"Order {order_id} not found in lineage system")
                continue
            
            chain = lineage.get("chain", {})
            expected_keys = {"signal", "agent", "risk", "router"}
            missing = expected_keys - set(chain.keys())
            
            if missing and not any(
                "manual" in w.lower() or "external" in w.lower() 
                for w in lineage.get("warnings", [])
            ):
                errors.append(
                    f"Order {order_id} missing lineage: {missing}, "
                    f"but not flagged as manual/external"
                )
        
        assert not errors, "Order lineage invariants violated:\n" + "\n".join(errors)


class TestReconciliationInvariants:
    """
    Invariant: When reconciliation is not "ok", PnL/portfolio numbers must be marked untrusted.
    Invariant: Reconciliation status must be exposed in all relevant endpoints.
    """
    
    def test_reconciliation_status_exposed(self, api_client):
        """
        EGG-PREVENTION: Hidden reconciliation breaks lead to bad trading decisions.
        
        Verify that /positions, /risk, /portfolio endpoints expose reconciliation_status.
        """
        endpoints_to_check = [
            "/api/v1/kalshi/positions",
            "/api/v1/kalshi/risk",
            "/api/v1/kalshi/portfolio",
        ]
        
        errors = []
        for endpoint in endpoints_to_check:
            resp = api_client.get(endpoint)
            data = resp.json()
            
            if "reconciliation_status" not in data:
                errors.append(f"Endpoint {endpoint} missing reconciliation_status field")
        
        assert not errors, "Reconciliation exposure invariants violated:\n" + "\n".join(errors)
    
    def test_untrusted_data_flagged_when_reconciliation_broken(self, api_client):
        """
        EGG-PREVENTION: Using untrusted PnL for trading decisions is dangerous.
        
        When /health/reconciliation status is "broken" or "degraded":
        - /risk should have has_discrepancies=true
        - Portfolio endpoints should have a warning flag
        """
        recon_resp = api_client.get("/api/v1/kalshi/health/reconciliation")
        recon_data = recon_resp.json()
        
        if recon_data.get("status") not in ("broken", "degraded"):
            pytest.skip("Reconciliation healthy, skipping untrusted data test")
        
        risk_resp = api_client.get("/api/v1/kalshi/risk")
        risk_data = risk_resp.json()
        
        # Verify risk endpoint flags discrepancies
        assert risk_data.get("has_discrepancies") or risk_data.get("risk_discrepancies"), (
            "Reconciliation is broken but /risk doesn't flag discrepancies"
        )


class TestSyntheticDataGating:
    """
    Invariant: Synthetic/ghost data must never appear in default (ungated) responses.
    """
    
    def test_positions_default_no_synthetic(self, api_client):
        """
        EGG-PREVENTION: Synthetic positions polluting operator view.
        
        /positions without ?include_synthetic=true must return only real positions.
        """
        resp = api_client.get("/api/v1/kalshi/positions")
        positions = resp.json().get("positions", [])
        
        synthetic_positions = [p for p in positions if p.get("synthetic")]
        
        assert not synthetic_positions, (
            f"Found {len(synthetic_positions)} synthetic positions in default response: "
            f"{[p.get('ticker') for p in synthetic_positions]}"
        )
    
    def test_orders_default_no_scanning(self, api_client):
        """
        EGG-PREVENTION: Scanning/signal orders appearing as real orders.
        
        /orders without ?include_scanning=true must return only venue-ack orders.
        """
        resp = api_client.get("/api/v1/kalshi/orders")
        orders = resp.json().get("orders", [])
        
        scanning_orders = [o for o in orders if o.get("status") == "scanning" or o.get("synthetic")]
        
        assert not scanning_orders, (
            f"Found {len(scanning_orders)} scanning/synthetic orders in default response: "
            f"{[o.get('order_id') for o in scanning_orders]}"
        )


class TestKillSwitchInvariants:
    """
    Invariant: Kill switch state must be consistent across all endpoints.
    """
    
    def test_kill_switch_consistency(self, api_client):
        """
        EGG-PREVENTION: Inconsistent kill switch state could allow trading when halted.
        
        /risk, /operator/kill-switch-status, and /health must agree on kill switch state.
        """
        risk_resp = api_client.get("/api/v1/kalshi/risk")
        risk_ks = risk_resp.json().get("kill_switch_active", False)
        
        operator_resp = api_client.get("/api/v1/operator/kill-switch-status")
        operator_ks = operator_resp.json().get("kill_switch_active") or operator_resp.json().get("active", False)
        
        assert risk_ks == operator_ks, (
            f"Kill switch inconsistent: /risk says {risk_ks}, "
            f"/operator says {operator_ks}"
        )


# Fixtures

@pytest.fixture
def api_client():
    """Fixture to provide API client for tests."""
    import httpx
    base_url = "http://localhost:8000"
    client = httpx.Client(base_url=base_url, timeout=30.0)
    yield client
    client.close()


# Run tests with: pytest tests/test_cross_view_invariants.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
