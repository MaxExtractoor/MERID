"""
Dashboard API Endpoints for Kelly Metrics

FastAPI endpoints for Kelly metrics integration with SSE.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from .kelly_metrics import get_current_kelly_metrics, get_kelly_metrics_dict, are_kelly_metrics_available

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/kelly/metrics")
def get_kelly_metrics() -> Dict[str, Any]:
    """
    Get current Kelly metrics.
    
    Returns:
        Kelly metrics dictionary
    """
    if not are_kelly_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly metrics not available")
    
    metrics_dict = get_kelly_metrics_dict()
    if metrics_dict is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly metrics")
    
    return metrics_dict

@router.get("/kelly/metrics/summary")
def get_kelly_metrics_summary() -> Dict[str, Any]:
    """
    Get Kelly metrics summary.
    
    Returns:
        Summary of Kelly metrics availability
    """
    from .kelly_metrics import _kelly_store
    
    summary = _kelly_store.get_summary()
    
    # Add current metrics if available
    if are_kelly_metrics_available():
        metrics = get_current_kelly_metrics()
        if metrics:
            summary["current_metrics"] = {
                "fraction_full": metrics.fraction_full,
                "fraction_half": metrics.fraction_half,
                "sharpe": metrics.sharpe,
                "max_drawdown": metrics.max_drawdown,
                "total_return": metrics.total_return
            }
    
    return summary

@router.get("/kelly/fractions")
def get_kelly_fractions() -> Dict[str, Any]:
    """
    Get current Kelly fractions.
    
    Returns:
        Kelly fractions dictionary
    """
    if not are_kelly_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly metrics not available")
    
    metrics = get_current_kelly_metrics()
    if metrics is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly metrics")
    
    return {
        "fraction_full": metrics.fraction_full,
        "fraction_half": metrics.fraction_half,
        "fraction_quarter": metrics.fraction_quarter,
        "vol_targeted_fraction": metrics.vol_targeted_fraction,
        "recommended_fraction": metrics.fraction_half,  # Default recommendation
        "timestamp": metrics.timestamp
    }

@router.get("/kelly/performance")
def get_kelly_performance() -> Dict[str, Any]:
    """
    Get Kelly performance metrics.
    
    Returns:
        Performance metrics dictionary
    """
    if not are_kelly_metrics_available():
        raise HTTPException(status_code=404, detail="Kelly metrics not available")
    
    metrics = get_current_kelly_metrics()
    if metrics is None:
        raise HTTPException(status_code=500, detail="Error retrieving Kelly metrics")
    
    return {
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "total_return": metrics.total_return,
        "win_rate": metrics.win_rate,
        "win_loss_ratio": metrics.win_loss_ratio,
        "total_trades": metrics.total_trades,
        "timestamp": metrics.timestamp
    }

@router.get("/kelly/status")
def get_kelly_status() -> Dict[str, Any]:
    """
    Get Kelly system status.
    
    Returns:
        Status dictionary
    """
    from .kelly_metrics import _kelly_store
    
    available = are_kelly_metrics_available()
    summary = _kelly_store.get_summary()
    
    status = {
        "available": available,
        "last_updated": summary.get("last_updated", 0),
        "age_seconds": summary.get("age_seconds", 0),
        "is_stale": summary.get("is_stale", True),
        "update_count": summary.get("update_count", 0)
    }
    
    # Add health status
    if available:
        metrics = get_current_kelly_metrics()
        if metrics:
            status["health"] = "healthy" if metrics.sharpe > 0.5 else "warning"
            status["fraction_range"] = {
                "min": min(metrics.fraction_quarter, metrics.fraction_half, metrics.fraction_full),
                "max": max(metrics.fraction_quarter, metrics.fraction_half, metrics.fraction_full)
            }
    else:
        status["health"] = "unavailable"
    
    return status

# Example Streamlit client code:
"""
import requests
import streamlit as st
import os

API_BASE = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))

def display_kelly_metrics():
    st.sidebar.subheader("Kelly Backtest Metrics")
    
    try:
        # Fetch Kelly metrics
        r = requests.get(f"{API_BASE}/kelly/metrics", timeout=3)
        
        if r.status_code == 200:
            km = r.json()
            
            # Display fractions
            st.sidebar.write("**Kelly Fractions:**")
            st.sidebar.write(f"Full Kelly: {km['fraction_full']:.2%}")
            st.sidebar.write(f"Half Kelly: {km['fraction_half']:.2%}")
            st.sidebar.write(f"Quarter Kelly: {km['fraction_quarter']:.2%}")
            st.sidebar.write(f"Vol-Targeted: {km['vol_targeted_fraction']:.2%}")
            
            # Display performance
            st.sidebar.write("**Performance:**")
            st.sidebar.write(f"Sharpe: {km['sharpe']:.2f}")
            st.sidebar.write(f"Max DD: {km['max_drawdown']:.2%}")
            st.sidebar.write(f"Total Return: {km['total_return']:.1%}")
            st.sidebar.write(f"Win Rate: {km['win_rate']:.1%}")
            st.sidebar.write(f"Total Trades: {km['total_trades']}")
            
            # Display timestamp
            import time
            age = time.time() - km['timestamp']
            st.sidebar.write(f"Last Updated: {age/3600:.1f} hours ago")
            
        else:
            st.sidebar.warning("Kelly metrics not available")
            st.sidebar.error(f"Error: {r.status_code}")
            
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"Kelly metrics error: {e}")
    except Exception as e:
        st.sidebar.error(f"Unexpected error: {e}")

def display_kelly_status():
    '''Display Kelly system status.'''
    try:
        r = requests.get(f"{API_BASE}/kelly/status", timeout=3)
        
        if r.status_code == 200:
            status = r.json()
            
            if status["available"]:
                if status["health"] == "healthy":
                    st.success("🟢 Kelly System Healthy")
                elif status["health"] == "warning":
                    st.warning("🟡 Kelly System Warning")
                else:
                    st.error("🔴 Kelly System Issue")
                
                st.write(f"Last Updated: {status['age_seconds']/3600:.1f} hours ago")
                st.write(f"Update Count: {status['update_count']}")
            else:
                st.error("🔴 Kelly Metrics Unavailable")
                
    except Exception as e:
        st.error(f"Status check failed: {e}")

# In Streamlit app:
# display_kelly_metrics()
# display_kelly_status()
"""
