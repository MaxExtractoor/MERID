#!/usr/bin/env python3
"""
Kalshi Event Stream Dashboard - Streamlit Visualization

Minimal dashboard to visualize Kalshi events and portfolio positions in real-time.
This provides immediate feedback on the event-driven architecture.
"""

import streamlit as st
import requests
import time
import pandas as pd
from datetime import datetime, timezone
import json
import os
from typing import Dict, List, Any

# Configuration - Use environment variable with fallback
API_BASE = os.getenv("KALSHI_API_BASE", "http://localhost:8000")  # Configurable via env var
REFRESH_INTERVAL = 2  # seconds

def fetch_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent Kalshi events from the real FastAPI endpoint."""
    try:
        response = requests.get(f"{API_BASE}/kalshi/events?limit={limit}", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch events: {e}")
        return []

def fetch_events_by_type(event_type: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch events filtered by type from the real FastAPI endpoint."""
    try:
        response = requests.get(f"{API_BASE}/kalshi/events/{event_type}?limit={limit}", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch {event_type} events: {e}")
        return []

def fetch_portfolio_positions() -> Dict[str, Any]:
    """Fetch current portfolio positions from the real FastAPI endpoint."""
    try:
        # This hits the real portfolio endpoint
        response = requests.get(f"{API_BASE}/portfolio/positions", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch positions: {e}")
        return {"positions": []}

def format_timestamp(ts: float) -> str:
    """Format timestamp for display."""
    if ts > 1e10:  # Milliseconds
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")

def get_event_emoji(event_type: str) -> str:
    """Get emoji for event type."""
    emoji_map = {
        "order_fill": "✅",
        "order_reject": "❌", 
        "rate_limiter": "⚠️",
        "order_group_trigger": "🚨",
        "api_error": "🔴",
        "position_update": "📊"
    }
    return emoji_map.get(event_type, "📋")

def create_simple_event_table(events: List[Dict[str, Any]]) -> None:
    """Create a simple table display for events (no plotly dependency)."""
    if not events:
        st.info("No events to display")
        return
    
    # Convert to DataFrame for display
    df = pd.DataFrame(events)
    df['time'] = df['ts'].apply(format_timestamp)
    df['emoji'] = df['type'].apply(get_event_emoji)
    
    # Reorder and format columns
    display_df = df[['emoji', 'type', 'time', 'payload']].copy()
    display_df.columns = ['Type', 'Event Type', 'Time', 'Payload']
    
    # Format payload for display
    display_df['Payload'] = display_df['Payload'].apply(
        lambda x: json.dumps(x, indent=2)[:100] + "..." if len(str(x)) > 100 else str(x)
    )
    
    st.dataframe(display_df, use_container_width=True)

def create_rate_limit_chart(events: List[Dict[str, Any]]) -> None:
    """Create a simple rate limiting visualization (no plotly dependency)."""
    rate_events = [e for e in events if e['type'] == 'rate_limiter']
    
    if not rate_events:
        st.info("No rate limiting events to display")
        return
    
    # Extract wait times
    wait_times = []
    timestamps = []
    for event in rate_events:
        payload = event.get('payload', {})
        if 'wait_time' in payload:
            wait_times.append(payload['wait_time'])
            timestamps.append(format_timestamp(event['ts']))
    
    if not wait_times:
        st.info("No wait time data available")
        return
    
    # Create simple chart using Streamlit
    chart_df = pd.DataFrame({
        'Time': timestamps,
        'Wait Time (s)': wait_times
    })
    
    st.line_chart(chart_df.set_index('Time'), use_container_width=True)
    st.caption("Rate limiting wait times over time")

def main():
    """Main Streamlit dashboard."""
    st.set_page_config(
        page_title="Kalshi Event Stream Dashboard",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🚀 Kalshi Event Stream Dashboard")
    st.markdown("Real-time visualization of Kalshi trading events and portfolio positions")
    
    # Show API configuration
    st.sidebar.markdown(f"**API Base:** `{API_BASE}`")
    st.sidebar.markdown(f"**Environment Variable:** `KALSHI_API_BASE`")
    
    # Sidebar controls
    st.sidebar.header("⚙️ Controls")
    
    auto_refresh = st.sidebar.checkbox("🔄 Auto Refresh", value=True)
    refresh_interval = st.sidebar.slider("Refresh Interval (seconds)", 1, 10, REFRESH_INTERVAL)
    
    # Event filters
    st.sidebar.header("📊 Event Filters")
    show_order_fills = st.sidebar.checkbox("✅ Order Fills", value=True)
    show_rate_limits = st.sidebar.checkbox("⚠️ Rate Limits", value=True)
    show_errors = st.sidebar.checkbox("🔴 API Errors", value=True)
    show_others = st.sidebar.checkbox("📋 Other Events", value=True)
    
    # Manual refresh button
    if st.sidebar.button("🔄 Refresh Now"):
        st.rerun()
    
    # Auto refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    # Track consecutive empty responses for guardrails
    if 'empty_event_count' not in st.session_state:
        st.session_state.empty_event_count = 0
        st.session_state.last_event_time = time.time()
    
    with col1:
        st.header("📈 Recent Events")
        
        # Fetch events
        with st.spinner("Fetching events..."):
            all_events = fetch_events(100)
        
        # Guardrails for empty events
        if not all_events:
            st.session_state.empty_event_count += 1
            time_since_last = time.time() - st.session_state.last_event_time
            
            if st.session_state.empty_event_count >= 3 and time_since_last > 30:
                st.warning(f"⚠️ **No events received in the last {int(time_since_last)} seconds**")
                st.markdown("""
                **Possible issues:**
                - Event bus not started
                - Engine not emitting events
                - API endpoint misconfigured
                
                **Check:**
                - FastAPI server is running
                - Event bus dispatcher started
                - Trading engine is active
                """)
            else:
                st.warning("No events available. Make sure the FastAPI server is running and events are being emitted.")
        else:
            # Reset counters on successful fetch
            st.session_state.empty_event_count = 0
            st.session_state.last_event_time = time.time()
        
        if all_events:
            # Filter events based on sidebar
            filtered_events = []
            for event in all_events:
                event_type = event['type']
                if event_type == 'order_fill' and show_order_fills:
                    filtered_events.append(event)
                elif event_type == 'rate_limiter' and show_rate_limits:
                    filtered_events.append(event)
                elif event_type == 'api_error' and show_errors:
                    filtered_events.append(event)
                elif event_type not in ['order_fill', 'rate_limiter', 'api_error'] and show_others:
                    filtered_events.append(event)
            
            # Display events table
            create_simple_event_table(filtered_events)
            
            # Rate limiting chart
            if show_rate_limits:
                st.subheader("⚠️ Rate Limiting")
                create_rate_limit_chart(all_events)
    
    with col2:
        st.header("📊 System Status")
        
        # Event statistics
        if all_events:
            st.subheader("📈 Event Statistics")
            
            # Count events by type
            event_counts = {}
            for event in all_events:
                event_type = event['type']
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            # Display counts
            for event_type, count in event_counts.items():
                emoji = get_event_emoji(event_type)
                st.metric(f"{emoji} {event_type}", count)
        
        # System health
        st.subheader("🏥 System Health")
        
        # Check API connectivity
        try:
            response = requests.get(f"{API_BASE}/health", timeout=2)
            if response.status_code == 200:
                st.success("✅ API Server: Healthy")
            else:
                st.error(f"❌ API Server: HTTP {response.status_code}")
        except:
            st.error("❌ API Server: Unreachable")
        
        # Check event bus
        try:
            events = fetch_events(1)
            if events:
                st.success("✅ Event Bus: Active")
            else:
                st.warning("⚠️ Event Bus: No events")
        except:
            st.error("❌ Event Bus: Error")
        
        # API endpoint status
        st.subheader("🔗 API Endpoints")
        
        endpoints = [
            ("/kalshi/events", "Event Stream"),
            ("/kalshi/events/order_fill", "Order Fills"),
            ("/portfolio/positions", "Portfolio")
        ]
        
        for endpoint, name in endpoints:
            try:
                response = requests.get(f"{API_BASE}{endpoint}?limit=1", timeout=2)
                if response.status_code == 200:
                    st.success(f"✅ {name}")
                else:
                    st.error(f"❌ {name} ({response.status_code})")
            except:
                st.error(f"❌ {name} (Failed)")
    
    # Portfolio section
    st.header("💼 Portfolio Positions")
    
    with st.spinner("Fetching portfolio positions..."):
        portfolio = fetch_portfolio_positions()
    
    if portfolio.get('positions'):
        positions_df = pd.DataFrame(portfolio['positions'])
        
        # Display positions table
        st.dataframe(positions_df, use_container_width=True)
        
        # Portfolio summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📊 Total Positions", len(positions_df))
        
        with col2:
            # Calculate notional (mock calculation)
            total_notional = positions_df.get('count', 0).sum() * 100  # Mock price
            st.metric("💰 Total Notional", f"${total_notional:,.0f}")
        
        with col3:
            # Count tickers
            unique_tickers = positions_df.get('ticker', pd.Series()).nunique()
            st.metric("🎯 Unique Tickers", unique_tickers)
        
        with col4:
            # Mock PnL
            st.metric("📈 Today's PnL", "+$245.67")
    else:
        st.info("No positions available or API not configured")
    
    # Footer
    st.markdown("---")
    st.markdown("🚀 **Kalshi Event Stream Dashboard** - Real-time monitoring of trading events")
    st.markdown(f"🔄 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Debug info
    with st.expander("🔍 Debug Information"):
        st.code(f"""
API Base URL: {API_BASE}
Refresh Interval: {refresh_interval}s
Auto Refresh: {auto_refresh}
Total Events Fetched: {len(all_events) if 'all_events' in locals() else 0}
        """)

if __name__ == "__main__":
    main()
