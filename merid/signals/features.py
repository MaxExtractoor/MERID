"""§2 Feature services — decay-aware accessors for news, macro, onchain, social.

Agents call these to get aggregated, time-weighted features:
  get_news_features(symbol, window)
  get_macro_features(series, window)
  get_onchain_features(chain, token)
  get_social_features(symbol, window)

Each returns DecayEnvelope objects so the caller always sees value + freshness.
Synthetic data fallback for development.
"""

from __future__ import annotations

import threading
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from merid.signals.decay import (
    DecayConfig,
    DecayEnvelope,
    SignalDomain,
    SignalSnapshot,
    decay_weight_at,
    get_decay_config,
    weighted_average,
)

from utils.logger import get_logger

logger = get_logger("merid.signals.features")


# ── Feature result container ──────────────────────────────────────────

@dataclass
class FeatureSet:
    """A bundle of decay-aware features for a symbol/topic."""
    symbol: str = ""
    domain: str = ""
    timestamp: float = field(default_factory=time.time)
    features: Dict[str, DecayEnvelope] = field(default_factory=dict)
    source: str = "synthetic"

    def avg_freshness(self) -> float:
        if not self.features:
            return 0.0
        return sum(f.decay_weight for f in self.features.values()) / len(self.features)

    def is_any_stale(self) -> bool:
        return any(f.is_stale for f in self.features.values())

    def get(self, key: str) -> Optional[DecayEnvelope]:
        return self.features.get(key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "domain": self.domain,
            "source": self.source,
            "avg_freshness": round(self.avg_freshness(), 4),
            "features": {k: v.to_dict() for k, v in self.features.items()},
        }


# ── News feature service ──────────────────────────────────────────────

class NewsFeatureService:
    """Provides decay-aware news features per symbol.

    In production: aggregates from NewsAPI, Finnhub, Polygon news.
    Here: synthetic data with realistic decay behavior.
    """

    def __init__(self):
        self._cache: Dict[str, List[Tuple[float, float, str]]] = {}  # symbol → [(ts, sentiment, headline)]

    def ingest(self, symbol: str, sentiment: float, headline: str = "", ts: Optional[float] = None):
        """Ingest a news data point."""
        ts = ts or time.time()
        self._cache.setdefault(symbol, []).append((ts, sentiment, headline))

    def get_news_features(
        self, symbol: str, window_seconds: float = 3600, now: Optional[float] = None,
    ) -> FeatureSet:
        """Get decay-aware news features for a symbol."""
        now = now or time.time()
        config = get_decay_config(SignalDomain.NEWS.value)

        # Check cache first
        points = self._cache.get(symbol, [])
        cutoff = now - config.max_age_seconds
        recent = [(ts, sent, hl) for ts, sent, hl in points if ts > cutoff]

        if not recent:
            recent = self._synthetic_news(symbol, now)

        # Build envelopes
        sentiment_envs = []
        for ts, sent, _ in recent:
            env = DecayEnvelope.create(sent, ts, SignalDomain.NEWS.value, "news_sentiment", now)
            sentiment_envs.append(env)

        # Aggregate
        avg_sent = weighted_average(sentiment_envs) if sentiment_envs else 0.0
        count = len(recent)
        window_recent = [(ts, s, h) for ts, s, h in recent if ts > now - window_seconds]
        rate = len(window_recent) / max(window_seconds / 3600, 0.01)  # articles per hour

        features: Dict[str, DecayEnvelope] = {
            "sentiment": DecayEnvelope.create(
                avg_sent, max((ts for ts, _, _ in recent), default=now),
                SignalDomain.NEWS.value, "news_sentiment_avg", now,
            ),
            "article_count": DecayEnvelope.create(
                float(count), now, SignalDomain.NEWS.value, "news_count", now,
            ),
            "article_rate": DecayEnvelope.create(
                rate, now, SignalDomain.NEWS.value, "news_rate_per_hour", now,
            ),
            "recency": DecayEnvelope.create(
                now - max((ts for ts, _, _ in recent), default=now),
                max((ts for ts, _, _ in recent), default=now),
                SignalDomain.NEWS.value, "news_recency_seconds", now,
            ),
        }

        return FeatureSet(
            symbol=symbol, domain=SignalDomain.NEWS.value,
            timestamp=now, features=features,
            source="live" if self._cache.get(symbol) else "synthetic",
        )

    def _synthetic_news(self, symbol: str, now: float) -> List[Tuple[float, float, str]]:
        """Neutral fallback — no data means neutral, not random."""
        return [(now - 300, 0.0, f"No live news data for {symbol}")]


# ── Macro feature service ─────────────────────────────────────────────

class MacroFeatureService:
    """Provides decay-aware macro features (CPI, FOMC, jobs, GDP).

    In production: fetches from FRED, Finnhub calendar.
    Here: synthetic data with slow decay (macro tau = 24h).
    """

    def __init__(self):
        self._data: Dict[str, List[Tuple[float, float, str]]] = {}  # series → [(ts, surprise, label)]

    def ingest(self, series: str, surprise: float, label: str = "", ts: Optional[float] = None):
        ts = ts or time.time()
        self._data.setdefault(series, []).append((ts, surprise, label))

    def get_macro_features(
        self, series: str = "all", window_seconds: float = 604800, now: Optional[float] = None,
    ) -> FeatureSet:
        now = now or time.time()
        config = get_decay_config(SignalDomain.MACRO.value)

        if series == "all":
            all_points = []
            for s, pts in self._data.items():
                for ts, val, lbl in pts:
                    if ts > now - config.max_age_seconds:
                        all_points.append((ts, val, f"{s}: {lbl}"))
            points = all_points
        else:
            points = [(ts, v, l) for ts, v, l in self._data.get(series, []) if ts > now - config.max_age_seconds]

        if not points:
            points = self._synthetic_macro(now)

        envs = [DecayEnvelope.create(v, ts, SignalDomain.MACRO.value, f"macro_{series}", now) for ts, v, _ in points]
        avg_surprise = weighted_average(envs) if envs else 0.0

        features: Dict[str, DecayEnvelope] = {
            "surprise_avg": DecayEnvelope.create(
                avg_surprise, max((ts for ts, _, _ in points), default=now),
                SignalDomain.MACRO.value, "macro_surprise_avg", now,
            ),
            "data_point_count": DecayEnvelope.create(
                float(len(points)), now, SignalDomain.MACRO.value, "macro_count", now,
            ),
            "last_release_age": DecayEnvelope.create(
                now - max((ts for ts, _, _ in points), default=now),
                max((ts for ts, _, _ in points), default=now),
                SignalDomain.MACRO.value, "macro_recency", now,
            ),
        }

        return FeatureSet(
            symbol=series, domain=SignalDomain.MACRO.value,
            timestamp=now, features=features,
            source="live" if self._data else "synthetic",
        )

    def _synthetic_macro(self, now: float) -> List[Tuple[float, float, str]]:
        """Neutral fallback — zero surprise, not random."""
        series_list = ["cpi", "fomc", "nfp", "gdp", "pce"]
        return [(now - 3600, 0.0, f"{s.upper()}: no data") for s in series_list]


# ── OnChain feature service ───────────────────────────────────────────

class OnChainFeatureService:
    """Provides decay-aware on-chain features.

    In production: fetches from Nansen, The Graph, Helius, Dune.
    Here: synthetic data with 1h decay.
    """

    def __init__(self):
        self._data: Dict[str, List[Tuple[float, Dict[str, float]]]] = {}  # chain:token → [(ts, metrics)]

    def ingest(self, chain: str, token: str, metrics: Dict[str, float], ts: Optional[float] = None):
        ts = ts or time.time()
        key = f"{chain}:{token}"
        self._data.setdefault(key, []).append((ts, metrics))

    def get_onchain_features(
        self, chain: str = "ethereum", token: str = "ETH", now: Optional[float] = None,
    ) -> FeatureSet:
        now = now or time.time()
        key = f"{chain}:{token}"
        config = get_decay_config(SignalDomain.ONCHAIN.value)

        points = [(ts, m) for ts, m in self._data.get(key, []) if ts > now - config.max_age_seconds]
        if not points:
            points = self._synthetic_onchain(chain, token, now)

        # Latest point
        latest_ts, latest_m = max(points, key=lambda x: x[0])

        features: Dict[str, DecayEnvelope] = {}
        for metric_name, metric_val in latest_m.items():
            features[metric_name] = DecayEnvelope.create(
                metric_val, latest_ts, SignalDomain.ONCHAIN.value, f"onchain_{metric_name}", now,
            )

        return FeatureSet(
            symbol=f"{chain}:{token}", domain=SignalDomain.ONCHAIN.value,
            timestamp=now, features=features,
            source="live" if self._data.get(key) else "synthetic",
        )

    def _synthetic_onchain(self, chain: str, token: str, now: float) -> List[Tuple[float, Dict[str, float]]]:
        """Neutral fallback — zeroed metrics, not random."""
        metrics = {
            "whale_flow_usd": 0.0,
            "tvl_change_pct": 0.0,
            "gas_avg_gwei": 0.0,
            "active_addresses": 0.0,
            "volume_24h_usd": 0.0,
            "net_exchange_flow": 0.0,
        }
        return [(now - 300, metrics)]


# ── Social feature service ────────────────────────────────────────────

class SocialFeatureService:
    """Provides fast-decaying social features per symbol.

    tau = 10 minutes — social signal ages very quickly.
    In production: aggregates from X/Twitter, Reddit via streaming.
    """

    def __init__(self):
        self._data: Dict[str, List[Tuple[float, float, float, int, bool]]] = {}
        # symbol → [(ts, sentiment, engagement, followers, is_kol)]

    def ingest(
        self, symbol: str, sentiment: float, engagement: float = 0.0,
        followers: int = 0, is_kol: bool = False, ts: Optional[float] = None,
    ):
        ts = ts or time.time()
        self._data.setdefault(symbol, []).append((ts, sentiment, engagement, followers, is_kol))

    def get_social_features(
        self, symbol: str, window_seconds: float = 900, now: Optional[float] = None,
    ) -> FeatureSet:
        now = now or time.time()
        config = get_decay_config(SignalDomain.SOCIAL.value)

        points = [p for p in self._data.get(symbol, []) if p[0] > now - config.max_age_seconds]
        if not points:
            points = self._synthetic_social(symbol, now)

        # Build envelopes
        sent_envs = [
            DecayEnvelope.create(sent, ts, SignalDomain.SOCIAL.value, "social_sentiment", now)
            for ts, sent, _, _, _ in points
        ]
        eng_envs = [
            DecayEnvelope.create(eng, ts, SignalDomain.SOCIAL.value, "social_engagement", now)
            for ts, _, eng, _, _ in points
        ]

        avg_sent = weighted_average(sent_envs) if sent_envs else 0.0
        avg_eng = weighted_average(eng_envs) if eng_envs else 0.0

        window_pts = [p for p in points if p[0] > now - window_seconds]
        mention_rate = len(window_pts) / max(window_seconds / 60, 0.01)

        # Hype spike detection: high volume + positive sentiment in short window
        hype_spike = len(window_pts) > 5 and avg_sent > 0.3

        # KOL ratio
        kol_count = sum(1 for _, _, _, _, is_kol in window_pts if is_kol)
        total_count = len(window_pts) or 1
        kol_ratio = kol_count / total_count

        # Attention score: combine volume, sentiment, engagement
        attention = min(1.0, (mention_rate / 10.0) * 0.4 + abs(avg_sent) * 0.3 + min(avg_eng / 1000, 1.0) * 0.3)

        latest_ts = max((ts for ts, _, _, _, _ in points), default=now)

        features: Dict[str, DecayEnvelope] = {
            "sentiment": DecayEnvelope.create(
                avg_sent, latest_ts, SignalDomain.SOCIAL.value, "social_sentiment", now,
            ),
            "attention_score": DecayEnvelope.create(
                attention, latest_ts, SignalDomain.SOCIAL.value, "social_attention", now,
            ),
            "mention_rate": DecayEnvelope.create(
                mention_rate, now, SignalDomain.SOCIAL.value, "social_mention_rate_per_min", now,
            ),
            "engagement_avg": DecayEnvelope.create(
                avg_eng, latest_ts, SignalDomain.SOCIAL.value, "social_engagement", now,
            ),
            "hype_spike": DecayEnvelope.create(
                1.0 if hype_spike else 0.0, latest_ts,
                SignalDomain.SOCIAL.value, "social_hype_spike", now,
            ),
            "kol_ratio": DecayEnvelope.create(
                kol_ratio, latest_ts, SignalDomain.SOCIAL.value, "social_kol_ratio", now,
            ),
        }

        return FeatureSet(
            symbol=symbol, domain=SignalDomain.SOCIAL.value,
            timestamp=now, features=features,
            source="live" if self._data.get(symbol) else "synthetic",
        )

    def _synthetic_social(self, symbol: str, now: float) -> List[Tuple[float, float, float, int, bool]]:
        """Neutral fallback — zero sentiment, not random."""
        return [(now - 60, 0.0, 0.0, 0, False)]


# ── Unified feature accessor ──────────────────────────────────────────

class FeatureService:
    """Unified facade for all feature services.

    Agents call this single service to get any domain's features.
    """

    def __init__(self):
        self.news = NewsFeatureService()
        self.macro = MacroFeatureService()
        self.onchain = OnChainFeatureService()
        self.social = SocialFeatureService()

    def get_news_features(self, symbol: str, window_seconds: float = 3600, now: Optional[float] = None) -> FeatureSet:
        return self.news.get_news_features(symbol, window_seconds, now)

    def get_macro_features(self, series: str = "all", window_seconds: float = 604800, now: Optional[float] = None) -> FeatureSet:
        return self.macro.get_macro_features(series, window_seconds, now)

    def get_onchain_features(self, chain: str = "ethereum", token: str = "ETH", now: Optional[float] = None) -> FeatureSet:
        return self.onchain.get_onchain_features(chain, token, now)

    def get_social_features(self, symbol: str, window_seconds: float = 900, now: Optional[float] = None) -> FeatureSet:
        return self.social.get_social_features(symbol, window_seconds, now)

    def build_snapshot(
        self, symbol: str, domains: Optional[List[str]] = None, now: Optional[float] = None,
    ) -> SignalSnapshot:
        """Build a SignalSnapshot combining features from requested domains.

        This is what agents attach to their opinions/plans.
        """
        now = now or time.time()
        domains = domains or [SignalDomain.NEWS.value, SignalDomain.SOCIAL.value, SignalDomain.ONCHAIN.value]

        all_signals: List[DecayEnvelope] = []
        summary: Dict[str, Any] = {}

        for domain in domains:
            if domain == SignalDomain.NEWS.value:
                fs = self.get_news_features(symbol, now=now)
            elif domain == SignalDomain.MACRO.value:
                fs = self.get_macro_features(now=now)
            elif domain == SignalDomain.SOCIAL.value:
                fs = self.get_social_features(symbol, now=now)
            elif domain == SignalDomain.ONCHAIN.value:
                chain = "solana" if symbol in ("SOL", "BONK", "WIF", "JUP") else "ethereum"
                fs = self.get_onchain_features(chain, symbol, now=now)
            else:
                continue

            all_signals.extend(fs.features.values())
            summary[domain] = {
                "freshness": round(fs.avg_freshness(), 4),
                "feature_count": len(fs.features),
                "source": fs.source,
            }

        return SignalSnapshot(
            snapshot_id=f"snap-{int(now)}-{symbol}",
            timestamp=now,
            signals=all_signals,
            summary=summary,
        )


# ── Singleton ─────────────────────────────────────────────────────────

_feature_service: Optional[FeatureService] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _feature_service_lock = threading.Lock()
_feature_service_lock = None  # Disabled to prevent startup hang


def get_feature_service() -> FeatureService:
    global _feature_service
    if _feature_service is None:
        if _feature_service_lock is not None:
            with _feature_service_lock:
                if _feature_service is None:
                    _feature_service = FeatureService()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _feature_service = FeatureService()
    return _feature_service
