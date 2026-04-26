"""
15-Minute Crypto Strategy - Production Implementation

This strategy uses the event-driven infrastructure to trade 15-minute crypto contracts
with proper signal generation, order management, and PnL tracking.

Strategy Overview:
- Timeframe: 15-minute intervals
- Assets: BTC, ETH, SOL, XRP, DOGE (KX*15M series)
- Signals: Momentum + Mean Reversion combination
- Risk: 2% max per trade, 10% total portfolio
- Target: 15-25% annualized return
"""

import time
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging
from enum import Enum

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
from config.kalshi_universe import KALSHI_CRYPTO_ASSETS
from merid.event_venues.kalshi.market_selector import resolve_series_ticker
from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent, KalshiRateAwareClient
from merid.trading.kalshi_crypto_spot_adapter import get_kalshi_crypto_spot_adapter, SpotPolicy

logger = logging.getLogger(__name__)

class SignalType(Enum):
    """Signal types for the 15m strategy."""
    MOMENTUM_LONG = "momentum_long"
    MOMENTUM_SHORT = "momentum_short"
    MEAN_REVERSION_LONG = "mean_reversion_long"
    MEAN_REVERSION_SHORT = "mean_reversion_short"
    NO_SIGNAL = "no_signal"

class TradeStatus(Enum):
    """Trade status tracking."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class Signal:
    """Trading signal with metadata including spot source tracking."""
    signal_type: SignalType
    ticker: str
    confidence: float  # 0.0 to 1.0
    entry_price: float
    target_price: float
    stop_loss: float
    position_size: int
    timestamp: float
    reasoning: str
    expected_return: float
    risk_reward_ratio: float
    
    # Spot metadata for policy enforcement and observability
    spot_price: float = 0.0
    spot_source: str = ""  # 'coinbase', 'binanceus', 'coingecko', etc.
    spot_is_stale: bool = False
    spot_age_seconds: float = 0.0
    size_factor: float = 1.0  # Applied to position sizing (1.0 = full, <1.0 = degraded)

@dataclass
class Trade:
    """Active trade tracking."""
    signal: Signal
    trade_id: str
    status: TradeStatus
    filled_quantity: int
    filled_price: float
    entry_time: float
    exit_time: Optional[float]
    exit_price: Optional[float]
    pnl: float
    fees: float
    events: List[Dict[str, Any]]

@dataclass
class StrategyMetrics:
    """Strategy performance metrics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_fees: float
    max_drawdown: float
    sharpe_ratio: float
    avg_trade_duration: float
    current_positions: Dict[str, int]

class Crypto15MStrategy:
    """15-minute crypto trading strategy using event-driven infrastructure."""
    
    def __init__(
        self,
        max_position_size: int = 1000,
        max_portfolio_risk: float = 0.10,
        confidence_threshold: float = 0.65,
        target_tickers: Optional[List[str]] = None,
    ):
        """
        Initialize the 15m crypto strategy.

        Args:
            max_position_size: Maximum contracts per trade
            max_portfolio_risk: Maximum portfolio risk (0.10 = 10%)
            confidence_threshold: Minimum confidence to execute trades
            target_tickers: Optional explicit market tickers; default is one 15m lane
                per asset in :data:`KALSHI_CRYPTO_ASSETS` (placeholder suffix for tests;
                production should pass catalog-backed tickers).
        """
        self.max_position_size = max_position_size
        self.max_portfolio_risk = max_portfolio_risk
        self.confidence_threshold = confidence_threshold
        
        # Initialize rate-aware client
        self.client = KalshiRateAwareClient(safety_factor=0.8)
        
        # Strategy state
        self.active_trades: Dict[str, Trade] = {}
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}
        self.signals: List[Signal] = []
        
        # Performance tracking
        self.metrics = StrategyMetrics(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            total_fees=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            avg_trade_duration=0.0,
            current_positions={}
        )
        
        # Strategy parameters
        self.momentum_period = 20  # 20 periods for momentum
        self.mean_reversion_period = 50  # 50 periods for mean reversion
        self.volatility_window = 30  # 30 periods for volatility
        self.risk_per_trade = 0.02  # 2% risk per trade
        
        # Target tickers — one 15m series per canonical asset unless overridden
        if target_tickers:
            self.target_tickers = list(target_tickers)
        else:
            self.target_tickers = [
                f"{resolve_series_ticker(asset, '15m')}-WATCHLIST" for asset in KALSHI_CRYPTO_ASSETS
            ]
        
        # Subscribe to event bus
        kalshi_event_bus.subscribe(self._handle_event)
        
        logger.info("15M Crypto Strategy initialized")
        
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
        trade_id = payload.get("order_id")
        
        if trade_id in self.active_trades:
            trade = self.active_trades[trade_id]
            trade.status = TradeStatus.FILLED
            trade.filled_quantity = payload.get("count", 0)
            trade.filled_price = payload.get("price", 0.0)
            trade.events.append({"type": "fill", "timestamp": event.ts, "payload": payload})
            
            logger.info(f"Trade {trade_id} filled: {trade.filled_quantity} @ {trade.filled_price}")
    
    def _handle_order_reject(self, event: KalshiEvent):
        """Handle order rejection events."""
        payload = event.payload
        trade_id = payload.get("order_id")
        
        if trade_id in self.active_trades:
            trade = self.active_trades[trade_id]
            trade.status = TradeStatus.REJECTED
            trade.events.append({"type": "reject", "timestamp": event.ts, "payload": payload})
            
            logger.warning(f"Trade {trade_id} rejected: {payload.get('reason', 'Unknown')}")
    
    def _handle_position_update(self, event: KalshiEvent):
        """Handle position update events."""
        payload = event.payload
        # Update current positions for risk management
        self._update_current_positions(payload)
    
    def _handle_api_error(self, event: KalshiEvent):
        """Handle API error events."""
        payload = event.payload
        logger.error(f"API error in strategy: {payload.get('error', 'Unknown')}")
    
    def _update_current_positions(self, position_data: Dict[str, Any]):
        """Update current position tracking."""
        for position in position_data.get("positions", []):
            ticker = position.get("ticker")
            count = position.get("count", 0)
            if ticker:
                self.metrics.current_positions[ticker] = count
    
    def generate_signals(self) -> List[Signal]:
        """Generate trading signals based on current market data."""
        signals = []
        
        for ticker in self.target_tickers:
            try:
                # Get current spot price with source metadata
                spot = self._get_current_price(ticker)
                if spot is None:
                    continue
                
                # Extract price from SpotPrice for price history
                current_price = spot.price
                
                # Update price history
                self._update_price_history(ticker, current_price)
                
                # Generate signals
                signal = self._analyze_ticker(ticker, current_price, spot)
                if signal and signal.confidence >= self.confidence_threshold:
                    signals.append(signal)
                    
            except Exception as e:
                logger.error(f"Error generating signal for {ticker}: {e}")
        
        self.signals.extend(signals)
        return signals
    
    def _get_current_price(self, ticker: str):
        """Get current spot price for ticker using KalshiCryptoSpotAdapter.
        
        Returns SpotPrice dataclass with source metadata, not just a float.
        This enables source/stale policy enforcement upstream.
        """
        try:
            adapter = get_kalshi_crypto_spot_adapter()
            
            # Resolve asset via longest-prefix series map (same as risk/WS)
            asset = kalshi_ticker_to_asset(ticker)
            if asset is None or asset not in ACTIVE_CRYPTO_ASSETS:
                logger.warning(f"Could not extract asset from ticker: {ticker}")
                return None
            
            spot = adapter.get_spot(asset)
            if spot is None:
                logger.warning(f"No spot price available for {asset} ({ticker})")
                return None
            
            logger.info(
                f"Spot for {ticker}: price={spot.price:.2f}, source={spot.source}, "
                f"stale={spot.is_stale}, age={spot.age_seconds:.1f}s"
            )
            return spot
            
        except Exception as e:
            logger.error(f"Error fetching spot price for {ticker}: {e}")
            return None
    
    def _update_price_history(self, ticker: str, price: float):
        """Update price history for analysis."""
        if ticker not in self.price_history:
            self.price_history[ticker] = []
        
        self.price_history[ticker].append((time.time(), price))
        
        # Keep only recent history (last 200 periods)
        if len(self.price_history[ticker]) > 200:
            self.price_history[ticker] = self.price_history[ticker][-200:]
    
    def _analyze_ticker(self, ticker: str, current_price: float, spot=None) -> Optional[Signal]:
        """Analyze ticker and generate signal with spot metadata."""
        if ticker not in self.price_history or len(self.price_history[ticker]) < 50:
            return None
        
        # Extract price series
        prices = [p[1] for p in self.price_history[ticker]]
        
        # Calculate indicators
        momentum_signal = self._calculate_momentum_signal(prices)
        mean_reversion_signal = self._calculate_mean_reversion_signal(prices)
        volatility = self._calculate_volatility(prices)
        
        # Combine signals
        combined_signal = self._combine_signals(momentum_signal, mean_reversion_signal, volatility)
        
        if not combined_signal:
            return None
        
        # Calculate position size
        position_size = self._calculate_position_size(combined_signal, volatility)
        
        # Calculate targets
        entry_price = current_price
        if combined_signal["direction"] > 0:  # Long
            target_price = entry_price * (1 + combined_signal["expected_return"])
            stop_loss = entry_price * (1 - self.risk_per_trade)
            signal_type = SignalType.MOMENTUM_LONG if combined_signal["source"] == "momentum" else SignalType.MEAN_REVERSION_LONG
        else:  # Short
            target_price = entry_price * (1 - combined_signal["expected_return"])
            stop_loss = entry_price * (1 + self.risk_per_trade)
            signal_type = SignalType.MOMENTUM_SHORT if combined_signal["source"] == "momentum" else SignalType.MEAN_REVERSION_SHORT
        
        # Compute size factor from spot quality if spot provided
        size_factor = 1.0
        spot_price = current_price
        spot_source = ""
        spot_is_stale = False
        spot_age_seconds = 0.0
        
        if spot is not None:
            from merid.trading.kalshi_crypto_spot_adapter import get_kalshi_crypto_spot_adapter
            adapter = get_kalshi_crypto_spot_adapter()
            size_factor = adapter.get_size_factor(spot)
            spot_price = spot.price
            spot_source = spot.source
            spot_is_stale = spot.is_stale
            spot_age_seconds = spot.age_seconds
        
        return Signal(
            signal_type=signal_type,
            ticker=ticker,
            confidence=combined_signal["confidence"],
            entry_price=entry_price,
            target_price=target_price,
            stop_loss=stop_loss,
            position_size=position_size,
            timestamp=time.time(),
            reasoning=combined_signal["reasoning"],
            expected_return=combined_signal["expected_return"],
            risk_reward_ratio=combined_signal["risk_reward_ratio"],
            # Spot metadata for policy enforcement
            spot_price=spot_price,
            spot_source=spot_source,
            spot_is_stale=spot_is_stale,
            spot_age_seconds=spot_age_seconds,
            size_factor=size_factor,
        )
    
    def _calculate_momentum_signal(self, prices: List[float]) -> Optional[Dict[str, Any]]:
        """Calculate momentum-based signal."""
        if len(prices) < self.momentum_period:
            return None
        
        # Simple momentum: current price vs moving average
        recent_prices = prices[-self.momentum_period:]
        ma = np.mean(recent_prices)
        current_price = prices[-1]
        
        # Calculate momentum strength
        momentum_strength = (current_price - ma) / ma
        
        # Calculate confidence based on momentum strength and volatility
        volatility = np.std(recent_prices) / ma
        confidence = min(abs(momentum_strength) / (volatility + 0.01), 1.0)
        
        if abs(momentum_strength) < 0.01:  # 1% threshold
            return None
        
        direction = 1 if momentum_strength > 0 else -1
        expected_return = abs(momentum_strength) * 2  # Expected 2x momentum
        
        return {
            "direction": direction,
            "confidence": confidence,
            "expected_return": expected_return,
            "source": "momentum",
            "reasoning": f"Momentum: {momentum_strength:.3f}, Volatility: {volatility:.3f}",
            "risk_reward_ratio": expected_return / self.risk_per_trade
        }
    
    def _calculate_mean_reversion_signal(self, prices: List[float]) -> Optional[Dict[str, Any]]:
        """Calculate mean reversion signal."""
        if len(prices) < self.mean_reversion_period:
            return None
        
        # Mean reversion: price deviation from longer-term mean
        recent_prices = prices[-self.mean_reversion_period:]
        long_ma = np.mean(recent_prices)
        current_price = prices[-1]
        
        # Calculate deviation
        deviation = (current_price - long_ma) / long_ma
        
        # Calculate confidence based on deviation and recent volatility
        recent_volatility = np.std(prices[-self.volatility_window:]) / long_ma
        confidence = min(abs(deviation) / (recent_volatility + 0.01), 1.0)
        
        if abs(deviation) < 0.02:  # 2% threshold
            return None
        
        # Mean reversion: bet on return to mean
        direction = -1 if deviation > 0 else 1
        expected_return = abs(deviation) * 1.5  # Expected 1.5x deviation
        
        return {
            "direction": direction,
            "confidence": confidence,
            "expected_return": expected_return,
            "source": "mean_reversion",
            "reasoning": f"Mean reversion: {deviation:.3f}, Volatility: {recent_volatility:.3f}",
            "risk_reward_ratio": expected_return / self.risk_per_trade
        }
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate volatility for position sizing."""
        if len(prices) < self.volatility_window:
            return 0.02  # Default 2% volatility
        
        recent_prices = prices[-self.volatility_window:]
        returns = [(recent_prices[i] / recent_prices[i-1] - 1) for i in range(1, len(recent_prices))]
        return np.std(returns)
    
    def _combine_signals(self, momentum: Optional[Dict], mean_reversion: Optional[Dict], volatility: float) -> Optional[Dict[str, Any]]:
        """Combine momentum and mean reversion signals."""
        signals = []
        if momentum:
            signals.append(momentum)
        if mean_reversion:
            signals.append(mean_reversion)
        
        if not signals:
            return None
        
        # Choose strongest signal
        strongest = max(signals, key=lambda s: s["confidence"])
        
        # Adjust confidence based on volatility (higher volatility = lower confidence)
        volatility_adjustment = max(0.5, 1.0 - volatility * 10)
        strongest["confidence"] *= volatility_adjustment
        
        return strongest
    
    def _calculate_position_size(self, signal: Signal, volatility: float) -> int:
        """Calculate optimal position size based on signal, volatility, and spot quality.
        
        Applies size degradation when spot source is fallback or stale:
        - Primary (Coinbase) + fresh: size_factor = 1.0
        - Fallback (BinanceUS/Coingecko): size_factor = 0.5
        - Stale data: size_factor = 0.3 (or 0.0 if block_if_stale enabled)
        """
        # Base position size
        base_size = self.max_position_size
        
        # Adjust for confidence
        confidence_adjustment = signal.confidence
        
        # Adjust for volatility (inverse relationship)
        volatility_adjustment = max(0.5, 1.0 - volatility * 5)
        
        # Adjust for risk-reward ratio
        rr_adjustment = min(1.5, signal.risk_reward_ratio / 2.0)
        
        # Apply spot source quality factor (key policy enforcement)
        spot_size_factor = signal.size_factor
        
        # Calculate final size with all adjustments
        adjusted_size = int(
            base_size * confidence_adjustment * volatility_adjustment * rr_adjustment * spot_size_factor
        )
        
        # Log if size was degraded due to spot quality
        if spot_size_factor < 1.0:
            logger.warning(
                f"Position size degraded for {signal.ticker}: "
                f"factor={spot_size_factor:.2f} (source={signal.spot_source}, "
                f"stale={signal.spot_is_stale}), "
                f"size={adjusted_size} vs base={base_size}"
            )
        
        return max(1, min(adjusted_size, self.max_position_size))
    
    def execute_signals(self, signals: List[Signal]) -> List[str]:
        """Execute trading signals."""
        executed_trades = []
        
        for signal in signals:
            try:
                # Check risk limits
                if not self._check_risk_limits(signal):
                    logger.warning(f"Risk limits exceeded for {signal.ticker}")
                    continue
                
                # Execute trade
                trade_id = self._execute_trade(signal)
                if trade_id:
                    executed_trades.append(trade_id)
                    logger.info(f"Executed trade {trade_id} for {signal.ticker}")
                
            except Exception as e:
                logger.error(f"Error executing signal for {signal.ticker}: {e}")
        
        return executed_trades
    
    def _check_risk_limits(self, signal: Signal) -> bool:
        """Check if trade passes risk management rules."""
        # Check portfolio risk
        current_portfolio_value = self._calculate_portfolio_value()
        trade_value = signal.position_size * signal.entry_price
        
        if trade_value > current_portfolio_value * self.max_portfolio_risk:
            return False
        
        # Check position concentration (per-market ticker)
        current_position = self.metrics.current_positions.get(signal.ticker, 0)
        if abs(current_position + signal.position_size) > self.max_position_size * 2:
            return False

        return True
    
    def _calculate_portfolio_value(self) -> float:
        """Calculate current portfolio value from live Kalshi bankroll.
        
        PRODUCTION: Uses BankrollServiceV2 - no mock data.
        """
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity = get_equity_for_risk_calc_sync()
            if equity is not None and equity > 0:
                return float(equity)
        except Exception as exc:
            logger.error(f"[PORTFOLIO_VALUE] Failed to get live equity: {exc}")
        
        # PRODUCTION SAFETY: Fail closed with 0 if live bankroll unavailable
        logger.critical("[PORTFOLIO_VALUE] Live bankroll unavailable - returning 0 (fail closed)")
        return 0.0
    
    def _execute_trade(self, signal: Signal) -> Optional[str]:
        """Execute a trading trade."""
        try:
            # Create trade record
            trade_id = f"trade_{int(time.time())}_{signal.ticker[:8]}"
            
            trade = Trade(
                signal=signal,
                trade_id=trade_id,
                status=TradeStatus.PENDING,
                filled_quantity=0,
                filled_price=0.0,
                entry_time=time.time(),
                exit_time=None,
                exit_price=None,
                pnl=0.0,
                fees=0.0,
                events=[]
            )
            
            self.active_trades[trade_id] = trade
            
            # Prepare order
            order_data = {
                "ticker": signal.ticker,
                "side": "buy" if signal.signal_type in [SignalType.MOMENTUM_LONG, SignalType.MEAN_REVERSION_LONG] else "sell",
                "order_type": "limit",
                "price": signal.entry_price,
                "count": signal.position_size,
                "stop_price": signal.stop_loss,
                "take_profit": signal.target_price
            }
            
            # Submit order via rate-aware client
            response = self.client.post("/portfolio/orders", json=order_data)
            
            if response.get("success"):
                trade.events.append({"type": "submitted", "timestamp": time.time(), "payload": response})
                logger.info(f"Trade {trade_id} submitted successfully")
                return trade_id
            else:
                trade.status = TradeStatus.REJECTED
                trade.events.append({"type": "submit_failed", "timestamp": time.time(), "payload": response})
                logger.error(f"Trade {trade_id} submission failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return None
    
    def manage_positions(self):
        """Manage existing positions (stop loss, take profit, unwind)."""
        current_time = time.time()
        
        for trade_id, trade in list(self.active_trades.items()):
            try:
                # Check if trade should be closed
                if self._should_close_trade(trade, current_time):
                    self._close_trade(trade_id)
                    
            except Exception as e:
                logger.error(f"Error managing trade {trade_id}: {e}")
    
    def _should_close_trade(self, trade: Trade, current_time: float) -> bool:
        """Determine if a trade should be closed."""
        if trade.status != TradeStatus.FILLED:
            return False
        
        # Get current price
        current_price = self._get_current_price(trade.signal.ticker)
        if not current_price:
            return False
        
        # Check stop loss
        if trade.signal.signal_type in [SignalType.MOMENTUM_LONG, SignalType.MEAN_REVERSION_LONG]:
            if current_price <= trade.signal.stop_loss:
                return True
        else:  # Short positions
            if current_price >= trade.signal.stop_loss:
                return True
        
        # Check take profit
        if trade.signal.signal_type in [SignalType.MOMENTUM_LONG, SignalType.MEAN_REVERSION_LONG]:
            if current_price >= trade.signal.target_price:
                return True
        else:  # Short positions
            if current_price <= trade.signal.target_price:
                return True
        
        # Check time-based exit (max 4 hours for 15m strategy)
        if current_time - trade.entry_time > 4 * 3600:  # 4 hours
            return True
        
        return False
    
    def _close_trade(self, trade_id: str):
        """Close a trade."""
        trade = self.active_trades[trade_id]
        
        try:
            # Determine close side
            close_side = "sell" if trade.signal.signal_type in [SignalType.MOMENTUM_LONG, SignalType.MEAN_REVERSION_LONG] else "buy"
            
            # Submit close order
            order_data = {
                "ticker": trade.signal.ticker,
                "side": close_side,
                "order_type": "market",  # Market order for closing
                "count": trade.filled_quantity
            }
            
            response = self.client.post("/portfolio/orders", json=order_data)
            
            if response.get("success"):
                trade.status = TradeStatus.FILLED
                trade.exit_time = time.time()
                trade.exit_price = response.get("price", trade.filled_price)
                
                # Calculate PnL
                if trade.signal.signal_type in [SignalType.MOMENTUM_LONG, SignalType.MEAN_REVERSION_LONG]:
                    trade.pnl = (trade.exit_price - trade.filled_price) * trade.filled_quantity
                else:  # Short positions
                    trade.pnl = (trade.filled_price - trade.exit_price) * trade.filled_quantity
                
                # Calculate fees (mock 0.1% per trade)
                trade.fees = (trade.filled_price + trade.exit_price) * trade.filled_quantity * 0.001
                
                # Update metrics
                self._update_metrics(trade)
                
                # Remove from active trades
                del self.active_trades[trade_id]
                
                # Emit position update event
                kalshi_event_bus.publish(KalshiEvent(
                    type="position_update",
                    payload={
                        "trade_id": trade_id,
                        "ticker": trade.signal.ticker,
                        "pnl": trade.pnl,
                        "fees": trade.fees,
                        "duration": trade.exit_time - trade.entry_time
                    },
                    ts=time.time(),
                    source="15m_strategy"
                ))
                
                logger.info(f"Closed trade {trade_id} with PnL: ${trade.pnl:.2f}")
                
            else:
                logger.error(f"Failed to close trade {trade_id}: {response}")
                
        except Exception as e:
            logger.error(f"Error closing trade {trade_id}: {e}")
    
    def _update_metrics(self, trade: Trade):
        """Update strategy metrics."""
        self.metrics.total_trades += 1
        
        if trade.pnl > 0:
            self.metrics.winning_trades += 1
        else:
            self.metrics.losing_trades += 1
        
        self.metrics.win_rate = self.metrics.winning_trades / self.metrics.total_trades
        self.metrics.total_pnl += trade.pnl
        self.metrics.total_fees += trade.fees
        
        # Update average trade duration
        if trade.exit_time and trade.entry_time:
            duration = trade.exit_time - trade.entry_time
            if self.metrics.total_trades == 1:
                self.metrics.avg_trade_duration = duration
            else:
                self.metrics.avg_trade_duration = (self.metrics.avg_trade_duration * (self.metrics.total_trades - 1) + duration) / self.metrics.total_trades
    
    def get_strategy_status(self) -> Dict[str, Any]:
        """Get current strategy status."""
        return {
            "active_trades": len(self.active_trades),
            "total_trades": self.metrics.total_trades,
            "win_rate": self.metrics.win_rate,
            "total_pnl": self.metrics.total_pnl,
            "current_positions": self.metrics.current_positions,
            "recent_signals": len([s for s in self.signals if time.time() - s.timestamp < 3600]),
            "last_signal_time": max([s.timestamp for s in self.signals]) if self.signals else None
        }

    def plan_swarm_orders(self, catalog: Any, *, bankroll_cents: int = 500_000) -> List[Any]:
        """Build swarm + sizer plans for every (asset, timeframe) on the mood grid."""
        from merid.strategies.sentiment_swarm_execution import plan_swarm_orders_for_catalog

        return plan_swarm_orders_for_catalog(catalog, bankroll_cents=bankroll_cents)
    
    def run_strategy_cycle(self):
        """Run one complete strategy cycle."""
        try:
            # 1. Generate signals
            signals = self.generate_signals()
            
            # 2. Execute signals
            executed_trades = self.execute_signals(signals)
            
            # 3. Manage positions
            self.manage_positions()
            
            # 4. Emit status event
            kalshi_event_bus.publish(KalshiEvent(
                type="position_update",
                payload={
                    "strategy_cycle": {
                        "signals_generated": len(signals),
                        "trades_executed": len(executed_trades),
                        "active_trades": len(self.active_trades),
                        "status": self.get_strategy_status()
                    }
                },
                ts=time.time(),
                source="15m_strategy"
            ))
            
            logger.info(f"Strategy cycle completed: {len(signals)} signals, {len(executed_trades)} trades")
            
        except Exception as e:
            logger.error(f"Error in strategy cycle: {e}")
            kalshi_event_bus.publish(KalshiEvent(
                type="api_error",
                payload={
                    "error": "Strategy cycle error",
                    "details": str(e)
                },
                ts=time.time(),
                source="15m_strategy"
            ))

# Strategy singleton for easy access
crypto_15m_strategy = Crypto15MStrategy()

# Example usage:
"""
# Initialize strategy
strategy = Crypto15MStrategy()

# Run strategy cycles (every 15 minutes)
import schedule

def run_strategy():
    strategy.run_strategy_cycle()

# Schedule every 15 minutes
schedule.every(15).minutes.do(run_strategy)

# Or run manually for testing
strategy.run_strategy_cycle()

# Get strategy status
status = strategy.get_strategy_status()
print(f"Strategy Status: {status}")
"""
