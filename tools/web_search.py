from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import requests

from core.cache import cache
from core.env import capabilities
from core.settings import SEARXNG_URL
from utils.logger import get_logger

LOGGER = get_logger("tools.web_search")

_searxng_available: Optional[bool] = None  # None = untested, True/False = tested
_searxng_warned: bool = False  # dedup the "unreachable" log message


def _build_params(query: str, num_results: int) -> Dict[str, Any]:
    return {
        "q": query,
        "format": "json",
        "categories": "general",
        "pageno": 1,
        "safe": 1,
        "language": "en",
        "num": num_results,
    }


def _extract_results(payload: Dict[str, Any], num_results: int) -> List[Dict[str, str]]:
    extracted: List[Dict[str, str]] = []
    for item in payload.get("results", [])[:num_results]:
        extracted.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": (item.get("content") or "")[:400],
                "engine": item.get("engine") or "",
            }
        )
    return extracted


def web_search(query: str, num_results: int = 8, retries: int = 3) -> Dict[str, Any]:
    """Perform a cached SearXNG query with retries."""
    if not query:
        return {"query": query, "results": [], "cached": False, "error": "empty query"}

    cache_key = f"web-search:{query}:{num_results}"
    cached = cache.get_json(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    global _searxng_available
    url = capabilities.searxng_url or SEARXNG_URL

    # Fast-fail if SearXNG was already confirmed unreachable
    if _searxng_available is False:
        return {"query": query, "results": [], "total": 0, "cached": False, "error": "SearXNG unavailable"}

    last_error: Optional[str] = None
    for attempt in range(1, min(retries, 2) + 1):  # max 1 retry on first call
        try:
            response = requests.get(
                url,
                params=_build_params(query, num_results),
                timeout=capabilities._get("SEARXNG_TIMEOUT", 15),  # type: ignore[attr-defined]
            )
            response.raise_for_status()
            _searxng_available = True
            data = response.json()
            results = _extract_results(data, num_results)
            payload = {
                "query": query,
                "results": results,
                "total": len(results),
                "cached": False,
                "timestamp": time.time(),
            }
            cache.set_json(cache_key, payload, ttl=180)
            return payload
        except Exception as exc:
            last_error = str(exc)
            if isinstance(exc, requests.exceptions.ConnectionError):
                global _searxng_warned
                _searxng_available = False
                if not _searxng_warned:
                    _searxng_warned = True
                    LOGGER.warning("SearXNG unreachable at %s — disabling web search until restart", url)
                break
            LOGGER.warning("Web search attempt %s failed: %s", attempt, exc)
            time.sleep(0.5 * attempt)

    return {
        "query": query,
        "results": [],
        "total": 0,
        "cached": False,
        "error": last_error or "Unknown error",
    }


if __name__ == "__main__":
    print(json.dumps(web_search("Bitcoin price January 2026 FOMC impact"), indent=2))
