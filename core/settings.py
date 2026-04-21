"""Global configuration constants for MERID."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FAST_MODEL = os.getenv("MERID_FAST_MODEL", "gemma3:1b")
DEEP_MODEL = os.getenv("MERID_DEEP_MODEL", "gemma3:1b")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_GENERATE_ENDPOINT = os.getenv("OLLAMA_GENERATE_ENDPOINT", "/api/generate")

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080/search")
REDIS_URL = os.getenv("MERID_REDIS_URL", "redis://127.0.0.1:6379/0")

WEB_CONCURRENCY = int(os.getenv("MERID_WEB_CONCURRENCY", "4"))
CONSENSUS_THRESHOLD = float(os.getenv("MERID_CONSENSUS_THRESHOLD", "0.65"))
TRUTH_MIN_CONFIDENCE = float(os.getenv("MERID_TRUTH_MIN_CONFIDENCE", "0.55"))
HISTORY_CACHE_SECONDS = int(os.getenv("MERID_HISTORY_CACHE_SECONDS", "60"))
EVENT_BUFFER = int(os.getenv("MERID_EVENT_BUFFER", "200"))

TELEGRAM_ALERT_INTERVAL = int(os.getenv("MERID_TELEGRAM_INTERVAL", "120"))
X_POST_INTERVAL = int(os.getenv("MERID_X_POST_INTERVAL", "3600"))
POLYMARKET_SCAN_INTERVAL = int(os.getenv("MERID_POLYMARKET_INTERVAL", "600"))
MAX_TOOL_RESULTS = int(os.getenv("MERID_MAX_TOOL_RESULTS", "4"))

# ═══════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT — Top-N Allocator Feature Flag
# ═══════════════════════════════════════════════════════════════════════════
# When TRUE: Uses TopNEdgeAllocator with 1-2% cycle-wide risk cap + GlobalRiskGuard
# When FALSE: Uses legacy Kelly per-trade sizing (DANGEROUS — can cause oversizing)
# 
# This flag is the primary defense against the 7-BTC-orders-with-28-equity bug.
# See: tests/trading/test_risk_oversizing_regression.py
# ═══════════════════════════════════════════════════════════════════════════
USE_TOPN_ALLOCATOR: bool = str(os.getenv("USE_TOPN_ALLOCATOR", "false")).lower() in ("1", "true", "yes", "on")
MAX_CYCLE_RISK_PCT: float = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.02"))  # 2% default
MAX_TOTAL_RISK_PCT: float = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.02"))  # 2% default

# ═══════════════════════════════════════════════════════════════════════════
# MOMENTUM SCALPER STRATEGY MODE
# ═══════════════════════════════════════════════════════════════════════════
# When ``STRATEGY_MODE=MOMENTUM_SCALPER`` + ``SCALPER_SINGLE_BATCH_MODE=true``,
# the GlobalRiskGuard enforces:
#   - at most one active batch of positions at a time (no new entry while
#     ``existing_risk_cents > 0``),
#   - at most ``SCALPER_MAX_TRADES_PER_BATCH`` new entries per cycle/batch.
# Exits/sells are always exempt (they reduce exposure).
# See ``docs/MOMENTUM_SCALPER_SPEC.md`` (target) and the master spec for intent.
# ═══════════════════════════════════════════════════════════════════════════
STRATEGY_MODE: str = os.getenv("STRATEGY_MODE", "DEFAULT").upper()
SCALPER_MODE: bool = (STRATEGY_MODE == "MOMENTUM_SCALPER") or str(
    os.getenv("SCALPER_MODE", "false")
).lower() in ("1", "true", "yes", "on")
SCALPER_SINGLE_BATCH_MODE: bool = str(
    os.getenv("SCALPER_SINGLE_BATCH_MODE", "true" if SCALPER_MODE else "false")
).lower() in ("1", "true", "yes", "on")
SCALPER_MAX_TRADES_PER_BATCH: int = max(1, int(os.getenv("SCALPER_MAX_TRADES_PER_BATCH", "3")))
SCALPER_MAX_BATCH_RISK_PCT: float = float(
    os.getenv("SCALPER_MAX_BATCH_RISK_PCT", str(MAX_CYCLE_RISK_PCT))
)

# Canonical port configuration (single source of truth for all services)
HTTP_PORT = int(os.getenv("MERID_HTTP_PORT", os.getenv("MERID_BACKEND_PORT", "8011")))
API_BASE_URL = os.getenv("MERID_API_BASE_URL", f"http://127.0.0.1:{HTTP_PORT}")
WS_PORT = int(os.getenv("MERID_WS_PORT", str(HTTP_PORT)))

__all__ = [
    "PROJECT_ROOT",
    "FAST_MODEL",
    "DEEP_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_GENERATE_ENDPOINT",
    "SEARXNG_URL",
    "REDIS_URL",
    "WEB_CONCURRENCY",
    "CONSENSUS_THRESHOLD",
    "TRUTH_MIN_CONFIDENCE",
    "HISTORY_CACHE_SECONDS",
    "EVENT_BUFFER",
    "TELEGRAM_ALERT_INTERVAL",
    "X_POST_INTERVAL",
    "POLYMARKET_SCAN_INTERVAL",
    "MAX_TOOL_RESULTS",
    "USE_TOPN_ALLOCATOR",
    "MAX_CYCLE_RISK_PCT",
    "MAX_TOTAL_RISK_PCT",
    "STRATEGY_MODE",
    "SCALPER_MODE",
    "SCALPER_SINGLE_BATCH_MODE",
    "SCALPER_MAX_TRADES_PER_BATCH",
    "SCALPER_MAX_BATCH_RISK_PCT",
    "HTTP_PORT",
    "API_BASE_URL",
    "WS_PORT",
]
