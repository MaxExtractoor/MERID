"""
15-Minute Band Strategy API Endpoints
======================================

REST API endpoints for Bollinger Band "top edge" strategy monitoring,
signals, and backtesting.

Endpoints:
- GET /api/v1/band-strategy/status - Aggregate status across all assets
- GET /api/v1/band-strategy/signal/{asset} - Latest signal for specific asset
- GET /api/v1/band-strategy/snapshot/{asset} - Band snapshot for specific asset
- POST /api/v1/band-strategy/update - Update agent with OHLC data
- GET /api/v1/band-strategy/config/{asset} - Get config for specific asset
- GET /api/v1/band-strategy/rolling-stats/{asset} - Rolling window statistics
- POST /api/v1/band-strategy/record-trade - Record completed trade result
- GET /api/v1/band-strategy/throttle-status - Check throttling status
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime

from merid.prediction.band_strategy_agent import get_band_agent
from merid.strategies.band_strategy_15m import get_band_strategy_config
from utils.logger import get_logger

logger = get_logger("web.api.band_strategy_api")

router = APIRouter(prefix="/api/v1/band-strategy", tags=["band-strategy"])


# ═══════════════════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

class OHLCUpdate(BaseModel):
    """OHLC data for updating the band agent."""
    asset: str = Field(..., description="Asset symbol (BTC, ETH, SOL, XRP, DOGE)")
    high: float = Field(..., gt=0, description="High price")
    low: float = Field(..., gt=0, description="Low price")
    close: float = Field(..., gt=0, description="Close price")


class BandSignalResponse(BaseModel):
    """Response containing a band strategy signal."""
    asset: str
    side: str  # "long", "short", "neutral"
    entry_price: float
    tp_price: float
    sl_price: float
    r_multiple: float
    signal_strength: float
    regime: str
    bb_position: float
    rsi: float
    adx: float
    reason: str
    timestamp: str


class BandSnapshotResponse(BaseModel):
    """Response containing band indicator snapshot."""
    asset: str
    bb_sma: float
    bb_upper: float
    bb_lower: float
    bb_width: float
    bb_position: float
    bb_sd_multiplier: float
    kc_ema: float
    kc_upper: float
    kc_lower: float
    kc_atr: float
    kc_squeeze: bool
    trend_ema: float
    price_above_trend_ema: bool
    adx: float
    adx_trend_strength: str
    regime: str
    rsi: float
    rsi_zone: str
    atr: float
    atr_spike: bool
    touched_upper: bool
    touched_lower: bool
    reentry_upper: bool
    reentry_lower: bool
    signal: str
    signal_strength: float
    signal_reason: str
    price: float
    bars_available: int


class BandStatusResponse(BaseModel):
    """Aggregate status across all tracked assets."""
    assets_tracked: int
    total_signals: int
    regime_distribution: Dict[str, int]
    active_signals: List[Dict[str, Any]]
    last_update: Optional[str]
    asset_states: Dict[str, Dict[str, Any]]


class BandConfigResponse(BaseModel):
    """Configuration for a specific asset."""
    asset: str
    bb_period: int
    bb_sd_multiplier: float
    kc_period: int
    kc_ema_period: int
    kc_atr_period: int
    kc_atr_multiplier: float
    trend_ema_period: int
    adx_period: int
    adx_trend_threshold: float
    rsi_period: int
    sl_atr_multiplier: float
    tp_at_mid_band: bool


class RecordTradeRequest(BaseModel):
    """Request to record a completed trade result."""
    asset: str = Field(..., description="Asset symbol")
    side: str = Field(..., description="Trade side (long or short)")
    entry_price: float = Field(..., gt=0, description="Entry price")
    exit_price: float = Field(..., gt=0, description="Exit price")
    regime: str = Field(..., description="Regime at entry (trend or range)")
    r_multiple: float = Field(..., ge=0, description="R:R ratio achieved")
    exit_reason: str = Field(default="timeout", description="Exit reason (tp, sl, timeout)")


class RollingStatsResponse(BaseModel):
    """Rolling window statistics for an asset."""
    window_size: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    total_pnl_pct: float
    avg_r_multiple: float
    range_trades: int
    range_wins: int
    range_win_rate: float
    trend_trades: int
    trend_wins: int
    trend_win_rate: float
    tp_exits: int
    sl_exits: int
    timeout_exits: int
    is_throttled: bool
    throttle_reason: str


class ThrottleStatusResponse(BaseModel):
    """Throttling status across all assets."""
    any_throttled: bool
    assets: Dict[str, Dict[str, Any]]
    thresholds: Dict[str, float]


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/status", response_model=BandStatusResponse)
async def get_band_status():
    """Get aggregate band strategy status across all assets."""
    try:
        agent = get_band_agent()
        summary = agent.get_aggregate_summary()
        
        return BandStatusResponse(
            assets_tracked=summary["assets_tracked"],
            total_signals=summary["total_signals"],
            regime_distribution=summary["regime_distribution"],
            active_signals=summary["active_signals"],
            last_update=summary["last_update"].isoformat() if summary["last_update"] else None,
            asset_states=agent.get_all_states(),
        )
    except Exception as e:
        logger.error(f"Error getting band status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signal/{asset}", response_model=Optional[BandSignalResponse])
async def get_band_signal(asset: str):
    """Get the latest signal for a specific asset."""
    try:
        agent = get_band_agent()
        signal = agent.get_signal(asset)
        
        if signal is None or signal.side == "neutral":
            return None
        
        return BandSignalResponse(
            asset=asset,
            side=signal.side,
            entry_price=signal.entry_price,
            tp_price=signal.tp_price,
            sl_price=signal.sl_price,
            r_multiple=signal.r_multiple,
            signal_strength=signal.signal_strength,
            regime=signal.regime,
            bb_position=signal.bb_position,
            rsi=signal.rsi,
            adx=signal.adx,
            reason=signal.reason,
            timestamp=signal.timestamp.isoformat(),
        )
    except Exception as e:
        logger.error(f"Error getting band signal for {asset}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshot/{asset}", response_model=Optional[BandSnapshotResponse])
async def get_band_snapshot(asset: str):
    """Get the latest band snapshot for a specific asset."""
    try:
        agent = get_band_agent()
        snapshot = agent.get_snapshot(asset)
        
        if snapshot is None:
            return None
        
        return BandSnapshotResponse(
            asset=asset,
            bb_sma=snapshot.bb_sma,
            bb_upper=snapshot.bb_upper,
            bb_lower=snapshot.bb_lower,
            bb_width=snapshot.bb_width,
            bb_position=snapshot.bb_position,
            bb_sd_multiplier=snapshot.bb_sd_multiplier,
            kc_ema=snapshot.kc_ema,
            kc_upper=snapshot.kc_upper,
            kc_lower=snapshot.kc_lower,
            kc_atr=snapshot.kc_atr,
            kc_squeeze=snapshot.kc_squeeze,
            trend_ema=snapshot.trend_ema,
            price_above_trend_ema=snapshot.price_above_trend_ema,
            adx=snapshot.adx,
            adx_trend_strength=snapshot.adx_trend_strength,
            regime=snapshot.regime,
            rsi=snapshot.rsi,
            rsi_zone=snapshot.rsi_zone,
            atr=snapshot.atr,
            atr_spike=snapshot.atr_spike,
            touched_upper=snapshot.touched_upper,
            touched_lower=snapshot.touched_lower,
            reentry_upper=snapshot.reentry_upper,
            reentry_lower=snapshot.reentry_lower,
            signal=snapshot.signal,
            signal_strength=snapshot.signal_strength,
            signal_reason=snapshot.signal_reason,
            price=snapshot.price,
            bars_available=snapshot.bars_available,
        )
    except Exception as e:
        logger.error(f"Error getting band snapshot for {asset}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update")
async def update_band_agent(update: OHLCUpdate):
    """Update the band agent with new OHLC data.
    
    Returns the signal if one was generated, otherwise null.
    """
    try:
        agent = get_band_agent()
        signal = agent.update_asset(update.asset, update.high, update.low, update.close)
        
        if signal is None or signal.side == "neutral":
            return {"signal": None, "message": "No signal generated"}
        
        return {
            "signal": BandSignalResponse(
                asset=update.asset,
                side=signal.side,
                entry_price=signal.entry_price,
                tp_price=signal.tp_price,
                sl_price=signal.sl_price,
                r_multiple=signal.r_multiple,
                signal_strength=signal.signal_strength,
                regime=signal.regime,
                bb_position=signal.bb_position,
                rsi=signal.rsi,
                adx=signal.adx,
                reason=signal.reason,
                timestamp=signal.timestamp.isoformat(),
            ),
            "message": f"Signal generated: {signal.side}",
        }
    except Exception as e:
        logger.error(f"Error updating band agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/{asset}", response_model=BandConfigResponse)
async def get_band_config(asset: str):
    """Get the band strategy configuration for a specific asset."""
    try:
        config = get_band_strategy_config(asset)
        
        return BandConfigResponse(
            asset=config.asset,
            bb_period=config.bb_period,
            bb_sd_multiplier=config.bb_sd_multiplier,
            kc_period=config.kc_period,
            kc_ema_period=config.kc_ema_period,
            kc_atr_period=config.kc_atr_period,
            kc_atr_multiplier=config.kc_atr_multiplier,
            trend_ema_period=config.trend_ema_period,
            adx_period=config.adx_period,
            adx_trend_threshold=config.adx_trend_threshold,
            rsi_period=config.rsi_period,
            sl_atr_multiplier=config.sl_atr_multiplier,
            tp_at_mid_band=config.tp_at_mid_band,
        )
    except Exception as e:
        logger.error(f"Error getting band config for {asset}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rolling-stats/{asset}", response_model=Optional[RollingStatsResponse])
async def get_rolling_stats(asset: str):
    """Get rolling window statistics for a specific asset."""
    try:
        agent = get_band_agent()
        stats = agent.get_rolling_stats(asset)
        
        if stats is None:
            return None
        
        return RollingStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Error getting rolling stats for {asset}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/record-trade")
async def record_trade_result(request: RecordTradeRequest):
    """Record a completed trade result for rolling window tracking."""
    try:
        agent = get_band_agent()
        
        agent.record_trade_result(
            asset=request.asset,
            side=request.side,
            entry_price=request.entry_price,
            exit_price=request.exit_price,
            regime=request.regime,
            r_multiple=request.r_multiple,
            exit_reason=request.exit_reason,
        )
        
        return {
            "message": f"Trade result recorded for {request.asset}",
            "asset": request.asset,
            "pnl_pct": round((request.exit_price - request.entry_price) / request.entry_price * (1 if request.side == "long" else -1), 4),
        }
    except Exception as e:
        logger.error(f"Error recording trade result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/throttle-status", response_model=ThrottleStatusResponse)
async def get_throttle_status(
    min_win_rate: float = 0.65,
    min_range_win_rate: float = 0.70,
    min_trades: int = 20,
):
    """Check throttling status across all assets.
    
    Args:
        min_win_rate: Minimum overall win rate threshold.
        min_range_win_rate: Minimum range-only win rate threshold.
        min_trades: Minimum trades required before checking.
    """
    try:
        agent = get_band_agent()
        status = agent.check_throttling(min_win_rate, min_range_win_rate, min_trades)
        
        return ThrottleStatusResponse(
            any_throttled=status["any_throttled"],
            assets=status["assets"],
            thresholds=status["thresholds"],
        )
    except Exception as e:
        logger.error(f"Error checking throttle status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
