"""Rate limit metrics for Prometheus.

Wires TokenBucket metrics to Prometheus counters and histograms.
Add to your FastAPI startup to enable:

    from monitoring.rate_limit_metrics import enable_rate_limit_metrics
    enable_rate_limit_metrics()
"""

from typing import Dict, Any
from prometheus_client import Counter, Histogram, Gauge, Info
import time
from functools import wraps

from merid.external_api_rate_limiter import (
    TokenBucket,
    get_all_limiter_status,
    _buckets,
)
from utils.logger import get_logger

logger = get_logger("monitoring.rate_limit_metrics")

# =============================================================================
# Prometheus Metrics
# =============================================================================

# Counters
RATE_LIMIT_TOTAL = Counter(
    "merid_rate_limit_total",
    "Total requests by provider and type",
    ["provider", "type"]  # type: read|write
)

RATE_LIMIT_THROTTLED = Counter(
    "merid_rate_limit_throttled",
    "Requests throttled (rate limited locally)",
    ["provider", "type"]
)

RATE_LIMIT_429_RECEIVED = Counter(
    "merid_rate_limit_429_received",
    "429 Too Many Requests received from provider",
    ["provider"]
)

RATE_LIMIT_ERRORS = Counter(
    "merid_rate_limit_errors",
    "Rate limiter errors (bucket exhausted, timeout)",
    ["provider", "error_type"]
)

# Histograms
RATE_LIMIT_WAIT_SECONDS = Histogram(
    "merid_rate_limit_wait_seconds",
    "Time spent waiting for token acquisition",
    ["provider", "type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Gauges (current state)
RATE_LIMIT_TOKENS = Gauge(
    "merid_rate_limit_tokens",
    "Current available tokens",
    ["provider", "bucket"]  # bucket: read|write
)

RATE_LIMIT_REQUESTS_ACTIVE = Gauge(
    "merid_rate_limit_requests_active",
    "Current active (in-flight) requests",
    ["provider"]
)

# Info
RATE_LIMIT_CONFIG = Info(
    "merid_rate_limit_config",
    "Rate limiter configuration",
    ["provider"]
)


# =============================================================================
# Metric Collection
# =============================================================================

class RateLimitMetricsCollector:
    """Collects and exports rate limiter metrics to Prometheus."""
    
    def __init__(self, collection_interval: float = 10.0):
        self.interval = collection_interval
        self._running = False
        self._task = None
    
    async def start(self) -> None:
        """Start periodic metric collection."""
        if self._running:
            return
        
        self._running = True
        while self._running:
            try:
                self._collect_gauges()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.warning(f"Rate limit metrics collection failed: {e}")
    
    def stop(self) -> None:
        """Stop metric collection."""
        self._running = False
    
    def _collect_gauges(self) -> None:
        """Collect gauge metrics from all limiters."""
        for provider, bucket in _buckets.items():
            status = bucket.get_status()
            
            # Token gauges
            RATE_LIMIT_TOKENS.labels(
                provider=provider,
                bucket="read"
            ).set(status["read_tokens"])
            
            RATE_LIMIT_TOKENS.labels(
                provider=provider,
                bucket="write"
            ).set(status["write_tokens"])


def record_request(provider: str, is_write: bool, wait_time: float = 0.0) -> None:
    """Record a request in metrics.
    
    Args:
        provider: Provider name
        is_write: True for write requests
        wait_time: Time spent waiting for token (seconds)
    """
    req_type = "write" if is_write else "read"
    
    RATE_LIMIT_TOTAL.labels(
        provider=provider,
        type=req_type
    ).inc()
    
    if wait_time > 0:
        RATE_LIMIT_WAIT_SECONDS.labels(
            provider=provider,
            type=req_type
        ).observe(wait_time)


def record_throttled(provider: str, is_write: bool) -> None:
    """Record a throttled request."""
    RATE_LIMIT_THROTTLED.labels(
        provider=provider,
        type="write" if is_write else "read"
    ).inc()


def record_429_received(provider: str) -> None:
    """Record a 429 response from provider."""
    RATE_LIMIT_429_RECEIVED.labels(provider=provider).inc()


def record_error(provider: str, error_type: str) -> None:
    """Record a rate limiter error."""
    RATE_LIMIT_ERRORS.labels(
        provider=provider,
        error_type=error_type
    ).inc()


def export_config(provider: str, read_per_sec: float, write_per_sec: float) -> None:
    """Export rate limit configuration."""
    RATE_LIMIT_CONFIG.labels(provider=provider).info({
        "read_per_sec": str(read_per_sec),
        "write_per_sec": str(write_per_sec),
    })


# =============================================================================
# Integration with TokenBucket
# =============================================================================

def patch_token_bucket_for_metrics():
    """Monkey-patch TokenBucket to emit metrics.
    
    Call this once at startup to enable metrics collection.
    """
    original_acquire = TokenBucket.acquire
    
    @wraps(original_acquire)
    async def patched_acquire(
        self,
        is_write: bool = False,
        tokens: float = 1.0,
        block: bool = True,
        timeout: float = None
    ) -> bool:
        t0 = time.monotonic()
        result = await original_acquire(self, is_write, tokens, block, timeout)
        wait_time = time.monotonic() - t0 if block else 0.0
        
        # Record metrics
        record_request(self.provider, is_write, wait_time)
        
        if not result:
            record_throttled(self.provider, is_write)
        
        return result
    
    TokenBucket.acquire = patched_acquire
    
    # Patch record_rate_limited_response
    original_record_429 = TokenBucket.record_rate_limited_response
    
    @wraps(original_record_429)
    def patched_record_429(self):
        original_record_429(self)
        record_429_received(self.provider)
    
    TokenBucket.record_rate_limited_response = patched_record_429
    
    logger.info("TokenBucket patched for metrics collection")


def enable_rate_limit_metrics(collection_interval: float = 10.0):
    """Enable rate limit metrics collection.
    
    Call this in your FastAPI startup event.
    
    Args:
        collection_interval: Seconds between gauge metric collections
    """
    import asyncio
    
    # Patch TokenBucket to emit metrics
    patch_token_bucket_for_metrics()
    
    # Start collector
    collector = RateLimitMetricsCollector(collection_interval)
    asyncio.create_task(collector.start())
    
    logger.info(f"Rate limit metrics enabled (interval={collection_interval}s)")


# =============================================================================
# Alerting Rules (for Prometheus Alertmanager)
# =============================================================================

ALERT_RULES = """
groups:
  - name: rate_limit_alerts
    rules:
      # Alert: High throttling rate
      - alert: RateLimitThrottlingHigh
        expr: rate(merid_rate_limit_throttled[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limiting throttling for {{ $labels.provider }}"
          description: "Provider {{ $labels.provider }} has {{ $value }} throttled requests/sec"
      
      # Alert: Provider sending 429s
      - alert: ProviderRateLimit429
        expr: rate(merid_rate_limit_429_received[5m]) > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Provider {{ $labels.provider }} returning 429s"
          description: "Received {{ $value }} 429s/sec from {{ $labels.provider }}"
      
      # Alert: Long wait times (indicates approaching limit)
      - alert: RateLimitWaitTimeHigh
        expr: histogram_quantile(0.95, merid_rate_limit_wait_seconds) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High rate limit wait times for {{ $labels.provider }}"
          description: "p95 wait time is {{ $value }}s"
      
      # Alert: Token bucket near empty
      - alert: RateLimitTokensLow
        expr: merid_rate_limit_tokens < 1.0
        for: 1m
        labels:
          severity: info
        annotations:
          summary: "Rate limit bucket nearly empty for {{ $labels.provider }}"
"""


def get_alert_rules() -> str:
    """Get Prometheus alert rules for rate limiting."""
    return ALERT_RULES


# Global collector instance
_collector: RateLimitMetricsCollector = None

def get_collector() -> RateLimitMetricsCollector:
    """Get the global metrics collector instance."""
    global _collector
    if _collector is None:
        _collector = RateLimitMetricsCollector()
    return _collector
