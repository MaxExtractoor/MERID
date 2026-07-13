# web/api/kalshi_crypto_signals_api.py
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query

from web.api.auth import get_current_session
from utils.logger import get_logger
from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
# LEGACY REMOVAL: consensus.consensus_coordinator import removed - consensus module deleted
# from consensus.consensus_coordinator import get_consensus_coordinator
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

            # Use canonical EV calculation from canonical_buckets
            from merid.metrics.canonical_buckets import calculate_ev_cents, calculate_edge_pct
            ev_cents = calculate_ev_cents(int(implied * 100), model, "yes", 1)
            edge_pct = calculate_edge_pct(model, implied)
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
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.debug("Crypto consensus signals disabled - consensus module deleted")
    return KalshiConsensusSignalsResponse(
        signals=[],
        pending_votes=0,
        timestamp=int(datetime.now().timestamp()),
        source="disabled"
    )


@router.get("/rti")
async def get_crypto_rti_signals() -> Dict:
    """Get burn-in statistics for crypto 15m trading (trade count, win-rate, avg R, z-score).
    
    This endpoint aggregates per-asset trading statistics needed for tuning:
    - Trade count per asset
    - Win-rate in different range regimes
    - Average R per trade
    - Average z-score at entry
    
    Used to capture 30-50 trades per asset sample during 24-48h burn-in period.
    """
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        ledger = get_fills_ledger()
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        fills = ledger.get_fills(since=since, limit=10000)
        
        # Aggregate by asset
        asset_stats: Dict[str, Dict] = {}
        
        for fill in fills:
            # Extract asset from market_id (e.g., "KXBTC-15M-..." -> "BTC")
            market_id = getattr(fill, "market_id", "")
            asset = None
            if "KXBTC" in market_id:
                asset = "BTC"
            elif "KXETH" in market_id:
                asset = "ETH"
            elif "KXSOL" in market_id:
                asset = "SOL"
            elif "KXXRP" in market_id:
                asset = "XRP"
            elif "KXDOGE" in market_id:
                asset = "DOGE"
            
            if not asset:
                continue
            
            if asset not in asset_stats:
                asset_stats[asset] = {
                    "trade_count": 0,
                    "win_count": 0,
                    "total_r": 0.0,
                    "total_z_score": 0.0,
                    "entry_prices": [],
                    "regime_wins": {"tight": 0, "medium": 0, "wide": 0},
                    "regime_trades": {"tight": 0, "medium": 0, "wide": 0}
                }
            
            stats = asset_stats[asset]
            stats["trade_count"] += 1
            
            # Calculate R (risk/reward)
            pnl = float(getattr(fill, "realized_pnl_usd", 0.0))
            cost = float(getattr(fill, "cost_basis_usd", 1.0))
            r = pnl / cost if cost > 0 else 0.0
            stats["total_r"] += r
            
            if pnl > 0:
                stats["win_count"] += 1
            
            # Z-score at entry (if available)
            z_score = float(getattr(fill, "z_score_at_entry", 0.0))
            stats["total_z_score"] += z_score
            
            # Entry price for regime classification
            entry_price = float(getattr(fill, "avg_price_cents", 0.0))
            stats["entry_prices"].append(entry_price)
        
        # Calculate derived stats and filter by min_trades
        result: Dict[str, Dict] = {}
        for asset, stats in asset_stats.items():
            if stats["trade_count"] < min_trades:
                continue
            
            win_rate = stats["win_count"] / stats["trade_count"] if stats["trade_count"] > 0 else 0.0
            avg_r = stats["total_r"] / stats["trade_count"] if stats["trade_count"] > 0 else 0.0
            avg_z_score = stats["total_z_score"] / stats["trade_count"] if stats["trade_count"] > 0 else 0.0
            
            # Classify regime based on entry price spread
            if stats["entry_prices"]:
                price_std = (sum((x - sum(stats["entry_prices"]) / len(stats["entry_prices"])) ** 2 for x in stats["entry_prices"]) / len(stats["entry_prices"])) ** 0.5
                price_mean = sum(stats["entry_prices"]) / len(stats["entry_prices"])
                
                for price in stats["entry_prices"]:
                    deviation = abs(price - price_mean)
                    if deviation < price_std * 0.5:
                        stats["regime_trades"]["tight"] += 1
                        if price > 0:  # Simplified win tracking
                            stats["regime_wins"]["tight"] += 1
                    elif deviation < price_std:
                        stats["regime_trades"]["medium"] += 1
                        if price > 0:
                            stats["regime_wins"]["medium"] += 1
                    else:
                        stats["regime_trades"]["wide"] += 1
                        if price > 0:
                            stats["regime_wins"]["wide"] += 1
            
            # Calculate regime win-rates
            regime_win_rates = {}
            for regime in ["tight", "medium", "wide"]:
                regime_win_rates[regime] = (
                    stats["regime_wins"][regime] / stats["regime_trades"][regime]
                    if stats["regime_trades"][regime] > 0 else 0.0
                )
            
            result[asset] = {
                "trade_count": stats["trade_count"],
                "win_rate": win_rate,
                "avg_r_per_trade": avg_r,
                "avg_z_score_at_entry": avg_z_score,
                "regime_win_rates": regime_win_rates,
                "sample_hours": hours,
                "meets_burnin_threshold": stats["trade_count"] >= 30
            }
        
        return {
            "assets": result,
            "summary": {
                "total_assets": len(result),
                "assets_meeting_threshold": sum(1 for a in result.values() if a["meets_burnin_threshold"]),
                "min_trades_threshold": min_trades,
                "sample_period_hours": hours
            }
        }
    except Exception as exc:
        logger.error(f"Failed to get burn-in stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

