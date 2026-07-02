"""
Streamlit Components for Real-Time Kalshi Market Charts

Real-time OHLC charts with auto-refresh and live market monitoring.
"""

import os
import time
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Configuration
API_BASE = os.getenv("KALSHI_API_BASE", f"http://localhost:{os.getenv('MERID_PORT', '8011')}")

# Page configuration
st.set_page_config(
    page_title="Kalshi Live Markets", 
    layout="wide",
    page_icon="📈"
)

def fetch_live_ohlc(ticker: str, limit: int = 1000) -> pd.DataFrame:
    """
    Fetch live OHLC data from FastAPI backend.
    
    Args:
        ticker: Market ticker identifier
        limit: Maximum number of data points to fetch
        
    Returns:
        DataFrame with OHLC data
    """
    try:
        r = requests.get(f"{API_BASE}/kalshi/ohlc/{ticker}", params={"limit": limit}, timeout=5)
        r.raise_for_status()
        data = r.json()
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Convert timestamp
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df = df.set_index("ts")
        
        # Convert numeric columns
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching OHLC data for {ticker}: {e}")
        raise

def create_candlestick_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """
    Create candlestick chart from OHLC data.
    
    Args:
        df: DataFrame with OHLC data
        ticker: Market ticker for title
        
    Returns:
        Plotly figure with candlestick chart
    """
    if df.empty or "open" not in df.columns:
        return go.Figure()
    
    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Yes Price",
        increasing_line_color="green",
        decreasing_line_color="red"
    )])
    
    fig.update_layout(
        title=f"{ticker} - Live Price Chart",
        yaxis_title="Price (USD)",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=600
    )
    
    return fig

def create_volume_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """
    Create volume chart from OHLC data.
    
    Args:
        df: DataFrame with OHLC data
        ticker: Market ticker for title
        
    Returns:
        Plotly figure with volume chart
    """
    if df.empty or "volume" not in df.columns:
        return go.Figure()
    
    fig = go.Figure(data=[go.Bar(
        x=df.index,
        y=df["volume"],
        name="Volume",
        marker_color="lightblue"
    )])
    
    fig.update_layout(
        title=f"{ticker} - Volume",
        yaxis_title="Volume",
        template="plotly_white",
        height=300
    )
    
    return fig

def create_price_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate price statistics from OHLC data.
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        Dictionary with price statistics
    """
    if df.empty:
        return {}
    
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    
    stats = {
        "current_price": latest["close"],
        "price_change": latest["close"] - previous["close"],
        "price_change_pct": (latest["close"] - previous["close"]) / previous["close"] * 100 if previous["close"] != 0 else 0.0,
        "high_24h": df["high"].max(),
        "low_24h": df["low"].min(),
        "volume_24h": df["volume"].sum(),
        "volatility": (df["high"] - df["low"]).mean() / latest["close"] * 100 if latest["close"] != 0 else 0.0
    }
    
    return stats

def display_market_overview(ticker: str, stats: Dict[str, Any]):
    """
    Display market overview statistics.
    
    Args:
        ticker: Market ticker
        stats: Price statistics dictionary
    """
    if not stats:
        st.warning("No market data available")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Current Price",
            f"${stats['current_price']:.4f}",
            f"{stats['price_change_pct']:+.2f}%" if stats['price_change_pct'] != 0 else "0.00%"
        )
    
    with col2:
        st.metric(
            "24h High",
            f"${stats['high_24h']:.4f}"
        )
    
    with col3:
        st.metric(
            "24h Low",
            f"${stats['low_24h']:.4f}"
        )
    
    with col4:
        st.metric(
            "24h Volume",
            f"{stats['volume_24h']:,.0f}"
        )

def create_multi_chart_dashboard(df: pd.DataFrame, ticker: str) -> go.Figure:
    """
    Create comprehensive dashboard with multiple charts.
    
    Args:
        df: DataFrame with OHLC data
        ticker: Market ticker
        
    Returns:
        Plotly figure with subplots
    """
    if df.empty:
        return go.Figure()
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=("Price Chart", "Volume"),
        row_heights=[0.7, 0.3]
    )
    
    # Candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Yes Price",
            increasing_line_color="green",
            decreasing_line_color="red"
        ),
        row=1, col=1
    )
    
    # Volume chart
    if "volume" in df.columns:
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["volume"],
                name="Volume",
                marker_color="lightblue",
                yaxis="y2"
            ),
            row=2, col=1
        )
        
        # Add secondary y-axis for volume
        fig.update_layout(
            yaxis2=dict(
                title="Volume",
                overlaying="y",
                side="right",
                showgrid=False
            )
        )
    
    fig.update_layout(
        title=f"{ticker} - Live Market Dashboard",
        template="plotly_white",
        height=800,
        xaxis_rangeslider_visible=False
    )
    
    return fig

def monitor_market_health(ticker: str, df: pd.DataFrame) -> Dict[str, Any]:
    """
    Monitor market health and detect anomalies.
    
    Args:
        ticker: Market ticker
        df: DataFrame with OHLC data
        
    Returns:
        Health monitoring results
    """
    if df.empty or len(df) < 10:
        return {"status": "insufficient_data", "warnings": []}
    
    health = {
        "status": "healthy",
        "warnings": [],
        "metrics": {}
    }
    
    # Check for price gaps
    price_changes = df["close"].pct_change()
    large_gaps = price_changes[abs(price_changes) > 0.05]  # 5% gaps
    
    if len(large_gaps) > 0:
        health["warnings"].append(f"{len(large_gaps)} large price gaps detected")
        health["status"] = "warning"
    
    # Check for unusual volatility
    volatility = (df["high"] - df["low"]).mean() / df["close"].mean()
    if volatility > 0.1:  # 10% average range
        health["warnings"].append(f"High volatility: {volatility:.1%}")
        health["status"] = "warning"
    
    # Check for stale data
    latest_time = df.index[-1]
    age_minutes = (pd.Timestamp.now(tz="UTC") - latest_time).total_seconds() / 60
    
    if age_minutes > 5:  # 5 minutes old
        health["warnings"].append(f"Data is {age_minutes:.1f} minutes old")
        health["status"] = "warning"
    
    health["metrics"] = {
        "volatility": volatility,
        "data_age_minutes": age_minutes,
        "large_gaps_count": len(large_gaps),
        "total_periods": len(df)
    }
    
    return health

def main():
    """Main Streamlit application."""
    st.title("🚀 Kalshi Crypto – Live Markets")
    st.markdown("Real-time market monitoring with live OHLC charts and analytics")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Market selection
        available_markets = [
            "KXBTC15M-EXAMPLE",
            "KXETH15M-EXAMPLE",
            "KXLTC15M-EXAMPLE",
            "KXADA15M-EXAMPLE"
        ]
        
        market = st.selectbox("Market Ticker", available_markets, index=0)
        
        # Refresh settings
        auto_refresh = st.checkbox("Auto Refresh", value=True)
        refresh_sec = st.slider("Refresh Interval (seconds)", 1, 30, 5)
        
        # Data settings
        data_points = st.slider("Data Points", 100, 1000, 500)
        
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
    
    # Main content area
    if auto_refresh:
        # Create placeholders for dynamic content
        placeholder_overview = st.empty()
        placeholder_charts = st.empty()
        placeholder_health = st.empty()
        
        while True:
            try:
                # Fetch live data
                df = fetch_live_ohlc(market, limit=data_points)
                
                if df.empty:
                    st.error(f"No data available for {market}")
                    break
                
                # Calculate statistics
                stats = create_price_stats(df)
                
                # Market overview
                with placeholder_overview:
                    st.subheader(f"📊 Market Overview: {market}")
                    display_market_overview(market, stats)
                
                # Health monitoring
                health = monitor_market_health(market, df)
                with placeholder_health:
                    if health["status"] == "healthy":
                        st.success("🟢 Market Health: Healthy")
                    elif health["status"] == "warning":
                        st.warning("🟡 Market Health: Warning")
                    else:
                        st.error("🔴 Market Health: Issues Detected")
                    
                    if health["warnings"]:
                        for warning in health["warnings"]:
                            st.write(f"⚠️ {warning}")
                
                # Charts
                with placeholder_charts:
                    st.subheader(f"📈 Live Charts: {market}")
                    
                    # Chart selection
                    chart_type = st.selectbox(
                        "Chart Type",
                        ["Candlestick Only", "Volume Only", "Combined Dashboard"],
                        key=f"chart_type_{market}"
                    )
                    
                    if chart_type == "Candlestick Only":
                        fig = create_candlestick_chart(df, market)
                        st.plotly_chart(fig, use_container_width=True)
                        
                    elif chart_type == "Volume Only":
                        fig = create_volume_chart(df, market)
                        st.plotly_chart(fig, use_container_width=True)
                        
                    else:  # Combined Dashboard
                        fig = create_multi_chart_dashboard(df, market)
                        st.plotly_chart(fig, use_container_width=True)
                
                if not auto_refresh:
                    break
                    
                time.sleep(refresh_sec)
                
            except Exception as e:
                st.error(f"Error updating data: {e}")
                time.sleep(refresh_sec)
                
    else:
        # Manual refresh mode
        if st.button("🔄 Refresh Data"):
            try:
                df = fetch_live_ohlc(market, limit=data_points)
                
                if df.empty:
                    st.error(f"No data available for {market}")
                    return
                
                stats = create_price_stats(df)
                
                st.subheader(f"📊 Market Overview: {market}")
                display_market_overview(market, stats)
                
                health = monitor_market_health(market, df)
                st.subheader("🏥 Market Health")
                if health["status"] == "healthy":
                    st.success("🟢 Market Health: Healthy")
                else:
                    st.warning("🟡 Market Health: Warning")
                
                st.subheader(f"📈 Live Charts: {market}")
                fig = create_multi_chart_dashboard(df, market)
                st.plotly_chart(fig, use_container_width=True)
                
            except Exception as e:
                st.error(f"Error fetching data: {e}")

if __name__ == "__main__":
    main()
