"""§5 Prediction Market API — Dashboard endpoints, alerts, and control plane.

Endpoints:
- GET  /api/v1/prediction-markets/summary     — Full PM dashboard summary
- GET  /api/v1/prediction-markets/markets      — Active markets with edge/state
- GET  /api/v1/prediction-markets/positions     — Current PM positions + PnL
- GET  /api/v1/prediction-markets/risk          — Risk summary + breach log
- GET  /api/v1/prediction-markets/alerts        — Alert history
- POST /api/v1/prediction-markets/pause         — Pause PM trading
- POST /api/v1/prediction-markets/resume        — Resume PM trading
- POST /api/v1/prediction-markets/mode          — Switch PM mode (SIM/PAPER/LIVE)
- POST /api/v1/prediction-markets/kill-switch   — Activate/deactivate kill switch
- GET  /api/v1/prediction-markets/venue-gate    — Venue gate status
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from merid.prediction.venue_gate import TradingMode, VenueGate, get_venue_gate
from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
from merid.prediction.alerts import PredictionAlertManager
from merid.prediction.model import PredictionMarketModel
from merid.prediction.strategy import KalshiStrategy, StrategyConfig

from utils.logger import get_logger

logger = get_logger("web.api.prediction_markets")

router = APIRouter(prefix="/api/v1/prediction-markets", tags=["prediction-markets"])

# ── Singletons (initialised on first import) ─────────────────────────
_risk: Optional[PredictionMarketRisk] = None
_alerts: Optional[PredictionAlertManager] = None
_model: Optional[PredictionMarketModel] = None
_strategy: Optional[KalshiStrategy] = None


def _get_risk() -> PredictionMarketRisk:
    global _risk
    if _risk is None:
        _risk = PredictionMarketRisk()
    return _risk


def _get_alerts() -> PredictionAlertManager:
    global _alerts
    if _alerts is None:
        _alerts = PredictionAlertManager()
    return _alerts


def _get_model() -> PredictionMarketModel:
    global _model
    if _model is None:
        _model = PredictionMarketModel()
    return _model


def _get_strategy() -> KalshiStrategy:
    global _strategy
    if _strategy is None:
        _strategy = KalshiStrategy()
    return _strategy


# ── Request / Response models ─────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: str  # "sim", "paper", "live"


class KillSwitchRequest(BaseModel):
    activate: bool
    reason: str = ""
    unwind: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/summary")
async def pm_summary():
    """Full prediction-market dashboard summary."""
    gate = get_venue_gate()
    risk = _get_risk()
    alerts = _get_alerts()

    return {
        "venue_gate": gate.summary(),
        "risk": risk.summary(),
        "alerts": alerts.summary(),
    }


@router.get("/risk")
async def pm_risk():
    """Risk summary including exposures, daily PnL, and breach log."""
    return _get_risk().summary()


@router.get("/alerts")
async def pm_alerts(limit: int = 50, category: Optional[str] = None):
    """Alert history, optionally filtered by category."""
    mgr = _get_alerts()
    cat = None
    if category:
        from merid.prediction.alerts import AlertCategory
        try:
            cat = AlertCategory(category)
        except ValueError:
            raise HTTPException(400, f"Unknown category: {category}")
    history = mgr.get_history(limit=limit, category=cat)
    return {"alerts": [a.to_dict() for a in history]}


@router.get("/venue-gate")
async def pm_venue_gate():
    """Current venue gate status (mode, allowed venues, etc.)."""
    return get_venue_gate().summary()


@router.post("/pause")
async def pm_pause():
    """Pause prediction-market trading (switch to SIM mode)."""
    gate = get_venue_gate()
    old_mode = gate.mode
    gate.mode = TradingMode.SIM
    logger.info(f"PM trading paused from {old_mode.value}")
    return {"status": "paused", "previous_mode": old_mode.value, "current_mode": "sim"}


@router.post("/resume")
async def pm_resume():
    """Resume prediction-market trading (switch back to PAPER mode)."""
    gate = get_venue_gate()
    gate.mode = TradingMode.PAPER
    logger.info("PM trading resumed to PAPER mode")
    return {"status": "resumed", "current_mode": "paper"}


@router.post("/mode")
async def pm_set_mode(req: ModeRequest):
    """Switch prediction-market trading mode."""
    try:
        new_mode = TradingMode(req.mode.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid mode: {req.mode}. Use sim/paper/live.")

    gate = get_venue_gate()
    old_mode = gate.mode
    gate.mode = new_mode
    logger.info(f"PM mode changed: {old_mode.value} -> {new_mode.value}")
    return {"status": "ok", "previous_mode": old_mode.value, "current_mode": new_mode.value}


@router.post("/kill-switch")
async def pm_kill_switch(req: KillSwitchRequest):
    """Activate or deactivate the prediction-market kill switch."""
    risk = _get_risk()
    alerts = _get_alerts()

    if req.activate:
        risk.halt(req.reason or "Manual kill switch", unwind=req.unwind)
        alerts.fire_kill_switch(req.reason or "Manual kill switch", req.unwind)
        return {"status": "halted", "reason": req.reason, "unwind": req.unwind}
    else:
        risk.resume()
        return {"status": "resumed"}
