"""MERID relay client for local/cloud sentiment analysis.

Previously this file shipped with a BOM and hardcoded API key placeholders,
which prevented coverage analysis and CI linting.  This rewrite removes the BOM,
loads credentials from the environment, and handles missing dependencies safely.
"""

from __future__ import annotations

import os
import sys
from typing import List, Union

from dotenv import load_dotenv

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    from supabase import create_client  # type: ignore
except ImportError:  # pragma: no cover
    create_client = None  # type: ignore

try:
    from .twitter_agent import MERIDTwitterAgent
except ImportError:  # pragma: no cover
    MERIDTwitterAgent = None  # type: ignore

load_dotenv()

from merid_core import ExternalServiceError
import logging


def _build_openai_clients() -> tuple:
    local_api_key = os.getenv("OLLAMA_API_KEY", "ollama")
    local_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not OpenAI:
        raise RuntimeError("openai package not installed")

    local_client = OpenAI(base_url=local_base_url, api_key=local_api_key)
    cloud_client = OpenAI(api_key=openai_key) if openai_key else None
    return local_client, cloud_client


def _build_supabase_client():
    if not create_client:
        return None
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        return create_client(supabase_url, supabase_key)
    return None


def save_report(supabase_client, query: str, summary: str, tweets: Union[str, List[str]]) -> None:
    if not supabase_client:
        return
    payload = {
        "query": query,
        "sentiment_summary": summary,
        "raw_tweets": tweets if isinstance(tweets, list) else [tweets],
    }
    supabase_client.table("sentiment_reports").insert(payload).execute()


import logging

def run_relay(user_query: str) -> str:
    logger = logging.getLogger(__name__)
    try:
        local_client, cloud_client = _build_openai_clients()
        twitter = MERIDTwitterAgent() if MERIDTwitterAgent else None
        supabase_client = _build_supabase_client()

        analysis = local_client.chat.completions.create(
            model=os.getenv("LOCAL_RELAY_MODEL", "merid-strategist"),
            messages=[
                {"role": "system", "content": "Reply ONLY with RELAY if live data is needed."},
                {"role": "user", "content": user_query},
            ],
        )
        decision = analysis.choices[0].message.content.strip()

        if "RELAY" not in decision.upper():
            return f"\n[MERID-LOCAL]: {decision}"

        if not twitter or not cloud_client:
            logger.warning("Live relay called but dependencies missing: twitter=%s cloud=%s", bool(twitter), bool(cloud_client))
            raise ExternalServiceError("Live relay unavailable (missing dependencies)")

        tweets = twitter.get_market_sentiment(user_query)
        context = "\n".join(tweets) if isinstance(tweets, list) else str(tweets)

        cloud_res = cloud_client.chat.completions.create(
            model=os.getenv("CLOUD_RELAY_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": f"Context: {context}"},
                {"role": "user", "content": user_query},
            ],
        )
        summary = cloud_res.choices[0].message.content
        save_report(supabase_client, user_query, summary, tweets)
        return f"\n[MERID-X-RELAY]: {summary}"

    except ExternalServiceError:
        # re-raise known external errors after logging
        logger.exception("External service failure while running relay")
        raise
    except Exception as exc:
        logger.exception("Unexpected error in run_relay")
        raise ExternalServiceError(str(exc)) from exc


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Bitcoin vibe"
    print(run_relay(query))

