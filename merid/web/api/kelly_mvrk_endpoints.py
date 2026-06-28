"""
Dashboard API Endpoints for Kelly MVRK Metrics

FastAPI endpoints for multivariate Kelly/MVRK metrics integration.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from .kelly_mvrk_metrics import get_current_kelly_mvrk_metrics, get_kelly_mvrk_metrics_dict, are_kelly_mvrk_metrics_available

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/kelly/mvrk")
def get_kelly_mvrk() -> Dict[str, Any]:
    """
    Get current Kelly/MVRK metrics.
    
    Returns:
        Kelly/MVRK metrics dictionary
    """
    if not are_kelly_mvrk_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly/MVRK metrics not available")
    
    metrics_dict = get_kelly_mvrk_metrics_dict()
    if metrics_dict is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly/MVRK metrics")
    
    return metrics_dict

@router.get("/kelly/mvrk/summary")
def get_kelly_mvrk_summary() -> Dict[str, Any]:
    """
    Get Kelly/MVRK metrics summary.
    
    Returns:
        Summary of Kelly/MVRK metrics availability
    """
    from .kelly_mvrk_metrics import _kelly_mvrk_store
    
    summary = _kelly_mvrk_store.get_summary()
    
    # Add current metrics if available
    if are_kelly_mvrk_metrics_available():
        metrics = get_current_kelly_mvrk_metrics()
        if metrics:
            summary["current_metrics"] = {
                "assets": metrics.assets,
                "theta_used": metrics.theta_used,
                "sharpe_kelly": metrics.sharpe_kelly,
                "sharke_mvrk": metrics.sharpe_mvrk,
                "mvrk_better": metrics.sharpe_mvrk > metrics.sharpe_kelly,
                "ruin_improvement": metrics.ruin_kelly - metrics.ruin_mvrk
            }
    
    return summary

@router.get("/kelly/mvrk/weights")
def get_kelly_mvrk_weights() -> Dict[str, Any]:
    """
    Get current Kelly and MVRK weights.
    
    Returns:
        Kelly and MVRK weights dictionary
    """
    if not are_kelly_mvrk_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly/MVRK weights not available")
    
    metrics = get_current_kelly_mvrk_metrics()
    if metrics is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly/MVRK weights")
    
    return {
        "assets": metrics.assets,
        "kelly_weights": metrics.kelly_weights,
        "mvrk_weights": metrics.mvrk_weights,
        "theta_used": metrics.theta_used,
        "timestamp": metrics.timestamp
    }

@router.get("/kelly/mvrk/performance")
def get_kelly_mvrk_performance() -> Dict[str, Any]:
    """
    Get Kelly/MVRK performance metrics.
    
    Returns:
        Performance metrics dictionary
    """
    if not are_kelly_mvrk_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly/MVRK performance metrics not available")
    
    metrics = get_current_kelly_mvrk_metrics()
    if metrics is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly/MVRK performance metrics")
    
    return {
        "sharpe_kelly": metrics.sharpe_kelly,
        "sharpe_mvrk": metrics.sharpe_mvrk,
        "sharpe_improvement": metrics.sharpe_mvrk - metrics.sharpe_kelly,
        "max_dd_kelly": metrics.max_dd_kelly,
        "max_dd_mvrk": metrics.max_dd_mvrk,
        "dd_improvement": metrics.max_dd_mvrk - metrics.max_dd_kelly,
        "ruin_kelly": metrics.ruin_kelly,
        "ruin_mvrk": metrics.ruin_mvrk,
        "ruin_improvement": metrics.ruin_kelly - metrics.ruin_mvrk,
        "timestamp": metrics.timestamp
    }

@router.get("/kelly/mvrk/status")
def get_kelly_mvrk_status() -> Dict[str, Any]:
    """
    Get Kelly/MVRK system status.
    
    Returns:
        Status dictionary
    """
    from .kelly_mvrk_metrics import _kelly_mvrk_store
    
    available = are_kelly_mvrk_metrics_available()
    summary = _kelly_mvrk_store.get_summary()
    
    status = {
        "available": available,
        "last_updated": summary.get("last_updated", 0),
        "age_seconds": summary.get("age_seconds", 0),
        "is_stale": summary.get("is_stale", True),
        "update_count": summary.get("update_count", 0)
    }
    
    # Add health status
    if available:
        metrics = get_current_kelly_mvrk_metrics()
        if metrics:
            if metrics.sharpe_mvrk > metrics.sharpe_kelly and metrics.ruin_mvrk < metrics.ruin_kelly:
                status["health"] = "excellent"
            elif metrics.sharpe_mvrk > metrics.sharpe_kelly:
                status["health"] = "good"
            elif metrics.sharpe_mvrk > 0.5:
                status["health"] = "fair"
            else:
                status["health"] = "poor"
            
            status["assets"] = len(metrics.assets)
            status["theta_used"] = metrics.theta_used
            status["mvrk_dominant"] = metrics.sharpe_mvrk > metrics.sharpe_kelly
    else:
        status["health"] = "unavailable"
    
    return status

# Example Streamlit client code:
"""
import requests
import streamlit as st
import os

API_BASE = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))

def display_kelly_mvrk_metrics():
    st.sidebar.subheader("Multivariate Kelly / MVRK")
    
    try:
        # Fetch Kelly/MVRK metrics
        r = requests.get(f"{API_BASE}/kelly/mvrk", timeout=3)
        
        if r.status_code == 200:
            data = r.json()
            assets = data["assets"]
            kw = data["kelly_weights"]
            mw = data["mvrk_weights"]
            
            st.sidebar.write("**Kelly weights:**")
            for a, w in zip(assets, kw):
                st.sidebar.write(f"- {a}: {w:.2%}")
            
            st.sidebar.write("**MVRK weights:**")
            for a, w in zip(assets, mw):
                st.sidebar.write(f"- {a}: {w:.2%}")
            
            st.sidebar.write(f"Risk of ruin Kelly: {data['ruin_kelly']:.2%}")
            st.sidebar.write(f"Risk of ruin MVRK: {data['ruin_mvrk']:.2%}")
            
            # Performance comparison
            if data['sharpe_mvrk'] > data['sharpe_kelly']:
                st.sidebar.success(f"✅ MVRK outperforms Kelly")
                st.sidebar.write(f"Sharpe improvement: {data['sharpe_mvrk'] - data['sharpe_kelly']:.2f}")
            else:
                st.sidebar.warning(f"⚠️ Kelly outperforms MVRK")
                st.sidebar.write(f"Sharpe difference: {data['sharpe_kelly'] - data['sharpe_mvrk']:.2f}")
            
        else:
            st.sidebar.warning("MVRK metrics not available")
            st.sidebar.error(f"Error: {r.status_code}")
            
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"MVRK metrics error: {e}")
    except Exception as e:
        st.sidebar.error(f"Unexpected error: {e}")

def display_kelly_mvrk_status():
    \"\"\"Display Kelly/MVRK system status.\"\"\"
    try:
        r = requests.get(f"{API_BASE}/kelly/mvrk/status", timeout=3)
        
        if r.status_code == 200:
            status = r.json()
            
            if status["available"]:
                if status["health"] == "excellent":
                    st.success("🟢 Kelly/MVRK System Excellent")
                elif status["health"] == "good":
                    st.success("🟢 Kelly/MVRK System Good")
                elif status["health"] == "fair":
                    st.warning("🟡 Kelly/MVRK System Fair")
                else:
                    st.error("🔴 Kelly/MVRK System Poor")
                
                st.write(f"Assets: {status.get('assets', 0)}")
                st.write(f"Theta Used: {status.get('theta_used', 0):.2f}")
                st.write(f"MVRK Dominant: {'Yes' if status.get('mvrk_dominant', False) else 'No'}")
                st.write(f"Last Updated: {status['age_seconds']/3600:.1f} hours ago")
            else:
                st.error("🔴 Kelly/MVRK Metrics Unavailable")
                
    except Exception as e:
        st.error(f"Status check failed: {e}")

# In Streamlit app:
# display_kelly_mvrk_metrics()
# display_kelly_mvrk_status()
"""
