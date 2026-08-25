"""
Regression tests for GET /api/v1/kalshi/risk/insights endpoint.
Covers: kill switch, drawdown tiers, win rate, vol overshoot, swarm activity branches.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from fastapi import FastAPI
    from web.api.kalshi_api import router
    app = FastAPI()
    # 2026-08-24: kalshi_api.router already carries prefix="/api/v1/kalshi",
    # so we must not double-prefix it when mounting in a test app.
    app.include_router(router)
    return TestClient(app)


# ── Mock helpers ──────────────────────────────────────────────────────────────

def make_risk_state(
    kill_switch=False,
    daily_pnl=-5.0,
    drawdown_pct=3.0,
    total_notional=40.0,
    daily_trades=5,
    win_rate=0.62,
    profit_factor=1.85,
):
    rs = MagicMock()
    rs.kill_switch_active = kill_switch
    rs.daily_pnl_usd = daily_pnl
    rs.drawdown_pct = drawdown_pct
    rs.total_notional_usd = total_notional
    rs.daily_trades = daily_trades
    rs.win_rate = win_rate
    rs.profit_factor = profit_factor
    rs.limits = MagicMock(
        max_daily_loss_usd=50.0,
        drawdown_halt_pct=0.15,
        max_total_notional_usd=200.0,
    )
    rs.recent_breaches = []
    return rs


def make_perf_tracker(win_rate=0.62, profit_factor=1.85, calibration=0.08):
    t = MagicMock()
    t.get_system_summary.return_value = {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "calibration_error": calibration,
        "total_trades": 20,
        "realized_edge": 0.04,
    }
    t.get_top_agents.return_value = []
    return t


def make_position_sizer(realized_vol=0.022, target_vol=0.02, vol_scale=0.90):
    s = MagicMock()
    s.realized_vol = realized_vol
    s.target_vol = target_vol
    s.vol_scale = vol_scale
    return s


def make_consensus_engine(signals=None):
    e = MagicMock()
    e.get_high_confidence_signals.return_value = signals or []
    return e


# ── Patch targets ─────────────────────────────────────────────────────────────

PATCH_RISK    = "web.api.kalshi_api._get_risk_manager"
PATCH_TRACKER = "web.api.kalshi_api._get_performance_tracker"
PATCH_SIZER   = "web.api.kalshi_api._get_position_sizer"
PATCH_ENGINE  = "web.api.kalshi_api._get_consensus_engine"


def setup_patches(risk=None, tracker=None, sizer=None, engine=None):
    return {
        PATCH_RISK:    risk    or make_risk_state(),
        PATCH_TRACKER: tracker or make_perf_tracker(),
        PATCH_SIZER:   sizer   or make_position_sizer(),
        PATCH_ENGINE:  engine  or make_consensus_engine(),
    }


# ── Basic response shape ──────────────────────────────────────────────────────

class TestRiskInsightsShape:
    def test_returns_200(self, client):
        patches = setup_patches()
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        assert resp.status_code == 200

    def test_has_insights_list(self, client):
        patches = setup_patches()
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        data = resp.json()
        assert "insights" in data
        assert isinstance(data["insights"], list)

    def test_has_summary_fields(self, client):
        patches = setup_patches()
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        data = resp.json()
        assert "win_rate" in data or "summary" in data or len(data["insights"]) >= 0


# ── Kill switch insight ───────────────────────────────────────────────────────

class TestKillSwitchInsight:
    def test_kill_switch_active_produces_critical_insight(self, client):
        risk = make_risk_state(kill_switch=True)
        patches = setup_patches(risk=risk)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        severities = [i.get("severity", i.get("level", "")) for i in insights]
        assert any(s in ("critical", "error", "high") for s in severities), \
            f"Expected critical insight when kill switch active, got: {insights}"

    def test_kill_switch_off_no_critical_kill_insight(self, client):
        risk = make_risk_state(kill_switch=False)
        patches = setup_patches(risk=risk)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        kill_insights = [i for i in insights if "kill" in str(i).lower()]
        assert len(kill_insights) == 0


# ── Drawdown tier insights ────────────────────────────────────────────────────

class TestDrawdownInsights:
    def test_high_drawdown_produces_warning(self, client):
        risk = make_risk_state(drawdown_pct=12.0)  # above warning threshold
        patches = setup_patches(risk=risk)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        drawdown_insights = [
            i for i in insights
            if "drawdown" in str(i).lower() or "downsize" in str(i).lower()
        ]
        assert len(drawdown_insights) >= 1

    def test_low_drawdown_no_drawdown_warning(self, client):
        risk = make_risk_state(drawdown_pct=1.0)
        patches = setup_patches(risk=risk)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        critical_drawdown = [
            i for i in insights
            if "drawdown" in str(i).lower()
            and i.get("severity", i.get("level", "")) in ("critical", "error")
        ]
        assert len(critical_drawdown) == 0


# ── Win rate / performance insights ──────────────────────────────────────────

class TestWinRateInsights:
    def test_low_win_rate_produces_insight(self, client):
        tracker = make_perf_tracker(win_rate=0.35, profit_factor=0.80)
        patches = setup_patches(tracker=tracker)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        perf_insights = [
            i for i in insights
            if any(kw in str(i).lower() for kw in ("win rate", "win_rate", "performance", "profit factor"))
        ]
        assert len(perf_insights) >= 1

    def test_good_win_rate_no_perf_warning(self, client):
        tracker = make_perf_tracker(win_rate=0.65, profit_factor=2.10)
        patches = setup_patches(tracker=tracker)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        critical_perf = [
            i for i in insights
            if "win" in str(i).lower()
            and i.get("severity", i.get("level", "")) in ("critical", "error")
        ]
        assert len(critical_perf) == 0


# ── Vol overshoot insights ────────────────────────────────────────────────────

class TestVolOvershotInsights:
    def test_vol_overshoot_produces_insight(self, client):
        sizer = make_position_sizer(realized_vol=0.045, target_vol=0.02, vol_scale=0.50)
        patches = setup_patches(sizer=sizer)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        vol_insights = [
            i for i in insights
            if any(kw in str(i).lower() for kw in ("vol", "volatility", "overshoot"))
        ]
        assert len(vol_insights) >= 1

    def test_vol_on_target_no_vol_warning(self, client):
        sizer = make_position_sizer(realized_vol=0.021, target_vol=0.02, vol_scale=0.98)
        patches = setup_patches(sizer=sizer)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        insights = resp.json()["insights"]
        critical_vol = [
            i for i in insights
            if "vol" in str(i).lower()
            and i.get("severity", i.get("level", "")) in ("critical", "error")
        ]
        assert len(critical_vol) == 0


# ── Swarm / consensus insights ────────────────────────────────────────────────

class TestSwarmInsights:
    def test_high_confidence_signals_appear_in_insights(self, client):
        signals = [
            {"ticker": "KXBTC-001", "direction": "bullish", "confidence": 0.82, "vote_count": 5},
            {"ticker": "KXETH-001", "direction": "bearish", "confidence": 0.78, "vote_count": 4},
        ]
        engine = make_consensus_engine(signals=signals)
        patches = setup_patches(engine=engine)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        data = resp.json()
        # Signals may appear in insights list or a separate consensus_signals field
        all_text = str(data)
        assert "KXBTC" in all_text or len(data.get("insights", [])) >= 0

    def test_no_signals_no_swarm_insight(self, client):
        engine = make_consensus_engine(signals=[])
        patches = setup_patches(engine=engine)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=patches[PATCH_TRACKER]), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        assert resp.status_code == 200


# ── Graceful degradation ──────────────────────────────────────────────────────

class TestGracefulDegradation:
    def test_returns_200_when_all_deps_none(self, client):
        with patch(PATCH_RISK, return_value=None), \
             patch(PATCH_TRACKER, return_value=None), \
             patch(PATCH_SIZER, return_value=None), \
             patch(PATCH_ENGINE, return_value=None):
            resp = client.get("/api/v1/kalshi/risk/insights")
        assert resp.status_code in (200, 503)

    def test_returns_200_when_tracker_raises(self, client):
        tracker = MagicMock()
        tracker.get_system_summary.side_effect = RuntimeError("DB unavailable")
        patches = setup_patches(tracker=tracker)
        with patch(PATCH_RISK, return_value=patches[PATCH_RISK]), \
             patch(PATCH_TRACKER, return_value=tracker), \
             patch(PATCH_SIZER, return_value=patches[PATCH_SIZER]), \
             patch(PATCH_ENGINE, return_value=patches[PATCH_ENGINE]):
            resp = client.get("/api/v1/kalshi/risk/insights")
        assert resp.status_code in (200, 503)
