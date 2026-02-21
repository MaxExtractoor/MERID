"""
Visualization utilities for sentiment backtesting.

Plot equity curves, sentiment bands, and entry/exit markers.
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def plot_sentiment_backtest(
    bt_df: pd.DataFrame,
    title: str = "Kalshi Sentiment Strategy",
    save_path: Optional[str] = None,
) -> Any:
    """
    Plot sentiment backtest results.
    
    Shows:
    - Equity curve (strategy vs base)
    - Sentiment overlay with threshold bands
    - Entry/exit markers
    
    Args:
        bt_df: DataFrame with columns:
            - 'equity': Strategy equity curve
            - 'sent_combined': Combined sentiment
            - 'base_equity' (optional): Base equity (no sentiment)
            - 'signal': Position signals (1, 0, -1)
        title: Plot title
        save_path: Optional path to save figure
    
    Returns:
        Matplotlib figure object
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        logger.error("matplotlib not available for plotting")
        return None
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), 
                             gridspec_kw={'height_ratios': [2, 1, 1]})
    
    # 1. Equity curve
    ax1 = axes[0]
    ax1.plot(bt_df.index, bt_df["equity"], label="Sentiment Strategy", 
             color="tab:blue", linewidth=2)
    
    if "base_equity" in bt_df.columns:
        ax1.plot(bt_df.index, bt_df["base_equity"], label="Base (No Sentiment)",
                color="gray", linestyle="--", alpha=0.7)
    
    # Add drawdown shading
    if "equity" in bt_df.columns:
        equity = bt_df["equity"]
        peak = equity.cummax()
        drawdown = (peak - equity) / peak
        ax1.fill_between(bt_df.index, equity, peak, 
                        where=(drawdown > 0.05), alpha=0.3, color="red",
                        label="Drawdown > 5%")
    
    ax1.set_ylabel("Equity ($)")
    ax1.set_title(title, fontsize=14, fontweight='bold')
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    
    # 2. Sentiment with bands
    ax2 = axes[1]
    ax2.plot(bt_df.index, bt_df["sent_combined"], label="Combined Sentiment",
            color="orange", alpha=0.7)
    
    # Threshold bands
    ax2.axhline(0.2, color="green", linestyle=":", alpha=0.5, label="Bullish Threshold")
    ax2.axhline(-0.2, color="red", linestyle=":", alpha=0.5, label="Bearish Threshold")
    ax2.axhline(0, color="gray", linestyle="-", alpha=0.3)
    
    # Fill sentiment regions
    ax2.fill_between(bt_df.index, bt_df["sent_combined"], 0,
                    where=(bt_df["sent_combined"] >= 0.2), alpha=0.3, color="green")
    ax2.fill_between(bt_df.index, bt_df["sent_combined"], 0,
                    where=(bt_df["sent_combined"] <= -0.2), alpha=0.3, color="red")
    
    ax2.set_ylabel("Sentiment (-1 to 1)")
    ax2.set_ylim(-1, 1)
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    
    # 3. Position signals
    ax3 = axes[2]
    if "signal" in bt_df.columns:
        # Color-coded position bars
        colors = ['green' if s == 1 else 'red' if s == -1 else 'gray' 
                 for s in bt_df["signal"]]
        ax3.bar(bt_df.index, bt_df["signal"], color=colors, alpha=0.6, width=0.8)
        ax3.set_ylabel("Position")
        ax3.set_ylim(-1.5, 1.5)
        ax3.set_yticks([-1, 0, 1])
        ax3.set_yticklabels(['Short', 'Flat', 'Long'])
    
    ax3.set_xlabel("Date")
    ax3.grid(True, alpha=0.3)
    
    # Format x-axis
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        logger.info(f"Saved plot to {save_path}")
    
    return fig


def plot_sentiment_distribution(
    sentiment_series: pd.Series,
    title: str = "Sentiment Distribution",
    save_path: Optional[str] = None,
) -> Any:
    """
    Plot histogram of sentiment values.
    
    Args:
        sentiment_series: Series of sentiment values
        title: Plot title
        save_path: Optional save path
    
    Returns:
        Matplotlib figure
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        logger.error("matplotlib not available")
        return None
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Histogram
    ax.hist(sentiment_series, bins=50, alpha=0.7, color='blue', edgecolor='black')
    
    # Threshold lines
    ax.axvline(0.2, color='green', linestyle='--', label='Bullish Threshold')
    ax.axvline(-0.2, color='red', linestyle='--', label='Bearish Threshold')
    ax.axvline(0, color='gray', linestyle='-', alpha=0.5)
    
    ax.set_xlabel("Sentiment Score")
    ax.set_ylabel("Frequency")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Stats text
    mean_sent = sentiment_series.mean()
    std_sent = sentiment_series.std()
    ax.text(0.02, 0.95, f"Mean: {mean_sent:.3f}\nStd: {std_sent:.3f}",
           transform=ax.transAxes, verticalalignment='top',
           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def create_interactive_backtest_plot(
    bt_df: pd.DataFrame,
    title: str = "Kalshi Sentiment Backtest",
) -> Optional[str]:
    """
    Create interactive Plotly backtest visualization.
    
    Returns HTML string for embedding.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.warning("plotly not available, falling back to matplotlib")
        return None
    
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.5, 0.3, 0.2],
        subplot_titles=('Equity Curve', 'Sentiment', 'Position')
    )
    
    # Equity
    fig.add_trace(
        go.Scatter(x=bt_df.index, y=bt_df["equity"], 
                  name="Strategy", line=dict(color='blue')),
        row=1, col=1
    )
    
    if "base_equity" in bt_df.columns:
        fig.add_trace(
            go.Scatter(x=bt_df.index, y=bt_df["base_equity"],
                      name="Base", line=dict(color='gray', dash='dash')),
            row=1, col=1
        )
    
    # Sentiment
    fig.add_trace(
        go.Scatter(x=bt_df.index, y=bt_df["sent_combined"],
                  name="Sentiment", line=dict(color='orange')),
        row=2, col=1
    )
    
    # Threshold lines
    fig.add_hline(y=0.2, line_dash="dot", line_color="green", row=2, col=1)
    fig.add_hline(y=-0.2, line_dash="dot", line_color="red", row=2, col=1)
    
    # Position
    if "signal" in bt_df.columns:
        fig.add_trace(
            go.Bar(x=bt_df.index, y=bt_df["signal"], name="Position",
                  marker_color=['green' if s == 1 else 'red' if s == -1 else 'gray' 
                             for s in bt_df["signal"]]),
            row=3, col=1
        )
    
    fig.update_layout(
        title=title,
        showlegend=True,
        height=800,
        hovermode='x unified'
    )
    
    return fig.to_html(include_plotlyjs='cdn')


def generate_backtest_report(
    bt_df: pd.DataFrame,
    output_dir: str = "./backtest_reports",
) -> Dict[str, Any]:
    """
    Generate comprehensive backtest report with plots.
    
    Args:
        bt_df: Backtest DataFrame
        output_dir: Directory to save reports
    
    Returns:
        Dict with report paths and metrics
    """
    import os
    from datetime import datetime, timezone
    
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    report = {}
    
    # Main backtest plot
    main_plot_path = f"{output_dir}/backtest_{timestamp}.png"
    plot_sentiment_backtest(bt_df, save_path=main_plot_path)
    report["main_plot"] = main_plot_path
    
    # Sentiment distribution
    if "sent_combined" in bt_df.columns:
        dist_plot_path = f"{output_dir}/sentiment_dist_{timestamp}.png"
        plot_sentiment_distribution(bt_df["sent_combined"], save_path=dist_plot_path)
        report["sentiment_dist"] = dist_plot_path
    
    # Calculate metrics
    returns = bt_df["equity"].pct_change().dropna()
    report["metrics"] = {
        "total_return": (bt_df["equity"].iloc[-1] / bt_df["equity"].iloc[0] - 1) * 100,
        "sharpe": returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0,
        "max_drawdown": ((bt_df["equity"].cummax() - bt_df["equity"]) / bt_df["equity"].cummax()).max() * 100,
        "volatility": returns.std() * np.sqrt(252) * 100,
    }
    
    return report


# ── Convenience functions ─────────────────────────────────────────

def quick_plot_equity(equity_curve: List[float], title: str = "Equity") -> Any:
    """Quick one-liner to plot equity curve."""
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(equity_curve, color='blue', linewidth=2)
        ax.set_title(title)
        ax.set_ylabel("Equity")
        ax.grid(True, alpha=0.3)
        return fig
    except ImportError:
        logger.error("matplotlib not available")
        return None
