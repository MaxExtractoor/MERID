"""merid.scanning — Trending market scanning and summarization.

Exposes:
    TrendingScanner   — scans 10 domains and produces a ranked ScanResult
    ScanResult        — full output of one scanner run
    DomainItem        — a single high-conviction item within a domain
    TopOpportunity    — cross-domain ranked trading opportunity
    get_trending_scanner — singleton accessor
"""

from merid.scanning.trending_scanner import (
    DomainItem,
    TopOpportunity,
    ScanResult,
    TrendingScanner,
    get_trending_scanner,
    DOMAINS,
)

__all__ = [
    "DomainItem",
    "TopOpportunity",
    "ScanResult",
    "TrendingScanner",
    "get_trending_scanner",
    "DOMAINS",
]
