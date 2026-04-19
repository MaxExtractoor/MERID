"""Crypto15M Agent Integration — Intent publishing for 15m crypto agents.

This module provides:
1. Intent publishing from 15m agents to the allocator
2. Mode-based routing (intent_only vs live)
3. Validation of intent metadata
4. Integration with KalshiTradingAgent decision flow

Usage:
    from merid.prediction.crypto15m_agent_integration import Crypto15MIntentPublisher
    
    publisher = Crypto15MIntentPublisher()
    publisher.publish_intent_from_signal(
        agent_id="BTC15M",
        signal=strategy_signal,
        market=event_market,
        mode="intent_only",  # Will be converted to "live" by allocator if selected
    )
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto15m_agent_integration")


# Import with graceful fallback
_15m_imports_available = False
try:
    from merid.prediction.crypto15mallocator import (
        Crypto15MAllocator,
        TradeIntent,
        is_15m_crypto_ticker,
        resolve_expiry_id_from_ticker,
        extract_asset_from_ticker,
        compute_score,
        get_crypto15m_allocator,
    )
    _15m_imports_available = True
except ImportError as e:
    logger.warning(f"Crypto15M allocator imports unavailable: {e}")


def _generate_intent_id(agent_id: str, ticker: str, timestamp: float) -> str:
    """Generate a unique intent ID."""
    import hashlib
    preimage = f"{agent_id}|{ticker}|{timestamp}"
    digest = hashlib.sha256(preimage.encode()).hexdigest()[:16]
    return f"i15m-{digest}"


class Crypto15MIntentPublisher:
    """Publisher for 15m crypto agent intents.
    
    Integrates with KalshiTradingAgent to:
    1. Publish TradeIntents to the allocator during decision cycles
    2. Query allocator state for position tracking
    3. Validate intent metadata for 15m crypto markets
    
    The publisher is a lightweight wrapper that agents instantiate
    and use during their decision cycles.
    """
    
    def __init__(self, agent_id: str):
        """Initialize publisher for an agent.
        
        Args:
            agent_id: Agent identifier (e.g., "BTC15M", "CRYPTO15MMM")
        """
        self.agent_id = agent_id
        self._allocator: Optional[Any] = None
        
        # Check if this agent is a 15m crypto agent
        self.is_15m_crypto_agent = self._check_is_15m_crypto_agent(agent_id)
        
        # Check if this is a market maker agent
        self.is_market_maker = self._check_is_market_maker(agent_id)
        
        if self.is_15m_crypto_agent and _15m_imports_available:
            self._allocator = get_crypto15m_allocator()
            logger.info(
                "[CRYPTO15M-PUBLISHER] Initialized for %s (is_mm=%s)",
                agent_id, self.is_market_maker
            )
    
    def _check_is_15m_crypto_agent(self, agent_id: str) -> bool:
        """Check if agent ID indicates 15m crypto specialization."""
        aid = agent_id.upper()
        # Pattern match: BTC15M, ETH15M, SOL15M, XRP15M, DOGE15M, CRYPTO15MMM, etc.
        if "15M" in aid and any(a in aid for a in ["BTC", "ETH", "SOL", "XRP", "DOGE", "CRYPTO"]):
            return True
        if "CRYPTO15M" in aid:
            return True
        return False
    
    def _check_is_market_maker(self, agent_id: str) -> bool:
        """Check if agent is a market maker."""
        aid = agent_id.upper()
        return "MM" in aid or "MARKET_MAKER" in aid or aid == "CRYPTO15MMM"
    
    def validate_ticker(self, ticker: str) -> Tuple[bool, Optional[str]]:
        """Validate that ticker is a valid 15m crypto market.
        
        Args:
            ticker: Market ticker to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not _15m_imports_available:
            return False, "Allocator imports unavailable"
        
        if not is_15m_crypto_ticker(ticker):
            return False, f"Not a 15m crypto ticker: {ticker}"
        
        asset = extract_asset_from_ticker(ticker)
        if not asset:
            return False, f"Could not extract asset from: {ticker}"
        
        expiry_id = resolve_expiry_id_from_ticker(ticker)
        if not expiry_id:
            return False, f"Could not resolve expiry from: {ticker}"
        
        return True, None
    
    def publish_intent(
        self,
        ticker: str,
        side: str,
        intended_contracts: int,
        limit_price_cents: int,
        netedge: float,
        confidence: float,
        consensus_confidence: Optional[float] = None,
        implied_edge_from_spread: Optional[float] = None,
    ) -> bool:
        """Publish a TradeIntent to the allocator.
        
        Args:
            ticker: Market ticker (e.g., "KXBTC15M-26APR191400-00")
            side: "YES" or "NO"
            intended_contracts: Number of contracts to trade
            limit_price_cents: Limit price in cents
            netedge: Model edge (net of fees)
            confidence: Model confidence (0-100)
            consensus_confidence: Optional consensus confidence for MM scoring
            implied_edge_from_spread: Optional implied edge for MM scoring
            
        Returns:
            True if intent was published successfully
        """
        if not self.is_15m_crypto_agent:
            logger.debug(
                "[CRYPTO15M-PUBLISHER] Agent %s not a 15m crypto agent, skipping",
                self.agent_id
            )
            return False
        
        if not _15m_imports_available:
            logger.debug(
                "[CRYPTO15M-PUBLISHER] Allocator unavailable, cannot publish intent"
            )
            return False
        
        if self._allocator is None:
            logger.warning(
                "[CRYPTO15M-PUBLISHER] Allocator not initialized for %s", self.agent_id
            )
            return False
        
        # Validate ticker
        is_valid, error = self.validate_ticker(ticker)
        if not is_valid:
            logger.debug(
                "[CRYPTO15M-PUBLISHER] Invalid ticker for %s: %s",
                self.agent_id, error
            )
            return False
        
        # Resolve metadata
        asset = extract_asset_from_ticker(ticker)
        expiry_id = resolve_expiry_id_from_ticker(ticker)
        
        # Generate intent ID
        intent_id = _generate_intent_id(self.agent_id, ticker, time.time())
        
        # Create intent
        intent = TradeIntent(
            intent_id=intent_id,
            agent_id=self.agent_id,
            ticker=ticker,
            asset=asset,
            timeframe="15m",
            expiry_id=expiry_id,
            side=side.upper(),
            intended_contracts=intended_contracts,
            limit_price_cents=limit_price_cents,
            netedge=netedge,
            confidence=confidence,
            is_market_maker=self.is_market_maker,
            consensus_confidence=consensus_confidence,
            implied_edge_from_spread=implied_edge_from_spread,
            mode="intent_only",  # Allocator will change to "live" if selected
        )
        
        # Submit to allocator
        self._allocator.submit_intent(intent)
        
        logger.debug(
            "[CRYPTO15M-PUBLISHER] Published intent %s for %s: %s %s %d @ %dc",
            intent_id, self.agent_id, ticker, side, intended_contracts, limit_price_cents
        )
        
        return True
    
    def publish_intent_from_signal(
        self,
        signal: Any,
        market: Any,
        contracts: int,
    ) -> bool:
        """Publish intent from a StrategySignal and EventMarket.
        
        This is the main integration point for KalshiTradingAgent.
        
        Args:
            signal: StrategySignal with edge, confidence, action, etc.
            market: EventMarket with market_id, category, etc.
            contracts: Computed position size in contracts
            
        Returns:
            True if intent was published
        """
        if not self.is_15m_crypto_agent:
            return False
        
        try:
            ticker = market.market_id if hasattr(market, 'market_id') else str(market)
            
            # Extract side from signal action
            side = "YES"
            if hasattr(signal, 'action'):
                action_str = str(signal.action).lower()
                if 'no' in action_str or 'sell_yes' in action_str:
                    side = "NO"
            
            # Extract edge and confidence
            netedge = 0.0
            confidence = 50.0
            if hasattr(signal, 'edge'):
                if hasattr(signal.edge, 'net_edge'):
                    netedge = float(signal.edge.net_edge)
                if hasattr(signal.edge, 'confidence'):
                    confidence = float(signal.edge.confidence)
            
            # Extract limit price
            limit_price_cents = 50
            if hasattr(signal, 'limit_price_cents'):
                limit_price_cents = int(signal.limit_price_cents)
            elif hasattr(signal, 'price_cents'):
                limit_price_cents = int(signal.price_cents)
            
            # Get consensus confidence if available
            consensus_confidence = None
            try:
                from merid.swarm.consensus_aggregator import get_consensus_aggregator
                agg = get_consensus_aggregator()
                if hasattr(agg, 'last_consensus'):
                    consensus = agg.last_consensus
                    if consensus and hasattr(consensus, 'confidence'):
                        consensus_confidence = float(consensus.confidence)
            except Exception:
                pass
            
            return self.publish_intent(
                ticker=ticker,
                side=side,
                intended_contracts=contracts,
                limit_price_cents=limit_price_cents,
                netedge=netedge,
                confidence=confidence,
                consensus_confidence=consensus_confidence,
            )
            
        except Exception as e:
            logger.warning(
                "[CRYPTO15M-PUBLISHER] Failed to publish intent from signal: %s", e
            )
            return False
    
    def get_allocator_state(self) -> Dict[str, Any]:
        """Get current allocator state for this agent's context."""
        if not self._allocator:
            return {"error": "allocator_not_initialized"}
        
        try:
            return self._allocator.get_metrics()
        except Exception as e:
            return {"error": str(e)}


def should_use_allocator_for_agent(agent_id: str) -> bool:
    """Check if an agent should use the 15m allocator.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        True if agent is a 15m crypto agent that should use allocator
    """
    aid = agent_id.upper()
    
    # 15m crypto directional agents
    directional_agents = [
        "BTC15M", "ETH15M", "SOL15M", "XRP15M", "DOGE15M"
    ]
    
    # Market maker
    mm_agents = ["CRYPTO15MMM", "CRYPTO_15M_MM"]
    
    if any(a in aid for a in directional_agents):
        return True
    if any(a in aid for a in mm_agents):
        return True
    
    return False


def get_publisher_for_agent(agent_id: str) -> Optional[Crypto15MIntentPublisher]:
    """Get a publisher instance for an agent if applicable.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        Publisher instance if agent is 15m crypto, None otherwise
    """
    if not should_use_allocator_for_agent(agent_id):
        return None
    
    return Crypto15MIntentPublisher(agent_id)
