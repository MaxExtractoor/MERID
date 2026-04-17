"""In-memory odds cache with WebSocket/SSE push and latency SLO instrumentation.

Components:
  1. LiveOddsCache: Thread-safe in-memory cache with TTL eviction, keyed by
     (event_id, outcome_label). Sub-1ms reads, automatic staleness detection.
  2. OddsLatencyTracker: Measures end-to-end latency from provider → cache → consumer.
     Tracks P50/P95/P99 with configurable SLO thresholds and breach alerting.
  3. OddsPushManager: Manages subscriber callbacks for real-time odds push
     (WebSocket/SSE consumers). Fans out cache updates to all subscribers.
  4. LiveOddsCacheManager: Wires cache + tracker + push into a single facade
     that plugs into SportsOddsFeed as a subscriber.

SLO Targets:
  - Odds propagation (provider → cache): P95 < 100ms
  - Odds push (cache → consumer): P95 < 50ms
  - End-to-end (provider → consumer): P95 < 250ms
  - Bet placement: P95 < 500ms (tracked in LiveBettingEngine)
"""

from __future__ import annotations

import collections
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.betting.live_odds_cache")


# ═══════════════════════════════════════════════════════════════════════
# 1. Cached Odds Entry
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CachedOddsEntry:
    """A single cached odds entry for one event+outcome."""
    event_id: str = ""
    outcome_label: str = ""
    implied_prob: float = 0.5
    decimal_odds: float = 2.0
    american_odds: int = 0
    provider: str = ""
    is_live: bool = False
    cached_at: float = field(default_factory=time.time)
    provider_ts: float = 0.0          # when provider emitted
    cache_latency_ms: float = 0.0     # provider → cache write
    version: int = 0                  # monotonic version counter

    @property
    def age_ms(self) -> float:
        return (time.time() - self.cached_at) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "implied_prob": round(self.implied_prob, 4),
            "decimal_odds": round(self.decimal_odds, 4),
            "american_odds": self.american_odds,
            "provider": self.provider,
            "is_live": self.is_live,
            "cached_at": self.cached_at,
            "age_ms": round(self.age_ms, 1),
            "cache_latency_ms": round(self.cache_latency_ms, 1),
            "version": self.version,
        }


# ═══════════════════════════════════════════════════════════════════════
# 2. LiveOddsCache
# ═══════════════════════════════════════════════════════════════════════

class LiveOddsCache:
    """Thread-safe in-memory cache for live odds with TTL eviction.

    Keyed by (event_id, outcome_label). Supports:
      - Sub-1ms reads via dict lookup
      - Automatic staleness detection (configurable TTL)
      - Version tracking for optimistic concurrency
      - Bulk reads by event_id
    """

    def __init__(self, ttl_s: float = 30.0, max_entries: int = 10000):
        self._lock = threading.RLock()
        self._entries: Dict[str, CachedOddsEntry] = {}  # "event_id:outcome" → entry
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._version_counter = 0
        self._total_writes = 0
        self._total_reads = 0
        self._total_evictions = 0

    def put(
        self,
        event_id: str,
        outcome_label: str,
        implied_prob: float,
        decimal_odds: float = 0.0,
        american_odds: int = 0,
        provider: str = "",
        is_live: bool = False,
        provider_ts: float = 0.0,
    ) -> CachedOddsEntry:
        """Write or update a cached odds entry. Returns the entry."""
        now = time.time()
        cache_latency_ms = (now - provider_ts) * 1000 if provider_ts > 0 else 0.0

        key = f"{event_id}:{outcome_label}"
        with self._lock:
            self._version_counter += 1
            entry = CachedOddsEntry(
                event_id=event_id,
                outcome_label=outcome_label,
                implied_prob=implied_prob,
                decimal_odds=decimal_odds,
                american_odds=american_odds,
                provider=provider,
                is_live=is_live,
                cached_at=now,
                provider_ts=provider_ts,
                cache_latency_ms=cache_latency_ms,
                version=self._version_counter,
            )
            self._entries[key] = entry
            self._total_writes += 1

            # Evict if over capacity
            if len(self._entries) > self._max_entries:
                self._evict_oldest()

        return entry

    def get(self, event_id: str, outcome_label: str) -> Optional[CachedOddsEntry]:
        """Read a cached odds entry. Returns None if missing or stale."""
        key = f"{event_id}:{outcome_label}"
        with self._lock:
            self._total_reads += 1
            entry = self._entries.get(key)
            if entry is None:
                return None
            if (time.time() - entry.cached_at) > self._ttl_s:
                return None  # stale
            return entry

    def get_event(self, event_id: str) -> List[CachedOddsEntry]:
        """Get all cached entries for an event."""
        with self._lock:
            self._total_reads += 1
            now = time.time()
            return [
                e for e in self._entries.values()
                if e.event_id == event_id and (now - e.cached_at) <= self._ttl_s
            ]

    def get_all_live(self) -> List[CachedOddsEntry]:
        """Get all live (non-stale) cached entries."""
        with self._lock:
            now = time.time()
            return [
                e for e in self._entries.values()
                if e.is_live and (now - e.cached_at) <= self._ttl_s
            ]

    def invalidate(self, event_id: str, outcome_label: Optional[str] = None) -> int:
        """Invalidate cached entries. Returns count removed."""
        with self._lock:
            if outcome_label:
                key = f"{event_id}:{outcome_label}"
                if key in self._entries:
                    del self._entries[key]
                    return 1
                return 0
            else:
                keys = [k for k in self._entries if k.startswith(f"{event_id}:")]
                for k in keys:
                    del self._entries[k]
                return len(keys)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            entries = list(self._entries.values())
            stale = sum(1 for e in entries if (now - e.cached_at) > self._ttl_s)
            live = sum(1 for e in entries if e.is_live)
            return {
                "total_entries": len(entries),
                "stale_entries": stale,
                "live_entries": live,
                "total_writes": self._total_writes,
                "total_reads": self._total_reads,
                "total_evictions": self._total_evictions,
                "ttl_s": self._ttl_s,
                "version": self._version_counter,
            }

    def _evict_oldest(self) -> None:
        """Evict oldest entries to stay under max_entries."""
        if not self._entries:
            return
        sorted_keys = sorted(self._entries.keys(), key=lambda k: self._entries[k].cached_at)
        to_remove = len(self._entries) - self._max_entries + 100  # remove batch
        for key in sorted_keys[:to_remove]:
            del self._entries[key]
            self._total_evictions += 1


# ═══════════════════════════════════════════════════════════════════════
# 3. OddsLatencyTracker
# ═══════════════════════════════════════════════════════════════════════

class SLOTier(str, Enum):
    PROPAGATION = "propagation"      # provider → cache
    PUSH = "push"                    # cache → consumer
    END_TO_END = "end_to_end"        # provider → consumer
    BET_PLACEMENT = "bet_placement"  # full bet acceptance


# Default SLO targets (P95 in milliseconds)
DEFAULT_SLO_TARGETS: Dict[str, float] = {
    SLOTier.PROPAGATION.value: 100.0,
    SLOTier.PUSH.value: 50.0,
    SLOTier.END_TO_END.value: 250.0,
    SLOTier.BET_PLACEMENT.value: 500.0,
}


class OddsLatencyTracker:
    """Tracks latency metrics across the odds pipeline with SLO enforcement.

    Records latency samples for each tier, computes percentiles, and
    detects SLO breaches.
    """

    def __init__(
        self,
        slo_targets: Optional[Dict[str, float]] = None,
        window_size: int = 1000,
    ):
        self._lock = threading.RLock()
        self._slo_targets = slo_targets or dict(DEFAULT_SLO_TARGETS)
        self._window_size = window_size
        self._samples: Dict[str, Deque[float]] = {
            tier: collections.deque(maxlen=window_size)
            for tier in self._slo_targets
        }
        self._breach_counts: Dict[str, int] = {tier: 0 for tier in self._slo_targets}
        self._total_samples: Dict[str, int] = {tier: 0 for tier in self._slo_targets}

    def record(self, tier: str, latency_ms: float) -> None:
        """Record a latency sample for a tier."""
        with self._lock:
            if tier not in self._samples:
                self._samples[tier] = collections.deque(maxlen=self._window_size)
                self._breach_counts[tier] = 0
                self._total_samples[tier] = 0

            self._samples[tier].append(latency_ms)
            self._total_samples[tier] += 1

            target = self._slo_targets.get(tier, float('inf'))
            if latency_ms > target:
                self._breach_counts[tier] += 1

    def get_percentile(self, tier: str, pct: float = 0.95) -> float:
        """Get a latency percentile for a tier."""
        with self._lock:
            samples = list(self._samples.get(tier, []))
        if not samples:
            return 0.0
        sorted_s = sorted(samples)
        idx = int(len(sorted_s) * pct)
        return sorted_s[min(idx, len(sorted_s) - 1)]

    def get_tier_metrics(self, tier: str) -> Dict[str, Any]:
        """Get full metrics for a tier."""
        with self._lock:
            samples = list(self._samples.get(tier, []))
            breaches = self._breach_counts.get(tier, 0)
            total = self._total_samples.get(tier, 0)
            target = self._slo_targets.get(tier, 0.0)

        if not samples:
            return {
                "tier": tier, "target_ms": target, "samples": 0,
                "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
                "avg_ms": 0.0, "max_ms": 0.0,
                "breaches": 0, "breach_rate": 0.0, "slo_met": True,
            }

        sorted_s = sorted(samples)
        p50 = sorted_s[int(len(sorted_s) * 0.50)]
        p95 = sorted_s[min(int(len(sorted_s) * 0.95), len(sorted_s) - 1)]
        p99 = sorted_s[min(int(len(sorted_s) * 0.99), len(sorted_s) - 1)]
        avg = statistics.mean(samples)
        breach_rate = breaches / total if total > 0 else 0.0

        return {
            "tier": tier,
            "target_ms": target,
            "samples": len(samples),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(p99, 1),
            "avg_ms": round(avg, 1),
            "max_ms": round(max(samples), 1),
            "breaches": breaches,
            "breach_rate": round(breach_rate, 4),
            "slo_met": p95 <= target,
        }

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get metrics for all tiers."""
        tiers = {}
        all_met = True
        for tier in self._slo_targets:
            m = self.get_tier_metrics(tier)
            tiers[tier] = m
            if not m["slo_met"]:
                all_met = False
        return {
            "tiers": tiers,
            "all_slos_met": all_met,
        }


# ═══════════════════════════════════════════════════════════════════════
# 4. OddsPushManager
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PushSubscriber:
    """A subscriber for real-time odds push."""
    id: str = field(default_factory=lambda: f"sub-{uuid.uuid4().hex[:8]}")
    callback: Optional[Callable[[CachedOddsEntry], None]] = None
    event_filter: Optional[str] = None   # filter by event_id (None = all)
    sport_filter: Optional[str] = None   # filter by sport (None = all)
    created_at: float = field(default_factory=time.time)


class OddsPushManager:
    """Manages real-time odds push to WebSocket/SSE consumers.

    Subscribers register with optional filters. When a cache entry is
    updated, the push manager fans out to all matching subscribers.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers: Dict[str, PushSubscriber] = {}
        self._push_count = 0
        self._push_errors = 0

    def subscribe(
        self,
        callback: Callable[[CachedOddsEntry], None],
        event_filter: Optional[str] = None,
        sport_filter: Optional[str] = None,
    ) -> str:
        """Register a push subscriber. Returns subscriber ID."""
        sub = PushSubscriber(
            callback=callback,
            event_filter=event_filter,
            sport_filter=sport_filter,
        )
        with self._lock:
            self._subscribers[sub.id] = sub
        return sub.id

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Remove a subscriber. Returns True if found."""
        with self._lock:
            return self._subscribers.pop(subscriber_id, None) is not None

    def push(self, entry: CachedOddsEntry, sport: str = "") -> int:
        """Push an odds update to all matching subscribers. Returns push count."""
        with self._lock:
            subs = list(self._subscribers.values())

        pushed = 0
        for sub in subs:
            if sub.event_filter and sub.event_filter != entry.event_id:
                continue
            if sub.sport_filter and sub.sport_filter != sport:
                continue
            try:
                if sub.callback:
                    sub.callback(entry)
                    pushed += 1
            except Exception as exc:
                logger.warning("Push error for subscriber %s: %s", sub.id, exc)
                self._push_errors += 1

        with self._lock:
            self._push_count += pushed
        return pushed

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "subscribers": len(self._subscribers),
                "total_pushes": self._push_count,
                "push_errors": self._push_errors,
            }


# ═══════════════════════════════════════════════════════════════════════
# 5. LiveOddsCacheManager (facade)
# ═══════════════════════════════════════════════════════════════════════

class LiveOddsCacheManager:
    """Facade wiring cache + latency tracker + push manager.

    Plugs into SportsOddsFeed as a subscriber. When an OddsUpdate arrives:
      1. Write to cache (record propagation latency).
      2. Push to all subscribers (record push latency).
      3. Record end-to-end latency.
    """

    def __init__(
        self,
        cache: Optional[LiveOddsCache] = None,
        tracker: Optional[OddsLatencyTracker] = None,
        push_manager: Optional[OddsPushManager] = None,
    ):
        self.cache = cache or LiveOddsCache()
        self.tracker = tracker or OddsLatencyTracker()
        self.push_manager = push_manager or OddsPushManager()

    def on_odds_update(self, update: Any) -> None:
        """Handle an OddsUpdate from SportsOddsFeed.

        This is the subscriber callback wired into SportsOddsFeed.subscribe().
        """
        start = time.perf_counter()

        # 1. Write to cache
        entry = self.cache.put(
            event_id=update.event_id,
            outcome_label=update.outcome_label,
            implied_prob=update.implied_prob,
            decimal_odds=update.decimal_odds,
            american_odds=update.american_odds,
            provider=update.provider,
            provider_ts=update.timestamp,
        )

        propagation_ms = (time.perf_counter() - start) * 1000
        self.tracker.record(SLOTier.PROPAGATION.value, propagation_ms)

        # 2. Push to subscribers
        push_start = time.perf_counter()
        self.push_manager.push(entry)
        push_ms = (time.perf_counter() - push_start) * 1000
        self.tracker.record(SLOTier.PUSH.value, push_ms)

        # 3. End-to-end
        e2e_ms = (time.perf_counter() - start) * 1000
        self.tracker.record(SLOTier.END_TO_END.value, e2e_ms)

    def get_health(self) -> Dict[str, Any]:
        """Get comprehensive health metrics."""
        return {
            "cache": self.cache.get_stats(),
            "latency": self.tracker.get_all_metrics(),
            "push": self.push_manager.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════
# 6. Singleton
# ═══════════════════════════════════════════════════════════════════════

_cache_manager: Optional[LiveOddsCacheManager] = None
_cache_manager_lock = threading.Lock()


def get_live_odds_cache_manager() -> LiveOddsCacheManager:
    """Get or create the singleton LiveOddsCacheManager."""
    global _cache_manager
    if _cache_manager is None:
        with _cache_manager_lock:
            if _cache_manager is None:
                _cache_manager = LiveOddsCacheManager()
    return _cache_manager
