"""
Cross-venue arbitrage detector.

Consumes best bid/ask snapshots from order book reconstructor and emits
candidate arbitrage opportunities when price gaps exceed configurable
thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, List
import logging


logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_venue: str
    sell_venue: str
    spread: float


class CrossVenueDetector:
    def __init__(self, threshold: float = 0.001) -> None:
        self.threshold = threshold

    def detect(self, books: Dict[Tuple[str, str], Tuple[float, float]]) -> List[ArbitrageOpportunity]:
        """
        books: {(venue, symbol): (best_bid, best_ask)}
        """
        opportunities: List[ArbitrageOpportunity] = []
        symbols = {symbol for _, symbol in books.keys()}
        for symbol in symbols:
            venue_data = [(venue, books[(venue, symbol)]) for venue, sym in books.keys() if sym == symbol]
            for buy in venue_data:
                for sell in venue_data:
                    if buy[0] == sell[0]:
                        continue
                    buy_bid = buy[1][1]
                    sell_ask = sell[1][0]
                    spread = buy_bid - sell_ask
                    if spread / sell_ask >= self.threshold:
                        opportunities.append(
                            ArbitrageOpportunity(
                                symbol=symbol,
                                buy_venue=sell[0],
                                sell_venue=buy[0],
                                spread=spread,
                            )
                        )
        logger.debug("Detected %d opportunities", len(opportunities))
        return opportunities
