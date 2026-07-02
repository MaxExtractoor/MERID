"""
15M Strategy Engine - Order Management with Event Bus Integration

High-level strategy engine that orchestrates signal generation, risk management,
and order execution using the existing event-driven infrastructure.
"""

import time
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass

from config.kalshi_crypto_config import kalshi_ticker_to_asset
from config.kalshi_universe import KALSHI_CRYPTO_ASSETS
from merid.event_venues.kalshi.market_selector import resolve_series_ticker

from .signals_15m import compute_signals_15m, Signal, Side, price_service
from .risk_15m import RiskManager, RiskConfig
from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent, KalshiRateAwareClient

logger = logging.getLogger(__name__)

@dataclass
class DesiredPosition:
    """Desired position for an asset."""
    asset: str
    ticker: str
    side: str  # "long_up" or "long_down"
    contracts: int
    signal: Signal

class Strategy15mEngine:
    """15-minute crypto strategy engine with event-driven order management."""
    
    def __init__(self, risk_config: Optional[RiskConfig] = None):
        """Initialize the strategy engine."""
        self.risk_config = risk_config or RiskConfig(capital_usd=100000.0)
        self.risk_manager = RiskManager(self.risk_config)
        self.client = KalshiRateAwareClient(safety_factor=0.8)
        
        # Asset to ticker mapping (canonical five assets; UP/DOWN placeholders for tests)
        self.asset_ticker_map = {}
        for _a in KALSHI_CRYPTO_ASSETS:
            base = resolve_series_ticker(_a, "15m")
            self.asset_ticker_map[(_a, "long_up")] = f"{base}-UP"
            self.asset_ticker_map[(_a, "long_down")] = f"{base}-DOWN"
        
        # Strategy state
        self.current_positions: Dict[str, int] = {}
        self.last_bar_time = 0.0
        self.cycle_count = 0
        
        # Subscribe to event bus for order fills
        kalshi_event_bus.subscribe(self._handle_event)
        
        logger.info("15M Strategy Engine initialized")
    
    def _handle_event(self, event: KalshiEvent):
        """Handle events from the event bus."""
        try:
            if event.type == "order_fill":
                self._handle_order_fill(event)
            elif event.type == "order_reject":
                self._handle_order_reject(event)
            elif event.type == "position_update":
                self._handle_position_update(event)
            elif event.type == "api_error":
                self._handle_api_error(event)
                
        except Exception as e:
            logger.error(f"Error handling event {event.type}: {e}")
    
    def _handle_order_fill(self, event: KalshiEvent):
        """Handle order fill events."""
        payload = event.payload
        ticker = payload.get("ticker")
        count = payload.get("count", 0)
        side = payload.get("side")
        
        if ticker and count:
            # Update risk manager position
            asset = self._ticker_to_asset(ticker)
            if asset:
                # Convert side to position sign
                position_change = count if side == "buy" else -count
                self.risk_manager.update_position(asset, position_change)
                
                # Emit strategy event
                kalshi_event_bus.publish(KalshiEvent(
                    type="position_update",
                    payload={
                        "strategy": "15m_engine",
                        "ticker": ticker,
                        "asset": asset,
                        "contracts": position_change,
                        "side": side,
                        "timestamp": event.ts
                    },
                    ts=time.time(),
                    source="15m_strategy"
                ))
                
                logger.info(f"Position updated: {asset} {position_change} contracts")
    
    def _handle_order_reject(self, event: KalshiEvent):
        """Handle order rejection events."""
        payload = event.payload
        logger.warning(f"Order rejected: {payload}")
        
        # Emit strategy error event
        kalshi_event_bus.publish(KalshiEvent(
            type="api_error",
            payload={
                "strategy": "15m_engine",
                "error": "order_rejected",
                "details": payload
            },
            ts=time.time(),
            source="15m_strategy"
        ))
    
    def _handle_position_update(self, event: KalshiEvent):
        """Handle position update events."""
        payload = event.payload
        
        # Update current positions if this is from external source
        if "positions" in payload:
            for pos in payload["positions"]:
                ticker = pos.get("ticker")
                count = pos.get("count", 0)
                if ticker:
                    asset = self._ticker_to_asset(ticker)
                    if asset:
                        self.current_positions[ticker] = count
    
    def _handle_api_error(self, event: KalshiEvent):
        """Handle API error events."""
        payload = event.payload
        logger.error(f"API error in strategy: {payload}")
    
    def _ticker_to_asset(self, ticker: str) -> Optional[str]:
        """Convert Kalshi market ticker to canonical asset."""
        return kalshi_ticker_to_asset(ticker)
    
    def _desired_side_to_ticker(self, asset: str, side: str) -> Optional[str]:
        """Map asset+side to specific Kalshi contract ticker."""
        key = (asset, side)
        return self.asset_ticker_map.get(key)
    
    def _fetch_current_positions(self) -> Dict[str, int]:
        """Fetch current positions from portfolio."""
        try:
            response = self.client.get("/portfolio/positions")
            if response and "positions" in response:
                positions = {}
                for pos in response["positions"]:
                    ticker = pos.get("ticker")
                    count = pos.get("count", 0)
                    if ticker:
                        positions[ticker] = count
                return positions
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")
        
        return {}
    
    def run_bar(self, prices: Dict[str, "pd.DataFrame"]) -> Dict[str, any]:
        """
        Run one strategy bar cycle.
        
        Args:
            prices: Dict of asset -> OHLCV DataFrame
            
        Returns:
            Dict with cycle results
        """
        cycle_start = time.time()
        self.cycle_count += 1
        
        logger.info(f"Running strategy bar #{self.cycle_count}")
        
        # 1. Generate signals
        signals = compute_signals_15m(prices, cycle_start, z_thresh=0.7)
        
        # 2. Fetch current positions
        current_positions = self._fetch_current_positions()
        self.current_positions = current_positions
        
        # 3. Determine desired positions
        desired_positions = self._compute_desired_positions(signals)
        
        # 4. Generate and execute orders
        orders_placed = self._execute_orders(desired_positions, current_positions)
        
        # 5. Emit cycle completion event
        cycle_results = {
            "cycle_number": self.cycle_count,
            "signals_generated": len(signals),
            "desired_positions": len(desired_positions),
            "orders_placed": len(orders_placed),
            "current_positions": current_positions,
            "cycle_duration": time.time() - cycle_start
        }
        
        kalshi_event_bus.publish(KalshiEvent(
            type="position_update",
            payload={
                "strategy_cycle": cycle_results,
                "signals": [
                    {
                        "asset": s.asset,
                        "side": s.side,
                        "strength": s.strength,
                        "reasoning": s.reasoning
                    } for s in signals
                ]
            },
            ts=time.time(),
            source="15m_strategy"
        ))
        
        logger.info(f"Strategy cycle completed: {cycle_results}")
        
        return cycle_results
    
    def _compute_desired_positions(self, signals: List[Signal]) -> List[DesiredPosition]:
        """Compute desired positions from signals."""
        desired_positions = []
        
        for signal in signals:
            if signal.side == "flat":
                continue
            
            # Map signal to ticker
            ticker = self._desired_side_to_ticker(signal.asset, signal.side)
            if not ticker:
                logger.warning(f"No ticker mapping for {signal.asset}/{signal.side}")
                continue
            
            # Compute position size
            contracts = self.risk_manager.compute_position_size(signal.strength, signal.asset)
            if contracts <= 0:
                continue
            
            desired_position = DesiredPosition(
                asset=signal.asset,
                ticker=ticker,
                side=signal.side,
                contracts=contracts,
                signal=signal
            )
            
            desired_positions.append(desired_position)
        
        return desired_positions
    
    def _execute_orders(self, desired_positions: List[DesiredPosition], current_positions: Dict[str, int]) -> List[Dict[str, any]]:
        """Execute orders to move to desired positions."""
        orders_placed = []
        
        for desired_pos in desired_positions:
            current_count = current_positions.get(desired_pos.ticker, 0)
            target_count = desired_pos.contracts
            
            # For v1, only increase positions (no closing logic)
            if current_count >= target_count:
                logger.info(f"Current position {current_count} >= target {target_count} for {desired_pos.ticker}")
                continue
            
            delta = target_count - current_count
            
            # Check risk limits
            if not self.risk_manager.check_risk_limits(desired_pos.asset, delta, desired_pos.side):
                logger.warning(f"Risk limits exceeded for {desired_pos.asset}")
                continue
            
            # Place order
            order = {
                "ticker": desired_pos.ticker,
                "side": "buy",
                "count": delta,
                "order_type": "market",  # Use market orders for simplicity
                "reason": f"15m_strategy_{desired_pos.signal.side}"
            }
            
            try:
                response = self.client.post("/portfolio/orders", json=order)
                
                if response and response.get("success"):
                    orders_placed.append({
                        "order": order,
                        "response": response,
                        "signal": desired_pos.signal
                    })
                    
                    logger.info(f"Order placed: {desired_pos.ticker} {delta} contracts")
                    
                    # Emit order event
                    kalshi_event_bus.publish(KalshiEvent(
                        type="position_update",
                        payload={
                            "strategy": "15m_engine",
                            "action": "order_placed",
                            "order": order,
                            "signal": {
                                "asset": desired_pos.asset,
                                "side": desired_pos.side,
                                "strength": desired_pos.signal.strength,
                                "reasoning": desired_pos.signal.reasoning
                            }
                        },
                        ts=time.time(),
                        source="15m_strategy"
                    ))
                else:
                    logger.error(f"Order placement failed: {response}")
                    
            except Exception as e:
                logger.error(f"Error placing order: {e}")
                
                # Emit error event
                kalshi_event_bus.publish(KalshiEvent(
                    type="api_error",
                    payload={
                        "strategy": "15m_engine",
                        "error": "order_placement_failed",
                        "details": str(e),
                        "order": order
                    },
                    ts=time.time(),
                    source="15m_strategy"
                ))
        
        return orders_placed
    
    def get_strategy_status(self) -> Dict[str, any]:
        """Get current strategy status."""
        risk_status = self.risk_manager.get_risk_status()
        
        return {
            "cycle_count": self.cycle_count,
            "last_bar_time": self.last_bar_time,
            "current_positions": self.current_positions,
            "risk_status": risk_status,
            "asset_ticker_map": self.asset_ticker_map,
            "running": True
        }
    
    def run_strategy_loop(self, interval_sec: int = 900):
        """Run the strategy in a continuous loop."""
        logger.info(f"Starting 15M strategy loop with {interval_sec}s interval")
        
        while True:
            try:
                cycle_start = time.time()
                
                # Get latest prices
                prices = price_service.get_latest_15m_bars(["BTC", "ETH"])
                
                # Run strategy bar
                results = self.run_bar(prices)
                
                # Update last bar time
                self.last_bar_time = cycle_start
                
                # Sleep until next bar
                elapsed = time.time() - cycle_start
                sleep_time = max(0, interval_sec - elapsed)
                
                logger.info(f"Sleeping for {sleep_time:.1f}s until next bar")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("Strategy loop stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in strategy loop: {e}")
                
                # Emit error event
                kalshi_event_bus.publish(KalshiEvent(
                    type="api_error",
                    payload={
                        "strategy": "15m_engine",
                        "error": "strategy_loop_error",
                        "details": str(e)
                    },
                    ts=time.time(),
                    source="15m_strategy"
                ))
                
                # Sleep longer after error
                time.sleep(60)

# Strategy engine singleton
strategy_engine = Strategy15mEngine()

# Example usage:
"""
# Initialize and run strategy
engine = Strategy15mEngine()

# Run single cycle
prices = price_service.get_latest_15m_bars(["BTC", "ETH"])
results = engine.run_bar(prices)

# Run continuous loop
engine.run_strategy_loop(interval_sec=900)  # 15 minutes

# Get status
status = engine.get_strategy_status()
print(f"Strategy status: {status}")
"""
