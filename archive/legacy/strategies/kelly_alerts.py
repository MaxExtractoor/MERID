"""
Streamlit Real-Time Kelly Alerts on Kalshi

Real-time monitoring of Kelly fraction and drawdown with configurable alerts.
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
    page_title="Kalshi Kelly Alerts", 
    layout="wide",
    page_icon="🚨"
)

def fetch_sizing() -> Optional[Dict[str, Any]]:
    """
    Fetch current Kelly sizing data from FastAPI endpoint.
    
    Returns:
        Sizing data dictionary or None if error
    """
    try:
        r = requests.get(f"{API_BASE}/sizing/vix-kelly", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching sizing data: {e}")
        return None

def fetch_equity() -> Optional[Dict[str, Any]]:
    """
    Fetch current equity data from FastAPI endpoint.
    
    Returns:
        Equity data dictionary or None if error
    """
    try:
        r = requests.get(f"{API_BASE}/kelly/equity", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching equity data: {e}")
        return None

def fetch_market_data() -> Optional[Dict[str, Any]]:
    """
    Fetch additional market data for comprehensive monitoring.
    
    Returns:
        Market data dictionary or None if error
    """
    try:
        r = requests.get(f"{API_BASE}/kalshi/markets/status", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching market data: {e}")
        return None

def create_alert_indicator(value: float, threshold: float, warning_above: bool = True) -> str:
    """
    Create alert indicator based on threshold comparison.
    
    Args:
        value: Current value
        threshold: Warning threshold
        warning_above: True if warning when value > threshold, False when < threshold
        
    Returns:
        Alert indicator emoji
    """
    if warning_above:
        if value > threshold:
            return "🚨"
        elif value > threshold * 0.8:
            return "⚠️"
        else:
            return "✅"
    else:
        if value < threshold:
            return "🚨"
        elif value < threshold * 1.2:
            return "⚠️"
        else:
            return "✅"

def create_kelly_gauge(fraction: float, threshold: float) -> go.Figure:
    """
    Create Kelly fraction gauge chart.
    
    Args:
        fraction: Current Kelly fraction
        threshold: Warning threshold
        
    Returns:
        Plotly gauge figure
    """
    fig = go.Figure(go.Indicator(
        mode = "gauge+number+delta",
        value = fraction,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Kelly Fraction"},
        delta = {'reference': threshold},
        gauge = {
            'axis': {'range': [None, 1]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, threshold * 0.8], 'color': "lightgreen"},
                {'range': [threshold * 0.8, threshold], 'color': "yellow"},
                {'range': [threshold, 1], 'color': "lightcoral"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': threshold
            }
        }
    ))
    
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
    
    return fig

def create_equity_chart(equity_data: List[float], threshold: float) -> go.Figure:
    """
    Create equity chart with drawdown threshold.
    
    Args:
        equity_data: List of equity values
        threshold: Drawdown warning threshold
        
    Returns:
        Plotly equity chart
    """
    if not equity_data:
        return go.Figure()
    
    # Create equity series
    equity_series = list(range(len(equity_data)))
    
    # Calculate drawdown
    peak = 1.0
    drawdowns = []
    for i, eq in enumerate(equity_data):
        peak = max(peak, eq)
        dd = (eq - peak) / peak
        drawdowns.append(dd)
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=("Equity Curve", "Drawdown"),
        row_heights=[0.7, 0.3]
    )
    
    # Add equity curve
    fig.add_trace(go.Scatter(
        x=equity_series,
        y=equity_data,
        mode='lines',
        name='Equity',
        line=dict(color='blue', width=2)
    ), row=1, col=1)
    
    # Add drawdown line
    fig.add_trace(go.Scatter(
        x=equity_series,
        y=[threshold] * len(equity_series),
        mode='lines',
        name='Warning Threshold',
        line=dict(color='red', dash='dash', width=2)
    ), row=2, col=1)
    
    # Add drawdown area
    fig.add_trace(go.Scatter(
        x=equity_series,
        y=drawdowns,
        mode='lines',
        name='Drawdown',
        line=dict(color='orange', width=2),
        fill='tonexty',
        fillcolor='rgba(255, 165, 0, 0.3)'
    ), row=2, col=1)
    
    fig.update_layout(
        title="Equity and Drawdown Monitoring",
        height=600,
        showlegend=True
    )
    
    fig.update_yaxes(title_text="Equity (x)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown", tickformat=".1%", row=2, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    
    return fig

def create_alert_history(alerts: List[Dict[str, Any]]) -> go.Figure:
    """
    Create alert history timeline chart.
    
    Args:
        alerts: List of alert dictionaries
        
    Returns:
        Plotly timeline chart
    """
    if not alerts:
        return go.Figure()
    
    # Extract alert data
    timestamps = [alert['timestamp'] for alert in alerts]
    types = [alert['type'] for alert in alerts]
    messages = [alert['message'] for alert in alerts]
    
    # Create color mapping
    colors = {'warning': 'orange', 'critical': 'red', 'info': 'blue'}
    marker_colors = [colors.get(alert_type, 'gray') for alert_type in types]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=[1] * len(alerts),
        mode='markers',
        marker=dict(
            size=15,
            color=marker_colors,
            symbol='diamond'
        ),
        text=messages,
        hovertemplate="<b>%{text}</b><br>%{x}<extra></extra>",
        name="Alerts"
    ))
    
    fig.update_layout(
        title="Alert History",
        xaxis_title="Time",
        yaxis_title="Alert Level",
        height=200,
        showlegend=False
    )
    
    fig.update_yaxes(visible=False)
    
    return fig

def main():
    """Main Streamlit application."""
    st.title("🚨 Kalshi – Real-Time Kelly Alerts")
    st.markdown("Real-time monitoring of Kelly fraction and drawdown with configurable alerts")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Alert Configuration")
        
        # Alert thresholds
        st.subheader("Warning Thresholds")
        frac_warn = st.slider(
            "Warn above Kelly fraction", 
            0.0, 1.0, 0.5, 0.05,
            help="Alert when Kelly fraction exceeds this value"
        )
        
        dd_warn = st.slider(
            "Warn below equity (fraction of start)", 
            0.0, 1.0, 0.7, 0.05,
            help="Alert when equity falls below this fraction of starting capital"
        )
        
        # Refresh settings
        st.subheader("Refresh Settings")
        refresh_sec = st.slider("Refresh interval (seconds)", 1, 30, 5)
        
        # Alert history
        st.subheader("Alert History")
        max_alerts = st.slider("Max alerts to display", 10, 100, 50)
        
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
    
    # Alert history storage
    if 'alert_history' not in st.session_state:
        st.session_state.alert_history = []
    
    # Main content area
    placeholder = st.empty()
    
    # Auto-refresh loop
    while True:
        try:
            # Fetch data
            sizing_data = fetch_sizing()
            equity_data = fetch_equity()
            market_data = fetch_market_data()
            
            if not sizing_data or not equity_data:
                st.error("Failed to fetch required data")
                break
            
            # Extract current values
            current_fraction = sizing_data.get("hybrid_fraction", 0.0)
            current_equity = equity_data.get("equity", [1.0])[-1] if equity_data.get("equity") else 1.0
            
            # Check alerts
            new_alerts = []
            
            if current_fraction > frac_warn:
                alert_msg = f"Kelly fraction ({current_fraction:.3f}) above warning threshold ({frac_warn:.3f})"
                new_alerts.append({
                    'timestamp': datetime.now(),
                    'type': 'warning',
                    'message': alert_msg
                })
            
            if current_equity < dd_warn:
                alert_msg = f"Equity ({current_equity:.3f}x) below drawdown warning threshold ({dd_warn:.3f}x)"
                new_alerts.append({
                    'timestamp': datetime.now(),
                    'type': 'critical',
                    'message': alert_msg
                })
            
            # Add new alerts to history
            if new_alerts:
                st.session_state.alert_history.extend(new_alerts)
                # Keep only recent alerts
                st.session_state.alert_history = st.session_state.alert_history[-max_alerts:]
            
            # Display dashboard
            with placeholder.container():
                # Status metrics
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    fraction_indicator = create_alert_indicator(current_fraction, frac_warn, True)
                    st.metric(f"Kelly Fraction {fraction_indicator}", f"{current_fraction:.3f}")
                
                with col2:
                    equity_indicator = create_alert_indicator(current_equity, dd_warn, False)
                    st.metric(f"Current Equity {equity_indicator}", f"{current_equity:.3f}x")
                
                with col3:
                    if sizing_data.get("base_kelly"):
                        st.metric("Base Kelly", f"{sizing_data['base_kelly']:.3f}")
                
                with col4:
                    if market_data and market_data.get("active_markets"):
                        st.metric("Active Markets", market_data["active_markets"])
                
                # Alert messages
                if new_alerts:
                    for alert in new_alerts:
                        if alert['type'] == 'critical':
                            st.error(alert['message'])
                        else:
                            st.warning(alert['message'])
                
                # Visual charts
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("📊 Kelly Fraction Monitor")
                    fig_gauge = create_kelly_gauge(current_fraction, frac_warn)
                    st.plotly_chart(fig_gauge, use_container_width=True)
                
                with col2:
                    st.subheader("📈 Equity & Drawdown")
                    equity_series = equity_data.get("equity", [1.0])
                    fig_equity = create_equity_chart(equity_series, dd_warn)
                    st.plotly_chart(fig_equity, use_container_width=True)
                
                # Alert history
                if st.session_state.alert_history:
                    st.subheader("📋 Recent Alerts")
                    
                    # Create timeline chart
                    fig_timeline = create_alert_history(st.session_state.alert_history)
                    st.plotly_chart(fig_timeline, use_container_width=True)
                    
                    # Alert details table
                    alert_df_data = []
                    for alert in st.session_state.alert_history[-10:]:  # Last 10 alerts
                        alert_df_data.append({
                            "Time": alert['timestamp'].strftime("%H:%M:%S"),
                            "Type": alert['type'].title(),
                            "Message": alert['message']
                        })
                    
                    if alert_df_data:
                        alert_df = pd.DataFrame(alert_df_data)
                        st.dataframe(alert_df, use_container_width=True)
                
                # Additional info
                with st.expander("📊 Detailed Metrics"):
                    if sizing_data:
                        st.write("**Sizing Data:**")
                        for key, value in sizing_data.items():
                            if isinstance(value, (int, float)):
                                st.write(f"  {key}: {value:.4f}")
                            else:
                                st.write(f"  {key}: {value}")
                    
                    if equity_data:
                        st.write("**Equity Data:**")
                        equity_series = equity_data.get("equity", [])
                        if equity_series:
                            st.write(f"  Current: {equity_series[-1]:.4f}")
                            st.write(f"  Peak: {max(equity_series):.4f}")
                            st.write(f"  Min: {min(equity_series):.4f}")
                            st.write(f"  Points: {len(equity_series)}")
            
        except Exception as e:
            st.error(f"Error updating dashboard: {e}")
            logger.error(f"Dashboard update error: {e}")
        
        # Wait for next refresh
        time.sleep(refresh_sec)
        st.experimental_rerun()

if __name__ == "__main__":
    main()
