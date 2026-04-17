"""
Plotly Candlestick Charts for Kalshi Event Markets

Professional candlestick charts for Kalshi event market visualization.
"""

import plotly.graph_objects as go
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def kalshi_candlestick(df: pd.DataFrame, 
                     title: str = "Kalshi Market",
                     show_volume: bool = True,
                     price_format: str = "${:.4f}",
                     volume_format: str = "{:,}") -> go.Figure:
    """
    Create professional candlestick chart for Kalshi market data.
    
    Args:
        df: DataFrame with OHLC data (columns: open, high, low, close, optional volume)
        title: Chart title
        show_volume: Whether to show volume subplot
        price_format: Format string for price labels
        volume_format: Format string for volume labels
        
    Returns:
        Plotly figure with candlestick chart
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['open', 'high', 'low', 'close']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create subplots if volume is shown
    if show_volume and 'volume' in df.columns:
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=(title, "Volume"),
            row_heights=[0.7, 0.3]
        )
        
        # Add candlestick chart
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Yes Price",
            increasing_line_color="green",
            decreasing_line_color="red",
            increasing_fillcolor="rgba(0, 255, 0, 0.8)",
            decreasing_fillcolor="rgba(255, 0, 0, 0.8)",
            line_width=1
        ), row=1, col=1)
        
        # Add volume bars
        fig.add_trace(go.Bar(
            x=df.index,
            y=df["volume"],
            name="Volume",
            marker_color="lightblue",
            opacity=0.7
        ), row=2, col=1)
        
        # Update layout
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            template="plotly_white",
            height=700,
            showlegend=False
        )
        
        # Update y-axis for volume
        fig.update_yaxes(
            title_text="Volume",
            row=2, col=1,
            tickformat=","
        )
        
    else:
        # Simple candlestick chart
        fig = go.Figure(data=[go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Yes Price",
            increasing_line_color="green",
            decreasing_line_color="red",
            increasing_fillcolor="rgba(0, 255, 0, 0.8)",
            decreasing_fillcolor="rgba(255, 0, 0, 0.8)",
            line_width=1
        )])
        
        fig.update_layout(
            title=title,
            xaxis_title="Time",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            template="plotly_white",
            height=600,
            showlegend=False
        )
    
    # Format price axis
    fig.update_yaxes(tickformat=price_format)
    
    return fig

def kalshi_candlestick_enhanced(df: pd.DataFrame,
                               title: str = "Kalshi Market",
                               show_ma: bool = True,
                               ma_periods: list = [20, 50],
                               show_volume: bool = True,
                               show_trades: bool = False,
                               price_format: str = "${:.4f}") -> go.Figure:
    """
    Enhanced candlestick chart with moving averages and additional features.
    
    Args:
        df: DataFrame with OHLC data
        title: Chart title
        show_ma: Whether to show moving averages
        ma_periods: List of moving average periods
        show_volume: Whether to show volume subplot
        show_trades: Whether to show individual trades
        price_format: Format string for price labels
        
    Returns:
        Enhanced Plotly figure
    """
    if df.empty:
        logger.warning("Empty DataFrame provided")
        return go.Figure()
    
    # Validate required columns
    required_cols = ['open', 'high', 'low', 'close']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create subplots
    if show_volume and 'volume' in df.columns:
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=3 if show_trades else 2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=(title, "Volume", "Trades") if show_trades else (title, "Volume"),
            row_heights=[0.6, 0.25, 0.15] if show_trades else [0.75, 0.25]
        )
        volume_row = 2
        trades_row = 3 if show_trades else None
    else:
        fig = go.Figure()
        volume_row = None
        trades_row = None
    
    # Add candlestick chart
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Yes Price",
        increasing_line_color="green",
        decreasing_line_color="red",
        increasing_fillcolor="rgba(0, 255, 0, 0.8)",
        decreasing_fillcolor="rgba(255, 0, 0, 0.8)",
        line_width=1
    ), row=1, col=1)
    
    # Add moving averages
    if show_ma and len(df) > max(ma_periods):
        colors = ['blue', 'orange', 'purple', 'brown']
        
        for i, period in enumerate(ma_periods):
            if len(df) >= period:
                ma = df["close"].rolling(window=period).mean()
                
                fig.add_trace(go.Scatter(
                    x=df.index,
                    y=ma,
                    mode='lines',
                    name=f'MA {period}',
                    line=dict(color=colors[i % len(colors)], width=2),
                    opacity=0.8
                ), row=1, col=1)
    
    # Add volume bars
    if show_volume and 'volume' in df.columns and volume_row:
        fig.add_trace(go.Bar(
            x=df.index,
            y=df["volume"],
            name="Volume",
            marker_color="lightblue",
            opacity=0.7
        ), row=volume_row, col=1)
    
    # Add individual trades
    if show_trades and 'trades' in df.columns and trades_row:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df["trades"],
            mode='markers',
            name="Trades",
            marker=dict(
                color='red',
                size=4,
                symbol='x'
            ),
            opacity=0.6
        ), row=trades_row, col=1)
    
    # Update layout
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=900 if show_trades else 700,
        showlegend=True,
        legend=dict(
            x=0.01,
            y=0.99,
            bgcolor="rgba(255,255,255,0.8)"
        )
    )
    
    # Format price axis
    fig.update_yaxes(tickformat=price_format, row=1, col=1)
    
    # Format volume axis
    if volume_row:
        fig.update_yaxes(
            title_text="Volume",
            tickformat=",",
            row=volume_row, col=1
        )
    
    return fig

def kalshi_ohlc_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate summary statistics for OHLC data.
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        Dictionary of summary statistics
    """
    if df.empty:
        return {}
    
    # Basic price statistics
    latest = df.iloc[-1]
    first = df.iloc[0]
    
    price_change = latest["close"] - first["close"]
    price_change_pct = (price_change / first["close"]) * 100 if first["close"] != 0 else 0.0
    
    # High/Low statistics
    period_high = df["high"].max()
    period_low = df["low"].min()
    
    # Volume statistics
    avg_volume = df["volume"].mean() if "volume" in df.columns else 0
    total_volume = df["volume"].sum() if "volume" in df.columns else 0
    
    # Volatility
    daily_returns = df["close"].pct_change().dropna()
    volatility = daily_returns.std() * np.sqrt(252) if len(daily_returns) > 1 else 0.0
    
    # Price ranges
    avg_range = (df["high"] - df["low"]).mean()
    max_range = (df["high"] - df["low"]).max()
    
    summary = {
        "current_price": latest["close"],
        "price_change": price_change,
        "price_change_pct": price_change_pct,
        "period_high": period_high,
        "period_low": period_low,
        "avg_volume": avg_volume,
        "total_volume": total_volume,
        "volatility": volatility,
        "avg_range": avg_range,
        "max_range": max_range,
        "periods": len(df),
        "date_range": {
            "start": df.index[0],
            "end": df.index[-1]
        }
    }
    
    return summary

def create_technical_indicators(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Calculate common technical indicators for Kalshi markets.
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        Dictionary of technical indicators
    """
    indicators = {}
    
    # Moving averages
    indicators["MA_20"] = df["close"].rolling(window=20).mean()
    indicators["MA_50"] = df["close"].rolling(window=50).mean()
    
    # Exponential moving averages
    indicators["EMA_12"] = df["close"].ewm(span=12).mean()
    indicators["EMA_26"] = df["close"].ewm(span=26).mean()
    
    # MACD
    macd_line = indicators["EMA_12"] - indicators["EMA_26"]
    signal_line = macd_line.ewm(span=9).mean()
    indicators["MACD"] = macd_line
    indicators["MACD_Signal"] = signal_line
    indicators["MACD_Histogram"] = macd_line - signal_line
    
    # RSI (Relative Strength Index)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    indicators["RSI"] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    ma_20 = df["close"].rolling(window=20).mean()
    std_20 = df["close"].rolling(window=20).std()
    indicators["BB_Upper"] = ma_20 + (std_20 * 2)
    indicators["BB_Middle"] = ma_20
    indicators["BB_Lower"] = ma_20 - (std_20 * 2)
    
    return indicators

def create_technical_chart(df: pd.DataFrame, indicators: Dict[str, pd.Series]) -> go.Figure:
    """
    Create technical analysis chart with indicators.
    
    Args:
        df: DataFrame with OHLC data
        indicators: Dictionary of technical indicators
        
    Returns:
        Plotly figure with technical analysis
    """
    from plotly.subplots import make_subplots
    
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=("Price & MA", "MACD", "RSI"),
        row_heights=[0.5, 0.25, 0.25]
    )
    
    # Price and moving averages
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Price",
        increasing_line_color="green",
        decreasing_line_color="red"
    ), row=1, col=1)
    
    # Add moving averages
    colors = ['blue', 'orange']
    for i, (name, ma) in enumerate([("MA_20", indicators.get("MA_20")), ("MA_50", indicators.get("MA_50"))]):
        if ma is not None:
            fig.add_trace(go.Scatter(
                x=df.index,
                y=ma,
                mode='lines',
                name=name,
                line=dict(color=colors[i], width=2)
            ), row=1, col=1)
    
    # MACD
    if "MACD" in indicators and "MACD_Signal" in indicators:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=indicators["MACD"],
            mode='lines',
            name="MACD",
            line=dict(color='blue', width=2)
        ), row=2, col=1)
        
        fig.add_trace(go.Scatter(
            x=df.index,
            y=indicators["MACD_Signal"],
            mode='lines',
            name="Signal",
            line=dict(color='red', width=2)
        ), row=2, col=1)
    
    # RSI
    if "RSI" in indicators:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=indicators["RSI"],
            mode='lines',
            name="RSI",
            line=dict(color='purple', width=2)
        ), row=3, col=1)
        
        # Add RSI levels
        fig.add_hline(y=70, line_dash="dash", line_color="gray", opacity=0.5, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="gray", opacity=0.5, row=3, col=1)
    
    fig.update_layout(
        title="Technical Analysis - Kalshi Market",
        template="plotly_white",
        height=800,
        showlegend=True
    )
    
    # Format RSI axis
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    
    return fig

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample Kalshi OHLC data
np.random.seed(42)
dates = pd.date_range('2023-01-01', periods=100, freq='15min')

# Simulate price movements
price = 0.50
prices = [price]
for _ in range(99):
    change = np.random.normal(0, 0.01)  # 1% standard deviation
    price = max(0.01, min(0.99, price + change))
    prices.append(price)

# Create OHLC data
ohlc_data = []
for i in range(len(prices)):
    if i == 0:
        open_price = prices[i]
        high_price = prices[i]
        low_price = prices[i]
        close_price = prices[i]
    else:
        open_price = close_price
        close_price = prices[i]
        
        # Simulate high/low
        high_change = np.random.uniform(0, 0.005)
        low_change = np.random.uniform(-0.005, 0)
        
        high_price = max(open_price, close_price) + high_change
        low_price = min(open_price, close_price) + low_change
        high_price = max(high_price, close_price)
        low_price = min(low_price, close_price)
    
    ohlc_data.append({
        'open': open_price,
        'high': high_price,
        'low': low_price,
        'close': close_price,
        'volume': np.random.randint(1000, 10000)
    })

df = pd.DataFrame(ohlc_data, index=dates)

# Create candlestick chart
fig = kalshi_candlestick(df, "KXBTC15M - Kalshi Market")

# Create enhanced chart
fig_enhanced = kalshi_candlestick_enhanced(df, "KXBTC15M - Enhanced Chart")

# Get summary statistics
summary = kalshi_ohlc_summary(df)
print(f"Current price: ${summary['current_price']:.4f}")
print(f"Price change: {summary['price_change_pct']:+.2f}%")

# Calculate technical indicators
indicators = create_technical_indicators(df)

# Create technical chart
fig_tech = create_technical_chart(df, indicators)

# Use in Streamlit:
# st.plotly_chart(fig, use_container_width=True)
# st.plotly_chart(fig_enhanced, use_container_width=True)
# st.plotly_chart(fig_tech, use_container_width=True)
"""
