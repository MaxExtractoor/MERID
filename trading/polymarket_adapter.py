"""
Polymarket Adapter for MERID.

Real integration with Polymarket prediction markets API.
"""

from __future__ import annotations

import os
from typing import List, Dict, Optional
import httpx
from utils.logger import get_logger

logger = get_logger("trading.polymarket_adapter")


class PolymarketAdapter:
    """
    Production Polymarket adapter.
    
    Fetches real prediction market data from Polymarket.
    """
    
    def __init__(self):
        """Initialize Polymarket adapter."""
        self.api_key = os.getenv('POLYMARKET_API_KEY')
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"
        
        self.client = httpx.Client(timeout=30.0)
        
        logger.info("Polymarket adapter initialized")
    
    def fetch_markets(
        self,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Fetch available prediction markets from Polymarket.
        
        Args:
            category: Filter by category (crypto, sports, politics, etc.)
            limit: Maximum number of markets to return
            
        Returns:
            List of market data dictionaries
        """
        try:
            # Fetch markets from Gamma API (public endpoint)
            url = f"{self.gamma_url}/markets"
            params = {
                "limit": limit,
                "closed": False  # Only active markets
            }
            
            if category:
                params["tag"] = category
            
            response = self.client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Format markets for MERID
            markets = []
            for market in data:
                markets.append({
                    "market_id": market.get("condition_id", market.get("id")),
                    "question": market.get("question", ""),
                    "description": market.get("description", ""),
                    "category": market.get("tags", [""])[0] if market.get("tags") else "",
                    "end_date": market.get("end_date_iso", ""),
                    "volume": market.get("volume", 0),
                    "liquidity": market.get("liquidity", 0),
                    "outcomes": self._extract_outcomes(market),
                    "active": market.get("active", True),
                    "closed": market.get("closed", False)
                })
            
            logger.info(f"Fetched {len(markets)} markets from Polymarket")
            return markets
            
        except Exception as exc:
            logger.error(f"Failed to fetch Polymarket markets: {exc}")
            # Return empty list instead of failing
            return []
    
    def _extract_outcomes(self, market: Dict) -> List[Dict]:
        """Extract outcome data from market."""
        outcomes = []
        
        # Polymarket typically has binary outcomes
        tokens = market.get("tokens", [])
        
        for token in tokens:
            outcomes.append({
                "outcome": token.get("outcome", ""),
                "price": token.get("price", 0.5),
                "token_id": token.get("token_id", "")
            })
        
        # If no tokens, create default binary outcomes
        if not outcomes:
            outcomes = [
                {"outcome": "Yes", "price": 0.5, "token_id": ""},
                {"outcome": "No", "price": 0.5, "token_id": ""}
            ]
        
        return outcomes
    
    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get detailed information for a specific market."""
        try:
            url = f"{self.gamma_url}/markets/{market_id}"
            response = self.client.get(url)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as exc:
            logger.error(f"Failed to fetch market {market_id}: {exc}")
            return None
    
    def __del__(self):
        """Cleanup HTTP client."""
        try:
            self.client.close()
        except:
            pass


# Global singleton
_polymarket_adapter: Optional[PolymarketAdapter] = None


def get_polymarket_adapter() -> PolymarketAdapter:
    """Get or create Polymarket adapter singleton."""
    global _polymarket_adapter
    if _polymarket_adapter is None:
        _polymarket_adapter = PolymarketAdapter()
    return _polymarket_adapter
