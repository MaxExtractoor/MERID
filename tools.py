"""Utility search stubs that agents import.

The production implementation can wire these to real services, but keeping
them as plain callables avoids pulling heavy optional dependencies (LangChain)
into the runtime.
"""

from langchain.tools import tool


@tool
def web_search(query: str) -> str:
    """Search the web for information."""
    return f"Web search results for: {query}"


@tool
def x_keyword_search(query: str) -> str:
    """Search X (Twitter) for keywords."""
    return f"X search results for: {query}"


@tool
def view_image(url: str) -> str:
    """View an image from a URL."""
    return f"Viewed image at: {url}"
