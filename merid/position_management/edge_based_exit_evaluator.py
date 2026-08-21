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

        The canonical current edge is the model's entry probability for the
        selected side minus the current market probability for that same side.
        This preserves the entry signal (p_yes/p_no) and stays consistent with
        the decision engine as the market price moves.

        If the entry model probability is not available (e.g. a position that
        arrived via REST sync without provenance), we fall back to
        UnifiedEdgeComputer using the market's actual strike price, never the
        fill price.

        Args:
            position: Position to compute edge for
            current_price_cents: Current market price in cents (own-side bid)
            time_to_expiry_seconds: Time to expiry in seconds

        Returns:
            Current edge percentage or None if computation fails
        """
        try:
            # Lazy load dependencies
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

            # Canonical path: use the model probability that opened the position.
            # current_price_cents is the own-side bid, so current_market_probability
            # is already the selected-side market price (cents -> fraction).
            entry_model_probability = self._extract_entry_model_probability(position)
            if (
                entry_model_probability is not None
                and current_price_cents is not None
                and 0 < current_price_cents < 100
            ):
                current_market_probability = current_price_cents / 100.0
                edge = float(entry_model_probability) - current_market_probability
                logger.debug(
                    "[EDGE-BASED-EXIT-EVALUATOR] Signal-based edge=%.4f "
                    "model_p=%.4f current_p=%.4f for asset=%s position=%s",
                    edge,
                    entry_model_probability,
                    current_market_probability,
                    asset,
                    getattr(position, 'position_id', 'unknown')[:8]
                )
                return edge

            # Fallback: UnifiedEdgeComputer with the market's actual strike.
            if self._edge_computer is None:
                from merid.prediction.unified_edge import get_unified_edge_computer
                self._edge_computer = get_unified_edge_computer()

            from merid.prediction.unified_edge import SpotReference, ContractState

            strike_price = self._extract_strike_price(
                position, asset, getattr(spot_data, 'price_usd', None)
            )
            if strike_price is None:
                logger.warning(
                    "[EDGE-BASED-EXIT-EVALUATOR] Could not determine strike price for asset=%s",
                    asset
                )
                return None

            # Construct SpotReference from spot_data
            spot_ref = SpotReference(
                asset=asset,
                price_usd=spot_data.price_usd,
                timestamp=datetime.now(timezone.utc),
                source=spot_data.source or "unified_spot_service",
                is_rti_proxy=True
            )

            # Construct ContractState from position data
            market_id = getattr(position, 'market_id', 'unknown')
            side = self._side_str(position)

            contract_state = ContractState(
                market_id=market_id,
                asset=asset,
                side=side,
                strike_price=strike_price,
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
                    "[EDGE-BASED-EXIT-EVALUATOR] Unified-edge edge=%.4f for asset=%s position=%s",
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

    def _side_str(self, position: Any) -> str:
        """Return canonical side string ('yes' or 'no') for a position."""
        side = getattr(position, 'side', 'yes')
        if hasattr(side, 'value'):
            return side.value.lower()
        return str(side).lower()

    def _extract_entry_model_probability(self, position: Any) -> Optional[float]:
        """
        Extract the model probability for the selected side that was persisted
        at entry.  This is the same p_selected used by the decision engine, so
        it keeps the exit edge consistent with the entry signal.

        If the direct field is missing, try to reconstruct it from the entry
        edge and the entry market probability.
        """
        p = getattr(position, 'entry_model_probability', None)
        if p is not None:
            pf = float(p)
            if 0.0 <= pf <= 1.0:
                return pf

        entry_edge = getattr(position, 'entry_edge', None)
        entry_market_p = getattr(position, 'entry_market_probability', None)
        if entry_edge is not None and entry_market_p is not None:
            pf = float(entry_edge) + float(entry_market_p)
            if 0.0 <= pf <= 1.0:
                return pf

        # Legacy positions may only have entry_edge_pct (net edge), but that
        # is after fees and cannot reconstruct p_selected accurately.
        return None

    def _extract_strike_price(
        self, position: Any, asset: str, spot_price_usd: Optional[float]
    ) -> Optional[float]:
        """
        Return the market's actual reference strike price, never the fill price.

        Priority:
          1. KalshiMarketState.window_strike_price (captured at market open)
          2. KalshiMarketState.floor_strike / strike_price / cap_strike
          3. Current spot price as a neutral fallback (q ~ 0.5)
        """
        market_id = getattr(position, 'market_id', None)
        if market_id:
            try:
                from merid.event_venues.kalshi.market_state import (
                    get_kalshi_market_state_store
                )
                store = get_kalshi_market_state_store()
                if store is not None:
                    state = store.get(market_id)
                    if state is not None:
                        for attr in (
                            'window_strike_price',
                            'floor_strike',
                            'strike_price',
                            'cap_strike',
                        ):
                            strike = getattr(state, attr, None)
                            if strike is not None and float(strike) > 0:
                                return float(strike)
            except Exception as e:
                logger.debug(
                    "[EDGE-BASED-EXIT-EVALUATOR] Could not load market state "
                    "for strike: %s",
                    e
                )

        if spot_price_usd is not None and spot_price_usd > 0:
            return float(spot_price_usd)

        return None
