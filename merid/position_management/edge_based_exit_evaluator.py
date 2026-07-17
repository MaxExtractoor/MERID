"""
Edge-Based Exit Evaluator

Computes real-time edge for exit decisions using UnifiedEdgeComputer.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)


class EdgeBasedExitEvaluator:
    """Computes real-time edge for exit decisions."""
    
    def __init__(self):
        """Initialize edge-based exit evaluator."""
        self._edge_computer = None  # Will be lazy-loaded
        self._spot_service = None  # Will be lazy-loaded
        logger.info("[EDGE-BASED-EXIT-EVALUATOR] Initialized")
    
    def compute_current_edge(
        self,
        position: Any,
        current_price_cents: int,
        time_to_expiry_seconds: float
    ) -> Optional[float]:
        """
        Compute current edge percentage for position.
        
        Args:
            position: Position to compute edge for
            current_price_cents: Current market price in cents
            time_to_expiry_seconds: Time to expiry in seconds
        
        Returns:
            Current edge percentage or None if computation fails
        """
        try:
            # Lazy load dependencies
            if self._edge_computer is None:
                from merid.prediction.unified_edge import get_unified_edge_computer
                self._edge_computer = get_unified_edge_computer()
            
            if self._spot_service is None:
                from data.unified_spot_service import get_unified_spot_service
                self._spot_service = get_unified_spot_service()
            
            # Extract asset from position
            asset = self._extract_asset(position)
            if not asset:
                logger.warning("[EDGE-BASED-EXIT-EVALUATOR] Could not extract asset from position")
                return None
            
            # Get spot data for asset
            spot_data = self._spot_service.get_spot_data(asset)
            if not spot_data:
                logger.warning("[EDGE-BASED-EXIT-EVALUATOR] No spot data for asset=%s", asset)
                return None
            
            # Get entry price from position
            entry_price_cents = self._extract_entry_price(position)
            if entry_price_cents is None:
                logger.warning("[EDGE-BASED-EXIT-EVALUATOR] Could not extract entry price from position")
                return None
            
            # CRITICAL FIX (2026-07-17): Use correct UnifiedEdgeComputer API
            # The compute_edge method expects SpotReference and ContractState, not individual parameters
            from merid.prediction.unified_edge import SpotReference, ContractState
            
            # Construct SpotReference from spot_data
            spot_ref = SpotReference(
                asset=asset,
                price_usd=spot_data.price_usd,
                timestamp=datetime.now(timezone.utc),
                source=spot_data.source or "unified_spot_service",
                is_rti_proxy=True
            )
            
            # Construct ContractState from position data
            # Extract market_id from position
            market_id = getattr(position, 'market_id', 'unknown')
            side = getattr(position, 'side', 'yes')
            
            contract_state = ContractState(
                market_id=market_id,
                asset=asset,
                side=side,
                strike_price=entry_price_cents / 100.0,  # Convert cents to USD
                mid_price_cents=current_price_cents,
                time_to_expiry_seconds=time_to_expiry_seconds,
                ticker=getattr(position, 'series_ticker', '')
            )
            
            # Compute edge using correct API
            edge_result = self._edge_computer.compute_edge(
                asset=asset,
                spot_ref=spot_ref,
                contract=contract_state,
                order_size=1,
                order_side="taker"
            )
            
            if edge_result:
                # Use edge_fee_adjusted as the final edge for trade decisions
                edge_pct = getattr(edge_result, 'edge_fee_adjusted', None)
                if edge_pct is None:
                    # Fallback to raw edge if fee_adjusted not available
                    edge_pct = getattr(edge_result, 'edge', None)
                
                logger.debug(
                    "[EDGE-BASED-EXIT-EVALUATOR] Computed edge=%.4f for asset=%s position=%s",
                    edge_pct,
                    asset,
                    getattr(position, 'position_id', 'unknown')[:8]
                )
                return edge_pct
            else:
                logger.warning("[EDGE-BASED-EXIT-EVALUATOR] Edge computation returned None")
                return None
            
        except Exception as e:
            logger.error("[EDGE-BASED-EXIT-EVALUATOR] Failed to compute edge: %s", e, exc_info=True)
            return None
    
    def _extract_asset(self, position: Any) -> Optional[str]:
        """Extract asset symbol from position."""
        # Try to get asset from market_id
        if hasattr(position, 'market_id'):
            market_id = position.market_id
            # Extract asset from market_id (e.g., "KXBTC15M" -> "BTC")
            if "BTC" in market_id.upper():
                return "BTC"
            elif "ETH" in market_id.upper():
                return "ETH"
            elif "SOL" in market_id.upper():
                return "SOL"
            elif "XRP" in market_id.upper():
                return "XRP"
            elif "DOGE" in market_id.upper():
                return "DOGE"
        
        # Try to get asset from series_ticker
        if hasattr(position, 'series_ticker'):
            series_ticker = position.series_ticker
            if "BTC" in series_ticker.upper():
                return "BTC"
            elif "ETH" in series_ticker.upper():
                return "ETH"
            elif "SOL" in series_ticker.upper():
                return "SOL"
            elif "XRP" in series_ticker.upper():
                return "XRP"
            elif "DOGE" in series_ticker.upper():
                return "DOGE"
        
        return None
    
    def _extract_entry_price(self, position: Any) -> Optional[int]:
        """Extract entry price from position."""
        if hasattr(position, 'avg_entry_price_cents'):
            return position.avg_entry_price_cents
        return None
