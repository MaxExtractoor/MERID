"""
Plotly Heatmaps for Kalshi Volume Analysis

Professional volume analysis heatmaps for Kalshi crypto markets.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

def kalshi_volume_heatmap(df: pd.DataFrame,
                          title: str = "Kalshi Crypto Volume Heatmap",
                          color_scale: str = "Blues") -> go.Figure:
    """
    Create volume heatmap for Kalshi markets.
    
    Args:
        df: DataFrame with columns ['market_ticker', 'volume_24h', 'category', 'underlying']
        title: Chart title
        color_scale: Plotly color scale name
        
    Returns:
        Plotly figure with volume heatmap
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['market_ticker', 'volume_24h', 'category', 'underlying']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create pivot table
    pivot = df.pivot_table(
        index="underlying",
        columns="category",
        values="volume_24h",
        aggfunc="sum",
        fill_value=0,
    )
    
    # Create heatmap
    fig = px.imshow(
        pivot,
        labels=dict(x="Category", y="Underlying", color="24h Volume"),
        color_continuous_scale=color_scale,
        title=title,
        text_auto=".0f",
        aspect="auto"
    )
    
    # Update layout
    fig.update_layout(
        xaxis_title="Category",
        yaxis_title="Underlying",
        height=600,
        template="plotly_white"
    )
    
    return fig

def kalshi_volume_heatmap_enhanced(df: pd.DataFrame,
                                    title: str = "Kalshi Crypto Volume Analysis",
                                    show_values: bool = True,
                                    normalize: bool = False) -> go.Figure:
    """
    Enhanced volume heatmap with additional features.
    
    Args:
        df: DataFrame with market data
        title: Chart title
        show_values: Whether to show values on heatmap
        normalize: Whether to normalize values by row/column
        
    Returns:
        Enhanced Plotly figure
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['market_ticker', 'volume_24h', 'category', 'underlying']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create pivot table
    pivot = df.pivot_table(
        index="underlying",
        columns="category",
        values="volume_24h",
        aggfunc="sum",
        fill_value=0,
    )
    
    # Normalize if requested
    if normalize:
        # Normalize by row (underlying)
        pivot_normalized = pivot.div(pivot.sum(axis=1), axis=0)
        title += " (Normalized by Underlying)"
        color_label = "Normalized Volume"
    else:
        pivot_normalized = pivot
        color_label = "24h Volume"
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=pivot_normalized.values,
        x=pivot_normalized.columns,
        y=pivot_normalized.index,
        colorscale="Blues",
        text=pivot_normalized.round(2).values if show_values else None,
        texttemplate="%{text}" if show_values else None,
        textfont={"size": 10},
        hoverongaps=False,
        colorbar=dict(title=color_label)
    ))
    
    # Update layout
    fig.update_layout(
        title=title,
        xaxis_title="Category",
        yaxis_title="Underlying",
        height=700,
        template="plotly_white"
    )
    
    return fig

def create_volume_bubble_chart(df: pd.DataFrame,
                               title: str = "Kalshi Volume Bubble Chart") -> go.Figure:
    """
    Create bubble chart for volume analysis with additional dimensions.
    
    Args:
        df: DataFrame with market data
        title: Chart title
        
    Returns:
        Plotly bubble chart figure
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['market_ticker', 'volume_24h', 'category', 'underlying']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Calculate additional metrics if not present
    if 'market_count' not in df.columns:
        market_count = df.groupby(['underlying', 'category']).size().reset_index(name='market_count')
        df = df.merge(market_count, on=['underlying', 'category'], how='left')
    
    # Create bubble chart
    fig = px.scatter(
        df,
        x="underlying",
        y="category",
        size="volume_24h",
        color="market_count",
        hover_name="market_ticker",
        size_max=60,
        title=title,
        labels={
            "underlying": "Underlying Asset",
            "category": "Market Category",
            "volume_24h": "24h Volume",
            "market_count": "Number of Markets"
        },
        color_continuous_scale="Viridis"
    )
    
    fig.update_layout(
        height=600,
        template="plotly_white"
    )
    
    return fig

def create_volume_treemap(df: pd.DataFrame,
                          title: str = "Kalshi Volume Treemap") -> go.Figure:
    """
    Create treemap for hierarchical volume visualization.
    
    Args:
        df: DataFrame with market data
        title: Chart title
        
    Returns:
        Plotly treemap figure
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['market_ticker', 'volume_24h', 'category', 'underlying']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create hierarchical labels
    df['hierarchy'] = df['underlying'] + ' | ' + df['category']
    
    # Sort by volume for better visualization
    df_sorted = df.sort_values('volume_24h', ascending=False)
    
    # Create treemap
    fig = go.Figure(go.Treemap(
        labels=df_sorted['market_ticker'],
        parents=df_sorted['hierarchy'],
        values=df_sorted['volume_24h'],
        textinfo="label+value+percent parent",
        hovertemplate="<b>%{label}</b><br>" +
                     "Volume: %{value:,.0f}<br>" +
                     "Parent: %{parent}<br>" +
                     "Percent of parent: %{percentParent:.1%}<extra></extra>",
        root_color="lightgrey"
    ))
    
    fig.update_layout(
        title=title,
        height=700,
        template="plotly_white"
    )
    
    return fig

def create_volume_analysis_dashboard(df: pd.DataFrame) -> Dict[str, go.Figure]:
    """
    Create comprehensive volume analysis dashboard.
    
    Args:
        df: DataFrame with market data
        
    Returns:
        Dictionary of Plotly figures
    """
    dashboard = {}
    
    # Basic heatmap
    dashboard['heatmap'] = kalshi_volume_heatmap(df, "Kalshi Volume Heatmap")
    
    # Enhanced heatmap
    dashboard['heatmap_enhanced'] = kalshi_volume_heatmap_enhanced(
        df, "Enhanced Volume Analysis", show_values=True, normalize=True
    )
    
    # Bubble chart
    dashboard['bubble'] = create_volume_bubble_chart(df, "Volume Bubble Chart")
    
    # Treemap
    dashboard['treemap'] = create_volume_treemap(df, "Volume Treemap")
    
    return dashboard

def analyze_volume_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze volume patterns and provide insights.
    
    Args:
        df: DataFrame with market data
        
    Returns:
        Analysis results dictionary
    """
    if df.empty:
        return {}
    
    analysis = {}
    
    # Basic statistics
    analysis['total_volume'] = df['volume_24h'].sum()
    analysis['avg_volume'] = df['volume_24h'].mean()
    analysis['median_volume'] = df['volume_24h'].median()
    analysis['max_volume'] = df['volume_24h'].max()
    analysis['min_volume'] = df['volume_24h'].min()
    
    # By underlying
    volume_by_underlying = df.groupby('underlying')['volume_24h'].sum().sort_values(ascending=False)
    analysis['top_underlyings'] = volume_by_underlying.head(10).to_dict()
    
    # By category
    volume_by_category = df.groupby('category')['volume_24h'].sum().sort_values(ascending=False)
    analysis['top_categories'] = volume_by_category.to_dict()
    
    # Market concentration
    top_10_volume = volume_by_underlying.head(10).sum()
    analysis['concentration_top_10'] = top_10_volume / analysis['total_volume']
    
    # Volume growth (if time data available)
    if 'timestamp' in df.columns:
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        volume_by_date = df.groupby('date')['volume_24h'].sum()
        if len(volume_by_date) > 1:
            growth_rate = (volume_by_date.iloc[-1] / volume_by_date.iloc[0] - 1) * 100
            analysis['volume_growth_rate'] = growth_rate
    
    # Correlation analysis
    pivot = df.pivot_table(
        index="underlying",
        columns="category",
        values="volume_24h",
        aggfunc="sum",
        fill_value=0,
    )
    
    if pivot.shape[0] > 1 and pivot.shape[1] > 1:
        correlation_matrix = pivot.corr()
        analysis['category_correlation'] = correlation_matrix.to_dict()
    
    return analysis

def create_volume_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create summary table for volume analysis.
    
    Args:
        df: DataFrame with market data
        
    Returns:
        Summary table DataFrame
    """
    if df.empty:
        return pd.DataFrame()
    
    # Group by underlying and category
    summary = df.groupby(['underlying', 'category']).agg({
        'volume_24h': ['sum', 'mean', 'count'],
        'market_ticker': 'nunique'
    }).round(2)
    
    # Flatten column names
    summary.columns = ['Total Volume', 'Avg Volume', 'Market Count', 'Unique Tickers']
    
    # Calculate percentage of total
    total_volume = df['volume_24h'].sum()
    summary['Volume %'] = (summary['Total Volume'] / total_volume * 100).round(2)
    
    # Sort by total volume
    summary = summary.sort_values('Total Volume', ascending=False)
    
    return summary.reset_index()

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample Kalshi volume data
np.random.seed(42)

underlyings = ['BTC', 'ETH', 'LTC', 'ADA', 'SOL', 'DOT', 'AVAX', 'MATIC']
categories = ['15m', '1H', '4H', '1D', 'Weekly']

data = []
for underlying in underlyings:
    for category in categories:
        # Generate realistic volume patterns
        base_volume = np.random.uniform(10000, 1000000)
        
        # Higher volume for major pairs and shorter timeframes
        if underlying in ['BTC', 'ETH']:
            base_volume *= 2
        if category in ['15m', '1H']:
            base_volume *= 1.5
        
        volume = base_volume * np.random.uniform(0.5, 2.0)
        
        data.append({
            'market_ticker': f'KX{underlying}{category}-EXAMPLE',
            'volume_24h': volume,
            'category': category,
            'underlying': underlying
        })

df = pd.DataFrame(data)

# Create visualizations
fig_heatmap = kalshi_volume_heatmap(df)
fig_enhanced = kalshi_volume_heatmap_enhanced(df, show_values=True, normalize=True)
fig_bubble = create_volume_bubble_chart(df)
fig_treemap = create_volume_treemap(df)

# Create dashboard
dashboard = create_volume_analysis_dashboard(df)

# Analyze patterns
analysis = analyze_volume_patterns(df)
print(f"Total volume: ${analysis['total_volume']:,.0f}")
print(f"Top underlying: {list(analysis['top_underlyings'].keys())[:3]}")

# Summary table
summary_table = create_volume_summary_table(df)
print(summary_table.head())

# Use in Streamlit:
# st.plotly_chart(fig_heatmap, use_container_width=True)
# st.plotly_chart(fig_enhanced, use_container_width=True)
# st.plotly_chart(fig_bubble, use_container_width=True)
# st.plotly_chart(fig_treemap, use_container_width=True)
# st.dataframe(summary_table, use_container_width=True)
"""
