"""MERID Chart Generation Module.

Generate interactive financial charts using Plotly and Bokeh for the dashboard.
Supports candlesticks, heatmaps, equity curves, and real-time streaming charts.
"""

from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import json
import structlog
import pandas as pd
import numpy as np

logger = structlog.get_logger(__name__)


class PlotlyChartGenerator:
    """Generate interactive Plotly charts for trading data."""
    
    def __init__(self):
        self.logger = logger.bind(generator="Plotly")
    
    def create_candlestick_chart(
        self,
        data: pd.DataFrame,
        symbol: str,
        title: Optional[str] = None,
        volume: bool = True
    ) -> Dict[str, Any]:
        """Create interactive candlestick chart."""
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            logger.error("plotly_not_installed")
            return {}
        
        # Validate required columns
        required = ['open', 'high', 'low', 'close']
        if not all(col in data.columns for col in required):
            raise ValueError(f"DataFrame must contain columns: {required}")
        
        # Create figure
        if volume and 'volume' in data.columns:
            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.8, 0.2]
            )
            
            # Add volume bars
            fig.add_trace(
                go.Bar(
                    x=data.index,
                    y=data['volume'],
                    name='Volume',
                    marker_color='rgba(128, 128, 128, 0.5)'
                ),
                row=2, col=1
            )
            
            row = 1
        else:
            fig = go.Figure()
            row = 1
        
        # Add candlestick
        fig.add_trace(
            go.Candlestick(
                x=data.index,
                open=data['open'],
                high=data['high'],
                low=data['low'],
                close=data['close'],
                name=symbol
            ),
            row=row, col=1
        )
        
        # Add moving averages if enough data
        if len(data) >= 20:
            ma20 = data['close'].rolling(window=20).mean()
            fig.add_trace(
                go.Scatter(
                    x=data.index,
                    y=ma20,
                    name='MA20',
                    line=dict(color='orange', width=1)
                ),
                row=row, col=1
            )
        
        if len(data) >= 50:
            ma50 = data['close'].rolling(window=50).mean()
            fig.add_trace(
                go.Scatter(
                    x=data.index,
                    y=ma50,
                    name='MA50',
                    line=dict(color='blue', width=1)
                ),
                row=row, col=1
            )
        
        # Layout
        fig.update_layout(
            title=title or f"{symbol} Price Chart",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=600 if volume else 500
        )
        
        if volume:
            fig.update_xaxes(title_text="Date", row=2, col=1)
            fig.update_yaxes(title_text="Price", row=1, col=1)
            fig.update_yaxes(title_text="Volume", row=2, col=1)
        
        return json.loads(fig.to_json())
    
    def create_equity_curve(
        self,
        data: pd.DataFrame,
        title: str = "Portfolio Equity Curve"
    ) -> Dict[str, Any]:
        """Create portfolio equity curve with drawdown."""
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            return {}
        
        # Calculate drawdown
        peak = data['equity'].expanding(min_periods=1).max()
        drawdown = (data['equity'] - peak) / peak * 100
        
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("Equity", "Drawdown %")
        )
        
        # Equity curve
        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data['equity'],
                name='Equity',
                fill='tozeroy',
                line=dict(color='green')
            ),
            row=1, col=1
        )
        
        # Drawdown
        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=drawdown,
                name='Drawdown',
                fill='tozeroy',
                line=dict(color='red')
            ),
            row=2, col=1
        )
        
        fig.update_layout(
            title=title,
            template="plotly_dark",
            height=600,
            showlegend=False
        )
        
        fig.update_yaxes(title_text="Value ($)", row=1, col=1)
        fig.update_yaxes(title_text="Drawdown %", row=2, col=1)
        
        return json.loads(fig.to_json())
    
    def create_heatmap(
        self,
        data: pd.DataFrame,
        title: str = "Correlation Heatmap",
        colorscale: str = "RdBu"
    ) -> Dict[str, Any]:
        """Create correlation heatmap for portfolio."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return {}
        
        # Calculate correlation
        corr = data.corr()
        
        fig = go.Figure(data=go.Heatmap(
            z=corr.values,
            x=corr.columns,
            y=corr.columns,
            colorscale=colorscale,
            zmid=0,
            text=[[f"{val:.2f}" for val in row] for row in corr.values],
            texttemplate="%{text}",
            textfont={"size": 10}
        ))
        
        fig.update_layout(
            title=title,
            template="plotly_dark",
            height=500
        )
        
        return json.loads(fig.to_json())
    
    def create_risk_heatmap(
        self,
        positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create risk heatmap for positions."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return {}
        
        symbols = [p['symbol'] for p in positions]
        values = [p.get('market_value', 0) for p in positions]
        risks = [p.get('var_95', 0) for p in positions]
        
        fig = go.Figure(data=go.Bar(
            x=symbols,
            y=risks,
            marker_color=['red' if r > max(risks)*0.5 else 'orange' if r > max(risks)*0.3 else 'green' for r in risks],
            text=[f"${v:,.0f}" for v in values],
            textposition='outside'
        ))
        
        fig.update_layout(
            title="Position Risk Heatmap (VaR 95%)",
            xaxis_title="Symbol",
            yaxis_title="Value at Risk ($)",
            template="plotly_dark",
            height=400
        )
        
        return json.loads(fig.to_json())
    
    def create_pnl_waterfall(
        self,
        trades: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create P&L waterfall chart."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return {}
        
        # Calculate cumulative P&L
        cumulative = [0]
        for trade in trades:
            pnl = trade.get('realized_pnl', 0)
            cumulative.append(cumulative[-1] + pnl)
        
        fig = go.Figure(go.Waterfall(
            name="P&L",
            orientation="v",
            x=[f"Trade {i+1}" for i in range(len(trades))],
            y=[t.get('realized_pnl', 0) for t in trades],
            connector={"line": {"color": "rgb(63, 63, 63)"}}
        ))
        
        fig.add_trace(go.Scatter(
            x=[f"Trade {i+1}" for i in range(len(trades))],
            y=cumulative[1:],
            name="Cumulative P&L",
            line=dict(color='green')
        ))
        
        fig.update_layout(
            title="Trade P&L Waterfall",
            template="plotly_dark",
            height=500,
            showlegend=True
        )
        
        return json.loads(fig.to_json())


class BokehChartGenerator:
    """Generate high-frequency streaming charts with Bokeh."""
    
    def __init__(self):
        self.logger = logger.bind(generator="Bokeh")
    
    def create_ticker_chart_script(
        self,
        symbol: str,
        width: int = 800,
        height: int = 400
    ) -> str:
        """Generate Bokeh script for real-time ticker display."""
        try:
            from bokeh.plotting import figure
            from bokeh.models import ColumnDataSource, DatetimeTickFormatter
            from bokeh.embed import json_item
        except ImportError:
            return ""
        
        # Create figure
        p = figure(
            title=f"{symbol} Real-Time Price",
            width=width,
            height=height,
            x_axis_type="datetime",
            tools="pan,wheel_zoom,box_zoom,reset"
        )
        
        # Initial empty data source
        source = ColumnDataSource(data={
            'x': [],
            'y': [],
            'size': [],
            'color': []
        })
        
        # Add circle renderer for ticks
        p.circle(x='x', y='y', size='size', color='color', source=source)
        
        p.xaxis.formatter = DatetimeTickFormatter(
            hours="%H:%M:%S",
            minutes="%H:%M:%S"
        )
        
        p.yaxis.axis_label = "Price"
        
        return json.dumps(json_item(p))
    
    def create_orderbook_heatmap(
        self,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        mid_price: float
    ) -> str:
        """Create order book depth heatmap."""
        try:
            from bokeh.plotting import figure
            from bokeh.models import ColumnDataSource
            from bokeh.transform import linear_cmap
            from bokeh.embed import json_item
        except ImportError:
            return ""
        
        # Prepare data
        all_prices = [b[0] for b in bids] + [a[0] for a in asks]
        all_sizes = [b[1] for b in bids] + [a[1] for a in asks]
        all_sides = ['bid'] * len(bids) + ['ask'] * len(asks)
        all_depths = list(range(len(bids), 0, -1)) + list(range(1, len(asks) + 1))
        
        source = ColumnDataSource(data={
            'price': all_prices,
            'size': all_sizes,
            'side': all_sides,
            'depth': all_depths
        })
        
        p = figure(
            title="Order Book Depth",
            width=600,
            height=400,
            tools="pan,wheel_zoom,reset"
        )
        
        p.rect(
            x='price',
            y='depth',
            width=0.01,
            height=0.9,
            source=source,
            color=linear_cmap('size', 'Viridis256', min(all_sizes), max(all_sizes))
        )
        
        return json.dumps(json_item(p))


class DashboardChartService:
    """Service for generating dashboard charts."""
    
    def __init__(self):
        self.plotly = PlotlyChartGenerator()
        self.bokeh = BokehChartGenerator()
        self.logger = logger.bind(component="DashboardChartService")
    
    def generate_portfolio_summary(
        self,
        equity_history: pd.DataFrame,
        positions: List[Dict],
        correlation_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Generate complete portfolio summary charts."""
        charts = {}
        
        # Equity curve
        if not equity_history.empty:
            charts['equity'] = self.plotly.create_equity_curve(equity_history)
        
        # Risk heatmap
        if positions:
            charts['risk'] = self.plotly.create_risk_heatmap(positions)
        
        # Correlation
        if not correlation_data.empty:
            charts['correlation'] = self.plotly.create_heatmap(correlation_data)
        
        return charts
    
    def generate_trade_analysis(
        self,
        price_data: pd.DataFrame,
        trades: List[Dict],
        symbol: str
    ) -> Dict[str, Any]:
        """Generate trade analysis charts."""
        charts = {}
        
        # Price chart with trades
        if not price_data.empty:
            charts['price'] = self.plotly.create_candlestick_chart(
                price_data,
                symbol
            )
        
        # P&L waterfall
        if trades:
            charts['pnl'] = self.plotly.create_pnl_waterfall(trades)
        
        return charts
    
    def create_swarm_metrics_chart(
        self,
        agent_data: Dict[str, List[Dict]]
    ) -> Dict[str, Any]:
        """Create swarm agent performance metrics."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return {}
        
        fig = go.Figure()
        
        for agent, metrics in agent_data.items():
            x = [m['timestamp'] for m in metrics]
            y = [m['success_rate'] for m in metrics]
            
            fig.add_trace(go.Scatter(
                x=x,
                y=y,
                name=agent,
                mode='lines+markers'
            ))
        
        fig.update_layout(
            title="Swarm Agent Success Rates",
            xaxis_title="Time",
            yaxis_title="Success Rate",
            template="plotly_dark",
            height=400
        )
        
        return json.loads(fig.to_json())
    
    def create_sentiment_timeline(
        self,
        sentiment_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Create sentiment score timeline."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return {}
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=sentiment_data.index,
            y=sentiment_data['score'],
            name='Sentiment',
            fill='tozeroy',
            line=dict(color='purple')
        ))
        
        fig.add_hline(y=0.5, line_dash="dash", line_color="green")
        fig.add_hline(y=-0.5, line_dash="dash", line_color="red")
        
        fig.update_layout(
            title="Social Media Sentiment Timeline",
            yaxis_title="Sentiment Score",
            template="plotly_dark",
            height=300
        )
        
        return json.loads(fig.to_json())


# Singleton instance
chart_service = DashboardChartService()
plotly_generator = PlotlyChartGenerator()
