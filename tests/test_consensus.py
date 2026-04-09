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
  7. WebSocket stream: seeded opinions/plans appear in WS payload
  8. Golden-path agent insight: agents → decision → plan → REST + WS
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
        engine.fee_bps = dict(PaperTradingEngine.DEFAULT_FEE_BPS)
        engine.total_fees_paid = 0.0
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


# ---------------------------------------------------------------------------
# WebSocket: consensus stream delivers real opinions/plans
# ---------------------------------------------------------------------------

@pytest.fixture
def ws_client():
    """TestClient that mounts a minimal app with the consensus WS endpoint.

    We can't import ``web.main`` directly because it has heavy transitive deps.
    Instead we register a local copy of the consensus WS handler that exercises
    the same ConsensusStore path.
    """
    import asyncio, uuid as _uuid
    from datetime import datetime as _dt
    from fastapi import WebSocket as _WS, WebSocketDisconnect as _WSD
    from web.api.missing_endpoints import router as missing_router

    app = FastAPI()
    app.include_router(missing_router)

    @app.websocket("/api/v1/consensus/ws/stream")
    async def _consensus_ws(websocket: _WS):
        await websocket.accept()
        _sent_op: set = set()
        _sent_pl: set = set()

        await websocket.send_json({
            "event_id": str(_uuid.uuid4()),
            "event_type": "connected",
            "timestamp": int(_dt.utcnow().timestamp() * 1000),
            "source": "consensus",
            "payload": {"message": "Connected to consensus stream"},
        })

        try:
            from core.consensus_store import get_consensus_store
            store = get_consensus_store()
            for op in store.list_opinions(limit=20):
                d = op.to_dict()
                await websocket.send_json({
                    "event_id": d["id"], "event_type": "opinion",
                    "timestamp": op.created_at, "source": "consensus",
                    "payload": d,
                })
                _sent_op.add(d["id"])
            for plan in store.list_plans(limit=20):
                d = plan.to_dict()
                await websocket.send_json({
                    "event_id": d["id"], "event_type": "trade_plan",
                    "timestamp": plan.created_at, "source": "consensus",
                    "payload": d,
                })
                _sent_pl.add(d["id"])
        except Exception:
            pass

        # Send a sentinel so the test knows the snapshot is complete
        await websocket.send_json({
            "event_id": "snapshot_done",
            "event_type": "snapshot_complete",
            "timestamp": int(_dt.utcnow().timestamp() * 1000),
            "source": "consensus",
            "payload": {},
        })

        try:
            while True:
                await asyncio.sleep(10)
        except _WSD:
            pass

    return TestClient(app)


class TestConsensusWebSocket:

    @staticmethod
    def _collect_until_sentinel(ws) -> list:
        """Read WS messages until snapshot_complete sentinel."""
        msgs = []
        for _ in range(30):
            msg = ws.receive_json()
            if msg.get("event_type") == "snapshot_complete":
                break
            msgs.append(msg)
        return msgs

    def test_seeded_opinions_appear_in_ws_stream(self, ws_client):
        """Opinions seeded into the store appear in the WS initial snapshot."""
        from core.consensus_store import add_opinion

        add_opinion(
            agent_id="gemma-1", agent_name="Gemma Analyst",
            symbol="BTC-USD", stance="bullish", confidence=0.82,
            reasoning="Strong momentum on 4H",
        )
        add_opinion(
            agent_id="skeptic-1", agent_name="Skeptic Agent",
            symbol="ETH-USD", stance="bearish", confidence=0.6,
            reasoning="Volume declining",
        )

        with ws_client.websocket_connect("/api/v1/consensus/ws/stream") as ws:
            msgs = self._collect_until_sentinel(ws)

            welcome = [m for m in msgs if m.get("event_type") == "connected"]
            assert len(welcome) == 1

            opinion_msgs = [m for m in msgs if m.get("event_type") == "opinion"]
            assert len(opinion_msgs) >= 2, f"Expected 2 opinions, got {len(opinion_msgs)}"

            agents = {m["payload"]["agent_id"] for m in opinion_msgs}
            assert "gemma-1" in agents
            assert "skeptic-1" in agents

    def test_seeded_plans_appear_in_ws_stream(self, ws_client):
        """Plans seeded into the store appear in the WS initial snapshot."""
        from core.consensus_store import add_plan

        add_plan(
            symbol="BTC-USD", title="BTC Long Entry", direction="long",
            confidence=0.85, supporting_agents=["gemma-1", "strategy-1"],
            status="approved",
        )

        with ws_client.websocket_connect("/api/v1/consensus/ws/stream") as ws:
            msgs = self._collect_until_sentinel(ws)

            plan_msgs = [m for m in msgs if m.get("event_type") == "trade_plan"]
            assert len(plan_msgs) >= 1, f"Expected 1 plan, got {len(plan_msgs)}"
            assert plan_msgs[0]["payload"]["symbol"] == "BTC-USD"
            assert plan_msgs[0]["payload"]["status"] == "approved"


# ---------------------------------------------------------------------------
# Golden-path: agents → decision → plan → REST + WS (full pipeline)
# ---------------------------------------------------------------------------

class TestConsensusGoldenPath:

    def test_agent_insight_pipeline(self, ws_client, missing_endpoints_client):
        """End-to-end: seed agent opinions → create plan → vote → approve →
        verify via REST *and* WS stream."""
        from core.consensus_store import add_opinion, add_plan, get_consensus_store

        # Step 1: Agents emit opinions
        add_opinion(
            agent_id="analyst-gemma", agent_name="Gemma Analyst", role="bull_analyst",
            symbol="BTC-USD", stance="bullish", confidence=0.85,
            reasoning="RSI crossed 50 with volume confirmation",
        )
        add_opinion(
            agent_id="risk-mgr", agent_name="Risk Manager", role="risk_manager",
            symbol="BTC-USD", stance="cautious", confidence=0.7,
            reasoning="Position size within limits but near daily loss threshold",
        )

        # Step 2: Consensus produces a trade plan
        plan = add_plan(
            symbol="BTC-USD", title="BTC Long Entry", direction="long",
            target_size_usd=5000.0, confidence=0.8,
            supporting_agents=["analyst-gemma"], status="proposed",
        )

        # Step 3: Agents vote on the plan
        store = get_consensus_store()
        store.vote_on_plan(plan.id, "analyst-gemma", "for")
        store.vote_on_plan(plan.id, "risk-mgr", "for")

        # Step 4: Plan is approved
        store.update_plan_status(plan.id, "approved")

        # ── Verify via REST ──────────────────────────────────────────
        resp = missing_endpoints_client.get("/api/v1/consensus/opinions")
        data = resp.json()
        assert data["total"] == 2
        assert any(o["agent_id"] == "analyst-gemma" for o in data["opinions"])

        resp = missing_endpoints_client.get("/api/v1/consensus/plans")
        data = resp.json()
        assert data["total"] == 1
        assert data["plans"][0]["status"] == "approved"
        assert data["plans"][0]["votes_for"] == 2

        resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
        metrics = resp.json()
        assert metrics["total_opinions"] == 2
        assert metrics["total_decisions"] == 1
        assert metrics["approved"] == 1

        # ── Verify via WebSocket ─────────────────────────────────────
        with ws_client.websocket_connect("/api/v1/consensus/ws/stream") as ws:
            msgs = TestConsensusWebSocket._collect_until_sentinel(ws)

            opinion_msgs = [m for m in msgs if m.get("event_type") == "opinion"]
            plan_msgs = [m for m in msgs if m.get("event_type") == "trade_plan"]

            assert len(opinion_msgs) >= 2, "Both opinions should stream via WS"
            assert len(plan_msgs) >= 1, "Approved plan should stream via WS"
            assert plan_msgs[0]["payload"]["status"] == "approved"


# ---------------------------------------------------------------------------
# GET /api/v1/consensus/summary
# ---------------------------------------------------------------------------

class TestConsensusSummary:

    def test_empty_store_returns_empty_symbols(self, missing_endpoints_client):
        resp = missing_endpoints_client.get("/api/v1/consensus/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbols"] == []
        assert data["stub"] is False

    def test_multi_symbol_aggregation(self, missing_endpoints_client):
        from core.consensus_store import add_opinion, add_plan

        # BTC — mostly bullish, high confidence → strong_long
        add_opinion(agent_id="a1", agent_name="A1", symbol="BTC-USD",
                    stance="bullish", confidence=0.85)
        add_opinion(agent_id="a2", agent_name="A2", symbol="BTC-USD",
                    stance="bullish", confidence=0.75)
        add_opinion(agent_id="a3", agent_name="A3", symbol="BTC-USD",
                    stance="neutral", confidence=0.5)
        add_plan(symbol="BTC-USD", title="BTC Long", direction="long",
                 confidence=0.8, supporting_agents=["a1", "a2"], status="approved")

        # AAPL — balanced → neutral
        add_opinion(agent_id="a1", agent_name="A1", symbol="AAPL",
                    stance="bullish", confidence=0.5)
        add_opinion(agent_id="a2", agent_name="A2", symbol="AAPL",
                    stance="bearish", confidence=0.5)

        # ETH — bearish, high confidence → strong_short
        add_opinion(agent_id="a1", agent_name="A1", symbol="ETH-USD",
                    stance="bearish", confidence=0.9)
        add_opinion(agent_id="a2", agent_name="A2", symbol="ETH-USD",
                    stance="bearish", confidence=0.8)
        add_opinion(agent_id="a3", agent_name="A3", symbol="ETH-USD",
                    stance="bearish", confidence=0.75)

        resp = missing_endpoints_client.get("/api/v1/consensus/summary")
        data = resp.json()
        assert data["stub"] is False
        assert len(data["symbols"]) == 3

        by_sym = {s["symbol"]: s for s in data["symbols"]}

        # BTC: 2 bullish / 1 neutral, avg conf ~0.7 → strong_long
        assert by_sym["BTC-USD"]["stance"] == "strong_long"
        assert by_sym["BTC-USD"]["asset_class"] == "crypto"
        assert by_sym["BTC-USD"]["active_plans"]["approved"] == 1
        assert by_sym["BTC-USD"]["supporting_agents"] == 2

        # AAPL: 1 bull / 1 bear → neutral
        assert by_sym["AAPL"]["stance"] == "neutral"
        assert by_sym["AAPL"]["asset_class"] == "equity"

        # ETH: all bearish, high conf → strong_short
        assert by_sym["ETH-USD"]["stance"] == "strong_short"
        assert by_sym["ETH-USD"]["asset_class"] == "crypto"

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        with patch.dict("sys.modules", {"core.consensus_store": None}):
            resp = missing_endpoints_client.get("/api/v1/consensus/summary")
            data = resp.json()
            assert data.get("_stub") is True or data.get("stub") is True

    def test_asset_class_heuristics(self, missing_endpoints_client):
        from core.consensus_store import add_opinion

        add_opinion(agent_id="a1", symbol="BTC-USD", stance="bullish", confidence=0.7)
        add_opinion(agent_id="a1", symbol="AAPL", stance="bullish", confidence=0.6)
        add_opinion(agent_id="a1", symbol="EURUSD", stance="bearish", confidence=0.5)
        add_opinion(agent_id="a1", symbol="SPY", stance="neutral", confidence=0.5)

        resp = missing_endpoints_client.get("/api/v1/consensus/summary")
        by_sym = {s["symbol"]: s for s in resp.json()["symbols"]}

        assert by_sym["BTC-USD"]["asset_class"] == "crypto"
        assert by_sym["AAPL"]["asset_class"] == "equity"
        assert by_sym["EURUSD"]["asset_class"] == "fx"
        assert by_sym["SPY"]["asset_class"] == "equity"


# ---------------------------------------------------------------------------
# Consensus Quality Index
# ---------------------------------------------------------------------------

class TestConsensusQualityIndex:

    def test_no_decided_plans_returns_neutral(self, missing_endpoints_client):
        resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
        data = resp.json()
        assert "quality" in data
        assert data["quality"]["band"] == "neutral"
        assert data["quality"]["window_trades"] == 0

    def test_good_quality_band(self, missing_endpoints_client):
        from core.consensus_store import add_plan, get_consensus_store

        store = get_consensus_store()
        # Seed 5 approved plans with high confidence and no opposing votes
        for i in range(5):
            p = add_plan(symbol="BTC-USD", title=f"Plan {i}", direction="long",
                         confidence=0.85, supporting_agents=["a1"], status="approved")
            store.vote_on_plan(p.id, "a1", "for")

        resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
        q = resp.json()["quality"]
        assert q["band"] == "good"
        assert q["quality_index"] >= 0.65
        assert q["window_trades"] == 5

    def test_poor_quality_band(self, missing_endpoints_client):
        from core.consensus_store import add_plan, get_consensus_store

        store = get_consensus_store()
        # Seed 5 rejected plans with low confidence and opposing votes
        for i in range(5):
            p = add_plan(symbol="BTC-USD", title=f"Plan {i}", direction="long",
                         confidence=0.2, supporting_agents=[], status="rejected")
            store.vote_on_plan(p.id, "a1", "against")

        resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
        q = resp.json()["quality"]
        assert q["band"] == "poor"
        assert q["quality_index"] < 0.4

    def test_import_failure_returns_stub_quality(self, missing_endpoints_client):
        with patch.dict("sys.modules", {"core.consensus_store": None}):
            resp = missing_endpoints_client.get("/api/v1/consensus/metrics")
            data = resp.json()
            assert data.get("_stub") is True
            assert data["quality"]["band"] == "neutral"


# ---------------------------------------------------------------------------
# Notification enrichment: plan_id in fill notifications
# ---------------------------------------------------------------------------

class TestNotificationEnrichment:

    def test_trade_fill_notification_includes_plan_id(self, missing_endpoints_client):
        """When an order fills, the notification should reference the plan."""
        from trading.paper_trading import PaperTradingEngine, PaperPortfolio

        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        engine.starting_balance = 100000.0
        engine.portfolios = {"operator": PaperPortfolio(user_id="operator", starting_balance=100000.0, current_balance=100000.0)}
        engine.order_counter = 0
        engine.position_counter = 0
        engine.fee_bps = dict(PaperTradingEngine.DEFAULT_FEE_BPS)
        engine.total_fees_paid = 0.0
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

        # Check notification contains plan reference
        resp = missing_endpoints_client.get("/api/v1/notifications")
        notifs = resp.json()["notifications"]
        fill_notifs = [n for n in notifs if "Filled" in n.get("title", "")]
        assert len(fill_notifs) >= 1
        # plan_id should be in the message text
        assert "plan" in fill_notifs[0]["message"].lower()
        # metadata should contain plan_id
        if fill_notifs[0].get("metadata"):
            assert "plan_id" in fill_notifs[0]["metadata"]
            assert fill_notifs[0]["metadata"]["plan_id"].startswith("plan-")
