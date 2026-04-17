"""
Plotly Equity + Drawdown Visualization

Interactive plot with normalized equity and drawdown overlay.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging

from .max_drawdown_metric import max_drawdown

logger = logging.getLogger(__name__)

def plot_equity_and_drawdown(equity: pd.Series, title: str = "Strategy Equity vs Drawdown"):
    """
    Plot equity curve and drawdown in one interactive figure.
    
    Args:
        equity: Equity curve series
        title: Plot title
        
    Returns:
        Plotly figure object
    """
    if equity.empty:
        logger.warning("Empty equity series for plotting")
        return go.Figure()
    
    # Prepare data
    eq = equity.astype(float)
    eq_norm = eq / eq.iloc[0]  # Normalize to starting capital
    
    # Calculate drawdown
    peak = eq.cummax()
    dd = (eq - peak) / peak.replace(0, np.nan)
    
    # Create figure with secondary y-axis
    fig = make_subplots(
        rows=1, cols=1,
        specs=[[{"secondary_y": True}]],
        subplot_titles=[title]
    )
    
    # Add equity curve
    fig.add_trace(
        go.Scatter(
            x=eq.index,
            y=eq_norm,
            name="Equity (normalized)",
            line=dict(color="blue", width=2),
            hovertemplate="<b>%{fullData.name}</b><br>Time: %{x}<br>Value: %{y:.3f}<extra></extra>"
        ),
        secondary_y=False
    )
    
    # Add drawdown area
    fig.add_trace(
        go.Scatter(
            x=dd.index,
            y=dd,
            name="Drawdown",
            line=dict(color="red", width=1),
            fill='tozeroy',
            fillcolor="rgba(255,0,0,0.2)",
            hovertemplate="<b>%{fullData.name}</b><br>Time: %{x}<br>Drawdown: %{y:.2%}<extra></extra>"
        ),
        secondary_y=True
    )
    
    # Add zero line for drawdown
    fig.add_trace(
        go.Scatter(
            x=[dd.index[0], dd.index[-1]],
            y=[0, 0],
            mode="lines",
            line=dict(color="black", width=1, dash="dash"),
            showlegend=False,
            hoverinfo="skip"
        ),
        secondary_y=True
    )
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor="center",
            font=dict(size=16)
        ),
        xaxis=dict(
            title="Time",
            showgrid=True,
            gridcolor="lightgray"
        ),
        yaxis=dict(
            title="Equity (normalized)",
            side="left",
            showgrid=True,
            gridcolor="lightgray"
        ),
        yaxis2=dict(
            title="Drawdown",
            side="right",
            overlaying="y",
            showgrid=False,
            tickformat=".0%",
            zeroline=True,
            zerolinecolor="black",
            zerolinewidth=1
        ),
        legend=dict(
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1
        ),
        hovermode="x unified",
        height=600
    )
    
    return fig

def plot_multiple_strategies(equity_curves: dict, title: str = "Strategy Comparison"):
    """
    Plot multiple strategy equity curves with drawdowns.
    
    Args:
        equity_curves: Dictionary of strategy_name -> equity series
        title: Plot title
        
    Returns:
        Plotly figure object
    """
    if not equity_curves:
        logger.warning("No equity curves provided")
        return go.Figure()
    
    # Create figure with secondary y-axis
    fig = make_subplots(
        rows=1, cols=1,
        specs=[[{"secondary_y": True}]],
        subplot_titles=[title]
    )
    
    colors = ["blue", "green", "orange", "purple", "red", "cyan"]
    
    # Plot each strategy
    for i, (strategy_name, equity) in enumerate(equity_curves.items()):
        if equity.empty:
            continue
        
        # Normalize equity
        eq_norm = equity / equity.iloc[0]
        
        # Calculate drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        
        color = colors[i % len(colors)]
        
        # Add equity curve
        fig.add_trace(
            go.Scatter(
                x=eq_norm.index,
                y=eq_norm,
                name=f"{strategy_name} Equity",
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{strategy_name}</b><br>Time: %{{x}}<br>Value: %{{y:.3f}}<extra></extra>"
            ),
            secondary_y=False
        )
        
        # Add drawdown
        fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd,
                name=f"{strategy_name} Drawdown",
                line=dict(color=color, width=1, dash="dash"),
                visible="legendonly" if i > 0 else True,  # Only show first drawdown by default
                hovertemplate=f"<b>{strategy_name}</b><br>Time: %{{x}}<br>Drawdown: %{{y:.2%}}<extra></extra>"
            ),
            secondary_y=True
        )
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor="center",
            font=dict(size=16)
        ),
        xaxis=dict(
            title="Time",
            showgrid=True,
            gridcolor="lightgray"
        ),
        yaxis=dict(
            title="Equity (normalized)",
            side="left",
            showgrid=True,
            gridcolor="lightgray"
        ),
        yaxis2=dict(
            title="Drawdown",
            side="right",
            overlaying="y",
            showgrid=False,
            tickformat=".0%",
            zeroline=True,
            zerolinecolor="black",
            zerolinewidth=1
        ),
        legend=dict(
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1
        ),
        hovermode="x unified",
        height=600
    )
    
    return fig

def plot_performance_metrics(equity: pd.Series, title: str = "Strategy Performance Metrics"):
    """
    Plot equity curve with performance metrics panel.
    
    Args:
        equity: Equity curve series
        title: Plot title
        
    Returns:
        Plotly figure object
    """
    if equity.empty:
        return go.Figure()
    
    # Calculate metrics
    returns = equity.pct_change().dropna()
    
    # Basic metrics
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    volatility = returns.std() * np.sqrt(252 * 24 * 4)  # Annualized
    sharpe = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4) if returns.std() > 0 else 0
    
    # Drawdown
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    max_dd = dd.min()
    
    # Create figure with annotations
    fig = go.Figure()
    
    # Plot equity
    eq_norm = equity / equity.iloc[0]
    fig.add_trace(
        go.Scatter(
            x=eq_norm.index,
            y=eq_norm,
            name="Equity",
            line=dict(color="blue", width=2)
        )
    )
    
    # Add metrics annotations
    metrics_text = (
        f"Total Return: {total_return:.1%}<br>"
        f"Volatility: {volatility:.1%}<br>"
        f"Sharpe Ratio: {sharpe:.2f}<br>"
        f"Max Drawdown: {max_dd:.1%}<br>"
        f"Periods: {len(equity)}"
    )
    
    fig.add_annotation(
        x=0.02,
        y=0.98,
        xref="paper",
        yref="paper",
        text=metrics_text,
        showarrow=False,
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="gray",
        borderwidth=1,
        font=dict(size=12)
    )
    
    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="Equity (normalized)",
        height=500
    )
    
    return fig

def create_interactive_dashboard(equity_curves: dict, benchmark_equity: pd.Series = None):
    """
    Create comprehensive interactive dashboard.
    
    Args:
        equity_curves: Dictionary of strategy_name -> equity series
        benchmark_equity: Optional benchmark equity series
        
    Returns:
        Plotly figure object
    """
    if not equity_curves:
        return go.Figure()
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Equity Curves", "Drawdowns", "Performance Metrics", "Returns Distribution"),
        specs=[[{"secondary_y": False}, {"secondary_y": False}, {"secondary_y": False}, {"secondary_y": False}]],
        vertical_spacing=0.1,
        horizontal_spacing=0.1
    )
    
    # 1. Equity curves (top left)
    for i, (strategy_name, equity) in enumerate(equity_curves.items()):
        if equity.empty:
            continue
        
        eq_norm = equity / equity.iloc[0]
        colors = ["blue", "green", "orange", "purple"]
        color = colors[i % len(colors)]
        
        fig.add_trace(
            go.Scatter(
                x=eq_norm.index,
                y=eq_norm,
                name=strategy_name,
                line=dict(color=color, width=2)
            ),
            row=1, col=1
        )
    
    # 2. Drawdowns (top right)
    for i, (strategy_name, equity) in enumerate(equity_curves.items()):
        if equity.empty:
            continue
        
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        colors = ["blue", "green", "orange", "purple"]
        color = colors[i % len(colors)]
        
        fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd,
                name=f"{strategy_name} DD",
                line=dict(color=color, width=1, dash="dash"),
                visible="legendonly" if i > 0 else True
            ),
            row=1, col=2
        )
    
    # 3. Performance metrics table (bottom left)
    metrics_data = []
    for strategy_name, equity in equity_curves.items():
        if equity.empty:
            continue
        
        returns = equity.pct_change().dropna()
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
        sharpe = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4) if returns.std() > 0 else 0
        max_dd = max_drawdown(equity)
        
        metrics_data.append([
            strategy_name,
            f"{total_return:.1%}",
            f"{sharpe:.2f}",
            f"{max_dd:.1%}"
        ])
    
    if metrics_data:
        fig.add_trace(
            go.Table(
                header=dict(values=["Strategy", "Return", "Sharpe", "Max DD"]),
                cells=dict(values=list(zip(*metrics_data))),
                name="Metrics"
            ),
            row=2, col=1
        )
    
    # 4. Returns distribution (bottom right)
    for i, (strategy_name, equity) in enumerate(equity_curves.items()):
        if equity.empty:
            continue
        
        returns = equity.pct_change().dropna()
        colors = ["blue", "green", "orange", "purple"]
        color = colors[i % len(colors)]
        
        fig.add_trace(
            go.Histogram(
                x=returns,
                name=strategy_name,
                opacity=0.7,
                marker_color=color,
                nbinsx=50
            ),
            row=2, col=2
        )
    
    fig.update_layout(
        title="Strategy Performance Dashboard",
        height=800,
        showlegend=True
    )
    
    return fig

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample equity curve
np.random.seed(42)
returns = np.random.randn(200) * 0.01
equity = (1 + returns).cumprod() * 100000

# Create single strategy plot
fig = plot_equity_and_drawdown(equity, title="Strategy Performance")
fig.show()

# Create multi-strategy comparison
strategies = {
    "Strategy A": equity,
    "Strategy B": equity * 0.8 + np.random.randn(200) * 1000,
    "Strategy C": equity * 1.2 + np.random.randn(200) * 1500
}

fig_multi = plot_multiple_strategies(strategies, title="Strategy Comparison")
fig_multi.show()

# Create dashboard
fig_dashboard = create_interactive_dashboard(strategies)
fig_dashboard.show()
"""
