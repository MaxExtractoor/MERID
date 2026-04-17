"""
Kalshi Arbitrage Detection Bot

Detects cross-market and within-event mispricings on Kalshi.

Types of arbitrage:
1. Simple YES/NO sum ≠ 1 (within single market)
2. Cross-market mispricings (same outcome, different tickers)
3. Related markets (BTC daily vs weekly, correlated events)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timezone
from utils.logger import get_logger

from merid.risk.crypto_swarm_risk_btc15m import (
    CryptoSwarmRiskBTC15m,
    TradeProposal as RiskProposal,
    TradeMode,
    RiskPhase,
)

logger = get_logger(__name__)


@dataclass
class ArbOpportunity:
    """Arbitrage opportunity found."""
    arb_type: str  # 'yes_no_sum', 'cross_market', 'correlated'
    market_a: str
    market_b: Optional[str]
    edge: float  # Expected profit as decimal
    yes_price_a: float
    no_price_a: float
    yes_price_b: Optional[float]
    no_price_b: Optional[float]
    description: str
    confidence: float  # 0-1 based on liquidity/depth
    timestamp: datetime


class KalshiArbitrageBot:
    """
    Kalshi arbitrage detection bot.
    
    Scans markets for mispricings and generates trade signals.
    
    Usage:
        bot = KalshiArbitrageBot()
        
        # Find simple YES/NO arb within event
        opps = bot.find_simple_arb("KXBTC-25JAN-DAILY")
        
        # Scan all events
        all_opps = bot.scan_all_events()
    """
    
    def __init__(
        self,
        fee_bp: float = 10.0,
        min_edge: float = 0.02,
        kalshi_session=None,
        risk_engine: Optional[CryptoSwarmRiskBTC15m] = None,
        equity: float = 0.0,
    ):
        self.fee_bp = fee_bp
        self.min_edge = min_edge
        self.fee_decimal = fee_bp / 10000.0
        self.ksession = kalshi_session
        if risk_engine is not None:
            self.risk_engine: CryptoSwarmRiskBTC15m = risk_engine
        else:
            _init_phase = RiskPhase.PHASE_0
            try:
                from merid.risk.promotion_engine import get_promotion_engine
                _phase_name = get_promotion_engine().current_phase.name
                _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
            except Exception as _e:
                logger.debug("phase_lookup_promotion_engine: %s", _e)
            self.risk_engine = CryptoSwarmRiskBTC15m(current_equity=equity, phase=_init_phase)
    
    def fetch_markets_for_event(self, event_ticker: str) -> List[Dict[str, Any]]:
        """
        Fetch all markets for an event ticker.
        
        Args:
            event_ticker: Event ticker (e.g., "KXBTC-25JAN-DAILY")
        
        Returns:
            List of market dicts
        """
        if self.ksession is None:
            logger.warning("No Kalshi session provided, returning empty list")
            return []
        
        try:
            resp = self.ksession.request(
                "GET",
                "/markets",
                params={"event_ticker": event_ticker, "limit": 200},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("markets", [])
        except Exception as exc:
            logger.warning(f"Failed to fetch markets for {event_ticker}: {exc}")
            return []
    
    def find_simple_arb(
        self,
        markets: List[Dict[str, Any]],
    ) -> List[ArbOpportunity]:
        """
        Find simple YES/NO arb opportunities where YES + NO ≠ 1.
        
        Args:
            markets: List of market dicts with yes_price, no_price
        
        Returns:
            List of ArbOpportunity
        """
        opps = []
        
        for m in markets:
            ticker = m.get("ticker", "unknown")
            yes_price = m.get("yes_price", 50) / 100.0
            no_price = m.get("no_price", 50) / 100.0
            
            total = yes_price + no_price
            edge = abs(1.0 - total)
            
            # Edge must overcome fees + safety margin
            threshold = self.fee_decimal + self.min_edge
            
            if edge > threshold:
                opp = ArbOpportunity(
                    arb_type="yes_no_sum",
                    market_a=ticker,
                    market_b=None,
                    edge=edge - self.fee_decimal,  # Net edge after fees
                    yes_price_a=yes_price,
                    no_price_a=no_price,
                    yes_price_b=None,
                    no_price_b=None,
                    description=f"YES({yes_price:.2%}) + NO({no_price:.2%}) = {total:.2%}",
                    confidence=0.8,  # Simple arb is high confidence
                    timestamp=datetime.now(timezone.utc),
                )
                opps.append(opp)
                logger.info(f"Arb found: {ticker} edge={opp.edge:.2%}")
        
        return opps
    
    def find_cross_market_arb(
        self,
        event_tickers: List[str],
    ) -> List[ArbOpportunity]:
        """
        Find cross-market mispricings across related events.
        
        Example: BTC Daily vs BTC Hourly with overlapping outcomes.
        
        Args:
            event_tickers: List of related event tickers
        
        Returns:
            List of ArbOpportunity
        """
        all_markets = []
        
        for event in event_tickers:
            markets = self.fetch_markets_for_event(event)
            for m in markets:
                m["source_event"] = event
            all_markets.extend(markets)
        
        opps = []
        
        # Compare all pairs looking for similar outcomes with divergent prices
        for i, m1 in enumerate(all_markets):
            for m2 in all_markets[i+1:]:
                opp = self._compare_markets(m1, m2)
                if opp:
                    opps.append(opp)
        
        return opps
    
    def _compare_markets(
        self,
        m1: Dict[str, Any],
        m2: Dict[str, Any],
    ) -> Optional[ArbOpportunity]:
        """
        Compare two markets for mispricing.
        
        Returns ArbOpportunity if significant edge found, else None.
        """
        # Check if markets are related (same underlying, similar titles)
        title1 = m1.get("title", "").lower()
        title2 = m2.get("title", "").lower()
        
        # Simple heuristic: look for common keywords
        keywords = ["bitcoin", "btc", "above", "below", "price"]
        match_score = sum(1 for kw in keywords if kw in title1 and kw in title2)
        
        if match_score < 2:
            return None  # Not related enough
        
        # Compare implied probabilities
        yes1 = m1.get("yes_price", 50) / 100.0
        yes2 = m2.get("yes_price", 50) / 100.0
        
        price_diff = abs(yes1 - yes2)
        threshold = self.fee_decimal + self.min_edge
        
        if price_diff > threshold:
            ticker1 = m1.get("ticker", "unknown")
            ticker2 = m2.get("ticker", "unknown")
            
            return ArbOpportunity(
                arb_type="cross_market",
                market_a=ticker1,
                market_b=ticker2,
                edge=price_diff - self.fee_decimal,
                yes_price_a=yes1,
                no_price_a=1-yes1,
                yes_price_b=yes2,
                no_price_b=1-yes2,
                description=f"Related markets diverge: {yes1:.1%} vs {yes2:.1%}",
                confidence=0.6 * (match_score / len(keywords)),  # Scale by match quality
                timestamp=datetime.now(timezone.utc),
            )
        
        return None
    
    def compute_safe_size(
        self,
        opp: ArbOpportunity,
        max_risk: float = 100.0,
        min_liquidity: int = 100,
    ) -> float:
        """
        Compute safe position size for an arb.
        
        Args:
            opp: ArbOpportunity
            max_risk: Maximum dollar risk
            min_liquidity: Minimum contracts needed
        
        Returns:
            Recommended position size (dollars)
        """
        # Base size on edge
        base_size = max_risk * opp.edge * 10  # 10x edge scaling
        
        # Cap by confidence
        size = base_size * opp.confidence
        
        # Hard cap
        size = min(size, max_risk)
        
        # Ensure minimum viable
        if size < 1.0:
            return 0.0
        
        return size
    
    def scan_all_events(
        self,
        event_list: Optional[List[str]] = None,
    ) -> List[ArbOpportunity]:
        """
        Scan all configured events for arbitrage.
        
        Args:
            event_list: Optional list of event tickers (default: BTC events)
        
        Returns:
            List of all opportunities found
        """
        if event_list is None:
            # Default: focus on BTC events
            event_list = [
                "KXBTC-25JAN-DAILY",
                "KXBTC-25JAN-HOURLY",
                "KXBTC-25JAN-15MIN",
            ]
        
        all_opps = []
        
        for event in event_list:
            markets = self.fetch_markets_for_event(event)
            
            # Find YES/NO sum arbs
            simple_opps = self.find_simple_arb(markets)
            all_opps.extend(simple_opps)
        
        # Find cross-market arbs
        cross_opps = self.find_cross_market_arb(event_list)
        all_opps.extend(cross_opps)
        
        # Sort by edge
        all_opps.sort(key=lambda x: x.edge, reverse=True)
        
        logger.info(f"Arb scan complete: {len(all_opps)} opportunities")
        return all_opps
    
    def execute_arb(
        self,
        opp: ArbOpportunity,
        size: float,
    ) -> Dict[str, Any]:
        """
        Execute an arbitrage trade, gated by the risk engine.

        All arb execution paths go through evaluate_arb_proposal.
        Returns a result dict including the risk decision.
        """
        # Risk gate — mandatory, no bypass
        proposal = RiskProposal(
            asset="BTC",
            timeframe="arb",
            side="yes",
            price_cents=int(opp.yes_price_a * 100),
            intent_risk=size,
            tags=["arb", "kalshi_arb_bot"],
        )
        decision = self.risk_engine.evaluate_arb_proposal(proposal)

        if decision.mode == TradeMode.BLOCKED:
            logger.info(
                "Arb blocked by risk engine: %s | market=%s size=%.2f",
                decision.reason, opp.market_a, size,
            )
            return {
                "status": "blocked",
                "reason": decision.reason,
                "market": opp.market_a,
                "size": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        approved_size = decision.final_size
        mode = decision.mode.value  # "paper" or "live"

        logger.info(
            f"[{mode.upper()}] Arb execute: market={opp.market_a} size={approved_size:.2f} edge={opp.edge:.4f} | {decision.reason}"
        )

        return {
            "status": mode,
            "market": opp.market_a,
            "market_b": opp.market_b,
            "size": approved_size,
            "expected_profit": approved_size * opp.edge,
            "risk_decision": decision.reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_arb_scan(
    event_ticker: str,
    kalshi_session=None,
) -> List[Dict[str, Any]]:
    """
    Quick one-liner to scan an event for arbitrage.
    
    Returns:
        List of opportunity dicts
    """
    bot = KalshiArbitrageBot(kalshi_session=kalshi_session)
    markets = bot.fetch_markets_for_event(event_ticker)
    opps = bot.find_simple_arb(markets)
    
    return [
        {
            "market": o.market_a,
            "edge_pct": o.edge * 100,
            "yes_price": o.yes_price_a,
            "no_price": o.no_price_a,
            "description": o.description,
        }
        for o in opps
    ]


def find_best_arb(
    event_tickers: List[str],
    kalshi_session=None,
) -> Optional[ArbOpportunity]:
    """
    Find the best arb across multiple events.
    
    Returns:
        Best ArbOpportunity or None
    """
    bot = KalshiArbitrageBot(kalshi_session=kalshi_session)
    all_opps = bot.scan_all_events(event_tickers)
    
    if not all_opps:
        return None
    
    return all_opps[0]  # Already sorted by edge
