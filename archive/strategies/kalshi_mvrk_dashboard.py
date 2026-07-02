"""
Streamlit MVRK Dashboard with Live Kalshi Data

Real-time dashboard for Kalshi crypto MVRK vs Kelly strategy monitoring.
"""

import os
import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Configuration
API_BASE = os.getenv("KALSHI_API_BASE", f"http://localhost:{os.getenv('MERID_PORT', '8011')}")

# Page configuration
st.set_page_config(
    page_title="Kalshi MVRK Dashboard", 
    layout="wide",
    page_icon="📊"
)

# Custom CSS for better styling
st.markdown("""
<style>
.metric-card {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    border: 1px solid #e1e5e9;
}
</style>
""", unsafe_allow_html=True)

def fetch_mvrk() -> Dict[str, Any]:
    """Fetch MVRK/Kelly metrics from FastAPI."""
    try:
        r = requests.get(f"{API_BASE}/kelly/mvrk", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching MVRK data: {e}")
        raise

def fetch_returns() -> pd.DataFrame:
    """Fetch Kalshi returns data from FastAPI."""
    try:
        r = requests.get(f"{API_BASE}/kalshi/returns", timeout=5)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data)
        # Convert index to datetime if provided
        if not df.empty and 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
        return df
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching returns data: {e}")
        raise

def fetch_events() -> Dict[str, Any]:
    """Fetch recent Kalshi events from FastAPI."""
    try:
        r = requests.get(f"{API_BASE}/kalshi/events", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching events data: {e}")
        return {}

def create_equity_chart(eq_kelly: pd.Series, eq_mvrk: pd.Series) -> go.Figure:
    """Create equity curve comparison chart."""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=list(range(len(eq_kelly))),
        y=eq_kelly,
        name="Kelly",
        line=dict(color="blue", width=2),
        hovertemplate="Kelly: %{y:.3f}<extra></extra>"
    ))
    
    fig.add_trace(go.Scatter(
        x=list(range(len(eq_mvrk))),
        y=eq_mvrk,
        name="MVRK",
        line=dict(color="red", width=2),
        hovertemplate="MVRK: %{y:.3f}<extra></extra>"
    ))
    
    fig.update_layout(
        title="Portfolio Equity – Kelly vs MVRK",
        xaxis_title="Trade #",
        yaxis_title="Equity (normalized)",
        legend=dict(x=0.01, y=0.99),
        hovermode="x unified",
        template="plotly_white"
    )
    
    return fig

def create_correlation_heatmap(returns_df: pd.DataFrame) -> go.Figure:
    """Create correlation heatmap for crypto events."""
    if returns_df.empty:
        return go.Figure()
    
    corr = returns_df.corr()
    
    fig = go.Figure(data=go.Heatmap(
        z=corr.values,
        x=corr.columns,
        y=corr.columns,
        colorscale="RdBu",
        zmid=0,
        zmin=-1,
        zmax=1,
        textauto=".2f",
        textfont={"size": 12},
        hoverongaps=False
    ))
    
    fig.update_layout(
        title="Kalshi Crypto Events Correlation Matrix",
        template="plotly_white"
    )
    
    return fig

def create_performance_metrics(mvrk_data: Dict[str, Any]) -> go.Figure:
    """Create performance metrics comparison chart."""
    if not mvrk_data:
        return go.Figure()
    
    # Extract metrics
    kelly_metrics = mvrk_data.get("kelly_metrics", {})
    mvrk_metrics = mvrk_data.get("mvrk_metrics", {})
    
    if not kelly_metrics or not mvrk_metrics:
        return go.Figure()
    
    metrics = ["total_return", "sharpe_ratio", "max_drawdown"]
    metric_labels = ["Total Return", "Sharpe Ratio", "Max Drawdown"]
    
    kelly_values = [kelly_metrics.get(m, 0) for m in metrics]
    mvrk_values = [mvrk_metrics.get(m, 0) for m in metrics]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        name="Kelly",
        x=metric_labels,
        y=kelly_values,
        marker_color="blue"
    ))
    
    fig.add_trace(go.Bar(
        name="MVRK",
        x=metric_labels,
        y=mvrk_values,
        marker_color="red"
    ))
    
    fig.update_layout(
        title="Performance Metrics Comparison",
        yaxis_title="Value",
        barmode="group",
        template="plotly_white"
    )
    
    return fig

def display_weight_analysis(mvrk_data: Dict[str, Any]):
    """Display detailed weight analysis."""
    if not mvrk_data:
        return
    
    assets = mvrk_data.get("assets", [])
    kelly_weights = mvrk_data.get("kelly_weights", [])
    mvrk_weights = mvrk_data.get("mvrk_weights", [])
    
    if not assets or not kelly_weights or not mvrk_weights:
        st.warning("Weight data not available")
        return
    
    # Create weights DataFrame
    df_weights = pd.DataFrame({
        "Asset": assets,
        "Kelly Weight": kelly_weights,
        "MVRK Weight": mvrk_weights,
        "Weight Change": [m - k for m, k in zip(mvrk_weights, kelly_weights)],
        "Kelly Allocation": [abs(k) * 100 for k in kelly_weights],
        "MVRK Allocation": [abs(m) * 100 for m in mvrk_weights]
    })
    
    # Format for display
    styled_df = df_weights.style.format({
        "Kelly Weight": "{:.3f}",
        "MVRK Weight": "{:.3f}",
        "Weight Change": "{:.3f}",
        "Kelly Allocation": "{:.1f}%",
        "MVRK Allocation": "{:.1f}%"
    }).background_gradient(subset=["Weight Change"], cmap="RdYlGn")
    
    st.dataframe(styled_df, use_container_width=True)
    
    # Weight distribution chart
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        name="Kelly",
        x=assets,
        y=[abs(w) for w in kelly_weights],
        marker_color="blue",
        opacity=0.7
    ))
    
    fig.add_trace(go.Bar(
        name="MVRK",
        x=assets,
        y=[abs(w) for w in mvrk_weights],
        marker_color="red",
        opacity=0.7
    ))
    
    fig.update_layout(
        title="Weight Distribution Comparison",
        xaxis_title="Asset",
        yaxis_title="Absolute Weight",
        barmode="group",
        template="plotly_white"
    )
    
    st.plotly_chart(fig, use_container_width=True)

def display_risk_analysis(mvrk_data: Dict[str, Any]):
    """Display risk analysis metrics."""
    if not mvrk_data:
        return
    
    # Risk metrics
    ruin_kelly = mvrk_data.get("ruin_kelly", 0)
    ruin_mvrk = mvrk_data.get("ruin_mvrk", 0)
    
    kelly_metrics = mvrk_data.get("kelly_metrics", {})
    mvrk_metrics = mvrk_data.get("mvrk_metrics", {})
    
    # Create risk metrics cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Kelly Risk of Ruin",
            f"{ruin_kelly:.1%}",
            delta=f"{(ruin_kelly - ruin_mvrk) * 100:.1f}pp vs MVRK"
        )
    
    with col2:
        st.metric(
            "MVRK Risk of Ruin",
            f"{ruin_mvrk:.1%}",
            delta=f"{(ruin_mvrk - ruin_kelly) * 100:.1f}pp vs Kelly"
        )
    
    with col3:
        kelly_dd = kelly_metrics.get("max_drawdown", 0)
        st.metric(
            "Kelly Max DD",
            f"{kelly_dd:.1%}"
        )
    
    with col4:
        mvrk_dd = mvrk_metrics.get("max_drawdown", 0)
        st.metric(
            "MVRK Max DD",
            f"{mvrk_dd:.1%}"
        )
    
    # Risk improvement analysis
    if ruin_kelly > 0 and ruin_mvrk > 0:
        risk_improvement = (ruin_kelly - ruin_mvrk) / ruin_kelly
        st.info(f"🛡️ MVRK reduces risk of ruin by {risk_improvement:.1%}")
    
    if kelly_dd < 0 and mvrk_dd < 0:
        dd_improvement = (mvrk_dd - kelly_dd) / abs(kelly_dd)
        if dd_improvement > 0:
            st.success(f"📈 MVRK improves max drawdown by {dd_improvement:.1%}")
        else:
            st.warning(f"⚠️ MVRK worsens max drawdown by {abs(dd_improvement):.1%}")

def main():
    """Main dashboard application."""
    st.title("🚀 Kalshi Crypto – MVRK vs Kelly Strategy")
    st.markdown("Real-time monitoring of multivariate volatility regulated Kelly strategy")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        auto_refresh = st.checkbox("Auto Refresh", value=True)
        refresh_sec = st.slider("Refresh Interval (seconds)", 2, 30, 5)
        
        st.markdown("---")
        st.markdown(f"**API Base:** `{API_BASE}`")
        
        # Connection status
        try:
            # Test connection
            r = requests.get(f"{API_BASE}/health", timeout=2)
            if r.status_code == 200:
                st.success("🟢 API Connected")
            else:
                st.error(f"🔴 API Error: {r.status_code}")
        except Exception:
            st.warning("🟡 API Status Unknown")
    
    # Main content area
    if auto_refresh:
        # Create placeholders for dynamic content
        placeholder_status = st.empty()
        placeholder_weights = st.empty()
        placeholder_equity = st.empty()
        placeholder_performance = st.empty()
        placeholder_risk = st.empty()
        placeholder_corr = st.empty()
        
        while True:
            try:
                # Fetch data
                mvrk_data = fetch_mvrk()
                returns_df = fetch_returns()
                events_data = fetch_events()
                
                # Update status
                with placeholder_status:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.info(f"📊 Last Updated: {time.strftime('%H:%M:%S')}")
                    with col2:
                        if events_data:
                            st.info(f"📈 Active Events: {len(events_data.get('events', []))}")
                    with col3:
                        if not returns_df.empty:
                            st.info(f"💰 Assets: {len(returns_df.columns)}")
                
                # Weights and risk analysis
                with placeholder_weights:
                    st.subheader("🎯 Weights & Risk Analysis")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("### Portfolio Weights")
                        display_weight_analysis(mvrk_data)
                    
                    with col2:
                        st.markdown("### Risk Metrics")
                        display_risk_analysis(mvrk_data)
                
                # Equity curves
                with placeholder_equity:
                    st.subheader("📈 Equity Curves")
                    
                    if mvrk_data and "eq_kelly" in mvrk_data and "eq_mvrk" in mvrk_data:
                        eq_kelly = pd.Series(mvrk_data["eq_kelly"])
                        eq_mvrk = pd.Series(mvrk_data["eq_mvrk"])
                        fig_eq = create_equity_chart(eq_kelly, eq_mvrk)
                        st.plotly_chart(fig_eq, use_container_width=True)
                    else:
                        st.warning("Equity data not available")
                
                # Performance metrics
                with placeholder_performance:
                    st.subheader("📊 Performance Comparison")
                    
                    fig_perf = create_performance_metrics(mvrk_data)
                    if fig_perf.data:
                        st.plotly_chart(fig_perf, use_container_width=True)
                    else:
                        st.warning("Performance metrics not available")
                
                # Risk analysis summary
                with placeholder_risk:
                    st.subheader("🛡️ Risk Analysis Summary")
                    
                    if mvrk_data:
                        ruin_kelly = mvrk_data.get("ruin_kelly", 0)
                        ruin_mvrk = mvrk_data.get("ruin_mvrk", 0)
                        
                        if ruin_kelly > 0 and ruin_mvrk > 0:
                            if ruin_mvrk < ruin_kelly:
                                st.success(f"✅ MVRK reduces risk of ruin from {ruin_kelly:.1%} to {ruin_mvrk:.1%}")
                            else:
                                st.warning(f"⚠️ MVRK increases risk of ruin from {ruin_kelly:.1%} to {ruin_mvrk:.1%}")
                
                # Correlation heatmap
                with placeholder_corr:
                    st.subheader("🔗 Asset Correlation")
                    
                    if not returns_df.empty:
                        fig_corr = create_correlation_heatmap(returns_df)
                        st.plotly_chart(fig_corr, use_container_width=True)
                    else:
                        st.warning("Returns data not available for correlation analysis")
                
                if not auto_refresh:
                    break
                    
                time.sleep(refresh_sec)
                
            except Exception as e:
                st.error(f"Error updating dashboard: {e}")
                time.sleep(refresh_sec)
                
    else:
        # Manual refresh mode
        if st.button("🔄 Refresh Data"):
            try:
                mvrk_data = fetch_mvrk()
                returns_df = fetch_returns()
                events_data = fetch_events()
                
                st.success("Data refreshed successfully!")
                
                # Display all components once
                display_weight_analysis(mvrk_data)
                display_risk_analysis(mvrk_data)
                
                if mvrk_data and "eq_kelly" in mvrk_data and "eq_mvrk" in mvrk_data:
                    eq_kelly = pd.Series(mvrk_data["eq_kelly"])
                    eq_mvrk = pd.Series(mvrk_data["eq_mvrk"])
                    fig_eq = create_equity_chart(eq_kelly, eq_mvrk)
                    st.plotly_chart(fig_eq, use_container_width=True)
                
                if not returns_df.empty:
                    fig_corr = create_correlation_heatmap(returns_df)
                    st.plotly_chart(fig_corr, use_container_width=True)
                
            except Exception as e:
                st.error(f"Error refreshing data: {e}")

if __name__ == "__main__":
    main()
