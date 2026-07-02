"""
Streamlit Kelly Alerts Filtered by VIX-Rank

Real-time Kelly monitoring with VIX-Rank filtering for enhanced risk management.
"""

import os
import time
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Configuration
API_BASE = os.getenv("KALSHI_API_BASE", f"http://localhost:{os.getenv('MERID_PORT', '8011')}")

# Page configuration
st.set_page_config(
    page_title="Kelly & VIX-Rank Alerts", 
    layout="wide",
    page_icon="🚨"
)

def fetch_vix_kelly() -> Optional[Dict[str, Any]]:
    """
    Fetch VIX-Kelly sizing data from FastAPI endpoint.
    
    Returns:
        Sizing data dictionary or None if error
    """
    try:
        r = requests.get(f"{API_BASE}/sizing/vix-kelly", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching VIX-Kelly data: {e}")
        return None

def create_vix_gauge(vix_value: float, vix_rank: float, max_vix_rank: float) -> go.Figure:
    """
    Create VIX gauge chart with rank indicator.
    
    Args:
        vix_value: Current VIX value
        vix_rank: Current VIX rank (0-1)
        max_vix_rank: Maximum acceptable VIX rank
        
    Returns:
        Plotly gauge figure
    """
    fig = go.Figure()
    
    # VIX value gauge
    fig.add_trace(go.Indicator(
        mode = "gauge+number+delta",
        value = vix_value,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "VIX Value"},
        gauge = {
            'axis': {'range': [None, 50]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 15], 'color': "lightgreen"},
                {'range': [15, 25], 'color': "yellow"},
                {'range': [25, 50], 'color': "lightcoral"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 25
            }
        }
    ))
    
    fig.update_layout(
        title="VIX Value and Rank",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    return fig

def create_kelly_vix_scatter(history: List[Dict[str, Any]]) -> go.Figure:
    """
    Create scatter plot of Kelly vs VIX-Rank over time.
    
    Args:
        history: List of historical data points
        
    Returns:
        Plotly scatter figure
    """
    if not history:
        return go.Figure()
    
    # Extract data
    timestamps = [point['timestamp'] for point in history]
    kelly_fractions = [point['hybrid_fraction'] for point in history]
    vix_ranks = [point['vix_rank'] for point in history]
    
    # Create color mapping based on alert severity
    colors = []
    for i, (kelly, vix) in enumerate(zip(kelly_fractions, vix_ranks)):
        if kelly > 0.5 and vix > 0.8:
            colors.append('red')  # Critical
        elif kelly > 0.5 or vix > 0.8:
            colors.append('orange')  # Warning
        else:
            colors.append('green')  # Normal
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=vix_ranks,
        y=kelly_fractions,
        mode='markers+lines',
        marker=dict(
            size=8,
            color=colors,
            symbol='circle'
        ),
        text=[f"Time: {t.strftime('%H:%M:%S')}<br>Kelly: {k:.3f}<br>VIX-Rank: {v:.3f}" 
              for t, k, v in zip(timestamps, kelly_fractions, vix_ranks)],
        hovertemplate="%{text}<extra></extra>",
        name="Kelly vs VIX-Rank"
    ))
    
    # Add threshold lines
    fig.add_hline(y=0.5, line_dash="dash", line_color="blue", annotation_text="Max Kelly")
    fig.add_vline(x=0.8, line_dash="dash", line_color="red", annotation_text="Max VIX-Rank")
    
    fig.update_layout(
        title="Kelly Fraction vs VIX-Rank Over Time",
        xaxis_title="VIX-Rank (0-1)",
        yaxis_title="Hybrid Kelly Fraction",
        template="plotly_white",
        height=500
    )
    
    return fig

def create_risk_matrix(kelly: float, vix_rank: float, max_kelly: float, max_vix_rank: float) -> go.Figure:
    """
    Create risk matrix visualization.
    
    Args:
        kelly: Current Kelly fraction
        vix_rank: Current VIX rank
        max_kelly: Maximum allowed Kelly
        max_vix_rank: Maximum allowed VIX rank
        
    Returns:
        Plotly matrix figure
    """
    # Create risk zones
    risk_data = []
    
    # Define zones
    zones = [
        {"name": "Safe", "x": [0, max_vix_rank], "y": [0, max_kelly], "color": "lightgreen"},
        {"name": "High Kelly", "x": [0, max_vix_rank], "y": [max_kelly, 1], "color": "orange"},
        {"name": "High Vol", "x": [max_vix_rank, 1], "y": [0, max_kelly], "color": "yellow"},
        {"name": "Critical", "x": [max_vix_rank, 1], "y": [max_kelly, 1], "color": "lightcoral"}
    ]
    
    fig = go.Figure()
    
    # Add risk zones
    for zone in zones:
        fig.add_shape(
            type="rect",
            x0=zone["x"][0], x1=zone["x"][1],
            y0=zone["y"][0], y1=zone["y"][1],
            fillcolor=zone["color"],
            opacity=0.5,
            line=dict(width=0),
            layer="below"
        )
    
    # Add current position
    fig.add_trace(go.Scatter(
        x=[vix_rank],
        y=[kelly],
        mode='markers',
        marker=dict(
            size=20,
            color='red',
            symbol='diamond',
            line=dict(width=2, color='darkred')
        ),
        name="Current Position",
        hovertemplate=f"Kelly: {kelly:.3f}<br>VIX-Rank: {vix_rank:.3f}<extra></extra>"
    ))
    
    # Add threshold lines
    fig.add_vline(x=max_vix_rank, line_dash="dash", line_color="red", annotation_text="Max VIX-Rank")
    fig.add_hline(y=max_kelly, line_dash="dash", line_color="blue", annotation_text="Max Kelly")
    
    fig.update_layout(
        title="Risk Matrix: Kelly vs VIX-Rank",
        xaxis_title="VIX-Rank (0-1)",
        yaxis_title="Kelly Fraction",
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1]),
        template="plotly_white",
        height=500,
        showlegend=True
    )
    
    return fig

def assess_risk_level(kelly: float, vix_rank: float, max_kelly: float, max_vix_rank: float) -> Dict[str, Any]:
    """
    Assess current risk level.
    
    Args:
        kelly: Current Kelly fraction
        vix_rank: Current VIX rank
        max_kelly: Maximum allowed Kelly
        max_vix_rank: Maximum allowed VIX rank
        
    Returns:
        Risk assessment dictionary
    """
    kelly_excess = max(0, kelly - max_kelly)
    vix_excess = max(0, vix_rank - max_vix_rank)
    
    # Determine risk level
    if kelly_excess > 0 and vix_excess > 0:
        risk_level = "CRITICAL"
        risk_color = "red"
        action = "IMMEDIATE DE-LEVERAGING REQUIRED"
    elif kelly_excess > 0:
        risk_level = "HIGH"
        risk_color = "orange"
        action = "Consider reducing Kelly fraction"
    elif vix_excess > 0:
        risk_level = "ELEVATED"
        risk_color = "yellow"
        action = "Monitor volatility, consider risk reduction"
    else:
        risk_level = "NORMAL"
        risk_color = "green"
        action = "Risk parameters within limits"
    
    return {
        "level": risk_level,
        "color": risk_color,
        "action": action,
        "kelly_excess": kelly_excess,
        "vix_excess": vix_excess,
        "combined_score": kelly_excess + vix_excess
    }

def main():
    """Main Streamlit application."""
    st.title("🚨 Kalshi – Kelly Alerts Filtered by VIX-Rank")
    st.markdown("Real-time Kelly monitoring with VIX-Rank filtering for enhanced risk management")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Alert Configuration")
        
        # Alert thresholds
        st.subheader("Risk Thresholds")
        max_kelly = st.slider(
            "Max allowed hybrid Kelly fraction", 
            0.0, 1.0, 0.5, 0.05,
            help="Alert when Kelly fraction exceeds this value"
        )
        
        max_vix_rank = st.slider(
            "Max allowed VIX-Rank (percentile)", 
            0.0, 1.0, 0.8, 0.05,
            help="Alert when VIX-Rank exceeds this percentile"
        )
        
        # Refresh settings
        st.subheader("Refresh Settings")
        refresh_sec = st.slider("Refresh interval (seconds)", 2, 60, 10)
        auto_refresh = st.checkbox("Auto refresh", True, help="Poll the sizing API periodically")
        
        # Alert history
        st.subheader("Alert History")
        max_history = st.slider("Max history points", 50, 500, 200)
        
        st.markdown("---")
        st.markdown(f"**API Base:** `{API_BASE}`")
        
        # Connection status
        try:
            r = requests.get(f"{API_BASE}/health", timeout=2)
            if r.status_code == 200:
                st.success("🟢 API Connected")
            else:
                st.error(f"🔴 API Error: {r.status_code}")
        except Exception:
            st.warning("🟡 API Status Unknown")
    
    # Initialize session state
    if 'vix_history' not in st.session_state:
        st.session_state.vix_history = []
    if 'alert_count' not in st.session_state:
        st.session_state.alert_count = 0
    
    # Main content area
    placeholder = st.empty()
    
    # Auto-refresh loop
    while True:
        try:
            # Fetch data
            data = fetch_vix_kelly()
            
            if not data:
                st.error("Failed to fetch VIX-Kelly data")
                break
            
            # Extract values
            base_kelly = data.get("base_kelly", 0.0)
            frac = data.get("hybrid_fraction", 0.0)
            vix_val = data.get("vix", 0.0)
            vix_rank = data.get("vix_rank", 0.0)
            
            # Add to history
            current_point = {
                "timestamp": datetime.now(),
                "base_kelly": base_kelly,
                "hybrid_fraction": frac,
                "vix": vix_val,
                "vix_rank": vix_rank
            }
            
            st.session_state.vix_history.append(current_point)
            # Keep only recent history
            st.session_state.vix_history = st.session_state.vix_history[-max_history:]
            
            # Assess risk
            risk_assessment = assess_risk_level(frac, vix_rank, max_kelly, max_vix_rank)
            
            # Display dashboard
            with placeholder.container():
                # Status metrics
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Hybrid Kelly", f"{frac:.3f}")
                
                with col2:
                    st.metric("Base Kelly", f"{base_kelly:.3f}")
                
                with col3:
                    st.metric("VIX", f"{vix_val:.2f}")
                
                with col4:
                    st.metric("VIX-Rank", f"{vix_rank:.3f}")
                
                # Risk assessment
                st.markdown("---")
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.subheader(f"🛡️ Risk Assessment: {risk_assessment['level']}")
                    _ra_color = risk_assessment['color']
                    _ra_action = risk_assessment['action']
                    st.markdown(f'<div style="background-color: {_ra_color}; color: white; padding: 10px; border-radius: 5px;">{_ra_action}</div>', unsafe_allow_html=True)
                
                with col2:
                    st.subheader("Risk Metrics")
                    st.metric("Kelly Excess", f"{risk_assessment['kelly_excess']:.3f}")
                    st.metric("VIX Excess", f"{risk_assessment['vix_excess']:.3f}")
                    st.metric("Combined Score", f"{risk_assessment['combined_score']:.3f}")
                
                # Alert logic
                st.markdown("---")
                if frac > max_kelly and vix_rank > max_vix_rank:
                    st.error(
                        f"🚨 **CRITICAL ALERT**: Kelly fraction {frac:.3f} exceeds {max_kelly:.3f} "
                        f"and VIX-Rank {vix_rank:.3f} exceeds {max_vix_rank:.3f}. "
                        "**IMMEDIATE DE-LEVERAGING REQUIRED.**"
                    )
                    st.session_state.alert_count += 1
                elif frac > max_kelly:
                    st.warning(
                        f"⚠️ **HIGH KELLY**: Kelly fraction {frac:.3f} above limit {max_kelly:.3f}, "
                        f"but VIX-Rank ({vix_rank:.3f}) still acceptable. "
                        "**Consider reducing position size.**"
                    )
                elif vix_rank > max_vix_rank:
                    st.warning(
                        f"⚠️ **HIGH VOLATILITY**: VIX-Rank {vix_rank:.3f} > {max_vix_rank:.3f}; "
                        f"you may want to cut risk even if Kelly ({frac:.3f}) allows more. "
                        "**Monitor volatility closely.**"
                    )
                else:
                    st.success(
                        f"✅ **NORMAL**: Kelly ({frac:.3f}) and VIX-Rank ({vix_rank:.3f}) "
                        f"are within configured risk limits."
                    )
                
                # Visualizations
                st.markdown("---")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("📊 Risk Matrix")
                    fig_matrix = create_risk_matrix(frac, vix_rank, max_kelly, max_vix_rank)
                    st.plotly_chart(fig_matrix, use_container_width=True)
                
                with col2:
                    st.subheader("📈 VIX Gauge")
                    fig_vix = create_vix_gauge(vix_val, vix_rank, max_vix_rank)
                    st.plotly_chart(fig_vix, use_container_width=True)
                
                # Historical trends
                if len(st.session_state.vix_history) > 1:
                    st.subheader("📈 Historical Trends")
                    fig_scatter = create_kelly_vix_scatter(st.session_state.vix_history)
                    st.plotly_chart(fig_scatter, use_container_width=True)
                
                # Alert statistics
                st.subheader("📋 Alert Statistics")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Total Alerts", st.session_state.alert_count)
                
                with col2:
                    critical_alerts = sum(1 for point in st.session_state.vix_history 
                                       if point['hybrid_fraction'] > max_kelly and point['vix_rank'] > max_vix_rank)
                    st.metric("Critical Alerts", critical_alerts)
                
                with col3:
                    avg_kelly = sum(point['hybrid_fraction'] for point in st.session_state.vix_history) / len(st.session_state.vix_history)
                    st.metric("Avg Kelly", f"{avg_kelly:.3f}")
                
                with col4:
                    avg_vix_rank = sum(point['vix_rank'] for point in st.session_state.vix_history) / len(st.session_state.vix_history)
                    st.metric("Avg VIX-Rank", f"{avg_vix_rank:.3f}")
                
                # Additional info
                with st.expander("📊 Detailed Analysis"):
                    st.write("**Current Market Conditions:**")
                    st.write(f"  Base Kelly: {base_kelly:.3f}")
                    st.write(f"  Hybrid Kelly: {frac:.3f}")
                    st.write(f"  VIX Value: {vix_val:.2f}")
                    st.write(f"  VIX Rank: {vix_rank:.3f} (percentile)")
                    
                    st.write("**Risk Thresholds:**")
                    st.write(f"  Max Kelly: {max_kelly:.3f}")
                    st.write(f"  Max VIX-Rank: {max_vix_rank:.3f}")
                    
                    st.write("**Risk Assessment:**")
                    st.write(f"  Level: {risk_assessment['level']}")
                    st.write(f"  Action: {risk_assessment['action']}")
                    st.write(f"  Kelly Excess: {risk_assessment['kelly_excess']:.3f}")
                    st.write(f"  VIX Excess: {risk_assessment['vix_excess']:.3f}")
            
        except Exception as e:
            st.error(f"Error updating dashboard: {e}")
            logger.error(f"Dashboard update error: {e}")
        
        # Wait for next refresh
        if not auto_refresh:
            break
        time.sleep(refresh_sec)
        st.experimental_rerun()

if __name__ == "__main__":
    main()
