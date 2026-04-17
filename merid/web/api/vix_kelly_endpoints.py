"""
Production FastAPI Endpoints for VIX-Kelly Sizing

Production API endpoints for real-time VIX-Kelly sizing signals.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from .vix_kelly_state import get_current_vix_kelly_state, get_vix_kelly_state_dict, are_vix_kelly_metrics_available, get_vix_kelly_manager

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/sizing/vix-kelly")
def get_vix_kelly_sizing() -> Dict[str, Any]:
    """
    Production endpoint: current Kelly-VIX fraction for sizing.
    
    Returns:
        Current VIX-Kelly sizing state
    """
    if not are_vix_kelly_metrics_available():
        raise HTTPException(status_code=503, detail="VIX-Kelly sizing not ready")
    
    state_dict = get_vix_kelly_state_dict()
    if state_dict is None:
        raise HTTPException(status_code=500, detail="Error retrieving VIX-Kelly sizing")
    
    return state_dict

@router.get("/sizing/vix-kelly/status")
def get_vix_kelly_status() -> Dict[str, Any]:
    """
    Get VIX-Kelly sizing system status.
    
    Returns:
        Status information
    """
    manager = get_vix_kelly_manager()
    summary = manager.get_summary()
    
    # Add health status
    if summary["available"]:
        state = manager.get_state()
        if state:
            # Determine health based on volatility regime and fraction
            regime = manager._get_volatility_regime()
            hybrid_fraction = state.hybrid_fraction
            
            if regime == "extreme" and hybrid_fraction > 0.1:
                health = "warning"  # High volatility but still aggressive
            elif regime == "high" and hybrid_fraction > 0.15:
                health = "warning"  # High volatility, moderate aggression
            elif hybrid_fraction < 0.01:
                health = "warning"  # Very conservative sizing
            elif hybrid_fraction > 0.3:
                health = "warning"  # Very aggressive sizing
            else:
                health = "healthy"
            
            summary["health"] = health
            summary["volatility_regime"] = regime
            summary["current_fraction"] = hybrid_fraction
            summary["base_kelly"] = state.base_kelly
    else:
        summary["health"] = "unavailable"
    
    return summary

@router.get("/sizing/vix-kelly/trend")
def get_vix_kelly_trend(window_minutes: int = 60) -> Dict[str, Any]:
    """
    Get VIX-Kelly sizing trend over recent window.
    
    Args:
        window_minutes: Time window in minutes for trend analysis
        
    Returns:
        Trend analysis
    """
    if not are_vix_kelly_metrics_available():
        raise HTTPException(status_code=503, detail="VIX-Kelly sizing not ready")
    
    manager = get_vix_kelly_manager()
    trend = manager.get_state_trend(window_minutes)
    
    if "error" in trend:
        raise HTTPException(status_code=404, detail=trend["error"])
    
    return trend

@router.get("/sizing/vix-kelly/history")
def get_vix_kelly_history(limit: int = 10) -> Dict[str, Any]:
    """
    Get recent VIX-Kelly sizing history.
    
    Args:
        limit: Number of recent updates to return
        
    Returns:
        Recent history
    """
    if not are_vix_kelly_metrics_available():
        raise HTTPException(status_code=503, detail="VIX-Kelly sizing not ready")
    
    manager = get_vix_kelly_manager()
    history = manager.get_recent_history(limit)
    
    return {
        "limit": limit,
        "count": len(history),
        "updates": history
    }

@router.post("/sizing/vix-kelly/refresh")
def refresh_vix_kelly_sizing(base_kelly: float = 0.15,
                             vix_lookback: int = 252,
                             low_vol_boost: float = 1.2,
                             high_vol_cut: float = 0.5,
                             max_fraction: float = None) -> Dict[str, Any]:
    """
    Manually refresh VIX-Kelly sizing with latest data.
    
    Args:
        base_kelly: Base Kelly fraction
        vix_lookback: Lookback period for VIX rank
        low_vol_boost: Low volatility boost factor
        high_vol_cut: High volatility cut factor
        max_fraction: Maximum allowed fraction
        
    Returns:
        Refresh result
    """
    try:
        from .vix_kelly_state import refresh_vix_kelly
        
        success = refresh_vix_kelly(
            base_kelly=base_kelly,
            vix_lookback=vix_lookback,
            low_vol_boost=low_vol_boost,
            high_vol_cut=high_vol_cut,
            max_fraction=max_fraction
        )
        
        if success:
            state = get_current_vix_kelly_state()
            return {
                "success": True,
                "message": "VIX-Kelly sizing refreshed successfully",
                "state": state.to_dict() if state else None
            }
        else:
            return {
                "success": False,
                "message": "Failed to refresh VIX-Kelly sizing"
            }
            
    except Exception as e:
        logger.error(f"Error in manual VIX-Kelly refresh: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sizing/vix-kelly/recommendations")
def get_vix_kelly_recommendations() -> Dict[str, Any]:
    """
    Get VIX-Kelly sizing recommendations based on current state.
    
    Returns:
        Recommendations for position sizing
    """
    if not are_vix_kelly_metrics_available():
        raise HTTPException(status_code=503, detail="VIX-Kelly sizing not ready")
    
    state = get_current_vix_kelly_state()
    if not state:
        raise HTTPException(status_code=500, detail="No VIX-Kelly state available")
    
    recommendations = []
    
    # Volatility regime recommendations
    regime = get_vix_kelly_manager()._get_volatility_regime()
    
    if regime == "extreme":
        recommendations.append({
            "type": "risk_management",
            "message": "Extreme volatility detected - consider reducing position size",
            "suggested_fraction": state.hybrid_fraction * 0.5,
            "priority": "high"
        })
    elif regime == "high":
        recommendations.append({
            "type": "risk_management",
            "message": "High volatility regime - monitor positions closely",
            "suggested_fraction": state.hybrid_fraction * 0.8,
            "priority": "medium"
        })
    elif regime == "low":
        recommendations.append({
            "type": "opportunity",
            "message": "Low volatility regime - consider increasing position size",
            "suggested_fraction": min(state.hybrid_fraction * 1.2, state.base_kelly),
            "priority": "low"
        })
    
    # Fraction size recommendations
    if state.hybrid_fraction > 0.3:
        recommendations.append({
            "type": "risk_management",
            "message": "Aggressive sizing detected - consider reducing exposure",
            "suggested_fraction": 0.25,
            "priority": "high"
        })
    elif state.hybrid_fraction < 0.05:
        recommendations.append({
            "type": "opportunity",
            "message": "Very conservative sizing - consider increasing exposure",
            "suggested_fraction": 0.15,
            "priority": "medium"
        })
    
    # VIX rank change recommendations
    manager = get_vix_kelly_manager()
    trend = manager.get_state_trend(window_minutes=120)  # 2-hour window
    
    if "rank_trend" in trend:
        rank_change = trend["rank_trend"]["change"]
        if rank_change > 0.3:
            recommendations.append({
                "type": "market_regime",
                "message": "VIX rank increasing significantly - volatility rising",
                "suggested_fraction": state.hybrid_fraction * 0.9,
                "priority": "medium"
            })
        elif rank_change < -0.3:
            recommendations.append({
                "type": "market_regime",
                "message": "VIX rank decreasing significantly - volatility falling",
                "suggested_fraction": min(state.hybrid_fraction * 1.1, state.base_kelly),
                "priority": "low"
            })
    
    return {
        "current_state": state.to_dict(),
        "volatility_regime": regime,
        "recommendations": recommendations,
        "generated_at": state.timestamp
    }

# Example Streamlit client code:
"""
import requests
import streamlit as st
import os

API_BASE = os.getenv("KALSHI_API_BASE", "http://localhost:8011")

def display_vix_kelly_sizing():
    st.sidebar.subheader("VIX-Kelly Sizing")
    
    try:
        # Fetch current VIX-Kelly sizing
        r = requests.get(f"{API_BASE}/sizing/vix-kelly", timeout=3)
        
        if r.status_code == 200:
            data = r.json()
            
            st.sidebar.write("**Current Sizing:**")
            st.sidebar.write(f"Base Kelly: {data['base_kelly']:.2%}")
            st.sidebar.write(f"Hybrid Fraction: {data['hybrid_fraction']:.2%}")
            st.sidebar.write(f"VIX Value: {data['vix_value']:.2f}")
            st.sidebar.write(f"VIX Rank: {data['vix_rank']:.3f}")
            
            # Volatility regime indicator
            r_status = requests.get(f"{API_BASE}/sizing/vix-kelly/status", timeout=3)
            if r_status.status_code == 200:
                status = r_status.json()
                
                if status['health'] == 'healthy':
                    st.sidebar.success("🟢 System Healthy")
                elif status['health'] == 'warning':
                    st.sidebar.warning("🟡 System Warning")
                else:
                    st.sidebar.error("🔴 System Issue")
                
                st.sidebar.write(f"Regime: {status.get('volatility_regime', 'Unknown')}")
            
            # Recommendations
            r_rec = requests.get(f"{API_BASE}/sizing/vix-kelly/recommendations", timeout=3)
            if r_rec.status_code == 200:
                rec_data = r_rec.json()
                
                if rec_data['recommendations']:
                    st.sidebar.write("**Recommendations:**")
                    for rec in rec_data['recommendations']:
                        if rec['priority'] == 'high':
                            st.sidebar.error(f"⚠️ {rec['message']}")
                        elif rec['priority'] == 'medium':
                            st.sidebar.warning(f"📊 {rec['message']}")
                        else:
                            st.sidebar.info(f"💡 {rec['message']}")
            
        else:
            st.sidebar.warning("VIX-Kelly sizing not available")
            st.sidebar.error(f"Error: {r.status_code}")
            
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"VIX-Kelly sizing error: {e}")
    except Exception as e:
        st.sidebar.error(f"Unexpected error: {e}")

def display_vix_kelly_trend():
    \"\"\"Display VIX-Kelly sizing trend.\"\"\"
    try:
        r = requests.get(f"{API_BASE}/sizing/vix-kelly/trend?window_minutes=60", timeout=3)
        
        if r.status_code == 200:
            trend = r.json()
            
            st.subheader("VIX-Kelly Trend (Last Hour)")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Hybrid Fraction Start", f"{trend['hybrid_fraction_trend']['start']:.3f}")
                st.metric("Hybrid Fraction End", f"{trend['hybrid_fraction_trend']['end']:.3f}")
                st.write(f"Direction: {trend['hybrid_fraction_trend']['direction'].title()}")
            
            with col2:
                st.metric("VIX Start", f"{trend['vix_trend']['start']:.2f}")
                st.metric("VIX End", f"{trend['vix_trend']['end']:.2f}")
                st.write(f"Direction: {trend['vix_trend']['direction'].title()}")
            
            with col3:
                st.metric("Rank Start", f"{trend['rank_trend']['start']:.3f}")
                st.metric("Rank End", f"{trend['rank_trend']['end']:.3f}")
                st.write(f"Direction: {trend['rank_trend']['direction'].title()}")
                
    except Exception as e:
        st.error(f"Trend data not available: {e}")

# In Streamlit app:
# display_vix_kelly_sizing()
# display_vix_kelly_trend()
"""
