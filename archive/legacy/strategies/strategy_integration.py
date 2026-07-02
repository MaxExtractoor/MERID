"""
Strategy Integration - Connect 15m Crypto Strategy to Event Infrastructure

This module integrates the 15m crypto strategy with the existing event-driven infrastructure,
providing a complete trading loop from signal generation to execution and monitoring.
"""

import asyncio
import schedule
import time
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from merid.strategies.crypto_15m_strategy import crypto_15m_strategy, Signal, Trade
from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent, KalshiRateAwareClient
from merid.kalshi.maker_bot_advanced import KalshiTelegramNotifier, KalshiXNotifier

logger = logging.getLogger(__name__)

class StrategyManager:
    """Manages the 15m crypto strategy with event-driven integration."""
    
    def __init__(self):
        """Initialize the strategy manager."""
        self.strategy = crypto_15m_strategy
        self.client = KalshiRateAwareClient(safety_factor=0.8)
        self.running = False
        self.last_cycle_time = 0
        self.cycle_interval = 15 * 60  # 15 minutes in seconds
        
        # Initialize notifiers if available
        self.telegram_notifier = None
        self.x_notifier = None
        
        try:
            self.telegram_notifier = KalshiTelegramNotifier()
            self.x_notifier = KalshiXNotifier()
        except Exception as e:
            logger.warning(f"Could not initialize notifiers: {e}")
        
        # Performance tracking
        self.daily_stats = {
            "signals": 0,
            "trades": 0,
            "pnl": 0.0,
            "errors": 0
        }
        
        # Subscribe to strategy events
        kalshi_event_bus.subscribe(self._handle_strategy_event)
        
        logger.info("Strategy Manager initialized")
    
    def _handle_strategy_event(self, event: KalshiEvent):
        """Handle strategy-related events."""
        try:
            if event.type == "position_update":
                self._handle_position_update(event)
            elif event.type == "order_fill":
                self._handle_order_fill(event)
            elif event.type == "order_reject":
                self._handle_order_reject(event)
                
        except Exception as e:
            logger.error(f"Error handling strategy event {event.type}: {e}")
    
    def _handle_position_update(self, event: KalshiEvent):
        """Handle position update events."""
        payload = event.payload
        
        # Send notifications for significant events
        if "strategy_cycle" in payload:
            cycle_data = payload["strategy_cycle"]
            if cycle_data["trades_executed"] > 0:
                self._send_trade_notification(cycle_data)
        
        # Send PnL notifications
        if "pnl" in payload and abs(payload["pnl"]) > 100:  # Significant PnL
            self._send_pnl_notification(payload)
    
    def _handle_order_fill(self, event: KalshiEvent):
        """Handle order fill events."""
        payload = event.payload
        
        # Send notification for order fills
        if self.telegram_notifier:
            self.telegram_notifier._handle_event(event)
    
    def _handle_order_reject(self, event: KalshiEvent):
        """Handle order rejection events."""
        payload = event.payload
        
        # Send notification for order rejections
        if self.telegram_notifier:
            self.telegram_notifier._handle_event(event)
    
    def _send_trade_notification(self, cycle_data: Dict[str, Any]):
        """Send trade execution notification."""
        if not self.telegram_notifier:
            return
        
        message = f"🔄 Strategy Cycle Complete\n"
        message += f"📊 Signals: {cycle_data['signals_generated']}\n"
        message += f"💼 Trades: {cycle_data['trades_executed']}\n"
        message += f"📈 Active: {cycle_data['active_trades']}"
        
        # Create event for notification
        event = KalshiEvent(
            type="position_update",
            payload={"message": message, "cycle_data": cycle_data},
            ts=time.time(),
            source="strategy_manager"
        )
        
        self.telegram_notifier._handle_event(event)
    
    def _send_pnl_notification(self, pnl_data: Dict[str, Any]):
        """Send PnL notification."""
        if not self.telegram_notifier:
            return
        
        pnl = pnl_data.get("pnl", 0)
        ticker = pnl_data.get("ticker", "Unknown")
        
        if pnl > 0:
            message = f"📈 Profit: ${pnl:.2f} on {ticker}"
        else:
            message = f"📉 Loss: ${pnl:.2f} on {ticker}"
        
        # Create event for notification
        event = KalshiEvent(
            type="position_update",
            payload={"message": message, "pnl_data": pnl_data},
            ts=time.time(),
            source="strategy_manager"
        )
        
        self.telegram_notifier._handle_event(event)
    
    def start_strategy(self):
        """Start the strategy manager."""
        if self.running:
            logger.warning("Strategy manager already running")
            return
        
        self.running = True
        
        # Start notifiers
        if self.telegram_notifier:
            self.telegram_notifier.start()
        if self.x_notifier:
            self.x_notifier.start()
        
        # Start strategy cycles
        self._run_strategy_loop()
        
        logger.info("Strategy manager started")
    
    def stop_strategy(self):
        """Stop the strategy manager."""
        self.running = False
        
        # Stop notifiers
        if self.telegram_notifier:
            self.telegram_notifier.stop()
        if self.x_notifier:
            self.x_notifier.stop()
        
        logger.info("Strategy manager stopped")
    
    def _run_strategy_loop(self):
        """Run the main strategy loop."""
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time for a new cycle
                if current_time - self.last_cycle_time >= self.cycle_interval:
                    self._run_strategy_cycle()
                    self.last_cycle_time = current_time
                
                # Sleep for a short interval
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in strategy loop: {e}")
                self.daily_stats["errors"] += 1
                
                # Emit error event
                kalshi_event_bus.publish(KalshiEvent(
                    type="api_error",
                    payload={
                        "error": "Strategy loop error",
                        "details": str(e)
                    },
                    ts=time.time(),
                    source="strategy_manager"
                ))
                
                time.sleep(60)  # Wait longer after error
    
    def _run_strategy_cycle(self):
        """Run one complete strategy cycle."""
        try:
            logger.info("Starting strategy cycle")
            
            # Run the strategy
            self.strategy.run_strategy_cycle()
            
            # Update daily stats
            status = self.strategy.get_strategy_status()
            self.daily_stats["signals"] += status.get("recent_signals", 0)
            self.daily_stats["trades"] += len(self.strategy.active_trades)
            self.daily_stats["pnl"] += status.get("total_pnl", 0)
            
            # Emit cycle completion event
            kalshi_event_bus.publish(KalshiEvent(
                type="position_update",
                payload={
                    "event": "strategy_cycle_completed",
                    "timestamp": time.time(),
                    "status": status,
                    "daily_stats": self.daily_stats.copy()
                },
                ts=time.time(),
                source="strategy_manager"
            ))
            
            logger.info(f"Strategy cycle completed: {status}")
            
        except Exception as e:
            logger.error(f"Error in strategy cycle: {e}")
            self.daily_stats["errors"] += 1
    
    def run_manual_cycle(self):
        """Run a manual strategy cycle for testing."""
        logger.info("Running manual strategy cycle")
        self._run_strategy_cycle()
    
    def get_strategy_report(self) -> Dict[str, Any]:
        """Get comprehensive strategy report."""
        strategy_status = self.strategy.get_strategy_status()
        
        report = {
            "timestamp": time.time(),
            "strategy_status": strategy_status,
            "daily_stats": self.daily_stats.copy(),
            "cycle_interval": self.cycle_interval,
            "last_cycle_time": self.last_cycle_time,
            "running": self.running
        }
        
        return report
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get detailed performance metrics."""
        metrics = self.strategy.metrics
        
        performance = {
            "total_trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
            "total_pnl": metrics.total_pnl,
            "total_fees": metrics.total_fees,
            "net_pnl": metrics.total_pnl - metrics.total_fees,
            "max_drawdown": metrics.max_drawdown,
            "sharpe_ratio": metrics.sharpe_ratio,
            "avg_trade_duration": metrics.avg_trade_duration,
            "current_positions": metrics.current_positions,
            "daily_stats": self.daily_stats.copy()
        }
        
        return performance
    
    def get_active_positions(self) -> List[Dict[str, Any]]:
        """Get information about active positions."""
        positions = []
        
        for trade_id, trade in self.strategy.active_trades.items():
            position_info = {
                "trade_id": trade_id,
                "ticker": trade.signal.ticker,
                "signal_type": trade.signal.signal_type.value,
                "status": trade.status.value,
                "filled_quantity": trade.filled_quantity,
                "filled_price": trade.filled_price,
                "entry_time": trade.entry_time,
                "entry_price": trade.signal.entry_price,
                "target_price": trade.signal.target_price,
                "stop_loss": trade.signal.stop_loss,
                "current_pnl": trade.pnl,
                "duration": time.time() - trade.entry_time if trade.entry_time else 0
            }
            
            positions.append(position_info)
        
        return positions
    
    def get_recent_signals(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent trading signals."""
        recent_signals = []
        
        # Get recent signals from strategy
        all_signals = self.strategy.signals
        recent_signals = all_signals[-limit:] if len(all_signals) > limit else all_signals
        
        signal_list = []
        for signal in recent_signals:
            signal_info = {
                "signal_type": signal.signal_type.value,
                "ticker": signal.ticker,
                "confidence": signal.confidence,
                "entry_price": signal.entry_price,
                "target_price": signal.target_price,
                "stop_loss": signal.stop_loss,
                "position_size": signal.position_size,
                "timestamp": signal.timestamp,
                "reasoning": signal.reasoning,
                "expected_return": signal.expected_return,
                "risk_reward_ratio": signal.risk_reward_ratio
            }
            
            signal_list.append(signal_info)
        
        return signal_list
    
    def reset_daily_stats(self):
        """Reset daily statistics."""
        self.daily_stats = {
            "signals": 0,
            "trades": 0,
            "pnl": 0.0,
            "errors": 0
        }
        
        logger.info("Daily statistics reset")

# Strategy manager singleton
strategy_manager = StrategyManager()

# Example usage:
"""
# Initialize and start strategy
manager = StrategyManager()
manager.start_strategy()

# Run manual cycle for testing
manager.run_manual_cycle()

# Get reports
report = manager.get_strategy_report()
performance = manager.get_performance_metrics()
positions = manager.get_active_positions()
signals = manager.get_recent_signals()

# Stop strategy
manager.stop_strategy()
"""

# Command line interface for testing
if __name__ == "__main__":
    import sys
    
    def print_help():
        print("Strategy Manager CLI")
        print("Usage: python strategy_integration.py [command]")
        print("Commands:")
        print("  start     - Start the strategy")
        print("  stop      - Stop the strategy")
        print("  cycle     - Run manual cycle")
        print("  report    - Get strategy report")
        print("  performance - Get performance metrics")
        print("  positions - Get active positions")
        print("  signals   - Get recent signals")
        print("  reset     - Reset daily stats")
        print("  help      - Show this help")
    
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "start":
        strategy_manager.start_strategy()
        print("Strategy started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            strategy_manager.stop_strategy()
            print("Strategy stopped.")
    
    elif command == "stop":
        strategy_manager.stop_strategy()
        print("Strategy stopped.")
    
    elif command == "cycle":
        strategy_manager.run_manual_cycle()
        print("Manual cycle completed.")
    
    elif command == "report":
        report = strategy_manager.get_strategy_report()
        print("Strategy Report:")
        for key, value in report.items():
            print(f"  {key}: {value}")
    
    elif command == "performance":
        performance = strategy_manager.get_performance_metrics()
        print("Performance Metrics:")
        for key, value in performance.items():
            print(f"  {key}: {value}")
    
    elif command == "positions":
        positions = strategy_manager.get_active_positions()
        print(f"Active Positions ({len(positions)}):")
        for pos in positions:
            print(f"  {pos['ticker']}: {pos['filled_quantity']} @ {pos['filled_price']}")
    
    elif command == "signals":
        signals = strategy_manager.get_recent_signals()
        print(f"Recent Signals ({len(signals)}):")
        for signal in signals:
            print(f"  {signal['ticker']}: {signal['signal_type']} (conf: {signal['confidence']:.2f})")
    
    elif command == "reset":
        strategy_manager.reset_daily_stats()
        print("Daily statistics reset.")
    
    elif command == "help":
        print_help()
    
    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)
