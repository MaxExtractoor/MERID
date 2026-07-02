"""
MVRK Live Trading Integration with Kalshi Orders

Live trading integration with sizing service and order execution for MVRK strategy.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class Position:
    """Position data structure."""
    asset: str
    current_notional: float
    contracts: int
    avg_price: float
    unrealized_pnl: float
    last_updated: float

@dataclass
class Order:
    """Order data structure."""
    asset: str
    side: OrderSide
    quantity: float
    price: Optional[float]
    status: OrderStatus
    order_id: Optional[str]
    timestamp: float
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None

class MVRKLIVETradingService:
    """
    MVRK live trading service with sizing and order management.
    """
    
    def __init__(self, 
                 total_risk_notional: float = 10000.0,
                 min_order_size: float = 100.0,
                 max_position_size: float = 5000.0,
                 rebalance_threshold: float = 0.1):
        """
        Initialize MVRK live trading service.
        
        Args:
            total_risk_notional: Total risk budget for the portfolio
            min_order_size: Minimum order size in notional
            max_position_size: Maximum position size per asset
            rebalance_threshold: Threshold for triggering rebalancing (10%)
        """
        self.total_risk_notional = total_risk_notional
        self.min_order_size = min_order_size
        self.max_position_size = max_position_size
        self.rebalance_threshold = rebalance_threshold
        
        self.current_positions: Dict[str, Position] = {}
        self.pending_orders: List[Order] = []
        self.last_rebalance_time = 0.0
        self.rebalance_interval = 300.0  # 5 minutes
        
        logger.info(f"MVRK live trading service initialized: notional=${total_risk_notional:,.0f}")
    
    def compute_live_mvrk_sizes(self, 
                               returns_df: pd.DataFrame, 
                               theta: float = 1.0) -> Dict[str, float]:
        """
        Compute live MVRK target sizes from returns data.
        
        Args:
            returns_df: DataFrame with asset returns
            theta: MVRK theta parameter
            
        Returns:
            Dictionary of target notionals per asset
        """
        try:
            from .mvrk_kalshi import run_mvrk_on_kalshi
            
            # Run MVRK calculation
            result = run_mvrk_on_kalshi(returns_df, theta=theta)
            
            # Extract weights (sum |w| = 1)
            weights = result.w_mvrk
            
            # Convert weights to target notionals
            target_sizes = {}
            for asset, weight in zip(result.assets, weights):
                target_notional = self.total_risk_notional * weight
                
                # Apply position size limits
                target_notional = np.clip(
                    target_notional,
                    -self.max_position_size,
                    self.max_position_size
                )
                
                target_sizes[asset] = target_notional
            
            logger.info(f"Computed MVRK target sizes: {len(target_sizes)} assets")
            return target_sizes
            
        except Exception as e:
            logger.error(f"Error computing MVRK sizes: {e}")
            return {}
    
    def get_current_positions(self) -> Dict[str, Position]:
        """
        Get current positions from Kalshi API.
        
        Returns:
            Dictionary of current positions
        """
        try:
            # This would integrate with your Kalshi private client
            positions_data = self._fetch_kalshi_positions()
            
            current_positions = {}
            for asset_data in positions_data:
                position = Position(
                    asset=asset_data['asset'],
                    current_notional=asset_data['notional'],
                    contracts=asset_data['contracts'],
                    avg_price=asset_data['avg_price'],
                    unrealized_pnl=asset_data['unrealized_pnl'],
                    last_updated=asset_data['last_updated']
                )
                current_positions[asset] = position
            
            self.current_positions = current_positions
            return current_positions
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return self.current_positions
    
    def _fetch_kalshi_positions(self) -> List[Dict[str, Any]]:
        """
        Fetch positions from Kalshi API (placeholder implementation).
        
        Returns:
            List of position data
        """
        # This would integrate with your actual Kalshi private client
        # For now, return empty positions
        return []
    
    def calculate_rebalance_orders(self, 
                                 target_sizes: Dict[str, float]) -> List[Order]:
        """
        Calculate orders needed to rebalance to target sizes.
        
        Args:
            target_sizes: Target notionals per asset
            
        Returns:
            List of orders to execute
        """
        orders = []
        current_positions = self.get_current_positions()
        
        for asset, target_notional in target_sizes.items():
            current_notional = current_positions.get(asset, Position(asset, 0, 0, 0, 0, 0)).current_notional
            delta = target_notional - current_notional
            
            # Skip if change is below minimum order size
            if abs(delta) < self.min_order_size:
                continue
            
            # Determine order side
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            
            # Calculate quantity (convert notional to contracts)
            # This would depend on Kalshi contract specifications
            quantity = abs(delta)  # Simplified - would need actual conversion
            
            order = Order(
                asset=asset,
                side=side,
                quantity=quantity,
                price=None,  # Market order
                status=OrderStatus.PENDING,
                order_id=None,
                timestamp=time.time()
            )
            
            orders.append(order)
            
            logger.info(f"Rebalance order: {asset} {side.value} {quantity:.2f} (delta: {delta:+.2f})")
        
        return orders
    
    def execute_orders(self, orders: List[Order]) -> List[Order]:
        """
        Execute orders through Kalshi API.
        
        Args:
            orders: List of orders to execute
            
        Returns:
            List of executed orders with updated status
        """
        executed_orders = []
        
        for order in orders:
            try:
                # Execute order through Kalshi API
                executed_order = self._execute_single_order(order)
                executed_orders.append(executed_order)
                
                # Update pending orders
                if executed_order.status == OrderStatus.PENDING:
                    self.pending_orders.append(executed_order)
                
            except Exception as e:
                logger.error(f"Error executing order {order.asset}: {e}")
                order.status = OrderStatus.REJECTED
                executed_orders.append(order)
        
        return executed_orders
    
    def _execute_single_order(self, order: Order) -> Order:
        """
        Execute a single order through Kalshi API.
        
        Args:
            order: Order to execute
            
        Returns:
            Updated order with execution results
        """
        try:
            # This would integrate with your actual Kalshi private client
            # For now, simulate order execution
            
            # Simulate API call
            order_id = f"order_{int(time.time() * 1000)}"
            
            # Simulate immediate fill (in reality, this would be async)
            order.order_id = order_id
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.avg_fill_price = self._get_market_price(order.asset)
            
            logger.info(f"Order executed: {order.asset} {order.side.value} {order.quantity:.2f} @ {order.avg_fill_price:.4f}")
            
            return order
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            order.status = OrderStatus.REJECTED
            return order
    
    def _get_market_price(self, asset: str) -> float:
        """
        Get current market price for an asset.
        
        Args:
            asset: Asset ticker
            
        Returns:
            Current market price
        """
        # This would fetch from Kalshi API
        # For now, return placeholder price
        return 0.5  # 50 cents for yes/no contracts
    
    def rebalance_portfolio(self, 
                          returns_df: pd.DataFrame,
                          theta: float = 1.0,
                          force_rebalance: bool = False) -> Dict[str, Any]:
        """
        Rebalance portfolio to MVRK target sizes.
        
        Args:
            returns_df: DataFrame with asset returns
            theta: MVRK theta parameter
            force_rebalance: Force rebalance regardless of threshold
            
        Returns:
            Rebalancing results
        """
        current_time = time.time()
        
        # Check if rebalance is needed
        time_since_rebalance = current_time - self.last_rebalance_time
        if not force_rebalance and time_since_rebalance < self.rebalance_interval:
            logger.info(f"Rebalance not needed (last: {time_since_rebalance:.0f}s ago)")
            return {"status": "skipped", "reason": "too_soon"}
        
        # Compute MVRK target sizes
        target_sizes = self.compute_live_mvrk_sizes(returns_df, theta)
        
        if not target_sizes:
            return {"status": "error", "reason": "no_targets"}
        
        # Calculate rebalance orders
        orders = self.calculate_rebalance_orders(target_sizes)
        
        if not orders:
            return {"status": "no_action", "reason": "no_orders_needed"}
        
        # Execute orders
        executed_orders = self.execute_orders(orders)
        
        # Update rebalance time
        self.last_rebalance_time = current_time
        
        # Prepare results
        results = {
            "status": "executed",
            "target_sizes": target_sizes,
            "orders_count": len(executed_orders),
            "successful_orders": len([o for o in executed_orders if o.status == OrderStatus.FILLED]),
            "failed_orders": len([o for o in executed_orders if o.status == OrderStatus.REJECTED]),
            "orders": executed_orders
        }
        
        logger.info(f"Rebalance completed: {results['successful_orders']}/{results['orders_count']} orders filled")
        
        return results
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Get current portfolio summary.
        
        Returns:
            Portfolio summary statistics
        """
        current_positions = self.get_current_positions()
        
        total_notional = sum(pos.current_notional for pos in current_positions.values())
        total_pnl = sum(pos.unrealized_pnl for pos in current_positions.values())
        
        summary = {
            "total_notional": total_notional,
            "total_pnl": total_pnl,
            "positions_count": len(current_positions),
            "pending_orders_count": len(self.pending_orders),
            "last_rebalance": self.last_rebalance_time,
            "risk_utilization": total_notional / self.total_risk_notional,
            "positions": {asset: {
                "notional": pos.current_notional,
                "contracts": pos.contracts,
                "pnl": pos.unrealized_pnl
            } for asset, pos in current_positions.items()}
        }
        
        return summary

class KalshiMVRKTrader:
    """
    High-level Kalshi MVRK trading interface.
    """
    
    def __init__(self, 
                 api_key: str,
                 api_secret: str,
                 total_risk_notional: float = 10000.0):
        """
        Initialize Kalshi MVRK trader.
        
        Args:
            api_key: Kalshi API key
            api_secret: Kalshi API secret
            total_risk_notional: Total risk budget
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_service = MVRKLIVETradingService(total_risk_notional)
        
        logger.info("Kalshi MVRK trader initialized")
    
    def run_live_trading_loop(self, 
                            update_interval: int = 60,
                            returns_window: int = 1000) -> None:
        """
        Run continuous live trading loop.
        
        Args:
            update_interval: Update interval in seconds
            returns_window: Window size for returns calculation
        """
        logger.info(f"Starting live trading loop: {update_interval}s interval, {returns_window} return window")
        
        while True:
            try:
                # Get recent returns data
                returns_df = self._get_recent_returns(returns_window)
                
                if returns_df.empty:
                    logger.warning("No returns data available")
                    time.sleep(update_interval)
                    continue
                
                # Rebalance portfolio
                results = self.trading_service.rebalance_portfolio(returns_df, theta=1.0)
                
                # Log results
                if results["status"] == "executed":
                    logger.info(f"Rebalance executed: {results['successful_orders']}/{results['orders_count']} filled")
                elif results["status"] == "skipped":
                    logger.debug(f"Rebalance skipped: {results['reason']}")
                
                # Get portfolio summary
                summary = self.trading_service.get_portfolio_summary()
                logger.info(f"Portfolio: ${summary['total_notional']:,.0f} notional, ${summary['total_pnl']:,.2f} PnL")
                
                # Wait for next update
                time.sleep(update_interval)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(update_interval)
    
    def _get_recent_returns(self, window: int) -> pd.DataFrame:
        """
        Get recent returns data for MVRK calculation.
        
        Args:
            window: Number of recent periods to include
            
        Returns:
            DataFrame with recent returns
        """
        # This would fetch from your data source
        # For now, return empty DataFrame
        return pd.DataFrame()

# Example usage:
"""
# Initialize trader
trader = KalshiMVRKTrader(
    api_key="your_api_key",
    api_secret="your_api_secret",
    total_risk_notional=50000.0
)

# Get current positions
positions = trader.trading_service.get_current_positions()
print(f"Current positions: {len(positions)}")

# Compute MVRK target sizes
returns_df = get_recent_returns()  # Your data fetching function
target_sizes = trader.trading_service.compute_live_mvrk_sizes(returns_df)
print(f"Target sizes: {target_sizes}")

# Rebalance portfolio
results = trader.trading_service.rebalance_portfolio(returns_df)
print(f"Rebalance results: {results}")

# Run live trading loop
# trader.run_live_trading_loop(update_interval=60, returns_window=1000)
"""

# =============================================================================
# SCHEDULER INTEGRATION
# =============================================================================

class MVRKTradingScheduler:
    """
    Scheduler for automated MVRK trading with configurable intervals.
    """
    
    def __init__(self, trader: KalshiMVRKTrader):
        """
        Initialize trading scheduler.
        
        Args:
            trader: Kalshi MVRK trader instance
        """
        self.trader = trader
        self.is_running = False
        self.scheduler_thread = None
        
    def start_scheduler(self, 
                        rebalance_interval: int = 300,  # 5 minutes
                        returns_window: int = 1000) -> None:
        """
        Start automated trading scheduler.
        
        Args:
            rebalance_interval: Rebalancing interval in seconds
            returns_window: Returns window for MVRK calculation
        """
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        self.is_running = True
        
        def scheduler_loop():
            while self.is_running:
                try:
                    # Get recent returns
                    returns_df = self.trader._get_recent_returns(returns_window)
                    
                    if not returns_df.empty:
                        # Rebalance portfolio
                        results = self.trader.trading_service.rebalance_portfolio(returns_df)
                        
                        if results["status"] == "executed":
                            logger.info(f"Scheduled rebalance: {results['successful_orders']}/{results['orders_count']} filled")
                    
                    # Wait for next interval
                    time.sleep(rebalance_interval)
                    
                except Exception as e:
                    logger.error(f"Error in scheduler loop: {e}")
                    time.sleep(rebalance_interval)
        
        import threading
        
        self.scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        
        logger.info(f"Trading scheduler started: {rebalance_interval}s interval")
    
    def stop_scheduler(self) -> None:
        """Stop automated trading scheduler."""
        self.is_running = False
        
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=10)
        
        logger.info("Trading scheduler stopped")

# =============================================================================
# MONITORING AND ALERTS
# =============================================================================

class MVRKTradingMonitor:
    """
    Monitor MVRK trading performance and send alerts.
    """
    
    def __init__(self, trader: KalshiMVRKTrader):
        """
        Initialize trading monitor.
        
        Args:
            trader: Kalshi MVRK trader instance
        """
        self.trader = trader
        self.alert_thresholds = {
            "max_drawdown": 0.1,  # 10%
            "max_position_size": 0.8,  # 80% of max
            "min_risk_utilization": 0.1,  # 10%
            "max_risk_utilization": 0.9,  # 90%
        }
    
    def check_alerts(self) -> List[str]:
        """
        Check for trading alerts.
        
        Returns:
            List of alert messages
        """
        alerts = []
        
        # Get portfolio summary
        summary = self.trading.trading_service.get_portfolio_summary()
        
        # Check drawdown
        if summary["total_pnl"] < -self.alert_thresholds["max_drawdown"] * summary["total_notional"]:
            alerts.append(f"🔴 High drawdown: {summary['total_pnl']:.2%}")
        
        # Check position sizes
        for asset, pos_data in summary["positions"].items():
            position_ratio = abs(pos_data["notional"]) / self.trader.trading_service.max_position_size
            if position_ratio > self.alert_thresholds["max_position_size"]:
                alerts.append(f"🟡 Large position: {asset} ({position_ratio:.1%} of max)")
        
        # Check risk utilization
        risk_util = summary["risk_utilization"]
        if risk_util < self.alert_thresholds["min_risk_utilization"]:
            alerts.append(f"🟡 Low risk utilization: {risk_util:.1%}")
        elif risk_util > self.alert_thresholds["max_risk_utilization"]:
            alerts.append(f"🔴 High risk utilization: {risk_util:.1%}")
        
        return alerts
    
    def send_alerts(self, alerts: List[str]) -> None:
        """
        Send alerts (placeholder implementation).
        
        Args:
            alerts: List of alert messages
        """
        for alert in alerts:
            logger.warning(f"ALERT: {alert}")
            # This would integrate with your alerting system (email, Slack, etc.)

# Example integration:
"""
# Initialize components
trader = KalshiMVRKTrader(api_key="key", api_secret="secret", total_risk_notional=50000)
scheduler = MVRKTradingScheduler(trader)
monitor = MVRKTradingMonitor(trader)

# Start automated trading
scheduler.start_scheduler(rebalance_interval=300, returns_window=1000)

# Monitor and send alerts
while True:
    alerts = monitor.check_alerts()
    if alerts:
        monitor.send_alerts(alerts)
    
    time.sleep(60)  # Check alerts every minute
"""
