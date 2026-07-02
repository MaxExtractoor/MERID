"""
Multivariate Event Correlation Backtest for Kalshi Crypto Markets

Compute and visualize correlation between Kalshi crypto event markets.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Any, Optional
import numpy as np
import logging

logger = logging.getLogger(__name__)

def kalshi_event_corr(returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute correlation matrix for Kalshi crypto event markets.
    
    Args:
        returns_df: DataFrame with per-market returns (columns = crypto markets)
        
    Returns:
        Correlation matrix DataFrame
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    # Calculate correlation matrix
    corr_matrix = returns_df.corr()
    
    logger.info(f"Calculated correlation matrix for {len(returns_df.columns)} markets")
    
    return corr_matrix

def plot_corr_heatmap(corr_df: pd.DataFrame, 
                     title: str = "Kalshi Crypto Events Correlation Matrix",
                     color_scale: str = "RdBu") -> go.Figure:
    """
    Create correlation heatmap visualization.
    
    Args:
        corr_df: Correlation matrix DataFrame
        title: Chart title
        color_scale: Plotly color scale
        
    Returns:
        Plotly figure with heatmap
    """
    fig = px.imshow(
        corr_df,
        text_auto=".2f",
        color_continuous_scale=color_scale,
        zmin=-1,
        zmax=1,
        title=title,
        labels=dict(x="Market", y="Market", color="Correlation")
    )
    
    fig.update_layout(
        xaxis_title="Market",
        yaxis_title="Market",
        width=600,
        height=500
    )
    
    return fig

def analyze_correlation_structure(corr_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze correlation structure and provide insights.
    
    Args:
        corr_df: Correlation matrix DataFrame
        
    Returns:
        Analysis results
    """
    if corr_df.empty:
        return {"error": "Empty correlation matrix"}
    
    # Basic statistics
    np_corr = corr_df.values
    np.fill_diagonal(np_corr, np.nan)  # Exclude self-correlations
    
    analysis = {
        "markets": list(corr_df.columns),
        "num_markets": len(corr_df.columns),
        "avg_correlation": np.nanmean(np_corr),
        "max_correlation": np.nanmax(np_corr),
        "min_correlation": np.nanmin(np_corr),
        "correlation_std": np.nanstd(np_corr)
    }
    
    # Find highest and lowest correlations
    correlations = []
    
    for i, market1 in enumerate(corr_df.columns):
        for j, market2 in enumerate(corr_df.columns):
            if i < j:  # Avoid duplicates and self-correlations
                corr_val = corr_df.iloc[i, j]
                correlations.append({
                    "market1": market1,
                    "market2": market2,
                    "correlation": corr_val,
                    "abs_correlation": abs(corr_val)
                })
    
    # Sort by absolute correlation
    correlations.sort(key=lambda x: x["abs_correlation"], reverse=True)
    
    analysis["highest_correlations"] = correlations[:5]
    analysis["lowest_correlations"] = correlations[-5:]
    
    # Correlation clusters
    high_corr_threshold = 0.7
    low_corr_threshold = 0.3
    
    high_corr_pairs = [c for c in correlations if c["abs_correlation"] >= high_corr_threshold]
    low_corr_pairs = [c for c in correlations if c["abs_correlation"] <= low_corr_threshold]
    
    analysis["high_correlation_pairs"] = high_corr_pairs
    analysis["low_correlation_pairs"] = low_corr_pairs
    analysis["diversification_score"] = len(low_corr_pairs) / len(correlations) if correlations else 0.0
    
    # Market risk assessment
    avg_abs_corr = np.nanmean(np.abs(np_corr))
    
    if avg_abs_corr < 0.2:
        risk_level = "Low"
        risk_desc = "Markets show low correlation - good for diversification"
    elif avg_abs_corr < 0.5:
        risk_level = "Medium"
        risk_desc = "Markets show moderate correlation - moderate diversification benefits"
    else:
        risk_level = "High"
        risk_desc = "Markets show high correlation - limited diversification benefits"
    
    analysis["correlation_risk"] = {
        "level": risk_level,
        "description": risk_desc,
        "avg_abs_correlation": avg_abs_corr
    }
    
    return analysis

def create_correlation_dashboard(corr_df: pd.DataFrame) -> go.Figure:
    """
    Create comprehensive correlation dashboard.
    
    Args:
        corr_df: Correlation matrix DataFrame
        
    Returns:
        Plotly figure with subplots
    """
    from plotly.subplots import make_subplots
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Correlation Heatmap", "Correlation Distribution", 
                      "Top Correlations", "Risk Assessment"),
        specs=[[{"type": "heatmap"}, {"type": "histogram"}],
               [{"type": "bar"}, {"type": "indicator"}]],
        vertical_spacing=0.1,
        horizontal_spacing=0.1
    )
    
    # 1. Correlation heatmap
    fig.add_trace(
        go.Heatmap(
            z=corr_df.values,
            x=corr_df.columns,
            y=corr_df.columns,
            colorscale="RdBu",
            zmid=0,
            zmin=-1,
            zmax=1,
            textauto=".2f",
            textfont={"size": 10},
            hoverongaps=False
        ),
        row=1, col=1
    )
    
    # 2. Correlation distribution
    np_corr = corr_df.values
    np.fill_diagonal(np_corr, np.nan)
    correlations = np_corr.flatten()
    correlations = correlations[~np.isnan(correlations)]
    
    fig.add_trace(
        go.Histogram(
            x=correlations,
            nbinsx=20,
            name="Correlation Distribution",
            marker_color="lightblue"
        ),
        row=1, col=2
    )
    
    # 3. Top correlations
    analysis = analyze_correlation_structure(corr_df)
    top_corr = analysis.get("highest_correlations", [])[:10]
    
    if top_corr:
        labels = [f"{c['market1']}-{c['market2']}" for c in top_corr]
        values = [c["correlation"] for c in top_corr]
        
        fig.add_trace(
            go.Bar(
                x=labels,
                y=values,
                name="Top Correlations",
                marker_color="orange"
            ),
            row=2, col=1
        )
    
    # 4. Risk assessment indicator
    risk_info = analysis.get("correlation_risk", {})
    risk_level = risk_info.get("level", "Unknown")
    avg_abs_corr = risk_info.get("avg_abs_correlation", 0.0)
    
    # Color coding for risk level
    risk_colors = {"Low": "green", "Medium": "orange", "High": "red"}
    risk_color = risk_colors.get(risk_level, "gray")
    
    fig.add_trace(
        go.Indicator(
            mode="number+gauge+delta",
            value=avg_abs_corr * 100,
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": f"Correlation Risk: {risk_level}"},
            gauge={
                "axis": {"range": [None, 100]},
                "bar": {"color": risk_color},
                "steps": [
                    {"range": [0, 30], "color": "green"},
                    {"range": [30, 60], "color": "orange"},
                    {"range": [60, 100], "color": "red"}
                ],
                "threshold": {
                    "line": {"color": "black", "width": 2},
                    "thickness": 0.75,
                    "value": 70
                }
            },
            number={"suffix": "%"}
        ),
        row=2, col=2
    )
    
    fig.update_layout(
        title="Kalshi Crypto Markets - Correlation Analysis Dashboard",
        height=800,
        showlegend=False
    )
    
    return fig

def print_correlation_analysis(analysis: Dict[str, Any]) -> None:
    """
    Print formatted correlation analysis results.
    
    Args:
        analysis: Analysis results from analyze_correlation_structure
    """
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    print("\n" + "="*60)
    print("KALSHI CRYPTO MARKETS CORRELATION ANALYSIS")
    print("="*60)
    
    print(f"\nBasic Statistics:")
    print("-" * 40)
    print(f"  Number of Markets: {analysis['num_markets']}")
    print(f"  Average Correlation: {analysis['avg_correlation']:.3f}")
    print(f"  Max Correlation: {analysis['max_correlation']:.3f}")
    print(f"  Min Correlation: {analysis['min_correlation']:.3f}")
    print(f"  Correlation Std: {analysis['correlation_std']:.3f}")
    
    print(f"\nHighest Correlations:")
    print("-" * 50)
    for i, corr in enumerate(analysis['highest_correlations'][:5]):
        print(f"  {i+1}. {corr['market1']} - {corr['market2']}: {corr['correlation']:.3f}")
    
    print(f"\nLowest Correlations:")
    print("-" * 50)
    for i, corr in enumerate(analysis['lowest_correlations'][:5]):
        print(f"  {i+1}. {corr['market1']} - {corr['market2']}: {corr['correlation']:.3f}")
    
    risk_info = analysis['correlation_risk']
    print(f"\nRisk Assessment:")
    print("-" * 40)
    print(f"  Risk Level: {risk_info['level']}")
    print(f"  Description: {risk_info['description']}")
    print(f"  Avg Absolute Correlation: {risk_info['avg_abs_correlation']:.3f}")
    print(f"  Diversification Score: {analysis['diversification_score']:.3f}")
    
    print("="*60)

def suggest_portfolio_allocation(corr_df: pd.DataFrame, 
                               max_correlation: float = 0.7) -> Dict[str, Any]:
    """
    Suggest portfolio allocation based on correlation analysis.
    
    Args:
        corr_df: Correlation matrix DataFrame
        max_correlation: Maximum allowed correlation in portfolio
        
    Returns:
        Portfolio allocation suggestions
    """
    if corr_df.empty:
        return {"error": "Empty correlation matrix"}
    
    markets = list(corr_df.columns)
    
    # Start with all markets
    selected = [markets[0]]
    available = markets[1:]
    
    # Greedy selection based on correlation
    while available and len(selected) < len(markets):
        best_market = None
        best_avg_corr = 1.0
        
        for market in available:
            # Calculate average correlation with selected markets
            correlations = []
            for sel_market in selected:
                corr_val = corr_df.loc[market, sel_market]
                correlations.append(abs(corr_val))
            
            avg_corr = np.mean(correlations) if correlations else 0.0
            
            # Select market with lowest average correlation
            if avg_corr < best_avg_corr:
                best_avg_corr = avg_corr
                best_market = market
        
        if best_market and best_avg_corr <= max_correlation:
            selected.append(best_market)
            available.remove(best_market)
        else:
            break
    
    # Calculate portfolio metrics
    if len(selected) > 1:
        selected_corr = corr_df.loc[selected, selected]
        portfolio_avg_corr = selected_corr.values[np.triu_indices_from(selected_corr.shape, k=1)].mean()
    else:
        portfolio_avg_corr = 0.0
    
    return {
        "selected_markets": selected,
        "excluded_markets": available,
        "portfolio_size": len(selected),
        "portfolio_avg_correlation": portfolio_avg_corr,
        "diversification_ratio": len(selected) / len(markets),
        "recommendation": f"Include {len(selected)}/{len(markets)} markets for optimal diversification"
    }

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample Kalshi crypto event returns
np.random.seed(42)
n_periods = 200

returns_df = pd.DataFrame({
    'BTC15M': np.random.normal(0.001, 0.02, n_periods),
    'ETH15M': np.random.normal(0.0015, 0.025, n_periods),
    'LTC15M': np.random.normal(0.0008, 0.018, n_periods),
    'ADA15M': np.random.normal(0.0012, 0.022, n_periods),
})

# Calculate correlation
corr_matrix = kalshi_event_corr(returns_df)
print("Correlation Matrix:")
print(corr_matrix)

# Create visualization
fig = plot_corr_heatmap(corr_matrix)
fig.show()

# Analyze correlation structure
analysis = analyze_correlation_structure(corr_matrix)
print_correlation_analysis(analysis)

# Create comprehensive dashboard
dashboard_fig = create_correlation_dashboard(corr_matrix)
dashboard_fig.show()

# Portfolio allocation suggestions
allocation = suggest_portfolio_allocation(corr_matrix, max_correlation=0.7)
print("Portfolio Allocation:")
print(f"Selected: {allocation['selected_markets']}")
print(f"Excluded: {allocation['excluded_markets']}")
print(f"Portfolio Avg Correlation: {allocation['portfolio_avg_correlation']:.3f}")
"""
