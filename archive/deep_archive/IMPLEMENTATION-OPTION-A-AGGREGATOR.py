"""
Implementation Template: Option A - Enhance Existing Aggregator

This template shows how to modify the existing aggregator to emit the required schema.
Location: monitoring/prediction_analytics.py
"""

def get_arbitrage_opportunities(min_spread: float = 0.05,
                                min_liquidity: float = 50000.0,
                                limit: int = 20,
                                aggregator=None) -> Dict:
    """
    Returns arbitrage opportunities in the required schema format.
    Enhanced to match MERID predictions API requirements.
    
    Args:
        min_spread: Minimum spread threshold
        min_liquidity: Minimum liquidity in USD
        limit: Maximum number of opportunities to return
        aggregator: Prediction market aggregator instance
    
    Returns:
        Dict: Formatted response matching required schema
    """
    try:
        # Get or create aggregator if not provided
        if aggregator is None:
            from monitoring.prediction_markets import get_prediction_aggregator
            aggregator = get_prediction_aggregator()
        
        # Get raw opportunities from aggregator
        raw_opps = aggregator.get_arbitrage_opportunities(min_spread, limit)
        
        # Transform to required schema
        opportunities = []
        for opp in raw_opps:
            # Extract venue data
            markets = {}
            for venue, data in opp.markets.items():
                markets[venue] = {
                    "yes_price": data.get("yes_price", 0.5),
                    "no_price": data.get("no_price", 0.5),
                    "liquidity": data.get("liquidity", 0.0),
                    "fee_rate": data.get("fee_rate", 0.02),
                    "last_updated": data.get("last_updated", datetime.utcnow().isoformat() + "Z")
                }
            
            opportunity = {
                "id": opp.get("id", f"arb-{int(time.time())}"),
                "canonical_question": opp.get("canonical_question", "Arbitrage opportunity"),
                "markets": markets,
                "max_probability": opp.get("max_probability", 0.5),
                "min_probability": opp.get("min_probability", 0.5),
                "spread_probability": opp.get("spread_probability", 0.0),
                "max_probability_venue": opp.get("max_probability_venue", "unknown"),
                "min_probability_venue": opp.get("min_probability_venue", "unknown"),
                "profit_potential": opp.get("profit_potential", 0.0),
                "confidence": opp.get("confidence", 0.5),
                "category": opp.get("category", "other"),
                "timestamp": opp.get("timestamp", datetime.utcnow().isoformat() + "Z")
            }
            
            # Apply minimum filters
            if (opportunity["spread_probability"] >= min_spread and 
                opportunity["profit_potential"] >= min_liquidity):
                opportunities.append(opportunity)
        
        # Return in required format
        return {
            "opportunities": opportunities[:limit],
            "count": len(opportunities),
            "status": "success",
            "data_freshness": {
                "max_age_seconds": 30,
                "last_update": datetime.utcnow().isoformat() + "Z"
            }
        }
        
    except Exception as e:
        import traceback
        logger.error(f"Arbitrage opportunities error: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {
            "opportunities": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }
