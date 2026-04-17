"""
Intelligence Layer - Real-Time Market Intelligence Processing

Aggregates, processes, and scores intelligence from multiple sources:
- News feeds (CoinTelegraph, CryptoCompare, etc.)
- Social signals (Twitter/X sentiment)
- On-chain data (whale movements, large transactions)
- Market microstructure (order flow, funding rates)
- Technical signals (price action, volume anomalies)
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from collections import deque

from utils.logger import get_logger

logger = get_logger("monitoring.intelligence_layer")


class IntelligenceType(Enum):
    """Types of intelligence signals."""
    NEWS = "news"
    SOCIAL = "social"
    ONCHAIN = "onchain"
    MARKET = "market"
    TECHNICAL = "technical"
    WHALE = "whale"
    REGULATORY = "regulatory"
    SENTIMENT = "sentiment"
    PREDICTION = "prediction"
    ODDS_DRIFT = "odds_drift"
    ARBITRAGE = "arbitrage"


class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    CRITICAL = "critical"


@dataclass
class IntelligenceSignal:
    """A single intelligence signal."""
    signal_id: str
    signal_type: IntelligenceType
    strength: SignalStrength
    source: str
    headline: str
    summary: str
    timestamp: float = field(default_factory=time.time)
    
    symbols: List[str] = field(default_factory=list)
    sentiment_score: float = 0.0
    confidence: float = 0.5
    
    url: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_id": self.signal_id,
            "type": self.signal_type.value,
            "strength": self.strength.value,
            "source": self.source,
            "headline": self.headline,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "symbols": self.symbols,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "url": self.url,
        }


@dataclass
class MarketAlert:
    """High-priority market alert."""
    alert_id: str
    alert_type: str
    severity: str
    message: str
    timestamp: float = field(default_factory=time.time)
    
    symbols: List[str] = field(default_factory=list)
    action_required: bool = False
    recommended_action: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
            "symbols": self.symbols,
            "action_required": self.action_required,
            "recommended_action": self.recommended_action,
        }


class IntelligenceProcessor:
    """
    Processes raw intelligence into actionable signals.
    
    Applies:
    - Sentiment analysis
    - Entity extraction (symbols, companies)
    - Importance scoring
    - Deduplication
    """
    
    BULLISH_KEYWORDS = [
        "surge", "rally", "bullish", "breakout", "all-time high", "ath",
        "adoption", "partnership", "approval", "etf", "institutional",
        "upgrade", "milestone", "record", "growth", "accumulation"
    ]
    
    BEARISH_KEYWORDS = [
        "crash", "dump", "bearish", "breakdown", "sell-off", "selloff",
        "hack", "exploit", "ban", "regulation", "lawsuit", "sec",
        "downgrade", "warning", "risk", "liquidation", "fear"
    ]
    
    SYMBOL_KEYWORDS = {
        # Layer 1 — large cap
        "bitcoin": ["BTC"], "btc": ["BTC"],
        "ethereum": ["ETH"], "eth": ["ETH"],
        "binance coin": ["BNB"], "bnb": ["BNB"],
        "solana": ["SOL"], "sol": ["SOL"],
        "xrp": ["XRP"], "ripple": ["XRP"],
        "cardano": ["ADA"], "ada": ["ADA"],
        "avalanche": ["AVAX"], "avax": ["AVAX"],
        "polkadot": ["DOT"], "dot": ["DOT"],
        "cosmos": ["ATOM"], "atom": ["ATOM"],
        "litecoin": ["LTC"], "ltc": ["LTC"],
        "near protocol": ["NEAR"], "near": ["NEAR"],
        "bitcoin cash": ["BCH"], "bch": ["BCH"],
        "aptos": ["APT"], "apt": ["APT"],
        "sui": ["SUI"],
        "celestia": ["TIA"], "tia": ["TIA"],
        "injective": ["INJ"], "inj": ["INJ"],
        "algorand": ["ALGO"], "algo": ["ALGO"],
        "vechain": ["VET"], "vet": ["VET"],
        "internet computer": ["ICP"], "icp": ["ICP"],
        # Layer 2
        "polygon": ["POL"], "matic": ["POL"], "pol": ["POL"],
        "optimism": ["OP"], "op": ["OP"],
        "arbitrum": ["ARB"], "arb": ["ARB"],
        "starknet": ["STRK"], "strk": ["STRK"],
        # DeFi
        "chainlink": ["LINK"], "link": ["LINK"],
        "uniswap": ["UNI"], "uni": ["UNI"],
        "aave": ["AAVE"],
        "maker": ["MKR"], "mkr": ["MKR"],
        "dydx": ["DYDX"],
        "curve": ["CRV"], "crv": ["CRV"],
        "compound": ["COMP"], "comp": ["COMP"],
        "gmx": ["GMX"],
        "the graph": ["GRT"], "grt": ["GRT"],
        "render": ["RNDR"], "rndr": ["RNDR"],
        "filecoin": ["FIL"], "fil": ["FIL"],
        # Meme
        "dogecoin": ["DOGE"], "doge": ["DOGE"],
        "shiba inu": ["SHIB"], "shib": ["SHIB"],
        "pepe": ["PEPE"],
        "floki": ["FLOKI"],
        # Stablecoins
        "tether": ["USDT"], "usdt": ["USDT"],
        "usd coin": ["USDC"], "usdc": ["USDC"],
        "dai": ["DAI"],
    }
    
    def __init__(self) -> None:
        self._processed_ids: set = set()
        self._signal_history: deque = deque(maxlen=500)
    
    def process_news_article(self, article: Dict[str, Any]) -> IntelligenceSignal:
        """Process a news article into an intelligence signal."""
        import uuid
        
        headline = article.get("headline", article.get("title", ""))
        summary = article.get("summary", "")
        text = f"{headline} {summary}".lower()
        
        sentiment = self._analyze_sentiment(text)
        symbols = self._extract_symbols(text)
        strength = self._determine_strength(sentiment, symbols, article)
        
        signal = IntelligenceSignal(
            signal_id=f"news_{uuid.uuid4().hex[:8]}",
            signal_type=IntelligenceType.NEWS,
            strength=strength,
            source=article.get("source", "unknown"),
            headline=headline,
            summary=summary[:300] if summary else "",
            symbols=symbols,
            sentiment_score=sentiment,
            confidence=0.7,
            url=article.get("url"),
            raw_data=article,
        )
        
        self._signal_history.append(signal)
        return signal
    
    def _analyze_sentiment(self, text: str) -> float:
        """Analyze sentiment of text. Returns -1.0 to 1.0."""
        bullish_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw in text)
        bearish_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw in text)
        
        total = bullish_count + bearish_count
        if total == 0:
            return 0.0
        
        return (bullish_count - bearish_count) / total
    
    def _extract_symbols(self, text: str) -> List[str]:
        """Extract cryptocurrency symbols from text."""
        symbols = set()
        for keyword, syms in self.SYMBOL_KEYWORDS.items():
            if keyword in text:
                symbols.update(syms)
        return list(symbols)
    
    def _determine_strength(
        self,
        sentiment: float,
        symbols: List[str],
        article: Dict[str, Any],
    ) -> SignalStrength:
        """Determine signal strength."""
        importance = article.get("importance", "medium")
        
        if importance == "high" or abs(sentiment) > 0.7:
            return SignalStrength.STRONG
        elif importance == "medium" or abs(sentiment) > 0.4:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def get_recent_signals(self, limit: int = 20) -> List[IntelligenceSignal]:
        """Get recent processed signals."""
        return list(self._signal_history)[-limit:]


class WhaleTracker:
    """
    Tracks large wallet movements and whale activity.
    
    Monitors:
    - Large exchange inflows/outflows
    - Whale wallet accumulation/distribution
    - Smart money movements
    """
    
    def __init__(self) -> None:
        self._whale_alerts: deque = deque(maxlen=100)
        self._tracked_wallets: Dict[str, Dict] = {}
    
    def generate_whale_signal(
        self,
        wallet: str,
        action: str,
        amount_usd: float,
        symbol: str,
    ) -> IntelligenceSignal:
        """Generate a whale movement signal."""
        import uuid
        
        if amount_usd >= 10_000_000:
            strength = SignalStrength.CRITICAL
        elif amount_usd >= 1_000_000:
            strength = SignalStrength.STRONG
        elif amount_usd >= 100_000:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK
        
        sentiment = 0.3 if action == "accumulation" else -0.3
        
        signal = IntelligenceSignal(
            signal_id=f"whale_{uuid.uuid4().hex[:8]}",
            signal_type=IntelligenceType.WHALE,
            strength=strength,
            source="whale_tracker",
            headline=f"Whale {action}: ${amount_usd:,.0f} {symbol}",
            summary=f"Large wallet {wallet[:8]}... {action} of {symbol}",
            symbols=[symbol],
            sentiment_score=sentiment,
            confidence=0.85,
        )
        
        self._whale_alerts.append(signal)
        return signal
    
    def get_recent_alerts(self, limit: int = 10) -> List[IntelligenceSignal]:
        """Get recent whale alerts."""
        return list(self._whale_alerts)[-limit:]


class TechnicalSignalGenerator:
    """
    Generates technical analysis signals.
    
    Monitors:
    - Price breakouts/breakdowns
    - Volume anomalies
    - RSI extremes
    - Moving average crossovers
    """
    
    def __init__(self) -> None:
        self._signals: deque = deque(maxlen=100)
        self._price_history: Dict[str, List[float]] = {}
    
    def update_price(self, symbol: str, price: float) -> Optional[IntelligenceSignal]:
        """Update price and check for signals."""
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        
        history = self._price_history[symbol]
        history.append(price)
        
        if len(history) > 100:
            history.pop(0)
        
        if len(history) < 10:
            return None
        
        return self._check_for_signals(symbol, history)
    
    def _check_for_signals(
        self,
        symbol: str,
        history: List[float],
    ) -> Optional[IntelligenceSignal]:
        """Check for technical signals."""
        import uuid
        
        current = history[-1]
        avg_10 = sum(history[-10:]) / 10
        
        pct_change = (current - avg_10) / avg_10
        
        if abs(pct_change) < 0.02:
            return None
        
        if pct_change > 0.05:
            headline = f"{symbol} breakout: +{pct_change*100:.1f}% above 10-period MA"
            sentiment = 0.6
            strength = SignalStrength.STRONG
        elif pct_change > 0.02:
            headline = f"{symbol} momentum: +{pct_change*100:.1f}% above MA"
            sentiment = 0.3
            strength = SignalStrength.MODERATE
        elif pct_change < -0.05:
            headline = f"{symbol} breakdown: {pct_change*100:.1f}% below 10-period MA"
            sentiment = -0.6
            strength = SignalStrength.STRONG
        else:
            headline = f"{symbol} weakness: {pct_change*100:.1f}% below MA"
            sentiment = -0.3
            strength = SignalStrength.MODERATE
        
        signal = IntelligenceSignal(
            signal_id=f"tech_{uuid.uuid4().hex[:8]}",
            signal_type=IntelligenceType.TECHNICAL,
            strength=strength,
            source="technical_analysis",
            headline=headline,
            summary=f"Price: ${current:,.2f}, 10-period MA: ${avg_10:,.2f}",
            symbols=[symbol.split("/")[0]],
            sentiment_score=sentiment,
            confidence=0.65,
        )
        
        self._signals.append(signal)
        return signal
    
    def get_recent_signals(self, limit: int = 10) -> List[IntelligenceSignal]:
        """Get recent technical signals."""
        return list(self._signals)[-limit:]


class IntelligenceLayer:
    """
    Main intelligence aggregation and processing layer.
    
    Combines all intelligence sources into a unified feed.
    """
    
    def __init__(self) -> None:
        self.processor = IntelligenceProcessor()
        self.whale_tracker = WhaleTracker()
        self.technical = TechnicalSignalGenerator()
        
        self._all_signals: deque = deque(maxlen=1000)
        self._alerts: deque = deque(maxlen=100)
        self._callbacks: List[Callable[[IntelligenceSignal], None]] = []
        
        self._running = False
        self._update_task: Optional[asyncio.Task] = None
        
        logger.info("IntelligenceLayer initialized")
    
    async def start(self) -> None:
        """Start intelligence processing."""
        if self._running:
            return
        
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("IntelligenceLayer started")
    
    async def stop(self) -> None:
        """Stop intelligence processing."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        logger.info("IntelligenceLayer stopped")
    
    async def _update_loop(self) -> None:
        """Main update loop."""
        while self._running:
            try:
                await self._fetch_and_process_news()
                await self._update_technical_signals()
                await self._update_prediction_signals()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Intelligence update error: {e}")
                await asyncio.sleep(10)
    
    async def _update_prediction_signals(self) -> None:
        """Update prediction market signals (drift, arbitrage)."""
        try:
            from monitoring.prediction_markets import get_prediction_aggregator
            import uuid
            
            aggregator = get_prediction_aggregator()
            
            # Process odds drift signals
            drift_signals = aggregator.get_drift_signals(limit=10)
            for drift in drift_signals:
                # Convert to IntelligenceSignal
                sentiment = 0.4 if drift.drift_direction == "up" else -0.4
                strength = SignalStrength.STRONG if drift.is_significant else SignalStrength.MODERATE
                
                signal = IntelligenceSignal(
                    signal_id=f"pred_drift_{uuid.uuid4().hex[:8]}",
                    signal_type=IntelligenceType.ODDS_DRIFT,
                    strength=strength,
                    source=drift.platform.value,
                    headline=f"Odds drift {drift.drift_direction}: {drift.drift_pct:+.1f}%",
                    summary=drift.question[:200],
                    symbols=[],
                    sentiment_score=sentiment,
                    confidence=drift.confidence,
                    raw_data=drift.to_dict(),
                )
                self._all_signals.append(signal)
                
                if drift.is_significant:
                    self._create_alert(signal)
            
            # Process arbitrage opportunities
            arb_opps = aggregator.get_arbitrage_opportunities(limit=5)
            for arb in arb_opps:
                signal = IntelligenceSignal(
                    signal_id=f"pred_arb_{uuid.uuid4().hex[:8]}",
                    signal_type=IntelligenceType.ARBITRAGE,
                    strength=SignalStrength.STRONG if arb.spread_pct > 5 else SignalStrength.MODERATE,
                    source="cross_platform",
                    headline=f"Arbitrage: {arb.spread_pct:.1f}% spread ({arb.platform_a.value} vs {arb.platform_b.value})",
                    summary=arb.question[:200],
                    symbols=[],
                    sentiment_score=0.5,  # Arbitrage is opportunity-positive
                    confidence=0.8,
                    raw_data=arb.to_dict(),
                )
                self._all_signals.append(signal)
                
                if arb.spread_pct > 5:
                    self._create_alert(signal)
                    
        except Exception as e:
            logger.debug(f"Prediction signal update: {e}")
    
    async def _fetch_and_process_news(self) -> None:
        """Fetch and process news articles."""
        try:
            from monitoring.news_feeds import get_news_aggregator
            aggregator = get_news_aggregator()
            articles = aggregator.fetch_all(limit_per_source=5)
            
            for article in articles:
                signal = self.processor.process_news_article(article.to_dict())
                self._all_signals.append(signal)
                
                for callback in self._callbacks:
                    try:
                        callback(signal)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                
                if signal.strength in (SignalStrength.STRONG, SignalStrength.CRITICAL):
                    self._create_alert(signal)
                    
        except Exception as e:
            logger.error(f"News fetch error: {e}")
    
    async def _update_technical_signals(self) -> None:
        """Update technical signals from price data."""
        try:
            from data.live_price_feed import get_live_price_feed
            feed = get_live_price_feed()
            prices = feed.get_all_prices()
            
            for symbol, price_data in prices.items():
                signal = self.technical.update_price(symbol, price_data.price)
                if signal:
                    self._all_signals.append(signal)
                    
                    for callback in self._callbacks:
                        try:
                            callback(signal)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                            
        except Exception as e:
            logger.error(f"Technical signal error: {e}")
    
    def _create_alert(self, signal: IntelligenceSignal) -> MarketAlert:
        """Create a market alert from a strong signal."""
        import uuid
        
        alert = MarketAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:8]}",
            alert_type=signal.signal_type.value,
            severity=signal.strength.value,
            message=signal.headline,
            symbols=signal.symbols,
            action_required=signal.strength == SignalStrength.CRITICAL,
            recommended_action="Review and assess impact" if signal.strength == SignalStrength.CRITICAL else None,
        )
        
        self._alerts.append(alert)
        return alert
    
    def add_signal(self, signal: IntelligenceSignal) -> None:
        """Manually add a signal."""
        self._all_signals.append(signal)
    
    def register_callback(
        self,
        callback: Callable[[IntelligenceSignal], None],
    ) -> None:
        """Register callback for new signals."""
        self._callbacks.append(callback)
    
    def get_all_signals(self, limit: int = 50) -> List[IntelligenceSignal]:
        """Get all recent signals."""
        return list(self._all_signals)[-limit:]
    
    def get_signals_by_type(
        self,
        signal_type: IntelligenceType,
        limit: int = 20,
    ) -> List[IntelligenceSignal]:
        """Get signals filtered by type."""
        filtered = [s for s in self._all_signals if s.signal_type == signal_type]
        return filtered[-limit:]
    
    def get_alerts(self, limit: int = 20) -> List[MarketAlert]:
        """Get recent alerts."""
        return list(self._alerts)[-limit:]
    
    def get_market_sentiment(self) -> Dict[str, Any]:
        """Get aggregated market sentiment."""
        recent = list(self._all_signals)[-50:]
        
        if not recent:
            return {
                "overall": 0.0,
                "label": "neutral",
                "signal_count": 0,
                "by_type": {},
            }
        
        total_sentiment = sum(s.sentiment_score for s in recent)
        avg_sentiment = total_sentiment / len(recent)
        
        if avg_sentiment > 0.3:
            label = "bullish"
        elif avg_sentiment > 0.1:
            label = "slightly_bullish"
        elif avg_sentiment < -0.3:
            label = "bearish"
        elif avg_sentiment < -0.1:
            label = "slightly_bearish"
        else:
            label = "neutral"
        
        by_type = {}
        for signal_type in IntelligenceType:
            type_signals = [s for s in recent if s.signal_type == signal_type]
            if type_signals:
                type_sentiment = sum(s.sentiment_score for s in type_signals) / len(type_signals)
                by_type[signal_type.value] = {
                    "sentiment": type_sentiment,
                    "count": len(type_signals),
                }
        
        return {
            "overall": avg_sentiment,
            "label": label,
            "signal_count": len(recent),
            "by_type": by_type,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get intelligence layer status."""
        return {
            "running": self._running,
            "total_signals": len(self._all_signals),
            "total_alerts": len(self._alerts),
            "sentiment": self.get_market_sentiment(),
        }


_intelligence_layer: Optional[IntelligenceLayer] = None
_intelligence_layer_lock = threading.Lock()


def get_intelligence_layer() -> IntelligenceLayer:
    """Get or create global intelligence layer."""
    global _intelligence_layer
    if _intelligence_layer is None:
        with _intelligence_layer_lock:
            if _intelligence_layer is None:
                _intelligence_layer = IntelligenceLayer()
    return _intelligence_layer


async def start_intelligence_layer() -> IntelligenceLayer:
    """Start intelligence layer."""
    layer = get_intelligence_layer()
    await layer.start()
    return layer


async def stop_intelligence_layer() -> None:
    """Stop intelligence layer."""
    global _intelligence_layer
    if _intelligence_layer is not None:
        await _intelligence_layer.stop()
