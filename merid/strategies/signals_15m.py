"""
15M Strategy Signals - Simple Trend Following with Volatility Filter

Clean, testable signal generation for 15m BTC/ETH contracts.
Based on short-term trend following with volatility filtering to avoid chop.
"""

import math
import pandas as pd
from dataclasses import dataclass
from typing import Literal, Dict, List, Optional
import time
import logging

logger = logging.getLogger(__name__)

Side = Literal["long_up", "long_down", "flat"]

@dataclass
class Signal:
    """Clean trading signal with strength and timestamp."""
    asset: str  # "BTC", "ETH"
    side: Side
    strength: float  # 0..1
    ts: float
    reasoning: str
    z_score: float
    r15: float
    r60: float
    sigma15: float

class PriceHistoryService:
    """Simple price history service for 15m data."""
    
    def __init__(self):
        self.price_data: Dict[str, pd.DataFrame] = {}
        self.mock_enabled = True  # Set to False when real data is available
    
    def get_latest_15m_bars(self, assets: List[str]) -> Dict[str, pd.DataFrame]:
        """Get latest 15m OHLCV bars for assets."""
        if self.mock_enabled:
            return self._generate_mock_data(assets)
        
        # TODO: Integrate with real data source
        # This would pull from your market data feed
        raise NotImplementedError("Real data integration not implemented")
    
    def _generate_mock_data(self, assets: List[str]) -> Dict[str, pd.DataFrame]:
        """Generate mock 15m price data for testing."""
        result = {}
        
        for asset in assets:
            # Generate 50 bars of mock data
            timestamps = pd.date_range(end=pd.Timestamp.now(), periods=50, freq='15min')
            
            # Base price with random walk
            base_price = 45000 if asset == "BTC" else 3000
            returns = pd.Series([0.001 * (i % 3 - 1) + 0.0005 * math.sin(i/5) for i in range(50)])
            prices = [base_price]
            
            for ret in returns:
                prices.append(prices[-1] * (1 + ret))
            
            # Create OHLCV DataFrame
            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': prices[:-1],
                'high': [p * (1 + abs(r) * 0.5) for p, r in zip(prices[:-1], returns)],
                'low': [p * (1 - abs(r) * 0.5) for p, r in zip(prices[:-1], returns)],
                'close': prices[1:],
                'volume': [1000 + abs(r) * 10000 for r in returns]
            })
            
            result[asset] = df
        
        return result
    
    def update_price(self, asset: str, price: float):
        """Update price for an asset (for real-time updates)."""
        if asset not in self.price_data:
            # Initialize with minimal data
            now = pd.Timestamp.now()
            self.price_data[asset] = pd.DataFrame({
                'timestamp': [now - pd.Timedelta(minutes=15)],
                'open': [price],
                'high': [price * 1.001],
                'low': [price * 0.999],
                'close': [price],
                'volume': [1000]
            })
        
        # Add new bar
        last_row = self.price_data[asset].iloc[-1]
        new_row = {
            'timestamp': pd.Timestamp.now(),
            'open': last_row['close'],
            'high': max(price, last_row['close']) * 1.001,
            'low': min(price, last_row['close']) * 0.999,
            'close': price,
            'volume': 1000 + abs(price - last_row['close']) * 100
        }
        
        self.price_data[asset] = pd.concat([self.price_data[asset], pd.DataFrame([new_row])], ignore_index=True)
        
        # Keep only last 50 bars
        if len(self.price_data[asset]) > 50:
            self.price_data[asset] = self.price_data[asset].tail(50)

def compute_signals_15m(prices: Dict[str, pd.DataFrame], now_ts: float, z_thresh: float = 0.7) -> List[Signal]:
    """
    Compute 15m trend-following signals with volatility filter.
    
    Signal logic:
    - If r15 > z_thresh * sigma15 and r60 > 0 → long_up
    - If r15 < -z_thresh * sigma15 and r60 < 0 → long_down
    - Else → flat
    
    Args:
        prices: Dict of asset -> OHLCV DataFrame
        now_ts: Current timestamp
        z_thresh: Z-score threshold for signal generation
    
    Returns:
        List of Signal objects
    """
    signals: List[Signal] = []

    for asset, df in prices.items():
        if len(df) < 40:
            logger.warning(f"Insufficient data for {asset}: {len(df)} bars")
            continue

        closes = df["close"].astype(float)
        
        # Calculate returns
        rets = closes.pct_change().dropna()
        
        # 15m return (log return)
        r15 = math.log(closes.iloc[-1] / closes.iloc[-2])
        
        # 1h return (sum of last 4 15m returns, using log returns)
        if len(closes) >= 5:
            r60 = math.log(closes.iloc[-1] / closes.iloc[-5])
        else:
            r60 = r15  # Fallback to 15m return
        
        # Rolling volatility (32 bars = 8 hours)
        if len(rets) >= 32:
            sigma15 = rets[-32:].std()
        else:
            sigma15 = rets.std()
        
        # Skip if volatility is zero or invalid
        if sigma15 == 0 or math.isnan(sigma15) or math.isnan(r15):
            logger.warning(f"Invalid volatility/return for {asset}: sigma15={sigma15}, r15={r15}")
            continue

        # Calculate Z-score
        z = r15 / sigma15

        # Determine signal
        side: Side = "flat"
        strength = 0.0
        reasoning = ""

        if z > z_thresh and r60 > 0:
            side = "long_up"
            strength = min(1.0, z / (2 * z_thresh))
            reasoning = f"Bullish: z={z:.2f} > {z_thresh}, r60={r60:.3f} > 0"
        elif z < -z_thresh and r60 < 0:
            side = "long_down"
            strength = min(1.0, abs(z) / (2 * z_thresh))
            reasoning = f"Bearish: z={z:.2f} < -{z_thresh}, r60={r60:.3f} < 0"
        else:
            reasoning = f"Flat: z={z:.2f}, r60={r60:.3f}"

        signal = Signal(
            asset=asset,
            side=side,
            strength=strength,
            ts=now_ts,
            reasoning=reasoning,
            z_score=z,
            r15=r15,
            r60=r60,
            sigma15=sigma15
        )
        
        signals.append(signal)
        
        logger.info(f"Signal generated for {asset}: {side} (strength={strength:.2f}, z={z:.2f})")

    return signals

def validate_signal_quality(signals: List[Signal]) -> Dict[str, Any]:
    """Validate signal quality and return statistics."""
    if not signals:
        return {"error": "No signals to validate"}
    
    stats = {
        "total_signals": len(signals),
        "long_up_signals": len([s for s in signals if s.side == "long_up"]),
        "long_down_signals": len([s for s in signals if s.side == "long_down"]),
        "flat_signals": len([s for s in signals if s.side == "flat"]),
        "avg_strength": sum(s.strength for s in signals) / len(signals),
        "avg_z_score": sum(abs(s.z_score) for s in signals) / len(signals),
        "assets_covered": list(set(s.asset for s in signals))
    }
    
    # Check for issues
    issues = []
    
    # Low signal strength
    weak_signals = [s for s in signals if s.strength < 0.3]
    if weak_signals:
        issues.append(f"Low strength signals: {len(weak_signals)}")
    
    # Extreme Z-scores (potential data issues)
    extreme_z = [s for s in signals if abs(s.z_score) > 5]
    if extreme_z:
        issues.append(f"Extreme Z-scores: {len(extreme_z)}")
    
    # Low volatility (potential chop)
    low_vol = [s for s in signals if s.sigma15 < 0.001]
    if low_vol:
        issues.append(f"Low volatility periods: {len(low_vol)}")
    
    stats["issues"] = issues
    
    return stats

# Price service singleton
price_service = PriceHistoryService()

# Example usage:
"""
# Get signals
prices = price_service.get_latest_15m_bars(["BTC", "ETH"])
signals = compute_signals_15m(prices, time.time(), z_thresh=0.7)

# Validate signals
stats = validate_signal_quality(signals)
print(f"Signal stats: {stats}")

# Process signals
for signal in signals:
    if signal.side != "flat":
        print(f"Trade {signal.asset}: {signal.side} (strength: {signal.strength:.2f})")
        print(f"Reasoning: {signal.reasoning}")
"""
