"""Global configuration constants for MERID."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FAST_MODEL = os.getenv("MERID_FAST_MODEL", "merid-interface:latest")
DEEP_MODEL = os.getenv("MERID_DEEP_MODEL", "merid-strategist:latest")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_GENERATE_ENDPOINT = os.getenv("OLLAMA_GENERATE_ENDPOINT", "/api/generate")

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080/search")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

WEB_CONCURRENCY = int(os.getenv("MERID_WEB_CONCURRENCY", "4"))
CONSENSUS_THRESHOLD = float(os.getenv("MERID_CONSENSUS_THRESHOLD", "0.65"))
TRUTH_MIN_CONFIDENCE = float(os.getenv("MERID_TRUTH_MIN_CONFIDENCE", "0.55"))
HISTORY_CACHE_SECONDS = int(os.getenv("MERID_HISTORY_CACHE_SECONDS", "60"))
EVENT_BUFFER = int(os.getenv("MERID_EVENT_BUFFER", "200"))

TELEGRAM_ALERT_INTERVAL = int(os.getenv("MERID_TELEGRAM_INTERVAL", "120"))
X_POST_INTERVAL = int(os.getenv("MERID_X_POST_INTERVAL", "3600"))
POLYMARKET_SCAN_INTERVAL = int(os.getenv("MERID_POLYMARKET_INTERVAL", "600"))
MAX_TOOL_RESULTS = int(os.getenv("MERID_MAX_TOOL_RESULTS", "4"))

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
]
