"""Real-time prediction market data publisher for WebSocket streaming."""

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List
from observability.event_stream import get_event_stream
from monitoring.prediction_markets import get_prediction_aggregator, ResolutionStatus
from trading.paper_trading import get_paper_trading_engine
from utils.logger import get_logger

logger = get_logger(__name__)


class PredictionPublisher:
    """Publishes live prediction market updates to WebSocket clients."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        
        # Connect to real prediction markets aggregator
        self.aggregator = get_prediction_aggregator()
        self.trading_engine = get_paper_trading_engine()
        
        logger.info(f"PredictionPublisher initialized with REAL data from Kalshi")
    
    async def start(self):
        """Start publishing prediction market updates."""
        if self.running:
            logger.warning("Prediction publisher already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
        logger.info("Prediction publisher started")
    
    async def stop(self):
        """Stop publishing prediction market updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Prediction publisher stopped")
    
    async def _publish_loop(self):
        """Main loop for publishing prediction market updates."""
        try:
            while self.running:
                prediction_data = self._get_real_prediction_data()
                logger.info(f"🔮 REAL predictions: {len(prediction_data['markets'])} markets | Total P&L: ${prediction_data['meta']['totalPnl']:,.2f}")
                await self.event_stream.publish("prediction_update", prediction_data)
                await asyncio.sleep(30)  # Update every 30 seconds
        except asyncio.CancelledError:
            logger.info("Prediction publisher loop cancelled")
        except Exception as e:
            logger.error(f"Error in prediction publisher loop: {e}", exc_info=True)
    
    def _get_real_prediction_data(self) -> Dict:
        """Get real prediction market data from aggregator."""
        try:
            # Get markets from aggregator
            all_markets = self.aggregator.get_all_markets()
            
            formatted_markets = []
            
            if all_markets:
                # Use real Kalshi markets
                for market in all_markets:
                    try:
                        # Skip markets without required fields
                        if not hasattr(market, 'market_id') or not market.market_id:
                            continue
                        
                        # Generate symbol from market_id
                        symbol = market.market_id[:8].upper() if len(market.market_id) >= 8 else market.market_id.upper()
                        
                        # Handle resolution_date - it's always a float timestamp or None
                        end_time = None
                        if market.resolution_date:
                            try:
                                end_time = datetime.fromtimestamp(float(market.resolution_date), tz=timezone.utc).isoformat()
                            except (ValueError, TypeError, OSError):
                                end_time = None
                        
                        if not end_time:
                            end_time = datetime.now(timezone.utc).isoformat()
                        
                        formatted_markets.append({
                            "id": market.market_id,
                            "symbol": symbol,
                            "question": market.question,
                            "yesPrice": market.yes_price,
                            "noPrice": market.no_price,
                            "ourPosition": "NONE",
                            "ourSize": 0,
                            "ourPnl": 0.0,
                            "modelConfidence": 0.0,
                            "endTime": end_time,
                            "status": "OPEN" if market.status == ResolutionStatus.OPEN else "CLOSED",
                            "volume": market.total_volume
                        })
                    except Exception as e:
                        market_id = getattr(market, 'market_id', 'unknown')
                        logger.warning(f"Failed to format market {market_id}: {e}")
                        continue
            else:
                logger.debug("No Kalshi markets available")
                formatted_markets = []
            
            # Calculate meta statistics
            total_pnl = sum(m["ourPnl"] for m in formatted_markets)
            total_volume = sum(m["volume"] for m in formatted_markets)
            open_markets = sum(1 for m in formatted_markets if m["status"] == "OPEN")
            
            return {
                "markets": formatted_markets,
                "meta": {
                    "total": len(formatted_markets),
                    "open": open_markets,
                    "totalVolume": total_volume,
                    "totalPnl": total_pnl
                },
                "timestamp": int(time.time() * 1000)
            }
        except Exception as e:
            logger.error(f"Failed to get real prediction data: {e}", exc_info=True)
            return {
                "markets": [],
                "meta": {
                    "total": 0,
                    "open": 0,
                    "totalVolume": 0,
                    "totalPnl": 0.0
                },
                "timestamp": int(time.time() * 1000)
            }


# Global instance
_prediction_publisher: PredictionPublisher = None
_prediction_publisher_lock = threading.Lock()


def get_prediction_publisher() -> PredictionPublisher:
    """Get the global prediction publisher instance."""
    global _prediction_publisher
    if _prediction_publisher is None:
        with _prediction_publisher_lock:
            if _prediction_publisher is None:
                _prediction_publisher = PredictionPublisher()
    return _prediction_publisher
