"""
Strategy Dashboard Extensions - Enhanced Monitoring for 15m Crypto Strategy

This extends the existing Streamlit dashboard with strategy-specific monitoring,
including performance metrics, active positions, and signal analysis.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
import time
import requests
import os

# Import strategy components
try:
    from merid.strategies.strategy_integration import strategy_manager
    from merid.strategies.crypto_15m_strategy import SignalType, TradeStatus
    STRATEGY_AVAILABLE = True
except ImportError:
    STRATEGY_AVAILABLE = False
    print("Strategy components not available - using mock data")

# Configuration
API_BASE = os.getenv("KALSHI_API_BASE", "http://localhost:8000")

def fetch_strategy_data():
    """Fetch strategy data from the strategy manager."""
    if not STRATEGY_AVAILABLE:
        return get_mock_strategy_data()
    
    try:
        return strategy_manager.get_strategy_report()
    except Exception as e:
        st.error(f"Failed to fetch strategy data: {e}")
        return get_mock_strategy_data()

def fetch_performance_data():
    """Fetch performance metrics."""
    if not STRATEGY_AVAILABLE:
        return get_mock_performance_data()
    
    try:
        return strategy_manager.get_performance_metrics()
    except Exception as e:
        st.error(f"Failed to fetch performance data: {e}")
        return get_mock_performance_data()

def fetch_active_positions():
    """Fetch active positions."""
    if not STRATEGY_AVAILABLE:
        return get_mock_positions()
    
    try:
        return strategy_manager.get_active_positions()
    except Exception as e:
        st.error(f"Failed to fetch positions: {e}")
        return get_mock_positions()

def fetch_recent_signals():
    """Fetch recent signals."""
    if not STRATEGY_AVAILABLE:
        return get_mock_signals()
    
    try:
        return strategy_manager.get_recent_signals(20)
    except Exception as e:
        st.error(f"Failed to fetch signals: {e}")
        return get_mock_signals()

def get_mock_strategy_data():
    """Mock strategy data for testing."""
    return {
        "timestamp": time.time(),
        "strategy_status": {
            "active_trades": 3,
            "total_trades": 25,
            "win_rate": 0.68,
            "total_pnl": 1250.50,
            "current_positions": {"KXBTC15M-25MAR26": 50, "KXETH15M-25MAR26": -25}
        },
        "daily_stats": {
            "signals": 8,
            "trades": 3,
            "pnl": 125.50,
            "errors": 0
        },
        "running": True
    }

def get_mock_performance_data():
    """Mock performance data for testing."""
    return {
        "total_trades": 25,
        "win_rate": 0.68,
        "total_pnl": 1250.50,
        "total_fees": 45.20,
        "net_pnl": 1205.30,
        "max_drawdown": -325.00,
        "sharpe_ratio": 1.85,
        "avg_trade_duration": 7200,  # 2 hours in seconds
        "current_positions": {"KXBTC15M-25MAR26": 50, "KXETH15M-25MAR26": -25},
        "daily_stats": {
            "signals": 8,
            "trades": 3,
            "pnl": 125.50,
            "errors": 0
        }
    }

def get_mock_positions():
    """Mock active positions for testing."""
    return [
        {
            "trade_id": "trade_1709841234_KXBTC15",
            "ticker": "KXBTC15M-25MAR26",
            "signal_type": "momentum_long",
            "status": "filled",
            "filled_quantity": 50,
            "filled_price": 45200,
            "entry_time": time.time() - 3600,
            "entry_price": 45000,
            "target_price": 46500,
            "stop_loss": 44100,
            "current_pnl": 1000.0,
            "duration": 3600
        },
        {
            "trade_id": "trade_1709841235_KXETH15",
            "ticker": "KXETH15M-25MAR26",
            "signal_type": "mean_reversion_short",
            "status": "filled",
            "filled_quantity": 25,
            "filled_price": 2980,
            "entry_time": time.time() - 1800,
            "entry_price": 3000,
            "target_price": 2850,
            "stop_loss": 3060,
            "current_pnl": 250.0,
            "duration": 1800
        },
        {
            "trade_id": "trade_1709841236_KXBTC15_2",
            "ticker": "KXBTC15M-25MAR26",
            "signal_type": "momentum_short",
            "status": "pending",
            "filled_quantity": 0,
            "filled_price": 0,
            "entry_time": time.time() - 300,
            "entry_price": 44800,
            "target_price": 43500,
            "stop_loss": 45700,
            "current_pnl": 0.0,
            "duration": 300
        }
    ]

def get_mock_signals():
    """Mock recent signals for testing."""
    return [
        {
            "signal_type": "momentum_long",
            "ticker": "KXBTC15M-25MAR26",
            "confidence": 0.78,
            "entry_price": 45200,
            "target_price": 46500,
            "stop_loss": 44100,
            "position_size": 50,
            "timestamp": time.time() - 900,
            "reasoning": "Strong momentum with low volatility",
            "expected_return": 0.028,
            "risk_reward_ratio": 2.8
        },
        {
            "signal_type": "mean_reversion_short",
            "ticker": "KXETH15M-25MAR26",
            "confidence": 0.72,
            "entry_price": 2980,
            "target_price": 2850,
            "stop_loss": 3060,
            "position_size": 30,
            "timestamp": time.time() - 600,
            "reasoning": "Price deviated 2.5% from mean",
            "expected_return": 0.043,
            "risk_reward_ratio": 2.15
        }
    ]

def create_performance_chart(performance_data):
    """Create performance visualization."""
    if not performance_data:
        return None
    
    # Create metrics display
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Total Trades", performance_data.get("total_trades", 0))
    
    with col2:
        win_rate = performance_data.get("win_rate", 0)
        st.metric("🎯 Win Rate", f"{win_rate:.1%}")
    
    with col3:
        net_pnl = performance_data.get("net_pnl", 0)
        st.metric("💰 Net PnL", f"${net_pnl:,.2f}")
    
    with col4:
        sharpe = performance_data.get("sharpe_ratio", 0)
        st.metric("📈 Sharpe Ratio", f"{sharpe:.2f}")
    
    # Create PnL chart (mock historical data)
    dates = pd.date_range(end=datetime.now(), periods=30, freq='D')
    pnl_data = pd.DataFrame({
        'Date': dates,
        'Cumulative PnL': [i * 50 + (i % 5 - 2) * 100 for i in range(30)],
        'Daily PnL': [50 + (i % 5 - 2) * 100 for i in range(30)]
    })
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pnl_data['Date'],
        y=pnl_data['Cumulative PnL'],
        mode='lines',
        name='Cumulative PnL',
        line=dict(color='green', width=2)
    ))
    
    fig.update_layout(
        title="📈 Cumulative PnL (Last 30 Days)",
        xaxis_title="Date",
        yaxis_title="PnL ($)",
        height=400
    )
    
    st.plotly_chart(fig, use_container_width=True)

def create_positions_table(positions):
    """Create active positions table."""
    if not positions:
        st.info("No active positions")
        return
    
    df = pd.DataFrame(positions)
    
    # Format columns for display
    df['entry_time'] = pd.to_datetime(df['entry_time'], unit='s').dt.strftime('%H:%M:%S')
    df['duration'] = df['duration'].apply(lambda x: f"{int(x//3600)}h {int((x%3600)//60)}m" if x > 0 else "0m")
    df['current_pnl'] = df['current_pnl'].apply(lambda x: f"${x:.2f}")
    df['filled_price'] = df['filled_price'].apply(lambda x: f"${x:,.0f}" if x > 0 else "Pending")
    
    # Select and rename columns
    display_df = df[[
        'ticker', 'signal_type', 'status', 'filled_quantity', 
        'filled_price', 'current_pnl', 'duration', 'entry_time'
    ]].copy()
    
    display_df.columns = [
        'Ticker', 'Signal', 'Status', 'Qty', 'Entry Price', 
        'PnL', 'Duration', 'Entry Time'
    ]
    
    # Color code PnL
    st.dataframe(display_df, use_container_width=True)

def create_signals_analysis(signals):
    """Create signals analysis section."""
    if not signals:
        st.info("No recent signals")
        return
    
    df = pd.DataFrame(signals)
    
    # Signal distribution
    col1, col2 = st.columns(2)
    
    with col1:
        signal_counts = df['signal_type'].value_counts()
        st.bar_chart(signal_counts, title="Signal Types")
    
    with col2:
        confidence_dist = df['confidence'].describe()
        st.metric("Avg Confidence", f"{confidence_dist['mean']:.2f}")
        st.metric("Max Confidence", f"{confidence_dist['max']:.2f}")
    
    # Recent signals table
    st.subheader("📋 Recent Signals")
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s').dt.strftime('%H:%M:%S')
    df['confidence'] = df['confidence'].apply(lambda x: f"{x:.2f}")
    df['expected_return'] = df['expected_return'].apply(lambda x: f"{x:.1%}")
    df['risk_reward_ratio'] = df['risk_reward_ratio'].apply(lambda x: f"{x:.1f}")
    
    display_df = df[[
        'timestamp', 'ticker', 'signal_type', 'confidence', 
        'expected_return', 'risk_reward_ratio', 'reasoning'
    ]].copy()
    
    display_df.columns = [
        'Time', 'Ticker', 'Signal', 'Conf', 'Exp Return', 'R/R', 'Reasoning'
    ]
    
    st.dataframe(display_df, use_container_width=True)

def create_strategy_controls():
    """Create strategy control panel."""
    st.subheader("🎛️ Strategy Controls")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Run Manual Cycle", type="primary"):
            if STRATEGY_AVAILABLE:
                try:
                    strategy_manager.run_manual_cycle()
                    st.success("Manual cycle completed")
                except Exception as e:
                    st.error(f"Error running cycle: {e}")
            else:
                st.warning("Strategy not available")
    
    with col2:
        if st.button("📊 Get Report"):
            report = fetch_strategy_data()
            st.json(report)
    
    with col3:
        if st.button("🔄 Reset Daily Stats"):
            if STRATEGY_AVAILABLE:
                try:
                    strategy_manager.reset_daily_stats()
                    st.success("Daily stats reset")
                except Exception as e:
                    st.error(f"Error resetting stats: {e}")
            else:
                st.warning("Strategy not available")

def main():
    """Main strategy dashboard function."""
    st.set_page_config(
        page_title="15M Crypto Strategy Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("📊 15M Crypto Strategy Dashboard")
    st.markdown("Real-time monitoring of the 15-minute crypto trading strategy")
    
    # Sidebar controls
    st.sidebar.header("⚙️ Strategy Settings")
    
    auto_refresh = st.sidebar.checkbox("🔄 Auto Refresh", value=True)
    refresh_interval = st.sidebar.slider("Refresh Interval (seconds)", 5, 60, 10)
    
    # Strategy status
    st.sidebar.header("📈 Strategy Status")
    
    strategy_data = fetch_strategy_data()
    status = strategy_data.get("strategy_status", {})
    
    st.sidebar.metric("🔄 Active Trades", status.get("active_trades", 0))
    st.sidebar.metric("📊 Total Trades", status.get("total_trades", 0))
    st.sidebar.metric("🎯 Win Rate", f"{status.get('win_rate', 0):.1%}")
    st.sidebar.metric("💰 Total PnL", f"${status.get('total_pnl', 0):,.2f}")
    
    st.sidebar.markdown("**Running:**" + (" ✅" if strategy_data.get("running") else " ❌"))
    
    # Auto refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
    
    # Main content
    st.header("📈 Performance Overview")
    
    performance_data = fetch_performance_data()
    create_performance_chart(performance_data)
    
    # Strategy controls
    create_strategy_controls()
    
    # Two column layout for positions and signals
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("💼 Active Positions")
        positions = fetch_active_positions()
        create_positions_table(positions)
    
    with col2:
        st.header("📋 Signal Analysis")
        signals = fetch_recent_signals()
        create_signals_analysis(signals)
    
    # Daily statistics
    st.header("📊 Daily Statistics")
    
    daily_stats = strategy_data.get("daily_stats", {})
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Signals", daily_stats.get("signals", 0))
    
    with col2:
        st.metric("💼 Trades", daily_stats.get("trades", 0))
    
    with col3:
        st.metric("💰 PnL", f"${daily_stats.get('pnl', 0):,.2f}")
    
    with col4:
        st.metric("❌ Errors", daily_stats.get("errors", 0))
    
    # Footer
    st.markdown("---")
    st.markdown("📊 **15M Crypto Strategy Dashboard** - Real-time strategy monitoring")
    st.markdown(f"🔄 Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

if __name__ == "__main__":
    main()
