#!/usr/bin/env python3
"""
Real-time End-to-End Trading Activity Monitor

Tracks all trading activity for 30 minutes across the entire pipeline:
- Signal generation (velocity, TA indicators)
- Market data (orderbook, spot prices)
- Candidate generation and validation
- Order placement and execution
- Risk enforcement and circuit breakers
- Fill reconciliation

Usage:
    python scripts/realtime_trading_monitor.py --duration 30
"""

import re
import time
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class TradingEvent:
    """Single trading event."""
    timestamp: datetime
    event_type: str
    asset: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    """Individual trade details."""
    timestamp: datetime
    asset: str
    ticker: str
    side: str  # BUY_YES, BUY_NO, SELL_YES, SELL_NO
    action: str  # BUY or SELL
    contract_side: str  # YES or NO
    entry_price_cents: int
    limit_price_cents: int
    market_mid_cents: int
    spread_cents: int
    edge_pct: float
    count: int
    notional_usd: float
    order_type: str  # limit, market, IOC
    confidence: float
    model_prob: float  # Model probability
    velocity: float
    rsi: float
    macd_hist: float
    time_to_expiry_sec: float
    macd_line: Optional[float] = None  # MACD line value
    macd_signal: Optional[float] = None  # MACD signal line value
    trend: Optional[str] = None  # Trend direction (UP, DOWN, SIDEWAYS)
    histogram: Optional[float] = None  # MACD histogram value
    # Threshold metrics for fine-tuning
    min_edge_threshold: Optional[float] = None  # Minimum edge threshold applied
    max_spread_threshold: Optional[int] = None  # Maximum spread threshold applied
    velocity_threshold: Optional[float] = None  # Velocity threshold applied
    confidence_threshold: Optional[float] = None  # Confidence threshold applied
    regime: Optional[str] = None  # Market regime (calm, elevated, violent)
    min_decision_minute: Optional[float] = None  # Minimum decision minute configured
    slot_id: Optional[str] = None  # Slot allocator ID
    is_exit_order: bool = False  # Whether this is an exit order
    outcome: Optional[str] = None  # WIN, LOSS, PENDING
    exit_price_cents: Optional[int] = None
    pnl_usd: Optional[float] = None
    reason: Optional[str] = None  # If rejected
    strike_price: Optional[float] = None  # Strike price for the 15-minute window
    event_price: Optional[float] = None  # Price at the time of event (generation/rejection)


@dataclass
class AssetStats:
    """Per-asset statistics."""
    asset: str
    
    # Signal generation
    velocity_signals: int = 0
    ta_signals: int = 0
    no_trade_decisions: int = 0
    
    # Market data
    spot_updates: int = 0
    orderbook_updates: int = 0
    spread_warnings: int = 0
    
    # Candidate generation
    candidates_generated: int = 0
    candidates_rejected: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Order flow
    orders_attempted: int = 0
    orders_accepted: int = 0
    orders_rejected: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Order details
    orders_by_side: Dict[str, int] = field(default_factory=lambda: defaultdict(int))  # BUY_YES, BUY_NO, etc.
    orders_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))  # limit, market, IOC
    
    # Price statistics
    avg_entry_price_cents: float = 0.0
    avg_edge_pct: float = 0.0
    avg_spread_cents: float = 0.0
    avg_confidence: float = 0.0
    
    # Risk
    risk_blocks: int = 0
    risk_vetoes: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Execution
    fills: int = 0
    slot_allocations: int = 0
    slot_rejections: int = 0
    exit_orders: int = 0
    trading_window_skips: int = 0
    
    # PnL
    total_pnl_usd: float = 0.0
    wins: int = 0
    losses: int = 0
    pending: int = 0
    
    # Advanced metrics (profit factor, expectancy, drawdown)
    gross_profit_usd: float = 0.0
    gross_loss_usd: float = 0.0
    average_win_usd: float = 0.0
    average_loss_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    current_drawdown_usd: float = 0.0
    peak_equity_usd: float = 0.0
    
    # Individual trades
    trades: List[Trade] = field(default_factory=list)
    
    # Detailed event tracking
    candidate_events: List[Dict[str, Any]] = field(default_factory=list)
    rejection_events: List[Dict[str, Any]] = field(default_factory=list)
    
    def summary(self) -> str:
        """Generate summary string."""
        lines = [
            f"\n{self.asset} SUMMARY:",
            f"  Signals: {self.velocity_signals} velocity, {self.ta_signals} TA, {self.no_trade_decisions} NO TRADE",
            f"  Market Data: {self.spot_updates} spot, {self.orderbook_updates} orderbook, {self.spread_warnings} spread warnings",
            f"  Candidates: {self.candidates_generated} generated, {sum(self.candidates_rejected.values())} rejected",
            f"  Orders: {self.orders_attempted} attempted, {self.orders_accepted} accepted, {sum(self.orders_rejected.values())} rejected",
            f"  Order Sides: {dict(self.orders_by_side)}",
            f"  Order Types: {dict(self.orders_by_type)}",
            f"  Risk: {self.risk_blocks} blocks, {sum(self.risk_vetoes.values())} vetoes",
            f"  Fills: {self.fills}",
        ]
        
        if self.orders_attempted > 0:
            lines.append(f"  Avg Entry Price: {self.avg_entry_price_cents:.1f}c")
            lines.append(f"  Avg Edge: {self.avg_edge_pct:.2f}%")
            lines.append(f"  Avg Spread: {self.avg_spread_cents:.1f}c")
            lines.append(f"  Avg Confidence: {self.avg_confidence:.2f}")
        
        if self.fills > 0:
            lines.append(f"  PnL: ${self.total_pnl_usd:.2f} ({self.wins}W/{self.losses}L/{self.pending}P)")
            if self.wins + self.losses > 0:
                win_rate = self.wins / (self.wins + self.losses) * 100
                lines.append(f"  Win Rate: {win_rate:.1f}%")
        
        if self.candidates_rejected:
            lines.append("  Candidate Rejections:")
            for reason, count in sorted(self.candidates_rejected.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    {reason}: {count}")
        
        if self.orders_rejected:
            lines.append("  Order Rejections:")
            for reason, count in sorted(self.orders_rejected.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    {reason}: {count}")
        
        if self.risk_vetoes:
            lines.append("  Risk Vetoes:")
            for reason, count in sorted(self.risk_vetoes.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    {reason}: {count}")
        
        return "\n".join(lines)


class RealtimeTradingMonitor:
    """Real-time trading activity monitor."""
    
    # Log patterns
    PATTERNS = {
        'velocity_signal': re.compile(r'\[VELOCITY-SIGNAL\] asset=(\w+) velocity=.*-> (BUY YES|BUY NO|NO TRADE)'),
        'candidate_generated': re.compile(r'\[CANDIDATE-GENERATED\] asset=(\w+)_15M side=(\w+)'),
        'candidate_rejected': re.compile(r'\[([A-Z-]+)\] asset=(\w+)_15M.*'),
        # Specific rejection reason patterns
        'spread_rejection': re.compile(r'spread exceeds coarse filter=(\d+)c \(spread=(\d+)c\)'),
        'min_edge_rejection': re.compile(r'MIN-EDGE-THRESHOLD.*edge=([\d.]+)%.*threshold=([\d.]+)%'),
        'time_expiry_rejection': re.compile(r'TIME-EXPIRY-VALIDATION.*asset=(\w+)_15M.*'),
        'cooldown_rejection': re.compile(r'\[COOLDOWN-CHECK\] asset=(\w+) in cooldown'),
        'strip_limit_rejection': re.compile(r'\[STRIP-LIMIT-CHECK\]'),
        'price_validation_rejection': re.compile(r'\[PRICE-VALIDATION\] ticker=(\w+).*deviation=(\d+)c'),
        'market_validation_rejection': re.compile(r'\[MARKET-VALIDATION-FAILED\] asset=(\w+)_15M'),
        'no_signal': re.compile(r'\[NO-SIGNAL\] asset=(\w+)_15M'),
        'momentum_fvg_no_edge': re.compile(r'\[MOMENTUM-FVG-NO-EDGE\] asset=(\w+)'),
        'price_filter_reject': re.compile(r'\[PRICE-FILTER-REJECT\] asset=(\w+)'),
        'trading_window_skip': re.compile(r'\[TRADING-WINDOW\] asset=(\w+)_15M'),
        'order_attempted': re.compile(r'\[15M-LOOP\] Order routed successfully: ticker=(\w+) side=(\w+) count=(\d+) result=(.+)'),
        'order_rejected': re.compile(r'\[ORDER-ROUTER\] .* ticker=(\w+).*'),
        'order_filled': re.compile(r'\[15M-LOOP\].*filled.*ticker=(\w+)'),
        'result_status': re.compile(r'result=([\w_]+)'),
        'fill_confirmation': re.compile(r'status.*filled|filled.*status'),
        'spot_update': re.compile(r'\[UNIFIED-SPOT\] Returning spot price for (\w+):'),
        'orderbook_update': re.compile(r'\[WS-FORWARDER-LOOP\] events_processed=(\d+)'),
        'spread_warning': re.compile(r'spread exceeds coarse filter=(\d+)c \(spread=(\d+)c\)'),
        'risk_block': re.compile(r'\[RISK-BLOCK\] asset=(\w+)'),
        'risk_veto': re.compile(r'event=risk_checked.*allowed=false.*reason=([^\s"]+)'),
        'fill': re.compile(r'\[FILL\] ticker=(\w+)'),
        'market_validation': re.compile(r'\[MARKET-VALIDATION\] asset=(\w+)_15M ticker=.* regime=(\w+)'),
        'cooldown': re.compile(r'\[COOLDOWN-CHECK\] asset=(\w+)'),
        'strip_limit': re.compile(r'\[STRIP-LIMIT-CHECK\]'),
        'circuit_breaker': re.compile(r'\[CIRCUIT-BREAKER\]'),
        'kill_switch': re.compile(r'\[KILL-SWITCH\]'),
        # New patterns for detailed metrics
        'order_construction': re.compile(r'\[ORDER-CONSTRUCTION-AUDIT\] ticker=(\w+) side=(BUY_YES|BUY_NO|SELL_YES|SELL_NO) action=(BUY|SELL) price_cents=(\d+) count=(\d+) agent_id=(\w+).*edge_pct=([\d.]+)'),
        'global_allocator_execute': re.compile(r'\[GLOBAL-ALLOCATOR-EXECUTE\] asset=(\w+) ticker=(\w+) side=(\w+) price=(\d+)c count=(\d+) edge=([\d.]+)%'),
        'price_validation': re.compile(r'\[PRICE-VALIDATION\] ticker=(\w+) .* mid=(\d+)c.*deviation=(\d+)c'),
        'dynamic_order_type': re.compile(r'\[DYNAMIC-ORDER-TYPE\] ticker=(\w+) using (\w+) due to'),
        'market_validation_spread': re.compile(r'\[MARKET-VALIDATION\] asset=(\w+)_15M.*spread=(\d+)c'),
        'velocity_magnitude': re.compile(r'velocity=([\d.-]+)'),
        'rsi_value': re.compile(r'rsi=([\d.]+)'),
        'macd_hist': re.compile(r'macd_hist=([\d.-]+)'),
        'macd_line': re.compile(r'macd_line=([\d.-]+)'),
        'macd_signal': re.compile(r'macd_signal=([\d.-]+)'),
        'trend': re.compile(r'trend=(\w+)'),
        'histogram': re.compile(r'histogram=([\d.-]+)'),
        'time_to_expiry': re.compile(r'time_to_expiry=([\d.]+)s'),
        'confidence': re.compile(r'confidence=([\d.]+)'),
        'model_prob': re.compile(r'model_prob=([\d.]+)'),
        'min_edge_threshold': re.compile(r'min_edge=([\d.]+)'),
        'max_spread_threshold': re.compile(r'max_spread=(\d+)c'),
        'velocity_threshold': re.compile(r'velocity_threshold=([\d.-]+)'),
        'confidence_threshold': re.compile(r'confidence_threshold=([\d.]+)'),
        'regime': re.compile(r'regime=(\w+)'),
        'settlement': re.compile(r'\[SETTLEMENT\] ticker=(\w+) outcome=(WIN|LOSS) pnl=([\d.-]+)'),
        # Slot allocator patterns
        'slot_allocator_allocated': re.compile(r'\[SLOT-ALLOCATOR-ALLOCATED\] asset=(\w+) side=(\w+) price_cents=(\d+) slot_id=(\w+) total_exposure=\$([\d.]+)'),
        'slot_allocator_reject': re.compile(r'\[SLOT-ALLOCATOR-REJECT\] asset=(\w+) side=(\w+) price_cents=(\d+) edge=([\d.]+)% - (.+)'),
        'slot_allocator_block': re.compile(r'\[order-router-SLOT-ALLOCATOR-BLOCK\]'),
        'slot_allocator_bypass': re.compile(r'\[order-router-SLOT-ALLOCATOR-BYPASS\]'),
        # Exit order patterns
        'exit_order': re.compile(r'\[EXIT-ORDER\]'),
        'exit_order_bypass': re.compile(r'\[EXIT-ORDER\] Exit order bypassed slot allocation'),
        # Min decision minute patterns
        'min_decision_minute': re.compile(r'\[MIN-DECISION-MINUTE\] asset=(\w+)_15M min_decision_minute=(\d+)'),
        'trading_window_skip': re.compile(r'\[TRADING-WINDOW\] asset=(\w+)_15M time_to_expiry=([\d.]+)s < min_time_to_expiry=(\d+)s'),
        # Strike price and event price patterns
        'strike_price': re.compile(r'strike_price=([\d.]+)'),
        'spot_price': re.compile(r'spot_price=([\d.]+)'),
        'market_price': re.compile(r'market_price=([\d.]+)'),
        'candidate_price': re.compile(r'\[CANDIDATE-GENERATED\] asset=(\w+)_15M.*price=([\d.]+)'),
        'rejection_price': re.compile(r'\[([A-Z-]+)\] asset=(\w+)_15M.*price=([\d.]+)')
    }
    
    def __init__(self, log_file: str, duration_minutes: int = 360):
        self.log_file = Path(log_file)
        self.duration_minutes = duration_minutes
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(minutes=duration_minutes)
        
        # Per-asset stats
        self.stats: Dict[str, AssetStats] = {
            "BTC": AssetStats("BTC"),
            "ETH": AssetStats("ETH"),
            "SOL": AssetStats("SOL"),
            "XRP": AssetStats("XRP"),
            "DOGE": AssetStats("DOGE"),
        }
        
        # Global stats
        self.global_events: List[TradingEvent] = []
        self.websocket_events = 0
        self.catalog_refreshes = 0
        self.agent_cycles = 0
        
        # System health
        self.circuit_breaker_trips = 0
        self.kill_switch_activations = 0
        
        # Trade tracking
        self.all_trades: List[Trade] = []
        
    def _extract_asset(self, ticker: str) -> Optional[str]:
        """Extract asset from ticker."""
        if ticker.startswith('KXBTC'):
            return 'BTC'
        elif ticker.startswith('KXETH'):
            return 'ETH'
        elif ticker.startswith('KXSOL'):
            return 'SOL'
        elif ticker.startswith('KXXRP'):
            return 'XRP'
        elif ticker.startswith('KXDOGE'):
            return 'DOGE'
        return None
    
    def _process_line(self, line: str):
        """Process a single log line."""
        # Try JSON format first
        try:
            log_entry = json.loads(line.strip())
            message = log_entry.get('message', '')
            timestamp_str = log_entry.get('ts', '')
            
            # Parse ISO timestamp
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
        except json.JSONDecodeError:
            # Fall back to plain text format
            message = line
            timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if not timestamp_match:
                return
            timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
        
        # Velocity signal
        match = self.PATTERNS['velocity_signal'].search(message)
        if match:
            asset = match.group(1)
            decision = match.group(2)
            if asset in self.stats:
                self.stats[asset].velocity_signals += 1
                if decision == 'NO TRADE':
                    self.stats[asset].no_trade_decisions += 1
            return
        
        # Candidate generated
        match = self.PATTERNS['candidate_generated'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                self.stats[asset].candidates_generated += 1
            return
        
        # Candidate rejected - specific patterns first
        # Spread rejection
        match = self.PATTERNS['spread_rejection'].search(message)
        if match:
            threshold = int(match.group(1))
            actual_spread = int(match.group(2))
            # Extract asset from message
            asset_match = re.search(r'asset=(\w+)_15M', message)
            if asset_match:
                asset = asset_match.group(1)
                if asset in self.stats:
                    reason = f'spread_exceeds_threshold_{threshold}c_actual_{actual_spread}c'
                    self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Min edge rejection
        match = self.PATTERNS['min_edge_rejection'].search(message)
        if match:
            edge = float(match.group(1))
            threshold = float(match.group(2))
            asset_match = re.search(r'asset=(\w+)_15M', message)
            if asset_match:
                asset = asset_match.group(1)
                if asset in self.stats:
                    reason = f'min_edge_threshold_{threshold}%_actual_{edge}%'
                    self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Time expiry rejection
        match = self.PATTERNS['time_expiry_rejection'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                self.stats[asset].candidates_rejected['time_expiry_validation'] += 1
            return
        
        # Cooldown rejection
        match = self.PATTERNS['cooldown_rejection'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                self.stats[asset].candidates_rejected['cooldown'] += 1
            return
        
        # Strip limit rejection
        match = self.PATTERNS['strip_limit_rejection'].search(message)
        if match:
            asset_match = re.search(r'asset=(\w+)_15M', message)
            if asset_match:
                asset = asset_match.group(1)
                if asset in self.stats:
                    self.stats[asset].candidates_rejected['strip_limit'] += 1
            return
        
        # Price validation rejection
        match = self.PATTERNS['price_validation_rejection'].search(message)
        if match:
            ticker = match.group(1)
            deviation = int(match.group(2))
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                reason = f'price_validation_deviation_{deviation}c'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Market validation rejection (only count FAILED, not VALID)
        match = self.PATTERNS['market_validation_rejection'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                reason = 'market_validation_failed'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # No signal generated
        match = self.PATTERNS['no_signal'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                reason = 'no_signal'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Momentum FVG no edge
        match = self.PATTERNS['momentum_fvg_no_edge'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                reason = 'momentum_fvg_no_edge'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Price filter reject
        match = self.PATTERNS['price_filter_reject'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                reason = 'price_filter_reject'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Trading window skip
        match = self.PATTERNS['trading_window_skip'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                reason = 'trading_window_skip'
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Generic candidate rejected (fallback)
        match = self.PATTERNS['candidate_rejected'].search(message)
        if match:
            tag = match.group(1)
            asset = match.group(2)
            if asset in self.stats:
                reason = tag.lower().replace('-', '_')
                self.stats[asset].candidates_rejected[reason] += 1
            return
        
        # Order attempted
        match = self.PATTERNS['order_attempted'].search(message)
        if match:
            ticker = match.group(1)
            side = match.group(2)
            count = int(match.group(3))
            result_status = match.group(4)
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                self.stats[asset].orders_attempted += 1
                # Only count as accepted if not rejected
                if 'rejected' not in result_status.lower():
                    self.stats[asset].orders_accepted += 1
                # Check if filled in result status
                if 'filled' in result_status.lower():
                    self.stats[asset].fills += 1
                    # Update the most recent trade with fill info
                    if self.stats[asset].trades:
                        last_trade = self.stats[asset].trades[-1]
                        last_trade.outcome = 'FILLED'
                        # Try to extract fill price from result status
                        fill_price_match = re.search(r'fill_price_cents=(\d+)', result_status)
                        if fill_price_match:
                            last_trade.exit_price_cents = int(fill_price_match.group(1))
            return
        
        # Alternative order pattern (if result status is not captured)
        match = re.search(r'\[15M-LOOP\] Order routed successfully: ticker=(\w+)', message)
        if match:
            ticker = match.group(1)
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                self.stats[asset].orders_attempted += 1
                self.stats[asset].orders_accepted += 1
                # Check for fill status in the full message
                if 'filled' in message.lower():
                    self.stats[asset].fills += 1
                    if self.stats[asset].trades:
                        last_trade = self.stats[asset].trades[-1]
                        last_trade.outcome = 'FILLED'
            return
        
        # Order rejected
        match = self.PATTERNS['order_rejected'].search(message)
        if match:
            ticker = match.group(1)
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                self.stats[asset].orders_attempted += 1
                reason = 'router_rejection'
                if 'MIN_EDGE_THRESHOLD' in message:
                    reason = 'min_edge_threshold'
                elif 'MODEL_PROB_DISTANCE' in message:
                    reason = 'model_prob_distance'
                elif 'BANKROLL_CAP' in message:
                    reason = 'bankroll_cap'
                self.stats[asset].orders_rejected[reason] += 1
            return
        
        # Spot update
        match = self.PATTERNS['spot_update'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                self.stats[asset].spot_updates += 1
            return
        
        # Orderbook update (from WebSocket forwarder)
        match = self.PATTERNS['orderbook_update'].search(message)
        if match:
            self.websocket_events = int(match.group(1))
            return
        
        # Spread warning
        match = self.PATTERNS['spread_warning'].search(message)
        if match:
            # This is logged per asset, need to extract asset from context
            for asset in self.stats:
                if f"{asset}_15M" in message:
                    self.stats[asset].spread_warnings += 1
                    break
            return
        
        # Risk block
        match = self.PATTERNS['risk_block'].search(message)
        if match:
            asset = match.group(1)
            if asset in self.stats:
                self.stats[asset].risk_blocks += 1
            return
        
        # Risk veto
        match = self.PATTERNS['risk_veto'].search(message)
        if match:
            reason = match.group(1)
            # Extract asset from context
            for asset in self.stats:
                if f"{asset}_15M" in message:
                    self.stats[asset].risk_vetoes[reason] += 1
                    break
            return
        
        # Fill confirmation (alternative pattern)
        match = self.PATTERNS['fill_confirmation'].search(message)
        if match:
            # Extract ticker from message if available
            ticker_match = re.search(r'ticker=(\w+)', message)
            if ticker_match:
                ticker = ticker_match.group(1)
                asset = self._extract_asset(ticker)
                if asset and asset in self.stats:
                    self.stats[asset].fills += 1
                    # Update the most recent trade with fill info
                    if self.stats[asset].trades:
                        last_trade = self.stats[asset].trades[-1]
                        if last_trade.outcome == 'PENDING':
                            last_trade.outcome = 'FILLED'
            return
        
        # Check for filled status in any message containing ticker
        if 'filled' in message.lower() and 'ticker=' in message:
            ticker_match = re.search(r'ticker=(\w+)', message)
            if ticker_match:
                ticker = ticker_match.group(1)
                asset = self._extract_asset(ticker)
                if asset and asset in self.stats:
                    # Only increment if this is a new fill (not already counted)
                    # Check if we already have a fill for this ticker recently
                    recent_fill = False
                    if self.stats[asset].trades:
                        for trade in reversed(self.stats[asset].trades[-5:]):  # Check last 5 trades
                            if trade.ticker == ticker and trade.outcome == 'FILLED':
                                recent_fill = True
                                break
                    if not recent_fill:
                        self.stats[asset].fills += 1
                        if self.stats[asset].trades:
                            last_trade = self.stats[asset].trades[-1]
                            if last_trade.outcome == 'PENDING':
                                last_trade.outcome = 'FILLED'
            return
        
        # Circuit breaker
        if self.PATTERNS['circuit_breaker'].search(message):
            self.circuit_breaker_trips += 1
        
        # Kill switch
        if self.PATTERNS['kill_switch'].search(message):
            self.kill_switch_activations += 1
        
        # Agent cycle
        if '[AGENT-GRID-RUN-CYCLE-AGENT]' in message:
            self.agent_cycles += 1
        
        # Catalog refresh
        if '[CATALOG-REFRESH]' in message:
            self.catalog_refreshes += 1
        
        # Order construction (detailed metrics)
        match = self.PATTERNS['order_construction'].search(message)
        if match:
            ticker = match.group(1)
            side = match.group(2)  # BUY_YES, BUY_NO, etc.
            action = match.group(3)  # BUY or SELL
            price_cents = int(match.group(4))
            count = int(match.group(5))
            asset = match.group(6)
            edge_pct = float(match.group(7))
            
            # Extract additional metrics from the message
            velocity = 0.0
            rsi = 50.0
            macd_hist = 0.0
            time_to_expiry = 0.0
            confidence = 0.0
            
            vel_match = self.PATTERNS['velocity_magnitude'].search(message)
            if vel_match:
                velocity = float(vel_match.group(1))
            
            rsi_match = self.PATTERNS['rsi_value'].search(message)
            if rsi_match:
                rsi = float(rsi_match.group(1))
            
            macd_match = self.PATTERNS['macd_hist'].search(message)
            if macd_match:
                macd_hist = float(macd_match.group(1))
            
            tte_match = self.PATTERNS['time_to_expiry'].search(message)
            if tte_match:
                time_to_expiry = float(tte_match.group(1))
            
            conf_match = self.PATTERNS['confidence'].search(message)
            if conf_match:
                confidence = float(conf_match.group(1))
            
            # Extract model probability
            model_prob = 0.5
            model_prob_match = self.PATTERNS['model_prob'].search(message)
            if model_prob_match:
                model_prob = float(model_prob_match.group(1))
            
            # Extract threshold metrics
            min_edge_threshold = None
            min_edge_match = self.PATTERNS['min_edge_threshold'].search(message)
            if min_edge_match:
                min_edge_threshold = float(min_edge_match.group(1))
            
            max_spread_threshold = None
            max_spread_match = self.PATTERNS['max_spread_threshold'].search(message)
            if max_spread_match:
                max_spread_threshold = int(max_spread_match.group(1))
            
            velocity_threshold = None
            vel_thresh_match = self.PATTERNS['velocity_threshold'].search(message)
            if vel_thresh_match:
                velocity_threshold = float(vel_thresh_match.group(1))
            
            confidence_threshold = None
            conf_thresh_match = self.PATTERNS['confidence_threshold'].search(message)
            if conf_thresh_match:
                confidence_threshold = float(conf_thresh_match.group(1))
            
            regime = None
            regime_match = self.PATTERNS['regime'].search(message)
            if regime_match:
                regime = regime_match.group(1)
            
            # Additional technical indicators
            macd_line = None
            macd_line_match = self.PATTERNS['macd_line'].search(message)
            if macd_line_match:
                macd_line = float(macd_line_match.group(1))
            
            macd_signal = None
            macd_signal_match = self.PATTERNS['macd_signal'].search(message)
            if macd_signal_match:
                macd_signal = float(macd_signal_match.group(1))
            
            trend = None
            trend_match = self.PATTERNS['trend'].search(message)
            if trend_match:
                trend = trend_match.group(1)
            
            histogram = None
            histogram_match = self.PATTERNS['histogram'].search(message)
            if histogram_match:
                histogram = float(histogram_match.group(1))
            
            # Strike price and event price
            strike_price = None
            strike_match = self.PATTERNS['strike_price'].search(message)
            if strike_match:
                strike_price = float(strike_match.group(1))
            
            event_price = None
            # Try candidate price first
            candidate_price_match = self.PATTERNS['candidate_price'].search(message)
            if candidate_price_match:
                event_price = float(candidate_price_match.group(2))
            else:
                # Try spot price
                spot_price_match = self.PATTERNS['spot_price'].search(message)
                if spot_price_match:
                    event_price = float(spot_price_match.group(1))
                else:
                    # Try market price
                    market_price_match = self.PATTERNS['market_price'].search(message)
                    if market_price_match:
                        event_price = float(market_price_match.group(1))
            
            # Map to asset
            mapped_asset = self._extract_asset(ticker)
            if mapped_asset and mapped_asset in self.stats:
                self.stats[mapped_asset].orders_by_side[side] += 1
                
                # Create trade record with all extracted metrics
                contract_side = 'YES' if 'YES' in side else 'NO'
                trade = Trade(
                    timestamp=datetime.now(),
                    asset=mapped_asset,
                    ticker=ticker,
                    side=side,
                    action=action,
                    contract_side=contract_side,
                    entry_price_cents=price_cents,
                    limit_price_cents=price_cents,
                    market_mid_cents=price_cents,  # Will be updated from price_validation
                    spread_cents=0,  # Will be updated from market_validation
                    edge_pct=edge_pct,
                    count=count,
                    notional_usd=count * price_cents / 100,
                    order_type='limit',  # Default
                    confidence=confidence,
                    model_prob=model_prob,
                    velocity=velocity,
                    rsi=rsi,
                    macd_hist=macd_hist,
                    macd_line=macd_line,
                    macd_signal=macd_signal,
                    trend=trend,
                    histogram=histogram,
                    time_to_expiry_sec=time_to_expiry,
                    min_edge_threshold=min_edge_threshold,
                    max_spread_threshold=max_spread_threshold,
                    velocity_threshold=velocity_threshold,
                    confidence_threshold=confidence_threshold,
                    regime=regime,
                    strike_price=strike_price,
                    event_price=event_price,
                    outcome='PENDING'
                )
                self.stats[mapped_asset].trades.append(trade)
                self.all_trades.append(trade)
                
                # Update averages
                n = self.stats[mapped_asset].orders_attempted + 1
                self.stats[mapped_asset].avg_entry_price_cents = (
                    (self.stats[mapped_asset].avg_entry_price_cents * (n - 1) + price_cents) / n
                )
                self.stats[mapped_asset].avg_edge_pct = (
                    (self.stats[mapped_asset].avg_edge_pct * (n - 1) + edge_pct) / n
                )
                self.stats[mapped_asset].avg_confidence = (
                    (self.stats[mapped_asset].avg_confidence * (n - 1) + confidence) / n
                )
            return
        
        # Global allocator execute (spread info)
        match = self.PATTERNS['global_allocator_execute'].search(message)
        if match:
            asset = match.group(1)
            ticker = match.group(2)
            side = match.group(3)
            price_cents = int(match.group(4))
            count = int(match.group(5))
            edge_pct = float(match.group(6))
            
            if asset in self.stats:
                # Create trade record
                trade = Trade(
                    timestamp=datetime.now(),
                    asset=asset,
                    ticker=ticker,
                    side=side,
                    action=side.split('_')[0] if '_' in side else 'BUY',
                    contract_side=side.split('_')[1] if '_' in side else 'YES',
                    entry_price_cents=price_cents,
                    limit_price_cents=price_cents,
                    market_mid_cents=0,  # Will be updated from price_validation
                    spread_cents=0,  # Will be updated from market_validation
                    edge_pct=edge_pct,
                    count=count,
                    notional_usd=price_cents * count / 100,
                    order_type='limit',
                    confidence=0.0,
                    velocity=0.0,
                    rsi=50.0,
                    macd_hist=0.0,
                    time_to_expiry_sec=0.0,
                    outcome='PENDING'
                )
                self.stats[asset].trades.append(trade)
                self.all_trades.append(trade)
            return
        
        # Price validation (market mid and spread)
        match = self.PATTERNS['price_validation'].search(message)
        if match:
            ticker = match.group(1)
            market_mid_cents = int(match.group(2))
            deviation_cents = int(match.group(3))
            
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                # Update the most recent trade with market info
                if self.stats[asset].trades:
                    last_trade = self.stats[asset].trades[-1]
                    last_trade.market_mid_cents = market_mid_cents
                    last_trade.spread_cents = deviation_cents
                    
                    # Update average spread
                    n = self.stats[asset].orders_attempted
                    if n > 0:
                        self.stats[asset].avg_spread_cents = (
                            (self.stats[asset].avg_spread_cents * (n - 1) + deviation_cents) / n
                        )
            return
        
        # Dynamic order type
        match = self.PATTERNS['dynamic_order_type'].search(message)
        if match:
            ticker = match.group(1)
            order_type = match.group(2)
            
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                self.stats[asset].orders_by_type[order_type] += 1
                
                # Update the most recent trade
                if self.stats[asset].trades:
                    self.stats[asset].trades[-1].order_type = order_type
            return
        
        # Market validation spread
        match = self.PATTERNS['market_validation_spread'].search(message)
        if match:
            asset = match.group(1)
            spread_cents = int(match.group(2))
            
            if asset in self.stats:
                # Update the most recent trade if not already set
                if self.stats[asset].trades and self.stats[asset].trades[-1].spread_cents == 0:
                    self.stats[asset].trades[-1].spread_cents = spread_cents
            return
        
        # Settlement (outcome and PnL)
        match = self.PATTERNS['settlement'].search(message)
        if match:
            ticker = match.group(1)
            outcome = match.group(2)
            pnl = float(match.group(3))
            
            asset = self._extract_asset(ticker)
            if asset and asset in self.stats:
                # Find the matching trade and update it
                for trade in reversed(self.stats[asset].trades):
                    if trade.ticker == ticker and trade.outcome == 'PENDING':
                        trade.outcome = outcome
                        trade.pnl_usd = pnl
                        
                        # Update stats
                        self.stats[asset].total_pnl_usd += pnl
                        if outcome == 'WIN':
                            self.stats[asset].wins += 1
                            self.stats[asset].gross_profit_usd += pnl
                        elif outcome == 'LOSS':
                            self.stats[asset].losses += 1
                            self.stats[asset].gross_loss_usd += abs(pnl)
                        
                        # Update average win/loss
                        if outcome == 'WIN':
                            n_wins = self.stats[asset].wins
                            self.stats[asset].average_win_usd = (
                                (self.stats[asset].average_win_usd * (n_wins - 1) + pnl) / n_wins
                            )
                        elif outcome == 'LOSS':
                            n_losses = self.stats[asset].losses
                            self.stats[asset].average_loss_usd = (
                                (self.stats[asset].average_loss_usd * (n_losses - 1) + abs(pnl)) / n_losses
                            )
                        
                        # Update drawdown tracking
                        current_equity = self.stats[asset].total_pnl_usd
                        if current_equity > self.stats[asset].peak_equity_usd:
                            self.stats[asset].peak_equity_usd = current_equity
                            self.stats[asset].current_drawdown_usd = 0.0
                        else:
                            self.stats[asset].current_drawdown_usd = self.stats[asset].peak_equity_usd - current_equity
                            if self.stats[asset].current_drawdown_usd > self.stats[asset].max_drawdown_usd:
                                self.stats[asset].max_drawdown_usd = self.stats[asset].current_drawdown_usd
                        
                        break
            return
        
        # Slot allocator allocated
        match = self.PATTERNS['slot_allocator_allocated'].search(message)
        if match:
            asset = match.group(1)
            side = match.group(2)
            price_cents = int(match.group(3))
            slot_id = match.group(4)
            total_exposure = float(match.group(5))
            if asset in self.stats:
                self.stats[asset].slot_allocations += 1
                # Update the most recent trade with slot info
                if self.stats[asset].trades:
                    last_trade = self.stats[asset].trades[-1]
                    last_trade.slot_id = slot_id
            return
        
        # Slot allocator reject
        match = self.PATTERNS['slot_allocator_reject'].search(message)
        if match:
            asset = match.group(1)
            side = match.group(2)
            price_cents = int(match.group(3))
            edge_pct = float(match.group(4))
            reason = match.group(5)
            if asset in self.stats:
                self.stats[asset].slot_rejections += 1
                self.stats[asset].candidates_rejected[f'slot_allocator_{reason}'] += 1
            return
        
        # Slot allocator block (router level)
        match = self.PATTERNS['slot_allocator_block'].search(message)
        if match:
            # Extract asset from message
            for asset in self.stats:
                if f"{asset}_15M" in message or asset in message:
                    self.stats[asset].slot_rejections += 1
                    self.stats[asset].orders_rejected['slot_allocator_insufficient_exposure'] += 1
                    break
            return
        
        # Slot allocator bypass (exit order)
        match = self.PATTERNS['slot_allocator_bypass'].search(message)
        if match:
            # Extract asset from message
            for asset in self.stats:
                if f"{asset}_15M" in message or asset in message:
                    self.stats[asset].exit_orders += 1
                    # Update the most recent trade as exit order
                    if self.stats[asset].trades:
                        last_trade = self.stats[asset].trades[-1]
                        last_trade.is_exit_order = True
                    break
            return
        
        # Exit order detection
        match = self.PATTERNS['exit_order'].search(message)
        if match:
            # Extract asset from message
            for asset in self.stats:
                if f"{asset}_15M" in message or asset in message:
                    self.stats[asset].exit_orders += 1
                    # Update the most recent trade as exit order
                    if self.stats[asset].trades:
                        last_trade = self.stats[asset].trades[-1]
                        last_trade.is_exit_order = True
                    break
            return
        
        # Min decision minute configuration
        match = self.PATTERNS['min_decision_minute'].search(message)
        if match:
            asset = match.group(1)
            min_decision_minute = int(match.group(2))
            if asset in self.stats:
                # Update the most recent trade with min_decision_minute
                if self.stats[asset].trades:
                    last_trade = self.stats[asset].trades[-1]
                    last_trade.min_decision_minute = float(min_decision_minute)
            return
        
        # Trading window skip (min_decision_minute rejection)
        match = self.PATTERNS['trading_window_skip'].search(message)
        if match:
            asset = match.group(1)
            time_to_expiry = float(match.group(2))
            min_time_to_expiry = int(match.group(3))
            if asset in self.stats:
                self.stats[asset].trading_window_skips += 1
                self.stats[asset].candidates_rejected[f'trading_window_skip_min_decision_{min_time_to_expiry//60}min'] += 1
            return
    
    def monitor(self):
        """Monitor log file for specified duration."""
        print(f"{'='*80}")
        print(f"REAL-TIME TRADING MONITOR")
        print(f"{'='*80}")
        print(f"Log file: {self.log_file}")
        print(f"Duration: {self.duration_minutes} minutes")
        print(f"Start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End time: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
        # Get initial file size
        if not self.log_file.exists():
            print(f"ERROR: Log file not found: {self.log_file}")
            return
        
        file_size = self.log_file.stat().st_size
        
        last_report_time = self.start_time
        report_interval = 60  # Report every 60 seconds
        
        while datetime.now() < self.end_time:
            # Check if file grew
            current_size = self.log_file.stat().st_size
            if current_size > file_size:
                # Read new lines
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(file_size)
                    new_lines = f.readlines()
                    
                    for line in new_lines:
                        self._process_line(line)
                
                file_size = current_size
            
            # Periodic report
            time_since_last_report = (datetime.now() - last_report_time).total_seconds()
            if time_since_last_report >= report_interval:
                self.print_interim_report()
                last_report_time = datetime.now()
            
            time.sleep(1)
        
        # Final report
        self.print_final_report()
    
    def print_interim_report(self):
        """Print interim progress report."""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        remaining = self.duration_minutes - elapsed
        
        print(f"\n{'='*80}")
        print(f"INTERIM REPORT - Elapsed: {elapsed:.1f}m, Remaining: {remaining:.1f}m")
        print(f"{'='*80}")
        print(f"WebSocket events: {self.websocket_events}")
        print(f"Agent cycles: {self.agent_cycles}")
        print(f"Catalog refreshes: {self.catalog_refreshes}")
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            stats = self.stats[asset]
            print(f"\n{asset}:")
            print(f"  Candidates: {stats.candidates_generated} gen, {sum(stats.candidates_rejected.values())} rej")
            if stats.candidates_rejected:
                print(f"  Rejection Reasons:")
                for reason, count in sorted(stats.candidates_rejected.items(), key=lambda x: -x[1])[:5]:
                    print(f"    {reason}: {count}")
            print(f"  Orders: {stats.orders_attempted} att, {stats.orders_accepted} acc, {stats.fills} fills")
            print(f"  Slot Allocator: {stats.slot_allocations} alloc, {stats.slot_rejections} rej")
            print(f"  Exit Orders: {stats.exit_orders}")
            print(f"  Trading Window Skips: {stats.trading_window_skips}")
            print(f"  Order Sides: {dict(stats.orders_by_side)}")
            print(f"  Order Types: {dict(stats.orders_by_type)}")
            print(f"  Risk: {stats.risk_blocks} blocks, {sum(stats.risk_vetoes.values())} vetoes")
            
            if stats.orders_attempted > 0:
                print(f"  Avg Entry: {stats.avg_entry_price_cents:.1f}c, Edge: {stats.avg_edge_pct:.2f}%, Spread: {stats.avg_spread_cents:.1f}c")
            
            if stats.fills > 0:
                print(f"  PnL: ${stats.total_pnl_usd:.2f} ({stats.wins}W/{stats.losses}L/{stats.pending}P)")
                if stats.wins + stats.losses > 0:
                    win_rate = stats.wins / (stats.wins + stats.losses) * 100
                    print(f"  Win Rate: {win_rate:.1f}%")
            
            # Show recent trades with threshold metrics
            if stats.trades:
                print(f"  Recent Trades (last 3):")
                for trade in stats.trades[-3:]:
                    threshold_info = f"conf={trade.confidence:.2f}"
                    if trade.min_edge_threshold:
                        threshold_info += f" min_edge={trade.min_edge_threshold:.2f}%"
                    if trade.max_spread_threshold:
                        threshold_info += f" max_spread={trade.max_spread_threshold}c"
                    if trade.regime:
                        threshold_info += f" regime={trade.regime}"
                    if trade.slot_id:
                        threshold_info += f" slot={trade.slot_id[:8]}"
                    if trade.is_exit_order:
                        threshold_info += " EXIT"
                    if trade.min_decision_minute:
                        threshold_info += f" min_dec={trade.min_decision_minute}m"
                    print(f"    {trade.timestamp.strftime('%H:%M:%S')} {trade.side} {trade.entry_price_cents}c edge={trade.edge_pct:.1f}% {trade.outcome} [{threshold_info}]")
    
    def print_final_report(self):
        """Print final comprehensive report."""
        print(f"\n{'='*80}")
        print(f"FINAL TRADING ACTIVITY REPORT")
        print(f"{'='*80}")
        print(f"Duration: {self.duration_minutes} minutes")
        print(f"Start: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        
        # Global stats
        print(f"\nGLOBAL STATISTICS:")
        print(f"  WebSocket events processed: {self.websocket_events}")
        print(f"  Agent cycles: {self.agent_cycles}")
        print(f"  Catalog refreshes: {self.catalog_refreshes}")
        print(f"  Circuit breaker trips: {self.circuit_breaker_trips}")
        print(f"  Kill switch activations: {self.kill_switch_activations}")
        
        # Per-asset summaries
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            print(self.stats[asset].summary())
        
        # Aggregate analysis
        print(f"\n{'='*80}")
        print("AGGREGATE ANALYSIS")
        print(f"{'='*80}")
        
        total_candidates = sum(s.candidates_generated for s in self.stats.values())
        total_orders = sum(s.orders_attempted for s in self.stats.values())
        total_fills = sum(s.fills for s in self.stats.values())
        total_risk_blocks = sum(s.risk_blocks for s in self.stats.values())
        total_pnl = sum(s.total_pnl_usd for s in self.stats.values())
        total_wins = sum(s.wins for s in self.stats.values())
        total_losses = sum(s.losses for s in self.stats.values())
        
        print(f"Total candidates generated: {total_candidates}")
        print(f"Total orders attempted: {total_orders}")
        print(f"Total fills: {total_fills}")
        print(f"Total risk blocks: {total_risk_blocks}")
        print(f"Total PnL: ${total_pnl:.2f}")
        print(f"Total Wins: {total_wins}, Total Losses: {total_losses}")
        
        if total_candidates > 0:
            print(f"Order conversion rate: {total_orders / total_candidates * 100:.1f}%")
        
        if total_orders > 0:
            print(f"Fill rate: {total_fills / total_orders * 100:.1f}%")
        
        if total_wins + total_losses > 0:
            print(f"Overall win rate: {total_wins / (total_wins + total_losses) * 100:.1f}%")
        
        # Advanced metrics (profit factor, expectancy, drawdown)
        print(f"\n{'='*80}")
        print("ADVANCED TRADING METRICS")
        print(f"{'='*80}")
        
        total_gross_profit = sum(s.gross_profit_usd for s in self.stats.values())
        total_gross_loss = sum(s.gross_loss_usd for s in self.stats.values())
        
        if total_gross_loss > 0:
            profit_factor = total_gross_profit / total_gross_loss
            print(f"Profit Factor: {profit_factor:.2f} (gross profit ${total_gross_profit:.2f} / gross loss ${total_gross_loss:.2f})")
            if profit_factor >= 2.0:
                print(f"  Status: EXCELLENT (above 2.0)")
            elif profit_factor >= 1.5:
                print(f"  Status: SOLID (above 1.5)")
            elif profit_factor >= 1.0:
                print(f"  Status: THIN (1.0-1.3, edge exists but razor-thin)")
            else:
                print(f"  Status: POOR (below 1.0, losing money)")
        else:
            print("Profit Factor: N/A (no losses yet)")
        
        # Expectancy calculation
        if total_wins + total_losses > 0:
            total_avg_win = sum(s.average_win_usd for s in self.stats.values() if s.average_win_usd > 0)
            total_avg_loss = sum(s.average_loss_usd for s in self.stats.values() if s.average_loss_usd > 0)
            win_rate = total_wins / (total_wins + total_losses)
            loss_rate = total_losses / (total_wins + total_losses)
            
            if total_avg_win > 0 and total_avg_loss > 0:
                expectancy = (win_rate * total_avg_win) - (loss_rate * total_avg_loss)
                print(f"Expectancy: ${expectancy:.2f} per trade")
                print(f"  Win rate: {win_rate:.1%}, Avg win: ${total_avg_win:.2f}, Avg loss: ${total_avg_loss:.2f}")
                if expectancy > 0:
                    print(f"  Status: POSITIVE (profitable over time)")
                else:
                    print(f"  Status: NEGATIVE (losing money over time)")
        
        # Average win vs average loss ratio
        total_avg_win = sum(s.average_win_usd for s in self.stats.values() if s.average_win_usd > 0)
        total_avg_loss = sum(s.average_loss_usd for s in self.stats.values() if s.average_loss_usd > 0)
        
        if total_avg_win > 0 and total_avg_loss > 0:
            win_loss_ratio = total_avg_win / total_avg_loss
            print(f"Average Win/Loss Ratio: {win_loss_ratio:.2f}")
            if win_loss_ratio >= 1.5:
                print(f"  Status: EXCELLENT (target: >= 1.5x)")
            elif win_loss_ratio >= 1.0:
                print(f"  Status: GOOD (at least 1:1)")
            else:
                print(f"  Status: POOR (need higher win rate to compensate)")
        
        # Drawdown analysis
        total_max_drawdown = sum(s.max_drawdown_usd for s in self.stats.values())
        total_current_drawdown = sum(s.current_drawdown_usd for s in self.stats.values())
        
        print(f"\nDrawdown Analysis:")
        print(f"  Maximum Drawdown: ${total_max_drawdown:.2f}")
        print(f"  Current Drawdown: ${total_current_drawdown:.2f}")
        
        # Per-asset drawdown
        print(f"\n  Per-Asset Drawdown:")
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            stats = self.stats[asset]
            if stats.max_drawdown_usd > 0 or stats.current_drawdown_usd > 0:
                print(f"    {asset}: Max ${stats.max_drawdown_usd:.2f}, Current ${stats.current_drawdown_usd:.2f}, Peak ${stats.peak_equity_usd:.2f}")
        
        # Price band analysis
        print(f"\n{'='*80}")
        print("PRICE BAND ANALYSIS")
        print(f"{'='*80}")
        
        price_bands = {'10-20c': 0, '20-30c': 0, '30-40c': 0, '40-50c': 0, '>50c': 0}
        for trade in self.all_trades:
            if trade.entry_price_cents <= 20:
                price_bands['10-20c'] += 1
            elif trade.entry_price_cents <= 30:
                price_bands['20-30c'] += 1
            elif trade.entry_price_cents <= 40:
                price_bands['30-40c'] += 1
            elif trade.entry_price_cents <= 50:
                price_bands['40-50c'] += 1
            else:
                price_bands['>50c'] += 1
        
        for band, count in price_bands.items():
            print(f"  {band}: {count} orders")
        
        # Side analysis
        print(f"\n{'='*80}")
        print("SIDE ANALYSIS")
        print(f"{'='*80}")
        
        side_counts = defaultdict(int)
        for trade in self.all_trades:
            side_counts[trade.side] += 1
        
        for side, count in sorted(side_counts.items()):
            print(f"  {side}: {count} orders")
        
        # Order type analysis
        print(f"\n{'='*80}")
        print("ORDER TYPE ANALYSIS")
        print(f"{'='*80}")
        
        order_type_counts = defaultdict(int)
        for trade in self.all_trades:
            order_type_counts[trade.order_type] += 1
        
        for order_type, count in sorted(order_type_counts.items()):
            print(f"  {order_type}: {count} orders")
        
        # Threshold analysis for fine-tuning
        print(f"\n{'='*80}")
        print("THRESHOLD ANALYSIS (Fine-Tuning)")
        print(f"{'='*80}")
        
        # Confidence distribution
        conf_buckets = {'<0.65': 0, '0.65-0.75': 0, '0.75-0.85': 0, '>0.85': 0}
        for trade in self.all_trades:
            if trade.confidence < 0.65:
                conf_buckets['<0.65'] += 1
            elif trade.confidence < 0.75:
                conf_buckets['0.65-0.75'] += 1
            elif trade.confidence < 0.85:
                conf_buckets['0.75-0.85'] += 1
            else:
                conf_buckets['>0.85'] += 1
        
        print("  Confidence Distribution:")
        for bucket, count in conf_buckets.items():
            if count > 0:
                print(f"    {bucket}: {count} orders")
        
        # Edge distribution
        edge_buckets = {'<1.5%': 0, '1.5-2.5%': 0, '2.5-3.5%': 0, '>3.5%': 0}
        for trade in self.all_trades:
            if trade.edge_pct < 1.5:
                edge_buckets['<1.5%'] += 1
            elif trade.edge_pct < 2.5:
                edge_buckets['1.5-2.5%'] += 1
            elif trade.edge_pct < 3.5:
                edge_buckets['2.5-3.5%'] += 1
            else:
                edge_buckets['>3.5%'] += 1
        
        print("  Edge Distribution:")
        for bucket, count in edge_buckets.items():
            if count > 0:
                print(f"    {bucket}: {count} orders")
        
        # Regime distribution
        regime_counts = defaultdict(int)
        for trade in self.all_trades:
            if trade.regime:
                regime_counts[trade.regime] += 1
        
        if regime_counts:
            print("  Market Regime Distribution:")
            for regime, count in sorted(regime_counts.items()):
                print(f"    {regime}: {count} orders")
        
        # Threshold effectiveness analysis
        print("\n  Threshold Effectiveness:")
        trades_with_thresholds = [t for t in self.all_trades if t.min_edge_threshold or t.max_spread_threshold]
        if trades_with_thresholds:
            print(f"    Orders with threshold data: {len(trades_with_thresholds)}")
            
            # Win rate by confidence bucket
            for bucket in ['<0.65', '0.65-0.75', '0.75-0.85', '>0.85']:
                bucket_trades = []
                if bucket == '<0.65':
                    bucket_trades = [t for t in trades_with_thresholds if t.confidence < 0.65]
                elif bucket == '0.65-0.75':
                    bucket_trades = [t for t in trades_with_thresholds if 0.65 <= t.confidence < 0.75]
                elif bucket == '0.75-0.85':
                    bucket_trades = [t for t in trades_with_thresholds if 0.75 <= t.confidence < 0.85]
                else:
                    bucket_trades = [t for t in trades_with_thresholds if t.confidence >= 0.85]
                
                if bucket_trades:
                    wins = sum(1 for t in bucket_trades if t.outcome == 'WIN')
                    losses = sum(1 for t in bucket_trades if t.outcome == 'LOSS')
                    total = wins + losses
                    if total > 0:
                        win_rate = wins / total * 100
                        print(f"    {bucket} confidence: {win_rate:.1f}% win rate ({wins}W/{losses}L)")
        else:
            print("    No threshold data available in logs")
        
        # Slot allocator analysis
        print(f"\n{'='*80}")
        print("SLOT ALLOCATOR ANALYSIS")
        print(f"{'='*80}")
        
        total_slot_allocations = sum(s.slot_allocations for s in self.stats.values())
        total_slot_rejections = sum(s.slot_rejections for s in self.stats.values())
        total_exit_orders = sum(s.exit_orders for s in self.stats.values())
        
        print(f"Total Slot Allocations: {total_slot_allocations}")
        print(f"Total Slot Rejections: {total_slot_rejections}")
        print(f"Total Exit Orders: {total_exit_orders}")
        
        if total_slot_allocations + total_slot_rejections > 0:
            allocation_rate = total_slot_allocations / (total_slot_allocations + total_slot_rejections) * 100
            print(f"Slot Allocation Success Rate: {allocation_rate:.1f}%")
        
        # Per-asset slot allocator stats
        print("\n  Per-Asset Slot Allocator:")
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            stats = self.stats[asset]
            if stats.slot_allocations > 0 or stats.slot_rejections > 0:
                print(f"    {asset}: {stats.slot_allocations} alloc, {stats.slot_rejections} rej, {stats.exit_orders} exit")
        
        # Exit order analysis
        print(f"\n{'='*80}")
        print("EXIT ORDER ANALYSIS")
        print(f"{'='*80}")
        
        exit_trades = [t for t in self.all_trades if t.is_exit_order]
        if exit_trades:
            print(f"Total Exit Orders: {len(exit_trades)}")
            
            # Exit orders by asset
            exit_by_asset = defaultdict(int)
            for trade in exit_trades:
                exit_by_asset[trade.asset] += 1
            
            print("  Exit Orders by Asset:")
            for asset, count in sorted(exit_by_asset.items()):
                print(f"    {asset}: {count}")
            
            # Exit order outcomes
            exit_outcomes = defaultdict(int)
            for trade in exit_trades:
                if trade.outcome:
                    exit_outcomes[trade.outcome] += 1
            
            if exit_outcomes:
                print("  Exit Order Outcomes:")
                for outcome, count in sorted(exit_outcomes.items()):
                    print(f"    {outcome}: {count}")
        else:
            print("No exit orders detected")
        
        # Min decision minute analysis
        print(f"\n{'='*80}")
        print("MIN DECISION MINUTE ANALYSIS")
        print(f"{'='*80}")
        
        total_trading_window_skips = sum(s.trading_window_skips for s in self.stats.values())
        print(f"Total Trading Window Skips: {total_trading_window_skips}")
        
        # Per-asset trading window skips
        print("\n  Per-Asset Trading Window Skips:")
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            stats = self.stats[asset]
            if stats.trading_window_skips > 0:
                print(f"    {asset}: {stats.trading_window_skips} skips")
        
        # Min decision minute distribution
        min_dec_values = [t.min_decision_minute for t in self.all_trades if t.min_decision_minute]
        if min_dec_values:
            print("\n  Min Decision Minute Distribution:")
            from collections import Counter
            min_dec_counts = Counter(min_dec_values)
            for value, count in sorted(min_dec_counts.items()):
                print(f"    {value}m: {count} orders")
        
        # Recent trades summary
        print(f"\n{'='*80}")
        print("RECENT TRADES (last 10)")
        print(f"{'='*80}")
        
        for trade in self.all_trades[-10:]:
            print(f"  {trade.timestamp.strftime('%H:%M:%S')} {trade.asset} {trade.side} {trade.entry_price_cents}c edge={trade.edge_pct:.1f}% spread={trade.spread_cents}c {trade.order_type} {trade.outcome} pnl=${trade.pnl_usd if trade.pnl_usd else 0:.2f}")
        
        # Top rejection reasons
        print(f"\nTOP CANDIDATE REJECTION REASONS:")
        all_rejections = defaultdict(int)
        for stats in self.stats.values():
            for reason, count in stats.candidates_rejected.items():
                all_rejections[reason] += count
        
        for reason, count in sorted(all_rejections.items(), key=lambda x: -x[1])[:10]:
            print(f"  {reason}: {count}")
        
        print(f"\nTOP ORDER REJECTION REASONS:")
        all_order_rejections = defaultdict(int)
        for stats in self.stats.values():
            for reason, count in stats.orders_rejected.items():
                all_order_rejections[reason] += count
        
        for reason, count in sorted(all_order_rejections.items(), key=lambda x: -x[1])[:10]:
            print(f"  {reason}: {count}")
        
        print(f"\nTOP RISK VETO REASONS:")
        all_risk_vetoes = defaultdict(int)
        for stats in self.stats.values():
            for reason, count in stats.risk_vetoes.items():
                all_risk_vetoes[reason] += count
        
        for reason, count in sorted(all_risk_vetoes.items(), key=lambda x: -x[1])[:10]:
            print(f"  {reason}: {count}")
        
        # Save to JSON
        output_file = Path(__file__).parent.parent / "output" / f"trading_monitor_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        report_data = {
            "duration_minutes": self.duration_minutes,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "global_stats": {
                "websocket_events": self.websocket_events,
                "agent_cycles": self.agent_cycles,
                "catalog_refreshes": self.catalog_refreshes,
                "circuit_breaker_trips": self.circuit_breaker_trips,
                "kill_switch_activations": self.kill_switch_activations,
            },
            "per_asset_stats": {
                asset: {
                    "velocity_signals": s.velocity_signals,
                    "candidates_generated": s.candidates_generated,
                    "candidates_rejected": dict(s.candidates_rejected),
                    "orders_attempted": s.orders_attempted,
                    "orders_accepted": s.orders_accepted,
                    "orders_rejected": dict(s.orders_rejected),
                    "orders_by_side": dict(s.orders_by_side),
                    "orders_by_type": dict(s.orders_by_type),
                    "avg_entry_price_cents": s.avg_entry_price_cents,
                    "avg_edge_pct": s.avg_edge_pct,
                    "avg_spread_cents": s.avg_spread_cents,
                    "avg_confidence": s.avg_confidence,
                    "risk_blocks": s.risk_blocks,
                    "risk_vetoes": dict(s.risk_vetoes),
                    "fills": s.fills,
                    "total_pnl_usd": s.total_pnl_usd,
                    "wins": s.wins,
                    "losses": s.losses,
                    "pending": s.pending,
                }
                for asset, s in self.stats.items()
            },
            "all_trades": [
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "asset": trade.asset,
                    "ticker": trade.ticker,
                    "side": trade.side,
                    "action": trade.action,
                    "contract_side": trade.contract_side,
                    "entry_price_cents": trade.entry_price_cents,
                    "limit_price_cents": trade.limit_price_cents,
                    "market_mid_cents": trade.market_mid_cents,
                    "spread_cents": trade.spread_cents,
                    "edge_pct": trade.edge_pct,
                    "count": trade.count,
                    "notional_usd": trade.notional_usd,
                    "order_type": trade.order_type,
                    "confidence": trade.confidence,
                    "velocity": trade.velocity,
                    "rsi": trade.rsi,
                    "macd_hist": trade.macd_hist,
                    "time_to_expiry_sec": trade.time_to_expiry_sec,
                    "outcome": trade.outcome,
                    "exit_price_cents": trade.exit_price_cents,
                    "pnl_usd": trade.pnl_usd,
                    "reason": trade.reason,
                }
                for trade in self.all_trades
            ]
        }
        
        with open(output_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        print(f"\nReport saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Real-time trading activity monitor')
    parser.add_argument('--log-file', default='logs/full.log', help='Path to log file')
    parser.add_argument('--duration', type=int, default=360, help='Duration in minutes (default: 360 = 6 hours)')
    
    args = parser.parse_args()
    
    monitor = RealtimeTradingMonitor(args.log_file, args.duration)
    monitor.monitor()


if __name__ == '__main__':
    main()
