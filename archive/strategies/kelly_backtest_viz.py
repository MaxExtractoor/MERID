"""
Backtest Visualization Comparing Full vs Fractional Kelly

Professional visualization tools for comparing Kelly strategies with equity curves and drawdown analysis.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

def equity_from_pnls(pnls: List[float], f: float, initial_capital: float = 1.0) -> pd.Series:
    """
    Generate equity curve from PnL series and Kelly fraction.
    
    Args:
        pnls: List of PnL values (1.0 for win, -1.0 for loss, or actual PnL amounts)
        f: Kelly fraction to use
        initial_capital: Starting capital
        
    Returns:
        Equity curve as pandas Series
    """
    capital = initial_capital
    equity = [capital]
    
    for pnl in pnls:
        capital *= (1 + f * pnl)
        equity.append(capital)
        
        # Prevent negative capital
        if capital <= 0:
            capital = 0
            equity.extend([0] * (len(pnls) - len(equity) + 1))
            break
    
    return pd.Series(equity)

def dd_from_equity(equity: pd.Series) -> pd.Series:
    """
    Calculate drawdown series from equity curve.
    
    Args:
        equity: Equity curve as pandas Series
        
    Returns:
        Drawdown series as pandas Series
    """
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return drawdown

def calculate_performance_metrics(equity: pd.Series, pnls: List[float]) -> Dict[str, float]:
    """
    Calculate comprehensive performance metrics.
    
    Args:
        equity: Equity curve
        pnls: PnL series
        
    Returns:
        Performance metrics dictionary
    """
    if equity.empty:
        return {}
    
    # Basic return metrics
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Calculate returns
    returns = equity.pct_change().dropna()
    
    # Annualization factor (assuming daily data)
    periods_per_year = 252
    
    # Sharpe ratio
    if len(returns) > 1 and returns.std() > 0:
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(periods_per_year)
    else:
        sharpe_ratio = 0.0
    
    # Sortino ratio
    downside_returns = returns[returns < 0]
    if len(downside_returns) > 0 and downside_returns.std() > 0:
        sortino_ratio = returns.mean() / downside_returns.std() * np.sqrt(periods_per_year)
    else:
        sortino_ratio = 0.0
    
    # Max drawdown
    drawdown = dd_from_equity(equity)
    max_drawdown = drawdown.min()
    
    # Win rate
    win_rate = sum(1 for pnl in pnls if pnl > 0) / len(pnls) if pnls else 0.0
    
    # Average win and loss
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    
    # Profit factor
    total_wins = sum(wins)
    total_losses = abs(sum(losses))
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
    
    # Calmar ratio
    if max_drawdown != 0:
        calmar_ratio = total_return / abs(max_drawdown)
    else:
        calmar_ratio = 0.0
    
    # Recovery time
    peak_indices = []
    for i in range(1, len(equity)):
        if equity.iloc[i] >= equity.iloc[:i].max():
            peak_indices.append(i)
    
    avg_recovery_time = 0
    if len(peak_indices) > 1:
        recovery_times = [peak_indices[i] - peak_indices[i-1] for i in range(1, len(peak_indices))]
        avg_recovery_time = np.mean(recovery_times)
    
    return {
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "calmar_ratio": calmar_ratio,
        "avg_recovery_time": avg_recovery_time,
        "final_capital": equity.iloc[-1],
        "peak_capital": equity.max(),
        "trades": len(pnls)
    }

def plot_full_vs_fractional(pnls: List[float], 
                           f_full: float, 
                           frac: float = 0.5,
                           initial_capital: float = 1.0) -> go.Figure:
    """
    Plot equity curves comparing full vs fractional Kelly.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        frac: Fraction of full Kelly to use
        initial_capital: Starting capital
        
    Returns:
        Plotly figure with equity curves
    """
    # Calculate equity curves
    eq_full = equity_from_pnls(pnls, f_full, initial_capital)
    eq_frac = equity_from_pnls(pnls, f_full * frac, initial_capital)
    
    # Create figure
    fig = go.Figure()
    
    # Add full Kelly curve
    fig.add_trace(go.Scatter(
        x=list(range(len(eq_full))),
        y=eq_full,
        mode='lines',
        name=f"Full Kelly ({f_full:.3f})",
        line=dict(color='blue', width=2),
        hovertemplate="Full Kelly<br>Trade: %{x}<br>Capital: %{y:.4f}<extra></extra>"
    ))
    
    # Add fractional Kelly curve
    fig.add_trace(go.Scatter(
        x=list(range(len(eq_frac))),
        y=eq_frac,
        mode='lines',
        name=f"{int(frac*100)}% Kelly ({f_full*frac:.3f})",
        line=dict(color='red', width=2),
        hovertemplate=f"{int(frac*100)}% Kelly<br>Trade: %{{x}}<br>Capital: %{{y:.4f}}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=f"Equity: Full vs {int(frac*100)}% Kelly",
        xaxis_title="Trade Number",
        yaxis_title="Capital",
        template="plotly_white",
        height=600,
        legend=dict(x=0.01, y=0.99),
        hovermode="x unified"
    )
    
    return fig

def plot_dd_full_vs_fractional(pnls: List[float], 
                              f_full: float, 
                              frac: float = 0.5,
                              initial_capital: float = 1.0) -> go.Figure:
    """
    Plot drawdown curves comparing full vs fractional Kelly.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        frac: Fraction of full Kelly to use
        initial_capital: Starting capital
        
    Returns:
        Plotly figure with drawdown curves
    """
    # Calculate equity curves and drawdowns
    eq_full = equity_from_pnls(pnls, f_full, initial_capital)
    eq_frac = equity_from_pnls(pnls, f_full * frac, initial_capital)
    
    dd_full = dd_from_equity(eq_full)
    dd_frac = dd_from_equity(eq_frac)
    
    # Create figure
    fig = go.Figure()
    
    # Add full Kelly drawdown
    fig.add_trace(go.Scatter(
        x=list(range(len(dd_full))),
        y=dd_full,
        mode='lines',
        name="Full Kelly DD",
        line=dict(color='blue', width=2),
        fill='tonexty',
        fillcolor='rgba(0, 0, 255, 0.2)',
        hovertemplate="Full Kelly DD<br>Trade: %{x}<br>Drawdown: %{y:.1%}<extra></extra>"
    ))
    
    # Add fractional Kelly drawdown
    fig.add_trace(go.Scatter(
        x=list(range(len(dd_frac))),
        y=dd_frac,
        mode='lines',
        name=f"{int(frac*100)}% Kelly DD",
        line=dict(color='red', width=2),
        fill='tonexty',
        fillcolor='rgba(255, 0, 0, 0.2)',
        hovertemplate=f"{int(frac*100)}% Kelly DD<br>Trade: %{{x}}<br>Drawdown: %{{y:.1%}}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=f"Drawdown: Full vs {int(frac*100)}% Kelly",
        xaxis_title="Trade Number",
        yaxis_title="Drawdown",
        yaxis_tickformat=".1%",
        template="plotly_white",
        height=400,
        legend=dict(x=0.01, y=0.99),
        hovermode="x unified"
    )
    
    return fig

def plot_multiple_fractions(pnls: List[float], 
                           f_full: float,
                           fractions: List[float],
                           initial_capital: float = 1.0) -> go.Figure:
    """
    Plot multiple Kelly fractions for comparison.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        fractions: List of fractions to compare
        initial_capital: Starting capital
        
    Returns:
        Plotly figure with multiple equity curves
    """
    fig = go.Figure()
    
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
    
    for i, frac in enumerate(fractions):
        eq = equity_from_pnls(pnls, f_full * frac, initial_capital)
        
        fig.add_trace(go.Scatter(
            x=list(range(len(eq))),
            y=eq,
            mode='lines',
            name=f"{int(frac*100)}% Kelly ({f_full*frac:.3f})",
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate=f"{int(frac*100)}% Kelly<br>Trade: %{{x}}<br>Capital: %{{y:.4f}}<extra></extra>"
        ))
    
    fig.update_layout(
        title="Equity: Multiple Kelly Fractions",
        xaxis_title="Trade Number",
        yaxis_title="Capital",
        template="plotly_white",
        height=600,
        legend=dict(x=0.01, y=0.99),
        hovermode="x unified"
    )
    
    return fig

def create_performance_comparison_table(pnls: List[float],
                                      f_full: float,
                                      fractions: List[float],
                                      initial_capital: float = 1.0) -> pd.DataFrame:
    """
    Create performance comparison table for multiple Kelly fractions.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        fractions: List of fractions to compare
        initial_capital: Starting capital
        
    Returns:
        DataFrame with performance comparison
    """
    results = []
    
    for frac in fractions:
        eq = equity_from_pnls(pnls, f_full * frac, initial_capital)
        metrics = calculate_performance_metrics(eq, pnls)
        
        results.append({
            "Fraction": f"{int(frac*100)}%",
            "Kelly Size": f"{f_full*frac:.3f}",
            "Final Capital": f"{metrics['final_capital']:.4f}",
            "Total Return": f"{metrics['total_return']:.2%}",
            "Sharpe Ratio": f"{metrics['sharpe_ratio']:.2f}",
            "Max Drawdown": f"{metrics['max_drawdown']:.2%}",
            "Win Rate": f"{metrics['win_rate']:.2%}",
            "Profit Factor": f"{metrics['profit_factor']:.2f}",
            "Calmar Ratio": f"{metrics['calmar_ratio']:.2f}"
        })
    
    return pd.DataFrame(results)

def create_risk_reward_scatter(pnls: List[float],
                               f_full: float,
                               fractions: List[float],
                               initial_capital: float = 1.0) -> go.Figure:
    """
    Create risk-reward scatter plot for Kelly fractions.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        fractions: List of fractions to compare
        initial_capital: Starting capital
        
    Returns:
        Plotly figure with risk-reward scatter
    """
    returns = []
    drawdowns = []
    labels = []
    
    for frac in fractions:
        eq = equity_from_pnls(pnls, f_full * frac, initial_capital)
        dd = dd_from_equity(eq)
        
        total_return = (eq.iloc[-1] / eq.iloc[0]) - 1
        max_dd = dd.min()
        
        returns.append(total_return)
        drawdowns.append(abs(max_dd))
        labels.append(f"{int(frac*100)}%")
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=drawdowns,
        y=returns,
        mode='markers+text',
        text=labels,
        textposition="top center",
        marker=dict(
            size=10,
            color=returns,
            colorscale='RdYlGn',
            showscale=True,
            colorbar=dict(title="Total Return")
        ),
        hovertemplate="Fraction: %{text}<br>Max DD: %{x:.2%}<br>Return: %{y:.2%}<extra></extra>"
    ))
    
    fig.update_layout(
        title="Risk-Reward Analysis: Kelly Fractions",
        xaxis_title="Maximum Drawdown",
        yaxis_title="Total Return",
        template="plotly_white",
        height=500
    )
    
    return fig

def create_comprehensive_dashboard(pnls: List[float],
                                  f_full: float,
                                  fractions: List[float],
                                  initial_capital: float = 1.0) -> Dict[str, go.Figure]:
    """
    Create comprehensive dashboard with multiple charts.
    
    Args:
        pnls: List of PnL values
        f_full: Full Kelly fraction
        fractions: List of fractions to compare
        initial_capital: Starting capital
        
    Returns:
        Dictionary of Plotly figures
    """
    dashboard = {}
    
    # Equity curves
    dashboard["equity"] = plot_multiple_fractions(pnls, f_full, fractions, initial_capital)
    
    # Drawdown curves
    dashboard["drawdown"] = plot_dd_full_vs_fractional(pnls, f_full, fractions[1], initial_capital)
    
    # Risk-reward scatter
    dashboard["risk_reward"] = create_risk_reward_scatter(pnls, f_full, fractions, initial_capital)
    
    # Performance table
    dashboard["performance_table"] = create_performance_comparison_table(pnls, f_full, fractions, initial_capital)
    
    return dashboard

# Example usage:
"""
import streamlit as st
import numpy as np

# Generate sample PnL data
np.random.seed(42)
win_rate = 0.55
win_loss_ratio = 1.5
n_trades = 1000

pnls = []
for _ in range(n_trades):
    if np.random.rand() < win_rate:
        pnls.append(win_loss_ratio)  # Win
    else:
        pnls.append(-1.0)  # Loss

# Calculate full Kelly
f_full = win_rate - (1 - win_rate) / win_loss_ratio

# Streamlit app
st.title("Kelly Strategy Comparison")

# User inputs
frac = st.slider("Fraction of Kelly", 0.1, 1.0, 0.5, 0.05)

# Create charts
fig_equity = plot_full_vs_fractional(pnls, f_full, frac)
fig_dd = plot_dd_full_vs_fractional(pnls, f_full, frac)

# Display charts
st.plotly_chart(fig_equity, use_container_width=True)
st.plotly_chart(fig_dd, use_container_width=True)

# Performance table
performance_df = create_performance_comparison_table(pnls, f_full, [0.25, 0.5, 0.75, 1.0])
st.dataframe(performance_df, use_container_width=True)

# Risk-reward scatter
fig_risk_reward = create_risk_reward_scatter(pnls, f_full, [0.25, 0.5, 0.75, 1.0])
st.plotly_chart(fig_risk_reward, use_container_width=True)
"""
