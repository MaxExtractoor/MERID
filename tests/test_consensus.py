"""
Integration tests for the consensus/agent plans feature.

Tests the full stack: ConsensusStore (SQLite) → API endpoints → response shape.
Uses a temporary DB to avoid polluting the real store.

Covers:
  1. GET /api/v1/consensus/opinions — empty, with data, stub fallback
  2. GET /api/v1/consensus/plans — empty, with data, status filter, stub fallback
  3. GET /api/v1/consensus/metrics — real metrics, stub fallback
  4. POST /api/v1/consensus/plans/{id}/vote — vote recording
  5. POST /api/v1/consensus/plans/{id}/status — status update + notification
  6. Golden-path: trade fill → consensus opinion + plan emitted
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_stores():
    """Inject temp ConsensusStore + NotificationStore for every test."""
    fd1, cs_path = tempfile.mkstemp(suffix=".db")
    os.close(fd1)
    os.unlink(cs_path)
    fd2, ns_path = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    os.unlink(ns_path)

    import core.consensus_store as cs_mod
    import core.notifications as notif_mod

    old_cs = cs_mod._store
    old_ns = notif_mod._store
    cs_mod._store = cs_mod.ConsensusStore(db_path=cs_path)
    notif_mod._store = notif_mod.NotificationStore(db_path=ns_path)

    yield

    cs_mod._store = old_cs
    notif_mod._store = old_ns
    for p in (cs_path, ns_path):
        try:
            os.unlink(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GET /api/v1/consensus/opinions
# ---------------------------------------------------------------------------

class TestConsensusOpinions:

    def test_empty_store_returns_real_empty(self, missing_endpoints_client):
        resp = missing_endpoints_client.get("/api/v1/consensus/opinions")
        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert data["opinions"] == []
        assert data["total"] == 0

    def test_returns_added_opinions(self, missing_endpoints_client):
        from core.consensus_store import add_opinion

        add_opinion(agent_id="gemma-1", agent_name="Gemma", symbol="BTC-USD",
                    stance="bullish", confidence=0.82, reasoning="Strong momentum")
        add_opinion(agent_id="skeptic-1", agent_name="Skeptic", symbol="BTC-USD",
                    stance="neutral", confidence=0.55, reasoning="Volume declining")

        resp = missing_endpoints_client.get("/api/v1/consensus/opinions")
        data = resp.json()
        assert "_stub" not in data
        assert data["total"] == 2
        assert len(data["opinions"]) == 2
        # Newest first
        assert data["opinions"][0]["agent"] == "Skeptic"
        assert data["opinions"][0]["stance"] == "neutral"

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        broken = MagicMock()
        broken.get_consensus_store.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"core.consensus_store": broken}):
            resp = missing_endpoints_client.get("/api/v1/consensus/opinions")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# GET /api/v1/consensus/plans
# ---------------------------------------------------------------------------

class TestConsensusPlans:

    def test_empty_store_returns_real_empty(self, missing_endpoints_client):
        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert data["plans"] == []
        assert data["total"] == 0

    def test_returns_added_plans(self, missing_endpoints_client):
        from core.consensus_store import add_plan

        add_plan(symbol="BTC-USD", title="BTC Long Entry", direction="long",
                 confidence=0.85, supporting_agents=["gemma-1", "strategy-1"],
                 status="approved")
        add_plan(symbol="ETH-USD", title="ETH Short Hedge", direction="short",
                 confidence=0.6, supporting_agents=["risk-1"],
                 status="pending")

        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        data = resp.json()
        assert "_stub" not in data
        assert data["total"] == 2
        assert len(data["plans"]) == 2

    def test_status_filter(self, missing_endpoints_client):
        from core.consensus_store import add_plan

        add_plan(symbol="BTC-USD", title="Plan A", status="approved")
        add_plan(symbol="ETH-USD", title="Plan B", status="pending")

        resp = missing_endpoints_client.get("/api/v1/consensus/plans?status=approved")
        data = resp.json()
        assert len(data["plans"]) == 1
        assert data["plans"][0]["status"] == "approved"

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        broken = MagicMock()
        broken.get_consensus_store.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"core.consensus_store": broken}):
            resp = missing_endpoints_client.get("/api/v1/consensus/plans")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# GET /api/v1/consensus/metrics
# ---------------------------------------------------------------------------

class TestConsensusMetrics:

    def test_metrics_with_data(self, missing_endpoints_client):
        from core.consensus_store import add_opinion, add_plan, get_consensus_store

        add_opinion(agent_id="a1", agent_name="A1", stance="bullish")
        add_plan(symbol="BTC-USD", title="P1", status="approved",
                 supporting_agents=["a1", "a2"])
        add_plan(symbol="ETH-USD", title="P2", status="rejected")

        resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
        data = resp.json()
        assert "_stub" not in data
        assert data["total_opinions"] == 1
        assert data["total_decisions"] == 2
        assert data["approved"] == 1
        assert data["rejected"] == 1
        assert data["consensus_rate"] == 0.5

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        broken = MagicMock()
        broken.get_consensus_store.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"core.consensus_store": broken}):
            resp = missing_endpoints_client.get("/api/v1/consensus/metrics")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# POST /api/v1/consensus/plans/{id}/vote
# ---------------------------------------------------------------------------

class TestPlanVoting:

    def test_vote_for_plan(self, missing_endpoints_client):
        from core.consensus_store import add_plan

        p = add_plan(symbol="BTC-USD", title="BTC Long", status="proposed")

        resp = missing_endpoints_client.post(
            f"/api/v1/consensus/plans/{p.id}/vote",
            json={"agent_id": "gemma-1", "vote": "for"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify vote recorded
        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        plan = resp.json()["plans"][0]
        assert plan["votes_for"] == 1
        assert "gemma-1" in plan["supporting_agents"]

    def test_vote_against_plan(self, missing_endpoints_client):
        from core.consensus_store import add_plan

        p = add_plan(symbol="BTC-USD", title="BTC Long", status="proposed")

        resp = missing_endpoints_client.post(
            f"/api/v1/consensus/plans/{p.id}/vote",
            json={"agent_id": "skeptic-1", "vote": "against"},
        )
        assert resp.json()["success"] is True

        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        plan = resp.json()["plans"][0]
        assert plan["votes_against"] == 1
        assert "skeptic-1" in plan["opposing_agents"]

    def test_vote_nonexistent_returns_false(self, missing_endpoints_client):
        resp = missing_endpoints_client.post(
            "/api/v1/consensus/plans/nonexistent/vote",
            json={"agent_id": "a1", "vote": "for"},
        )
        assert resp.json()["success"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/consensus/plans/{id}/status
# ---------------------------------------------------------------------------

class TestPlanStatusUpdate:

    def test_approve_plan_emits_notification(self, missing_endpoints_client):
        from core.consensus_store import add_plan

        p = add_plan(symbol="BTC-USD", title="BTC Long", status="proposed")

        resp = missing_endpoints_client.post(
            f"/api/v1/consensus/plans/{p.id}/status",
            json={"status": "approved"},
        )
        assert resp.json()["success"] is True

        # Verify plan status updated
        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        assert resp.json()["plans"][0]["status"] == "approved"

        # Verify notification emitted
        resp = missing_endpoints_client.get("/api/v1/notifications")
        notifs = resp.json()["notifications"]
        assert any("Plan Approved" in n["title"] for n in notifs)


# ---------------------------------------------------------------------------
# Golden-path: trade fill → consensus opinion + plan
# ---------------------------------------------------------------------------

class TestConsensusTradeIntegration:

    def test_trade_fill_emits_consensus_artifacts(self, missing_endpoints_client):
        """When an order fills, a consensus opinion and plan are emitted."""
        from trading.paper_trading import PaperTradingEngine, PaperPortfolio

        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        engine.starting_balance = 100000.0
        engine.portfolios = {"operator": PaperPortfolio(user_id="operator", starting_balance=100000.0, current_balance=100000.0)}
        engine.order_counter = 0
        engine.position_counter = 0
        engine.current_prices = {"BTC-USD": 68000.0, "BTC/USDT": 68000.0}
        engine.price_feed = None
        engine._listeners = {"trade": set(), "summary": set(), "position": set()}
        engine._summary_dirty = False
        engine._positions_dirty = False
        engine._last_summary_emit = 0.0
        engine._last_positions_emit = 0.0
        engine.summary_snapshot = None

        pt_mod = MagicMock()
        pt_mod.get_paper_engine = MagicMock(return_value=engine)

        pd_mock = MagicMock()
        pd_mock.price = 68000.0
        feed = MagicMock()
        feed.price_cache = {"BTC/USDT": pd_mock}
        pf_mod = MagicMock()
        pf_mod.get_live_price_feed = MagicMock(return_value=feed)

        mods = {
            "trading.paper_trading": pt_mod,
            "data.live_price_feed": pf_mod,
        }

        with patch.dict("sys.modules", mods):
            with patch("trading.paper_trading._save_paper_state"):
                with patch("trading.paper_trading._get_risk_controller", return_value=None):
                    resp = missing_endpoints_client.post("/api/v1/orders/submit", json={
                        "symbol": "BTC-USD", "side": "BUY",
                        "orderType": "MARKET", "size": "0.1",
                    })
                    assert resp.json()["success"] is True

        # Check consensus opinion was emitted
        resp = missing_endpoints_client.get("/api/v1/consensus/opinions")
        data = resp.json()
        assert data["total"] >= 1
        trading_ops = [o for o in data["opinions"] if o["agent_id"] == "trading-engine"]
        assert len(trading_ops) >= 1
        assert trading_ops[0]["stance"] == "bullish"
        assert "BTC-USD" in trading_ops[0]["symbol"]

        # Check consensus plan was emitted
        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        data = resp.json()
        assert data["total"] >= 1
        trade_plans = [p for p in data["plans"] if p["status"] == "executed"]
        assert len(trade_plans) >= 1
        assert "BTC-USD" in trade_plans[0]["symbol"]
