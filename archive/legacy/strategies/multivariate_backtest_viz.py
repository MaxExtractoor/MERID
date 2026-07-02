"""
Multivariate Event Backtest Visualization

Plot BTC/ETH Kalshi strategy PnLs and portfolio equity using Plotly.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional
import numpy as np

def plot_multivariate_backtest(btc_eq: pd.Series, 
                              eth_eq: pd.Series, 
                              port_eq: pd.Series,
                              title: str = "Kalshi BTC/ETH Strategies – Multivariate Equity Curves",
                              show_individual: bool = True,
                              show_portfolio: bool = True) -> go.Figure:
    """
    Plot multivariate backtest results with BTC/ETH individual strategies and portfolio.
    
    Args:
        btc_eq: BTC strategy equity curve
        eth_eq: ETH strategy equity curve
        port_eq: Portfolio equity curve (Kelly/MVRK)
        title: Chart title
        show_individual: Whether to show individual strategy curves
        show_portfolio: Whether to show portfolio curve
        
    Returns:
        Plotly figure object
    """
    fig = go.Figure()
    
    # Add individual strategy curves
    if show_individual:
        fig.add_trace(go.Scatter(
            x=btc_eq.index,
            y=btc_eq.values,
            name="BTC Strategy",
            line=dict(color="orange", width=2),
            hovertemplate="BTC: %{y:.3f}<extra></extra>"
        ))
        
        fig.add_trace(go.Scatter(
            x=eth_eq.index,
            y=eth_eq.values,
            name="ETH Strategy",
            line=dict(color="purple", width=2),
            hovertemplate="ETH: %{y:.3f}<extra></extra>"
        ))
    
    # Add portfolio curve
    if show_portfolio:
        fig.add_trace(go.Scatter(
            x=port_eq.index,
            y=port_eq.values,
            name="Portfolio (Kelly/MVRK)",
            line=dict(color="blue", width=3),
            hovertemplate="Portfolio: %{y:.3f}<extra></extra>"
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Time / Trade #",
        yaxis_title="Equity (normalized)",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
        hovermode="x unified",
        template="plotly_white"
    )
    
    return fig

def plot_multivariate_performance(btc_eq: pd.Series,
                                  eth_eq: pd.Series,
                                  port_eq: pd.Series,
                                  btc_returns: pd.Series = None,
                                  eth_returns: pd.Series = None,
                                  port_returns: pd.Series = None) -> go.Figure:
    """
    Create comprehensive multivariate performance visualization with multiple subplots.
    
    Args:
        btc_eq: BTC strategy equity curve
        eth_eq: ETH strategy equity curve
        port_eq: Portfolio equity curve
        btc_returns: BTC strategy returns (optional)
        eth_returns: ETH strategy returns (optional)
        port_returns: Portfolio returns (optional)
        
    Returns:
        Plotly figure with subplots
    """
    # Create subplots
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=("BTC Equity", "ETH Equity", "Portfolio Equity", 
                      "BTC Returns", "ETH Returns", "Portfolio Returns"),
        vertical_spacing=0.08,
        horizontal_spacing=0.05
    )
    
    # Equity curves (top row)
    fig.add_trace(go.Scatter(
        x=btc_eq.index, y=btc_eq.values,
        name="BTC Strategy",
        line=dict(color="orange", width=2)
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(
        x=eth_eq.index, y=eth_eq.values,
        name="ETH Strategy",
        line=dict(color="purple", width=2),
        showlegend=False
    ), row=1, col=2)
    
    fig.add_trace(go.Scatter(
        x=port_eq.index, y=port_eq.values,
        name="Portfolio",
        line=dict(color="blue", width=3),
        showlegend=False
    ), row=2, col=1)
    
    # Return series (middle row)
    if btc_returns is not None:
        fig.add_trace(go.Scatter(
            x=btc_returns.index, y=btc_returns.values,
            name="BTC Returns",
            line=dict(color="orange", width=1),
            showlegend=False
        ), row=2, col=2)
    
    if eth_returns is not None:
        fig.add_trace(go.Scatter(
            x=eth_returns.index, y=eth_returns.values,
            name="ETH Returns",
            line=dict(color="purple", width=1),
            showlegend=False
        ), row=3, col=1)
    
    if port_returns is not None:
        fig.add_trace(go.Scatter(
            x=port_returns.index, y=port_returns.values,
            name="Portfolio Returns",
            line=dict(color="blue", width=1),
            showlegend=False
        ), row=3, col=2)
    
    fig.update_layout(
        title="Kalshi BTC/ETH Strategies – Comprehensive Performance",
        height=800,
        template="plotly_white",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)")
    )
    
    return fig

def plot_drawdown_analysis(btc_eq: pd.Series,
                           eth_eq: pd.Series,
                           port_eq: pd.Series) -> go.Figure:
    """
    Plot drawdown analysis for all strategies.
    
    Args:
        btc_eq: BTC strategy equity curve
        eth_eq: ETH strategy equity curve
        port_eq: Portfolio equity curve
        
    Returns:
        Plotly figure with drawdown analysis
    """
    def calculate_drawdown(equity):
        peak = equity.cummax()
        drawdown = (equity - peak) / peak.replace(0, np.nan)
        return drawdown
    
    # Calculate drawdowns
    btc_dd = calculate_drawdown(btc_eq)
    eth_dd = calculate_drawdown(eth_eq)
    port_dd = calculate_drawdown(port_eq)
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=btc_dd.index, y=btc_dd.values,
        name="BTC Drawdown",
        line=dict(color="orange", width=2),
        fill='tonexty', fillcolor='rgba(255,165,0,0.2)'
    ))
    
    fig.add_trace(go.Scatter(
        x=eth_dd.index, y=eth_dd.values,
        name="ETH Drawdown",
        line=dict(color="purple", width=2),
        fill='tonexty', fillcolor='rgba(128,0,128,0.2)'
    ))
    
    fig.add_trace(go.Scatter(
        x=port_dd.index, y=port_dd.values,
        name="Portfolio Drawdown",
        line=dict(color="blue", width=3),
        fill='tonexty', fillcolor='rgba(0,0,255,0.2)'
    ))
    
    fig.update_layout(
        title="Kalshi BTC/ETH Strategies – Drawdown Analysis",
        xaxis_title="Time / Trade #",
        yaxis_title="Drawdown",
        yaxis_tickformat=".1%",
        template="plotly_white",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)")
    )
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="black", opacity=0.5)
    
    return fig

def plot_correlation_heatmap(btc_returns: pd.Series,
                           eth_returns: pd.Series,
                           port_returns: pd.Series) -> go.Figure:
    """
    Plot correlation heatmap between strategies.
    
    Args:
        btc_returns: BTC strategy returns
        eth_returns: ETH strategy returns
        port_returns: Portfolio returns
        
    Returns:
        Plotly figure with correlation heatmap
    """
    # Create correlation matrix
    returns_df = pd.DataFrame({
        'BTC': btc_returns,
        'ETH': eth_returns,
        'Portfolio': port_returns
    })
    
    corr_matrix = returns_df.corr()
    
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.columns,
        colorscale='RdBu',
        zmid=0,
        text=corr_matrix.round(3).values,
        texttemplate="%{text}",
        textfont={"size": 12},
        hoverongaps=False
    ))
    
    fig.update_layout(
        title="Strategy Correlation Heatmap",
        template="plotly_white"
    )
    
    return fig

def plot_performance_comparison(metrics: Dict[str, Dict[str, float]]) -> go.Figure:
    """
    Plot performance comparison bar chart.
    
    Args:
        metrics: Dictionary of performance metrics by strategy
        
    Returns:
        Plotly figure with performance comparison
    """
    strategies = list(metrics.keys())
    
    # Extract key metrics
    total_returns = [metrics[s].get('total_return', 0) for s in strategies]
    sharpe_ratios = [metrics[s].get('sharpe_ratio', 0) for s in strategies]
    max_drawdowns = [metrics[s].get('max_drawdown', 0) for s in strategies]
    
    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=("Total Return", "Sharpe Ratio", "Max Drawdown"),
        specs=[[{"type": "bar"}, {"type": "bar"}, {"type": "bar"}]]
    )
    
    colors = ['orange', 'purple', 'blue'][:len(strategies)]
    
    # Total return
    fig.add_trace(go.Bar(
        x=strategies,
        y=total_returns,
        name="Total Return",
        marker_color=colors,
        text=[f"{r:.1%}" for r in total_returns],
        textposition='auto'
    ), row=1, col=1)
    
    # Sharpe ratio
    fig.add_trace(go.Bar(
        x=strategies,
        y=sharpe_ratios,
        name="Sharpe Ratio",
        marker_color=colors,
        text=[f"{s:.2f}" for s in sharpe_ratios],
        textposition='auto',
        showlegend=False
    ), row=1, col=2)
    
    # Max drawdown
    fig.add_trace(go.Bar(
        x=strategies,
        y=[abs(dd) for dd in max_drawdowns],
        name="Max Drawdown",
        marker_color=colors,
        text=[f"{abs(dd):.1%}" for dd in max_drawdowns],
        textposition='auto',
        showlegend=False
    ), row=1, col=3)
    
    fig.update_layout(
        title="Strategy Performance Comparison",
        template="plotly_white",
        showlegend=False
    )
    
    # Format y-axes
    fig.update_yaxes(tickformat=".1%", row=1, col=1)
    fig.update_yaxes(tickformat=".2f", row=1, col=2)
    fig.update_yaxes(tickformat=".1%", row=1, col=3)
    
    return fig

def create_streamlit_dashboard(btc_eq: pd.Series,
                              eth_eq: pd.Series,
                              port_eq: pd.Series,
                              btc_returns: pd.Series = None,
                              eth_returns: pd.Series = None,
                              port_returns: pd.Series = None,
                              metrics: Dict[str, Dict[str, float]] = None):
    """
    Create Streamlit dashboard with all visualizations.
    
    Args:
        btc_eq: BTC strategy equity curve
        eth_eq: ETH strategy equity curve
        port_eq: Portfolio equity curve
        btc_returns: BTC strategy returns (optional)
        eth_returns: ETH strategy returns (optional)
        port_returns: Portfolio returns (optional)
        metrics: Performance metrics dictionary (optional)
    """
    import streamlit as st
    
    st.title("Kalshi BTC/ETH Multivariate Strategy Dashboard")
    
    # Main equity curves
    st.subheader("Equity Curves")
    fig_equity = plot_multivariate_backtest(btc_eq, eth_eq, port_eq)
    st.plotly_chart(fig_equity, use_container_width=True)
    
    # Performance comparison
    if metrics:
        st.subheader("Performance Comparison")
        fig_comparison = plot_performance_comparison(metrics)
        st.plotly_chart(fig_comparison, use_container_width=True)
    
    # Drawdown analysis
    st.subheader("Drawdown Analysis")
    fig_drawdown = plot_drawdown_analysis(btc_eq, eth_eq, port_eq)
    st.plotly_chart(fig_drawdown, use_container_width=True)
    
    # Correlation heatmap (if returns provided)
    if all(r is not None for r in [btc_returns, eth_returns, port_returns]):
        st.subheader("Strategy Correlation")
        fig_corr = plot_correlation_heatmap(btc_returns, eth_returns, port_returns)
        st.plotly_chart(fig_corr, use_container_width=True)
    
    # Detailed performance
    if btc_returns is not None and eth_returns is not None and port_returns is not None:
        st.subheader("Detailed Performance")
        fig_detailed = plot_multivariate_performance(
            btc_eq, eth_eq, port_eq, btc_returns, eth_returns, port_returns
        )
        st.plotly_chart(fig_detailed, use_container_width=True)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample equity curves
np.random.seed(42)
n_trades = 200

# Create sample equity curves
dates = pd.date_range('2023-01-01', periods=n_trades, freq='15min')

btc_returns = pd.Series(np.random.normal(0.001, 0.02, n_trades), index=dates)
eth_returns = pd.Series(np.random.normal(0.0015, 0.025, n_trades), index=dates)

btc_eq = (1 + btc_returns).cumprod()
eth_eq = (1 + eth_returns).cumprod()

# Portfolio equity (weighted combination)
port_returns = 0.6 * btc_returns + 0.4 * eth_returns
port_eq = (1 + port_returns).cumprod()

# Create visualizations
fig1 = plot_multivariate_backtest(btc_eq, eth_eq, port_eq)
fig1.show()

fig2 = plot_drawdown_analysis(btc_eq, eth_eq, port_eq)
fig2.show()

fig3 = plot_correlation_heatmap(btc_returns, eth_returns, port_returns)
fig3.show()

# Performance metrics
metrics = {
    'BTC': {'total_return': 0.15, 'sharpe_ratio': 1.2, 'max_drawdown': -0.08},
    'ETH': {'total_return': 0.18, 'sharpe_ratio': 1.4, 'max_drawdown': -0.12},
    'Portfolio': {'total_return': 0.16, 'sharpe_ratio': 1.5, 'max_drawdown': -0.06}
}

fig4 = plot_performance_comparison(metrics)
fig4.show()

# Streamlit dashboard
# create_streamlit_dashboard(btc_eq, eth_eq, port_eq, btc_returns, eth_returns, port_returns, metrics)
"""
