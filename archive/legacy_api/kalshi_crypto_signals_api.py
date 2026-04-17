# web/api/kalshi_crypto_signals_api.py
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException

from web.api.auth import get_current_session
from utils.logger import get_logger
from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
from consensus.consensus_coordinator import get_consensus_coordinator
from web.api.config.kalshi_signals import CRYPTO_AGENT_IDS

from .models.signals import (
    KalshiEdgeSignal,
    KalshiEdgeResponse,
    KalshiConsensusSignal,
    KalshiConsensusSignalsResponse)

logger = get_logger("web.api.kalshi_crypto_signals")

router = APIRouter(
    prefix="/api/v1/kalshi-grid/crypto",
    tags=["Kalshi Crypto Signals"],
)


@router.get("/edge", response_model=KalshiEdgeResponse)
async def get_crypto_edge_signals() -> KalshiEdgeResponse:
    try:
        tracker = get_agent_performance_tracker()
        signals: Dict[str, KalshiEdgeSignal] = {}

        for agent_id in CRYPTO_AGENT_IDS:
            m = tracker.get_agent_metrics(agent_id)
            if not m or getattr(m, "total_fills", 0) == 0:
                continue

            # Example: use last signal stats or rolling averages
            implied = getattr(m, "last_implied_prob", None)
            model = getattr(m, "last_model_prob", None)
            if implied is None or model is None:
                continue

            ev_cents = (model - implied) * 100
            edge_pct = model - implied
            confidence = getattr(m, "avg_confidence", 0.0)
            bucket = "high" if confidence > 0.7 else "medium" if confidence > 0.5 else "low"

            signals[agent_id] = KalshiEdgeSignal(
                implied_prob=implied,
                model_prob=model,
                ev_cents=ev_cents,
                edge_pct=edge_pct,
                confidence=confidence,
                confidence_bucket=bucket,
                sizing_tier="crypto",
                product=getattr(m, "product", None),
                agent_id=agent_id,
                market_id=getattr(m, "last_market_id", None),
                bid=getattr(m, "last_best_bid", None),
                ask=getattr(m, "last_best_ask", None))

        count = len(signals)
        kelly_fraction = 1.0  # or derive from portfolio risk
        effective_fraction = kelly_fraction  # adjusted for DD if needed
        drawdown_pct = tracker.get_system_summary().get("max_drawdown_pct", 0.0)

        return KalshiEdgeResponse(
            signals=signals,
            count=count,
            kelly_fraction=kelly_fraction,
            effective_fraction=effective_fraction,
            drawdown_pct=drawdown_pct)
    except Exception as exc:
        logger.error(f"Failed to get crypto edge signals: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/rti")
async def get_crypto_rti_signals() -> Dict:
    """Real-time indicator (RTI) data for crypto assets — vol ratio, SMA deviation, spike events."""
    try:
        tracker = get_agent_performance_tracker()
        data: Dict[str, dict] = {}

        for agent_id in CRYPTO_AGENT_IDS:
            m = tracker.get_agent_metrics(agent_id)
            if not m:
                continue
            asset = agent_id.split("_")[0].upper()
            data[asset] = {
                "rti": getattr(m, "rti", 0.0),
                "sma_60s": getattr(m, "sma_60s", 0.0),
                "vol_ratio": getattr(m, "vol_ratio", 1.0),
                "vol_spike_events": [],
                "rti_sma_deviation": getattr(m, "rti", 0.0) - getattr(m, "sma_60s", 0.0),
                "recent_vol_spikes": 0,
                "max_recent_spike": 0.0,
            }

        import time
        return {"data": data, "timestamp": int(time.time()), "source": "agent_tracker"}
    except Exception as exc:
        logger.error(f"Failed to get crypto RTI signals: {exc}")
        import time
        return {"data": {}, "timestamp": int(time.time()), "source": "error", "error": str(exc)}


@router.get("/consensus", response_model=KalshiConsensusSignalsResponse)
async def get_crypto_consensus_signals() -> KalshiConsensusSignalsResponse:
    try:
        coordinator = get_consensus_coordinator()
        # however you already pull consensus rows
        rows = coordinator.get_kalshi_crypto_consensus()  # adapt to your API

        signals: list[KalshiConsensusSignal] = []
        pending_votes = 0

        for r in rows:
            signals.append(
                KalshiConsensusSignal(
                    ticker=r.ticker,
                    direction=r.direction,
                    confidence=r.confidence,
                    vote_count=r.vote_count,
                    bull_weight=r.bull_weight,
                    bear_weight=r.bear_weight,
                    agents=r.agents,
                    product=getattr(r, "product", None),
                    agent_id=getattr(r, "agent_id", None))
            )
            pending_votes += getattr(r, "pending_votes", 0)

        return KalshiConsensusSignalsResponse(
            signals=signals,
            count=len(signals),
            pending_votes=pending_votes,
            consensus_rate=coordinator.get_consensus_rate(domain="kalshi_crypto"),
            engine_running=True,
            error=None)
    except Exception as exc:
        logger.error(f"Failed to get crypto consensus signals: {exc}")
        return KalshiConsensusSignalsResponse(
            signals=[],
            count=0,
            pending_votes=0,
            consensus_rate=0.0,
            engine_running=False,
            error=str(exc))
