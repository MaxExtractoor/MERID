"""Breaking news aggregation for MERID."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class NewsItem:
    source: str
    headline: str
    summary: str
    url: str
    importance: str
    timestamp_ms: float


class NewsSentinel:
    """Lightweight breaking-news fetcher (mock scaffold)."""

    def __init__(self, sources: Optional[List[str]] = None) -> None:
        self.sources = sources or ["CoinDesk", "CoinTelegraph", "BinanceAnn"]
        # Real implementation would require API keys / RSS polling. For now we mock.

    def fetch_headlines(self, limit: int = 5) -> List[NewsItem]:
        return self._mock_headlines(limit)

    def _mock_headlines(self, limit: int) -> List[NewsItem]:
        random.seed("news-mock")
        items: List[NewsItem] = []
        now_ms = time.time() * 1000
        templates = [
            ("CoinDesk", "Spot ETF Inflows Surge Again", "ETF desk notes strongest inflows week-over-week."),
            ("CoinTelegraph", "Layer-2 Fees Spike", "Gas wars return as meme season reignites."),
            ("BinanceAnn", "Maintenance Scheduled", "Perp engine maintenance planned for UTC night."),
            ("FTXCreditors", "Estate Sells Assets", "Latest court filing indicates fresh OTC sale."),
            ("Arkham", "Whale Wallet Reactivated", "Dormant ETH whale moved holdings after 5 years."),
        ]
        for idx in range(min(limit, len(templates))):
            source, headline, summary = templates[idx]
            importance = "high" if "ETF" in headline or "Maintenance" in headline else "normal"
            items.append(
                NewsItem(
                    source=source,
                    headline=headline,
                    summary=summary,
                    url=f"https://news.example.com/{idx}",
                    importance=importance,
                    timestamp_ms=now_ms - idx * 2 * 60 * 1000,
                )
            )
        return items
