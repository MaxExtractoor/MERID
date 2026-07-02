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
USE_TOPN_ALLOCATOR: bool = str(os.getenv("USE_TOPN_ALLOCATOR", "true")).lower() in ("1", "true", "yes", "on")
# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED RISK REGIME (SINGLE SOURCE OF TRUTH)
# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL: This is the ONLY place where risk percentages should be configured.
# All other modules (topn_allocator, global_risk_guard, kalshi_continuous_trader)
# MUST read from these settings. Do NOT add duplicate env vars or YAML settings.
# 
# 2026 BEST PRACTICES ALIGNMENT (2026-06-28): Aligned with leading algorithmic trading platforms
# Based on research from KlawTrade, GCC Brokers, and Algorier:
#   - Max daily loss: 3-5% (halt trading - most critical rule)
#   - Max weekly loss: 7-10%
#   - Max drawdown: 15%
#   - Max single position: 10%
#   - Max single trade loss: 1-2%
#   - Risk management as platform-level infrastructure
#
# Configuration:
#   - MAX_CYCLE_RISK_PCT: 3% of bankroll per cycle (allows 2-3 agents to trade simultaneously)
#   - MAX_TOTAL_RISK_PCT: 6% of bankroll total (allows 2 concurrent cycles of exposure)
#   - DAILY_LOSS_CAP_PCT: 5% of bankroll (2026 best practice - halt trading)
#   - CLUSTER_STOP_PCT: 3% of bankroll (half of daily cap)
#
# With $40 equity:
#   - Cycle cap: $1.20 (3%) → 2-3 contract winners at 50c/contract
#   - Total cap: $2.40 (6%) → allows multi-cycle concurrent exposure
#   - Daily loss: $2.00 (5%) → automatic halt trigger
# ═══════════════════════════════════════════════════════════════════════════
_DEFAULT_CYCLE_RISK_PCT = "0.03"  # 3% per cycle - 2026 best practice
# Read from env var to allow profile-driven configuration (but default to 2026 best practice)
MAX_CYCLE_RISK_PCT: float = float(os.getenv("MAX_CYCLE_RISK_PCT", _DEFAULT_CYCLE_RISK_PCT))
MAX_TOTAL_RISK_PCT: float = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.06"))  # 6% total max (2026 best practice)

# Daily and cluster risk caps (auto-scale with bankroll)
# DAILY_LOSS_CAP_PCT = 5% of bankroll (2026 best practice - halt trading)
DAILY_LOSS_CAP_PCT: float = float(os.getenv("DAILY_LOSS_CAP_PCT", "0.05"))  # 5% default (2026 best practice)
# CLUSTER_STOP_PCT = DAILY_LOSS_CAP_PCT / 2 = 2.5%
CLUSTER_STOP_PCT: float = float(os.getenv("CLUSTER_STOP_PCT", "0.025"))  # 2.5% default

# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED KELLY AND EXPOSURE SETTINGS (SINGLE SOURCE OF TRUTH)
# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL: All sizing and risk components MUST read from profile YAML for Kelly.
# Do NOT add duplicate Kelly fractions or caps in individual modules.
#
# Configuration:
#   - Kelly fraction: Single source of truth is profile YAML (kalshi_crypto_15m.yaml)
#   - MAX_CATEGORY_CRYPTO_PCT: 0.30 (30% category cap for crypto)
#   - CORRELATED_STACK_PCT: 0.20 (20% for same underlying across all timeframes)
#   - DRAWDOWN_HALT_PCT: 0.10 (10% drawdown triggers halt)
#   - DRAWDOWN_UNWIND_PCT: 0.15 (15% drawdown triggers unwind)
# ═══════════════════════════════════════════════════════════════════════════
# KELLY_FRACTION env var is DEPRECATED - use profile YAML instead
# KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.20"))  # DEPRECATED
MAX_CATEGORY_CRYPTO_PCT: float = float(os.getenv("MAX_CATEGORY_CRYPTO_PCT", "0.30"))  # 30% category cap
CORRELATED_STACK_PCT: float = float(os.getenv("CORRELATED_STACK_PCT", "0.25"))  # 25% correlated stack cap (for highly correlated crypto assets)
DRAWDOWN_HALT_PCT: float = float(os.getenv("DRAWDOWN_HALT_PCT", "0.10"))  # 10% drawdown halt
DRAWDOWN_UNWIND_PCT: float = float(os.getenv("DRAWDOWN_UNWIND_PCT", "0.15"))  # 15% drawdown unwind

# Per-asset caps (higher volatility = tighter cap)
# Defaults: BTC/ETH 2%, SOL/XRP 1.5%, DOGE 1%
ASSET_CAP_BTC_PCT: float = float(os.getenv("ASSET_CAP_BTC_PCT", "0.02"))
ASSET_CAP_ETH_PCT: float = float(os.getenv("ASSET_CAP_ETH_PCT", "0.02"))
ASSET_CAP_SOL_PCT: float = float(os.getenv("ASSET_CAP_SOL_PCT", "0.015"))
ASSET_CAP_XRP_PCT: float = float(os.getenv("ASSET_CAP_XRP_PCT", "0.015"))
ASSET_CAP_DOGE_PCT: float = float(os.getenv("ASSET_CAP_DOGE_PCT", "0.01"))

# ═══════════════════════════════════════════════════════════════════════════
# KALSHI MARKET DISCOVERY SETTINGS
# ═══════════════════════════════════════════════════════════════════════════
# KALSHI_MIN_CLOSE_SECONDS_AGO: Freshness cutoff for market discovery
# - None/0/empty string: DISABLED (return all open markets from Kalshi)
# - Positive integer: Only return markets closing after (now - N seconds)
# - Default: None (disabled) - use Kalshi's documented filters only
# ═══════════════════════════════════════════════════════════════════════════
_KALSHI_MIN_CLOSE_SECONDS_AGO = os.getenv("KALSHI_MIN_CLOSE_SECONDS_AGO", "")
KALSHI_MIN_CLOSE_SECONDS_AGO: Optional[int] = int(_KALSHI_MIN_CLOSE_SECONDS_AGO) if _KALSHI_MIN_CLOSE_SECONDS_AGO else None

# ═══════════════════════════════════════════════════════════════════════════
# MOMENTUM SCALPER STRATEGY MODE
# ═══════════════════════════════════════════════════════════════════════════
# OPTIMIZED (2026-05-07): Disabled binary SCALPER_SINGLE_BATCH_MODE by default.
# Now uses MAX_TOTAL_RISK_PCT (8%) as concurrent exposure limit instead of blocking
# on ANY existing risk. This allows multiple batches to overlap while respecting
# total exposure cap.
#
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
    os.getenv("SCALPER_SINGLE_BATCH_MODE", "false")  # Disabled by default for better throughput
).lower() in ("1", "true", "yes", "on")
SCALPER_MAX_TRADES_PER_BATCH: int = max(1, int(os.getenv("SCALPER_MAX_TRADES_PER_BATCH", "5")))  # Increased to 5

# Dedicated 15m scalper bankroll allocation (separate bucket from global caps)
# CRITICAL: Now aligned to 2% like all other modes - no exceptions
SCALPER15M_BANKROLL_PCT: float = float(os.getenv("SCALPER15M_BANKROLL_PCT", "0.02"))  # 2% aligned with MAX_CYCLE_RISK_PCT
SCALPER_MAX_BATCH_RISK_PCT: float = float(
    os.getenv("SCALPER_MAX_BATCH_RISK_PCT", str(MAX_CYCLE_RISK_PCT))
)

# 24/7-SCALPER-FIX: Raised to 12000ms for continuous 15m scalping operation
MERID_LOOP_SLOW_ACTION_BUDGET_MS: float = float(os.getenv("MERID_LOOP_SLOW_ACTION_BUDGET_MS", "12000.0"))

# 24/7-SCALPER-FIX: Raised to 15000ms - never halt for lag in scalper mode
MERID_LOOP_LAG_HALT_MS: float = float(os.getenv("MERID_LOOP_LAG_HALT_MS", "15000.0"))

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
    "DAILY_LOSS_CAP_PCT",
    "CLUSTER_STOP_PCT",
    "MAX_CATEGORY_CRYPTO_PCT",
    "CORRELATED_STACK_PCT",
    "DRAWDOWN_HALT_PCT",
    "DRAWDOWN_UNWIND_PCT",
    "ASSET_CAP_BTC_PCT",
    "ASSET_CAP_ETH_PCT",
    "ASSET_CAP_SOL_PCT",
    "ASSET_CAP_XRP_PCT",
    "ASSET_CAP_DOGE_PCT",
    "KALSHI_MIN_CLOSE_SECONDS_AGO",
    "STRATEGY_MODE",
    "SCALPER_MODE",
    "SCALPER_SINGLE_BATCH_MODE",
    "SCALPER_MAX_TRADES_PER_BATCH",
    "SCALPER_MAX_BATCH_RISK_PCT",
    "SCALPER15M_BANKROLL_PCT",  # Dedicated 15m scalper bankroll allocation
    "HTTP_PORT",
    "API_BASE_URL",
    "WS_PORT",
]
