"""
Integrate Fractional Kelly into Streamlit Dashboard

Expose Kelly fraction and live risk controls in dashboard sidebar.
"""

import os
import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

API_BASE = os.getenv("KALSHI_API_BASE", f"http://localhost:{os.getenv('MERID_PORT', '8011')}")

def render_kelly_sidebar(kelly_info: Optional[Dict[str, float]] = None) -> float:
    """
    Render Kelly risk sizing controls in Streamlit sidebar.
    
    Args:
        kelly_info: Precomputed Kelly information
        
    Returns:
        Current Kelly fraction to use
    """
    st.sidebar.markdown("### Risk Sizing (Kelly)")
    
    # Kelly fraction slider
    default_fraction = st.sidebar.slider(
        "Fraction of Kelly", 
        min_value=0.0, 
        max_value=1.0, 
        value=0.25, 
        step=0.05,
        help="Fraction of full Kelly to use for position sizing"
    )
    
    # Display Kelly statistics if available
    if kelly_info:
        st.sidebar.markdown("**Kelly Statistics:**")
        st.sidebar.write(f"Full Kelly: {kelly_info.get('full', 0.0):.2%}")
        st.sidebar.write(f"Half Kelly: {kelly_info.get('half', 0.0):.2%}")
        st.sidebar.write(f"Quarter Kelly: {kelly_info.get('quarter', 0.0):.2%}")
        
        # Display additional stats if available
        if 'win_rate' in kelly_info:
            st.sidebar.write(f"Win Rate: {kelly_info['win_rate']:.1%}")
        if 'win_loss_ratio' in kelly_info:
            st.sidebar.write(f"W/L Ratio: {kelly_info['win_loss_ratio']:.2f}")
        if 'total_trades' in kelly_info:
            st.sidebar.write(f"Total Trades: {kelly_info['total_trades']}")
    
    # Calculate current fraction
    current_fraction = default_fraction * kelly_info.get("full", 0.0) if kelly_info else 0.0
    
    # Display current selection
    st.sidebar.markdown("**Current Selection:**")
    st.sidebar.write(f"Using **{default_fraction:.0%}** of full Kelly")
    st.sidebar.write(f"Effective fraction: **{current_fraction:.2%}**")
    
    # Risk warnings
    if current_fraction > 0.15:
        st.sidebar.warning("⚠️ High Kelly fraction - consider reducing risk")
    elif current_fraction < 0.02:
        st.sidebar.info("ℹ️ Low Kelly fraction - conservative sizing")
    
    return current_fraction

def render_risk_controls_sidebar() -> Dict[str, Any]:
    """
    Render additional risk controls in sidebar.
    
    Returns:
        Dictionary with risk control settings
    """
    st.sidebar.markdown("### Risk Controls")
    
    # Drawdown limit
    max_drawdown = st.sidebar.slider(
        "Max Drawdown Limit",
        min_value=0.05,
        max_value=0.50,
        value=0.20,
        step=0.05,
        format="%.0%",
        help="Maximum allowed drawdown before trading stops"
    )
    
    # Position size limit
    max_position_size = st.sidebar.slider(
        "Max Position Size",
        min_value=0.01,
        max_value=0.50,
        value=0.10,
        step=0.01,
        format="%.1%",
        help="Maximum position size as fraction of portfolio"
    )
    
    # Daily loss limit
    daily_loss_limit = st.sidebar.slider(
        "Daily Loss Limit",
        min_value=0.01,
        max_value=0.20,
        value=0.05,
        step=0.01,
        format="%.1%",
        help="Maximum daily loss before trading stops"
    )
    
    # Volatility targeting
    enable_vol_targeting = st.sidebar.checkbox(
        "Enable Volatility Targeting",
        value=False,
        help="Adjust position size based on market volatility"
    )
    
    target_volatility = None
    if enable_vol_targeting:
        target_volatility = st.sidebar.slider(
            "Target Volatility",
            min_value=0.05,
            max_value=0.50,
            value=0.20,
            step=0.05,
            format="%.0%",
            help="Target annual volatility for position sizing"
        )
    
    return {
        "max_drawdown": max_drawdown,
        "max_position_size": max_position_size,
        "daily_loss_limit": daily_loss_limit,
        "enable_vol_targeting": enable_vol_targeting,
        "target_volatility": target_volatility
    }

def render_performance_metrics_sidebar(equity_curve: Optional[pd.Series] = None) -> Dict[str, Any]:
    """
    Render performance metrics in sidebar.
    
    Args:
        equity_curve: Current equity curve
        
    Returns:
        Performance metrics
    """
    st.sidebar.markdown("### Performance Metrics")
    
    if equity_curve is None or equity_curve.empty:
        st.sidebar.info("No performance data available")
        return {}
    
    # Calculate metrics
    current_equity = equity_curve.iloc[-1]
    initial_equity = equity_curve.iloc[0]
    total_return = (current_equity / initial_equity) - 1
    
    # Calculate returns
    returns = equity_curve.pct_change().dropna()
    
    # Sharpe ratio (annualized for 15m bars)
    if len(returns) > 1 and returns.std() > 0:
        periods_per_year = 365 * 24 * 4
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(periods_per_year)
    else:
        sharpe_ratio = 0.0
    
    # Max drawdown
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak.replace(0, np.nan)
    max_drawdown = drawdown.min()
    
    # Current drawdown
    current_drawdown = drawdown.iloc[-1]
    
    # Win rate (if enough data)
    if len(returns) > 10:
        win_rate = (returns > 0).sum() / len(returns)
    else:
        win_rate = 0.0
    
    # Display metrics
    st.sidebar.write(f"Current Equity: ${current_equity:,.2f}")
    st.sidebar.write(f"Total Return: {total_return:.1%}")
    st.sidebar.write(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    st.sidebar.write(f"Max Drawdown: {max_drawdown:.2%}")
    st.sidebar.write(f"Current Drawdown: {current_drawdown:.2%}")
    st.sidebar.write(f"Win Rate: {win_rate:.1%}")
    
    # Status indicators
    if current_drawdown < -0.15:
        st.sidebar.error("🔴 High current drawdown!")
    elif max_drawdown < -0.10:
        st.sidebar.warning("🟡 Elevated drawdown risk")
    else:
        st.sidebar.success("🟢 Drawdown within limits")
    
    return {
        "current_equity": current_equity,
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "current_drawdown": current_drawdown,
        "win_rate": win_rate
    }

def load_kelly_info_from_session() -> Optional[Dict[str, float]]:
    """
    Load Kelly information from Streamlit session state.
    
    Returns:
        Kelly information dictionary or None
    """
    return st.session_state.get("kelly_info")

def save_kelly_info_to_session(kelly_info: Dict[str, float]):
    """
    Save Kelly information to Streamlit session state.
    
    Args:
        kelly_info: Kelly information to save
    """
    st.session_state["kelly_info"] = kelly_info

def generate_sample_kelly_info() -> Dict[str, float]:
    """
    Generate sample Kelly information for demonstration.
    
    Returns:
        Sample Kelly information
    """
    return {
        "full": 0.12,
        "half": 0.06,
        "quarter": 0.03,
        "win_rate": 0.58,
        "win_loss_ratio": 1.35,
        "total_trades": 234
    }

def render_kelly_dashboard():
    """
    Render complete Kelly dashboard section.
    
    Returns:
        Dictionary with all Kelly settings
    """
    # Load or generate Kelly info
    kelly_info = load_kelly_info_from_session()
    if kelly_info is None:
        kelly_info = generate_sample_kelly_info()
        save_kelly_info_to_session(kelly_info)
    
    # Render Kelly controls
    current_fraction = render_kelly_sidebar(kelly_info)
    
    # Render risk controls
    risk_controls = render_risk_controls_sidebar()
    
    # Render performance metrics (would get from real data)
    performance_metrics = render_performance_metrics_sidebar()
    
    # Combine all settings
    dashboard_settings = {
        "kelly_fraction": current_fraction,
        "kelly_info": kelly_info,
        "risk_controls": risk_controls,
        "performance_metrics": performance_metrics
    }
    
    # Save to session
    st.session_state["dashboard_settings"] = dashboard_settings
    
    return dashboard_settings

def validate_dashboard_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate dashboard settings and provide warnings.
    
    Args:
        settings: Dashboard settings dictionary
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    kelly_fraction = settings.get("kelly_fraction", 0.0)
    risk_controls = settings.get("risk_controls", {})
    
    # Validate Kelly fraction
    if kelly_fraction > 0.20:
        validation["warnings"].append(f"High Kelly fraction: {kelly_fraction:.2%}")
        validation["recommendations"].append("Consider reducing Kelly fraction for better risk management")
    elif kelly_fraction < 0.01:
        validation["warnings"].append(f"Very low Kelly fraction: {kelly_fraction:.2%}")
        validation["recommendations"].append("Very conservative sizing may limit returns")
    
    # Validate risk controls
    max_dd = risk_controls.get("max_drawdown", 0.20)
    if max_dd > 0.30:
        validation["warnings"].append(f"High drawdown limit: {max_dd:.1%}")
        validation["recommendations"].append("Consider tighter drawdown limits")
    
    max_position = risk_controls.get("max_position_size", 0.10)
    if max_position > 0.25:
        validation["warnings"].append(f"High position size limit: {max_position:.1%}")
        validation["recommendations"].append("Consider smaller position limits")
    
    # Check for consistency
    if kelly_fraction > max_position:
        validation["warnings"].append("Kelly fraction exceeds position size limit")
        validation["recommendations"].append("Adjust Kelly fraction or position size limit")
    
    return validation

# Example usage in Streamlit app:
"""
import streamlit as st
from kelly_dashboard import render_kelly_dashboard, validate_dashboard_settings

def main():
    st.title("Trading Strategy Dashboard")
    
    # Render Kelly dashboard
    settings = render_kelly_dashboard()
    
    # Validate settings
    validation = validate_dashboard_settings(settings)
    
    if validation["warnings"]:
        st.warning("Risk Settings Warnings:")
        for warning in validation["warnings"]:
            st.write(f"• {warning}")
    
    # Use settings for trading
    kelly_fraction = settings["kelly_fraction"]
    risk_controls = settings["risk_controls"]
    
    st.write(f"Current Kelly fraction: {kelly_fraction:.2%}")
    st.write(f"Risk controls: {risk_controls}")

if __name__ == "__main__":
    main()
"""
