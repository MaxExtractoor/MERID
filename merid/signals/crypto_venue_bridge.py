"""Crypto Venue Price Bridge — Feeds CEX prices into DislocationScanner.

CRYPTO-15M-ARB: Connects the CryptoSpotService (Coinbase, BinanceUS, CoinGecko)
to the DislocationScanner for cross-venue arbitrage detection.

Usage:
    from merid.signals.crypto_venue_bridge import get_crypto_venue_bridge
    bridge = get_crypto_venue_bridge()
    bridge.update_prices()  # Call periodically (e.g., every 10s)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.crypto_venue_bridge")


@dataclass
class VenuePriceUpdate:
    """Normalized price update for a venue."""
    asset: str
    venue: str
    bid: float
    ask: float
    mid: float
    timestamp: float
    liquidity_usd: float = 100000.0  # Default $100k
    fees_bps: float = 10.0  # Default 10bps taker fee


class CryptoVenueBridge:
    """Bridge between CryptoSpotService and DislocationScanner.
    
    Fetches spot prices from multiple CEX venues and feeds them into the
    DislocationScanner for cross-venue arbitrage detection.
    """
    
    def __init__(self):
        self._last_update = 0.0
        self._update_interval = 10.0  # Update every 10 seconds
        self._assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
    def update_prices(self) -> bool:
        """Fetch and ingest prices from all crypto venues.
        
        Returns:
            True if prices were updated, False if skipped (throttled)
        """
        now = time.time()
        if now - self._last_update < self._update_interval:
            return False
        
        try:
            from merid.trading.crypto_spot_service import get_crypto_spot_service
            from merid.signals.arbitrage import get_dislocation_scanner, VenuePrice
            
            service = get_crypto_spot_service()
            scanner = get_dislocation_scanner()
            
            # Fetch prices for all 5 crypto assets
            for asset in self._assets:
                try:
                    result = service.get_spot_batch([asset])
                    spot = result.spots.get(asset)
                    
                    if spot and not spot.is_stale:
                        # Map source to venue name
                        venue = spot.source
                        
                        # Create synthetic bid/ask from mid (±5bps spread)
                        mid = spot.price
                        spread_factor = 0.0005  # 5bps
                        bid = mid * (1 - spread_factor)
                        ask = mid * (1 + spread_factor)
                        
                        # Create VenuePrice and ingest
                        vp = VenuePrice(
                            venue=venue,
                            symbol=asset,
                            bid=bid,
                            ask=ask,
                            mid=mid,
                            timestamp=spot.timestamp,
                            liquidity_usd=50000.0,  # $50k default
                            fees_bps=10.0 if venue == "coinbase" else 15.0,
                        )
                        scanner.ingest_price(vp)
                        
                except Exception as e:
                    logger.debug("Failed to update %s price: %s", asset, e)
            
            self._last_update = now
            logger.debug("[CRYPTO-15M-ARB] Updated prices for %d assets", len(self._assets))
            return True
            
        except Exception as e:
            logger.warning("[CRYPTO-15M-ARB] Price update failed: %s", e)
            return False
    
    def get_arb_opportunities(self, min_edge_bps: float = 20.0) -> List[Dict[str, Any]]:
        """Get current arbitrage opportunities across venues.
        
        Args:
            min_edge_bps: Minimum edge in basis points to report
            
        Returns:
            List of opportunity dicts with asset, venues, edge
        """
        try:
            from merid.signals.arbitrage import get_dislocation_scanner, CRYPTO_15M_ASSETS
            
            scanner = get_dislocation_scanner()
            now = time.time()
            
            # Run a focused scan
            signals = scanner.scan(now)
            
            opportunities = []
            for sig in signals:
                if sig.net_edge_bps >= min_edge_bps:
                    opportunities.append({
                        "asset": sig.symbol,
                        "buy_venue": sig.venues[0].venue if sig.venues else None,
                        "sell_venue": sig.venues[1].venue if len(sig.venues) > 1 else None,
                        "net_edge_bps": sig.net_edge_bps,
                        "arb_type": sig.arb_type,
                    })
            
            return opportunities
            
        except Exception as e:
            logger.debug("Failed to get arb opportunities: %s", e)
            return []


# Singleton instance
_bridge_instance: Optional[CryptoVenueBridge] = None


def get_crypto_venue_bridge() -> CryptoVenueBridge:
    """Get or create the singleton CryptoVenueBridge."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = CryptoVenueBridge()
    return _bridge_instance
