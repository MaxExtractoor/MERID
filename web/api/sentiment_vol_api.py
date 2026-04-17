"""
Fear/Greed, Volatility & Sizing API

Canonical API for the Fear/Greed, Volatility & Sizing lane.
Integrates with SentimentVolService to provide unified sentiment, volatility,
and sizing multiplier data for UI display and downstream consumers.

This is the canonical single source of truth for all fear/greed, volatility,
and position sizing multiplier data in the system.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/risk/sentiment-vol", tags=["sentiment-vol"])


# ── Core State Endpoints ─────────────────────────────────────────────────

@router.get("/assets")
async def get_all_assets_state() -> Dict[str, Any]:
    """
    Get complete sentiment, volatility, and sizing state for all tracked assets.
    
    This is the primary endpoint for the Fear/Greed Vol & Sizing dashboard view.
    """
    try:
        from merid.prediction.risk import get_sentiment_vol_service
        
        service = get_sentiment_vol_service()
        states = service.get_all_states()
        health = service.get_health()
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service_health": health,
            "assets": states,
            "asset_count": len(states),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "assets": {},
            "asset_count": 0,
        }


@router.get("/asset/{asset}")
async def get_asset_state(asset: str) -> Dict[str, Any]:
    """
    Get complete sentiment, volatility, and sizing state for a specific asset.
    
    Returns:
        - sentiment: Fear/greed index (0-100), regime, confidence
        - volatility: Annualized volatility, regime, uncertainty
        - sizing_multiplier: Final multiplier with reasoning
        - effective_size_factor: What to multiply base size by
        - regime_label: Human-readable regime (NORMAL, CAUTION, HALTED)
        - is_stale: Whether data is stale
    """
    try:
        from merid.prediction.risk import get_sentiment_vol_service
        
        service = get_sentiment_vol_service()
        asset = asset.upper()
        
        # Register asset if not tracked
        if asset not in service.get_tracked_assets():
            service.register_asset(asset)
        
        state = service.get_composite_state(asset)
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **state,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Individual Component Endpoints ─────────────────────────────────────────

@router.get("/asset/{asset}/sentiment")
async def get_asset_sentiment(asset: str) -> Dict[str, Any]:
    """Get canonical sentiment (fear/greed) for an asset."""
    try:
        from merid.prediction.risk import get_current_sentiment
        
        sentiment = get_current_sentiment(asset.upper())
        
        if sentiment is None:
            return {
                "status": "unavailable",
                "asset": asset.upper(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "No sentiment data available",
            }
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset.upper(),
            "sentiment": sentiment.to_dict(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/asset/{asset}/volatility")
async def get_asset_volatility(asset: str) -> Dict[str, Any]:
    """Get canonical volatility for an asset."""
    try:
        from merid.prediction.risk import get_current_volatility
        
        volatility = get_current_volatility(asset.upper())
        
        if volatility is None:
            return {
                "status": "unavailable",
                "asset": asset.upper(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "No volatility data available",
            }
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset.upper(),
            "volatility": volatility.to_dict(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/asset/{asset}/sizing-multiplier")
async def get_asset_sizing_multiplier(
    asset: str,
    is_contrarian: bool = False,
) -> Dict[str, Any]:
    """
    Get sizing multiplier for an asset.
    
    Args:
        is_contrarian: True if trading against crowd sentiment
                      (applies boost in extreme regimes)
    """
    try:
        from merid.prediction.risk import get_current_sizing_multiplier
        
        multiplier = get_current_sizing_multiplier(asset.upper(), is_contrarian)
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset.upper(),
            "is_contrarian": is_contrarian,
            "sizing_multiplier": multiplier.to_dict(),
            "effective_size_factor": multiplier.value,
            "regime_label": multiplier.get_regime_label(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Sizing Decision Support ──────────────────────────────────────────────

@router.get("/asset/{asset}/sizing-decision")
async def get_sizing_decision(
    asset: str,
    base_size: float = 1.0,
    is_contrarian: bool = False,
) -> Dict[str, Any]:
    """
    Get complete sizing decision data for a position.
    
    Args:
        base_size: Base position size (e.g., contracts or dollars)
        is_contrarian: True if trading against crowd sentiment
    
    Returns:
        Full sizing calculation with all components explained.
    """
    try:
        from merid.prediction.risk import explain_sizing_for_position
        
        explanation = explain_sizing_for_position(
            asset=asset.upper(),
            base_size=base_size,
            is_contrarian=is_contrarian,
        )
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **explanation,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Health & Configuration ───────────────────────────────────────────────

@router.get("/health")
async def get_service_health() -> Dict[str, Any]:
    """Get SentimentVolService health status."""
    try:
        from merid.prediction.risk import get_sentiment_vol_service
        
        service = get_sentiment_vol_service()
        health = service.get_health()
        
        return {
            "status": "success" if health["error_rate"] < 0.1 else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "health": health,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/config")
async def get_service_config() -> Dict[str, Any]:
    """Get current configuration (thresholds, multipliers)."""
    try:
        from merid.prediction.risk import get_sentiment_vol_config
        
        config = get_sentiment_vol_config()
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "sentiment_thresholds": {
                    "extreme_fear_max": config.extreme_fear_max,
                    "fear_max": config.fear_max,
                    "greed_min": config.greed_min,
                    "extreme_greed_min": config.extreme_greed_min,
                },
                "volatility_thresholds": {
                    "vol_dead_max": config.vol_dead_max,
                    "vol_low_max": config.vol_low_max,
                    "vol_target": config.vol_target,
                    "vol_high_min": config.vol_high_min,
                    "vol_extreme_min": config.vol_extreme_min,
                },
                "sizing_multipliers": {
                    "extreme_sentiment_mult": config.extreme_sentiment_mult,
                    "fear_greed_mult": config.fear_greed_mult,
                    "neutral_sentiment_mult": config.neutral_sentiment_mult,
                    "dead_vol_mult": config.dead_vol_mult,
                    "low_vol_mult": config.low_vol_mult,
                    "high_vol_mult": config.high_vol_mult,
                    "extreme_vol_mult": config.extreme_vol_mult,
                },
                "limits": {
                    "sizing_floor": config.sizing_floor,
                    "sizing_ceiling": config.sizing_ceiling,
                    "uncertainty_elevated_penalty": config.uncertainty_elevated_penalty,
                    "uncertainty_unstable_penalty": config.uncertainty_unstable_penalty,
                    "contrarian_boost": config.contrarian_boost,
                },
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Data Feeds (Manual Updates) ──────────────────────────────────────────

@router.post("/asset/{asset}/sentiment")
async def update_asset_sentiment(
    asset: str,
    value: float,
    confidence: float = 1.0,
    source: str = "manual",
) -> Dict[str, Any]:
    """
    Manually update sentiment for an asset.
    
    This is primarily for testing/debugging. In production,
    sentiment is updated automatically from CFGI API.
    """
    try:
        from merid.prediction.risk import feed_sentiment_update
        
        feed_sentiment_update(
            asset=asset.upper(),
            value=value,
            confidence=confidence,
            source=source,
        )
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset.upper(),
            "message": f"Sentiment updated to {value}",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/asset/{asset}/price")
async def feed_price(
    asset: str,
    price: float,
) -> Dict[str, Any]:
    """
    Feed a price update for volatility calculation.
    
    This is primarily for testing/debugging. In production,
    prices are fed from market data streams.
    """
    try:
        from merid.prediction.risk import feed_price_update
        
        feed_price_update(asset.upper(), price)
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": asset.upper(),
            "price": price,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Bulk Operations ──────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary() -> Dict[str, Any]:
    """
    Get executive summary of current market conditions.
    
    Aggregated view suitable for a dashboard card or alert system.
    """
    try:
        from merid.prediction.risk import (
            get_sentiment_vol_service,
            get_sentiment_vol_config,
        )
        
        service = get_sentiment_vol_service()
        config = get_sentiment_vol_config()
        states = service.get_all_states()
        health = service.get_health()
        
        # Aggregate statistics
        total_assets = len(states)
        extreme_fear = 0
        fear = 0
        neutral = 0
        greed = 0
        extreme_greed = 0
        
        extreme_vol = 0
        high_vol = 0
        normal_vol = 0
        low_vol = 0
        
        for asset, state in states.items():
            if state.get("sentiment"):
                regime = state["sentiment"].get("regime", "NEUTRAL")
                if regime == "EXTREME_FEAR":
                    extreme_fear += 1
                elif regime == "FEAR":
                    fear += 1
                elif regime == "GREED":
                    greed += 1
                elif regime == "EXTREME_GREED":
                    extreme_greed += 1
                else:
                    neutral += 1
            
            if state.get("volatility"):
                vol_regime = state["volatility"].get("regime", "TARGET")
                if vol_regime == "EXTREME":
                    extreme_vol += 1
                elif vol_regime == "HIGH":
                    high_vol += 1
                elif vol_regime in ["DEAD", "LOW"]:
                    low_vol += 1
                else:
                    normal_vol += 1
        
        # Overall system assessment
        critical_count = extreme_fear + extreme_greed + extreme_vol
        if critical_count > total_assets * 0.3:
            system_assessment = "CRITICAL"
        elif critical_count > 0:
            system_assessment = "CAUTION"
        else:
            system_assessment = "NORMAL"
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_assessment": system_assessment,
            "service_health": health,
            "summary": {
                "total_assets_tracked": total_assets,
                "sentiment_distribution": {
                    "extreme_fear": extreme_fear,
                    "fear": fear,
                    "neutral": neutral,
                    "greed": greed,
                    "extreme_greed": extreme_greed,
                },
                "volatility_distribution": {
                    "extreme": extreme_vol,
                    "high": high_vol,
                    "normal": normal_vol,
                    "low_dead": low_vol,
                },
            },
            "thresholds": {
                "extreme_fear": config.extreme_fear_max,
                "fear": config.fear_max,
                "greed": config.greed_min,
                "extreme_greed": config.extreme_greed_min,
                "high_vol": config.vol_high_min,
                "extreme_vol": config.vol_extreme_min,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Alerts & Monitoring ──────────────────────────────────────────────────

@router.get("/alerts")
async def get_current_alerts() -> Dict[str, Any]:
    """
    Get current alerts for extreme conditions.
    
    Returns alerts for assets in extreme fear/greed or extreme volatility.
    """
    try:
        from merid.prediction.risk import (
            get_sentiment_vol_service,
            FearGreedRegime,
            VolatilityRegime,
        )
        
        service = get_sentiment_vol_service()
        states = service.get_all_states()
        
        alerts = []
        
        for asset, state in states.items():
            sentiment = state.get("sentiment", {})
            volatility = state.get("volatility", {})
            multiplier = state.get("sizing_multiplier", {})
            
            # Check for extreme sentiment
            if sentiment:
                regime = sentiment.get("regime", "NEUTRAL")
                if regime in ["EXTREME_FEAR", "EXTREME_GREED"]:
                    alerts.append({
                        "asset": asset,
                        "type": "EXTREME_SENTIMENT",
                        "severity": "HIGH",
                        "message": f"{asset} in {regime} regime (FGI={sentiment.get('value')})",
                        "value": sentiment.get("value"),
                        "multiplier_impact": multiplier.get("value"),
                    })
            
            # Check for extreme volatility
            if volatility:
                vol_regime = volatility.get("regime", "TARGET")
                if vol_regime == "EXTREME":
                    alerts.append({
                        "asset": asset,
                        "type": "EXTREME_VOLATILITY",
                        "severity": "HIGH",
                        "message": f"{asset} volatility at {volatility.get('value', 0):.1%}",
                        "value": volatility.get("value"),
                        "multiplier_impact": multiplier.get("value"),
                    })
                elif vol_regime == "HIGH":
                    alerts.append({
                        "asset": asset,
                        "type": "HIGH_VOLATILITY",
                        "severity": "MEDIUM",
                        "message": f"{asset} volatility elevated at {volatility.get('value', 0):.1%}",
                        "value": volatility.get("value"),
                        "multiplier_impact": multiplier.get("value"),
                    })
            
            # Check for stale data
            if state.get("is_stale"):
                alerts.append({
                    "asset": asset,
                    "type": "STALE_DATA",
                    "severity": "LOW",
                    "message": f"{asset} data is stale: {state.get('stale_reason')}",
                })
        
        # Sort by severity
        severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        alerts.sort(key=lambda x: severity_order.get(x["severity"], 3))
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_count": len(alerts),
            "alerts": alerts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_count": 0,
            "alerts": [],
        }
