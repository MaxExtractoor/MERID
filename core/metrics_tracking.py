"""MERID Prometheus Metrics Tracking.

Metrics collection and monitoring for swarm health, trading performance,
and system performance. Integrates with Prometheus for scraping.
"""

from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import time
import structlog

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.core import CollectorRegistry

logger = structlog.get_logger(__name__)

# Create custom registry
merid_registry = CollectorRegistry()


class MERIDMetrics:
    """Centralized metrics collection for MERID."""
    
    # Trading metrics
    trades_executed = Counter(
        'merid_trades_executed_total',
        'Total number of trades executed',
        ['symbol', 'side', 'status'],
        registry=merid_registry
    )
    
    trade_latency = Histogram(
        'merid_trade_latency_seconds',
        'Trade execution latency',
        ['symbol', 'order_type'],
        buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10],
        registry=merid_registry
    )
    
    portfolio_value = Gauge(
        'merid_portfolio_value_usd',
        'Current portfolio value in USD',
        registry=merid_registry
    )
    
    position_size = Gauge(
        'merid_position_size',
        'Current position size',
        ['symbol'],
        registry=merid_registry
    )
    
    unrealized_pnl = Gauge(
        'merid_unrealized_pnl_usd',
        'Unrealized P&L in USD',
        ['symbol'],
        registry=merid_registry
    )
    
    # Risk metrics
    risk_score = Gauge(
        'merid_risk_score',
        'Current risk score (0-1)',
        ['metric_type'],
        registry=merid_registry
    )
    
    var_95 = Gauge(
        'merid_var_95_usd',
        'Value at Risk (95%) in USD',
        registry=merid_registry
    )
    
    # Swarm metrics
    swarm_agents_active = Gauge(
        'merid_swarm_agents_active',
        'Number of active swarm agents',
        ['agent_type'],
        registry=merid_registry
    )
    
    swarm_decisions = Counter(
        'merid_swarm_decisions_total',
        'Total swarm decisions made',
        ['agent', 'decision'],
        registry=merid_registry
    )
    
    swarm_decision_latency = Histogram(
        'merid_swarm_decision_latency_seconds',
        'Time for swarm agent to make decision',
        ['agent'],
        buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1],
        registry=merid_registry
    )
    
    # System metrics
    api_requests = Counter(
        'merid_api_requests_total',
        'Total API requests',
        ['method', 'endpoint', 'status'],
        registry=merid_registry
    )
    
    api_latency = Histogram(
        'merid_api_latency_seconds',
        'API endpoint latency',
        ['endpoint'],
        buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5],
        registry=merid_registry
    )
    
    websocket_connections = Gauge(
        'merid_websocket_connections',
        'Active WebSocket connections',
        registry=merid_registry
    )
    
    # Sentiment metrics
    sentiment_score = Gauge(
        'merid_sentiment_score',
        'Social media sentiment score',
        ['ticker', 'source'],
        registry=merid_registry
    )
    
    sentiment_mentions = Counter(
        'merid_sentiment_mentions_total',
        'Total social media mentions',
        ['ticker', 'source'],
        registry=merid_registry
    )
    
    # Blockchain metrics
    blockchain_tx_count = Counter(
        'merid_blockchain_tx_total',
        'Total blockchain transactions',
        ['chain', 'status'],
        registry=merid_registry
    )
    
    blockchain_gas_spent = Counter(
        'merid_blockchain_gas_spent',
        'Total gas spent',
        ['chain'],
        registry=merid_registry
    )
    
    # Application info
    app_info = Info(
        'merid_app',
        'MERID application information',
        registry=merid_registry
    )
    
    def __init__(self):
        self.logger = logger.bind(component="MERIDMetrics")
        self._init_app_info()
    
    def _init_app_info(self):
        """Initialize application info metric."""
        self.app_info.info({
            'version': '1.0.0',
            'environment': 'production',
            'build_date': datetime.now().isoformat()
        })
    
    def record_trade(
        self,
        symbol: str,
        side: str,
        status: str,
        latency: Optional[float] = None
    ):
        """Record trade execution."""
        self.trades_executed.labels(
            symbol=symbol,
            side=side,
            status=status
        ).inc()
        
        if latency:
            self.trade_latency.labels(
                symbol=symbol,
                order_type='market'
            ).observe(latency)
        
        self.logger.debug(
            "trade_recorded",
            symbol=symbol,
            side=side,
            status=status
        )
    
    def update_portfolio(self, value: float):
        """Update portfolio value gauge."""
        self.portfolio_value.set(value)
    
    def update_position(self, symbol: str, size: float, pnl: float):
        """Update position metrics."""
        self.position_size.labels(symbol=symbol).set(size)
        self.unrealized_pnl.labels(symbol=symbol).set(pnl)
    
    def record_risk_metrics(
        self,
        var_95: float,
        portfolio_heat: float,
        correlation_risk: float
    ):
        """Record risk metrics."""
        self.var_95.set(var_95)
        self.risk_score.labels(metric_type='portfolio_heat').set(portfolio_heat)
        self.risk_score.labels(metric_type='correlation').set(correlation_risk)
    
    def update_swarm_agents(self, agent_type: str, count: int):
        """Update active swarm agent count."""
        self.swarm_agents_active.labels(agent_type=agent_type).set(count)
    
    def record_swarm_decision(
        self,
        agent: str,
        decision: str,
        latency: Optional[float] = None
    ):
        """Record swarm agent decision."""
        self.swarm_decisions.labels(
            agent=agent,
            decision=decision
        ).inc()
        
        if latency:
            self.swarm_decision_latency.labels(agent=agent).observe(latency)
    
    def record_api_request(
        self,
        method: str,
        endpoint: str,
        status: int,
        latency: Optional[float] = None
    ):
        """Record API request."""
        status_class = f"{status // 100}xx"
        self.api_requests.labels(
            method=method,
            endpoint=endpoint,
            status=status_class
        ).inc()
        
        if latency:
            self.api_latency.labels(endpoint=endpoint).observe(latency)
    
    def update_websocket_connections(self, count: int):
        """Update WebSocket connection count."""
        self.websocket_connections.set(count)
    
    def record_sentiment(
        self,
        ticker: str,
        source: str,
        score: float,
        mentions: int
    ):
        """Record sentiment metrics."""
        self.sentiment_score.labels(
            ticker=ticker,
            source=source
        ).set(score)
        
        self.sentiment_mentions.labels(
            ticker=ticker,
            source=source
        ).inc(mentions)
    
    def record_blockchain_tx(
        self,
        chain: str,
        status: str,
        gas_spent: Optional[float] = None
    ):
        """Record blockchain transaction."""
        self.blockchain_tx_count.labels(
            chain=chain,
            status=status
        ).inc()
        
        if gas_spent:
            self.blockchain_gas_spent.labels(chain=chain).inc(gas_spent)


class PerformanceTracker:
    """Track trading performance metrics."""
    
    def __init__(self):
        self.logger = logger.bind(component="PerformanceTracker")
        self.trades: List[Dict] = []
        self.daily_returns: List[float] = []
        self.equity_curve: List[float] = [100000.0]  # Starting equity
    
    def record_trade(self, trade: Dict[str, Any]):
        """Record completed trade."""
        self.trades.append({
            'timestamp': datetime.now(),
            'symbol': trade.get('symbol'),
            'pnl': trade.get('realized_pnl', 0),
            'return_pct': trade.get('return_pct', 0)
        })
        
        # Update equity curve
        if self.equity_curve:
            new_equity = self.equity_curve[-1] + trade.get('realized_pnl', 0)
            self.equity_curve.append(new_equity)
    
    def calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(self.daily_returns) < 30:
            return 0.0
        
        import numpy as np
        
        returns = np.array(self.daily_returns)
        excess_returns = returns - (risk_free_rate / 252)
        
        if excess_returns.std() == 0:
            return 0.0
        
        sharpe = np.sqrt(252) * excess_returns.mean() / excess_returns.std()
        return sharpe
    
    def calculate_max_drawdown(self) -> Tuple[float, datetime, datetime]:
        """Calculate maximum drawdown with dates."""
        if len(self.equity_curve) < 2:
            return 0.0, datetime.now(), datetime.now()
        
        import numpy as np
        
        equity = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        
        max_dd = drawdown.max()
        max_dd_idx = drawdown.argmax()
        
        # Find peak before max drawdown
        peak_idx = np.argmax(equity[:max_dd_idx]) if max_dd_idx > 0 else 0
        
        return (
            max_dd,
            datetime.now(),  # Would use actual timestamps
            datetime.now()
        )
    
    def calculate_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if not self.trades:
            return 0.0
        
        wins = sum(1 for t in self.trades if t['pnl'] > 0)
        return (wins / len(self.trades)) * 100
    
    def calculate_profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)."""
        if not self.trades:
            return 0.0
        
        gross_profit = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in self.trades if t['pnl'] < 0))
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        
        return gross_profit / gross_loss
    
    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        sharpe = self.calculate_sharpe_ratio()
        max_dd, _, _ = self.calculate_max_drawdown()
        
        return {
            'total_trades': len(self.trades),
            'win_rate': self.calculate_win_rate(),
            'profit_factor': self.calculate_profit_factor(),
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_dd * 100,
            'current_equity': self.equity_curve[-1] if self.equity_curve else 0,
            'total_return_pct': (
                (self.equity_curve[-1] / self.equity_curve[0]) - 1
            ) * 100 if len(self.equity_curve) > 1 else 0
        }


class LatencyTracker:
    """Track latency metrics for various operations."""
    
    def __init__(self):
        self.measurements: Dict[str, List[float]] = {}
        self.logger = logger.bind(component="LatencyTracker")
    
    def measure(self, operation: str) -> 'LatencyContext':
        """Context manager for measuring operation latency."""
        return LatencyContext(self, operation)
    
    def record(self, operation: str, latency: float):
        """Record latency measurement."""
        if operation not in self.measurements:
            self.measurements[operation] = []
        
        self.measurements[operation].append(latency)
        
        # Keep only last 1000 measurements
        if len(self.measurements[operation]) > 1000:
            self.measurements[operation] = self.measurements[operation][-1000:]
    
    def get_stats(self, operation: str) -> Dict[str, float]:
        """Get latency statistics for operation."""
        if operation not in self.measurements:
            return {'count': 0, 'mean': 0, 'p50': 0, 'p95': 0, 'p99': 0}
        
        import numpy as np
        
        times = np.array(self.measurements[operation])
        
        return {
            'count': len(times),
            'mean': float(np.mean(times)),
            'p50': float(np.percentile(times, 50)),
            'p95': float(np.percentile(times, 95)),
            'p99': float(np.percentile(times, 99)),
            'min': float(np.min(times)),
            'max': float(np.max(times))
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get stats for all operations."""
        return {op: self.get_stats(op) for op in self.measurements.keys()}


class LatencyContext:
    """Context manager for latency tracking."""
    
    def __init__(self, tracker: LatencyTracker, operation: str):
        self.tracker = tracker
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            latency = time.time() - self.start_time
            self.tracker.record(self.operation, latency)


# Singleton instances
metrics = MERIDMetrics()
performance_tracker = PerformanceTracker()
latency_tracker = LatencyTracker()


def get_metrics_registry() -> CollectorRegistry:
    """Get the Prometheus metrics registry."""
    return merid_registry


def generate_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest(merid_registry)


def get_metrics_content_type() -> str:
    """Get content type for Prometheus metrics."""
    return CONTENT_TYPE_LATEST
