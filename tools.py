"""Utility search stubs that agents import.

The production implementation can wire these to real services, but keeping
them as plain callables avoids pulling heavy optional dependencies (LangChain)
into the runtime.
"""

from typing import Dict, Any, List
import httpx


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web for information using DuckDuckGo."""
    try:
        # Use DuckDuckGo instant answer API (no auth required)
        # Reduced timeout to fail faster
        with httpx.Client(timeout=5.0, verify=False) as client:
            response = client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1}
            )
            if response.status_code == 200:
                data = response.json()
                results = []
                
                # Extract abstract if available
                if data.get("Abstract"):
                    results.append({
                        "title": data.get("Heading", query),
                        "snippet": data.get("Abstract", "")[:300],
                        "url": data.get("AbstractURL", "")
                    })
                
                # Extract related topics
                for topic in data.get("RelatedTopics", [])[:max_results]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append({
                            "title": topic.get("Text", "")[:100],
                            "snippet": topic.get("Text", "")[:300],
                            "url": topic.get("FirstURL", "")
                        })
                
                return {"query": query, "results": results[:max_results]}
    except httpx.TimeoutException:
        # Silent fail on timeout - agents can work without web search
        pass
    except Exception as e:
        # Only log non-timeout errors
        if "timed out" not in str(e).lower():
            print(f"[Tools] Web search error: {e}")
    
    return {"query": query, "results": []}


def x_keyword_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search X (Twitter) for keywords - stub implementation."""
    return {"query": query, "results": [], "note": "X API requires authentication"}


def view_image(url: str) -> Dict[str, Any]:
    """View an image from a URL - stub implementation."""
    return {"url": url, "status": "Image URL recorded"}
