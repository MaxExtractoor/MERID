"""
KalshiNewsAgent — consumes InsightObjects and publishes to Telegram + X/Twitter.

Responsibilities:
  - Format InsightObjects into category-aware headlines and briefs
  - Route to Telegram (full brief) and X/Twitter (280-char post)
  - Enforce per-category rate limits and deduplication
  - Track post history for thread follow-ups
  - Write post IDs back for threading
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from merid.publishing.kalshi_insight_pipeline import InsightObject, CATEGORY_TAGS

logger = get_logger("merid.publishing.kalshi_news_agent")


# ── Per-category posting cadence (seconds between posts) ─────────────────────

CATEGORY_POST_COOLDOWN: Dict[str, int] = {
    "Trending":     300,    # 5 min
    "Mentions":     300,
    "Crypto":       300,
    "Politics":     600,    # 10 min
    "Sports":       600,
    "Economics":    600,
    "Companies":    600,
    "Financials":   600,
    "Culture":      900,    # 15 min
    "Climate":      1800,   # 30 min
    "Tech & Science": 900,
}

# Category emoji for posts
CATEGORY_EMOJI: Dict[str, str] = {
    "Trending":     "🔥",
    "Politics":     "🏛️",
    "Sports":       "🏆",
    "Culture":      "🎭",
    "Crypto":       "₿",
    "Climate":      "🌍",
    "Economics":    "📊",
    "Mentions":     "📰",
    "Companies":    "🏢",
    "Financials":   "💹",
    "Tech & Science": "🔬",
}

ACTION_EMOJI: Dict[str, str] = {
    "new_market":  "🆕",
    "prob_cross":  "📈",
    "swing":       "⚡",
    "resolution":  "🏁",
    "update":      "🔄",
}

DISCLAIMER = "Not financial advice."


# ── Post record ───────────────────────────────────────────────────────────────

@dataclass
class PostRecord:
    ticker: str
    category: str
    action: str
    telegram_sent: bool
    x_tweet_id: Optional[str]
    text_preview: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Agent ─────────────────────────────────────────────────────────────────────

class KalshiNewsAgent:
    """
    Downstream consumer of KalshiInsightPipeline.

    Wire up:
        pipeline.add_consumer(news_agent.handle_insight)
    """

    def __init__(self) -> None:
        self._last_post_ts: Dict[str, float] = defaultdict(float)   # category → ts
        self._ticker_last_post: Dict[str, float] = {}               # ticker → ts
        self._post_history: List[PostRecord] = []
        self._thread_ids: Dict[str, str] = {}   # ticker → last tweet_id (for threading)
        self._stats: Dict[str, Any] = {
            "total_processed": 0,
            "total_telegram": 0,
            "total_x": 0,
            "skipped_cooldown": 0,
            "errors": 0,
        }

    # ── Main entry point ──────────────────────────────────────────────────────

    async def handle_insight(self, insight: InsightObject) -> None:
        """Called by KalshiInsightPipeline for each emitted InsightObject."""
        self._stats["total_processed"] += 1

        # Per-category cooldown
        cat_cooldown = CATEGORY_POST_COOLDOWN.get(insight.category, 600)
        now = time.time()
        if now - self._last_post_ts[insight.category] < cat_cooldown:
            self._stats["skipped_cooldown"] += 1
            logger.debug("Cooldown skip: %s [%s]", insight.ticker, insight.category)
            return

        # Per-ticker minimum gap (don't spam same market)
        ticker_gap = self._ticker_last_post.get(insight.ticker, 0)
        if now - ticker_gap < 1800:  # 30 min per ticker minimum
            self._stats["skipped_cooldown"] += 1
            return

        # Format content
        telegram_text = self._format_telegram(insight)
        x_text        = self._format_x(insight)

        # Send
        telegram_ok = await self._send_telegram(insight, telegram_text)
        tweet_id    = await self._send_x(insight, x_text)

        # Update state
        self._last_post_ts[insight.category] = now
        self._ticker_last_post[insight.ticker] = now
        if tweet_id:
            self._thread_ids[insight.ticker] = tweet_id

        record = PostRecord(
            ticker=insight.ticker,
            category=insight.category,
            action=insight.action,
            telegram_sent=telegram_ok,
            x_tweet_id=tweet_id,
            text_preview=x_text[:120],
        )
        self._post_history.append(record)
        if len(self._post_history) > 500:
            self._post_history = self._post_history[-500:]

        logger.info(
            "Published [%s] %s — telegram=%s x=%s",
            insight.category, insight.ticker, telegram_ok, tweet_id or "dry-run",
        )

    # ── Formatters ────────────────────────────────────────────────────────────

    def _format_telegram(self, ins: InsightObject) -> str:
        """Full HTML brief for Telegram."""
        cat_emoji  = CATEGORY_EMOJI.get(ins.category, "📌")
        act_emoji  = ACTION_EMOJI.get(ins.action, "🔄")
        prob_pct   = f"{ins.kalshi_prob * 100:.0f}%"
        swarm_pct  = f"{ins.swarm_prob * 100:.0f}%"
        conf_pct   = f"{ins.swarm_confidence * 100:.0f}%"
        change_str = self._fmt_change(ins.change_24h)
        tags_str   = " ".join(ins.tags[:3])

        if ins.action == "resolution":
            result_word = "YES ✅" if ins.resolved_yes else "NO ❌"
            lines = [
                f"{cat_emoji} <b>{ins.category} · Kalshi Market Settled</b>",
                f"",
                f"<b>{ins.question}</b>",
                f"",
                f"Result: <b>{result_word}</b>",
                f"Final price: <b>{prob_pct}</b>",
                f"MERID swarm had called: <b>{swarm_pct}</b> ({conf_pct} confidence)",
                f"",
                f"🔗 <a href='{ins.market_url}'>View on Kalshi</a>",
                f"",
                f"<i>{DISCLAIMER}</i>",
                f"{tags_str}",
            ]
        elif ins.action == "new_market":
            lines = [
                f"{cat_emoji} {act_emoji} <b>{ins.category} · New Kalshi Market</b>",
                f"",
                f"<b>{ins.question}</b>",
                f"",
                f"Opening price: <b>{prob_pct}</b>",
                f"MERID swarm: <b>{swarm_pct}</b> ({conf_pct} confidence)",
                f"Volume: {ins.volume:,} contracts",
                f"",
                f"🔗 <a href='{ins.market_url}'>Trade on Kalshi</a>",
                f"",
                f"<i>{DISCLAIMER}</i>",
                f"{tags_str}",
            ]
        else:
            lines = [
                f"{cat_emoji} {act_emoji} <b>{ins.category} · Kalshi Market Update</b>",
                f"",
                f"<b>{ins.question}</b>",
                f"",
                f"Current odds: <b>{prob_pct}</b> {change_str}",
                f"MERID swarm: <b>{swarm_pct}</b> ({conf_pct} confidence)",
                f"Volume: {ins.volume:,} · OI: {ins.open_interest:,}",
                f"",
                f"{ins.narrative}",
                f"",
                f"🔗 <a href='{ins.market_url}'>View on Kalshi</a>",
                f"",
                f"<i>{DISCLAIMER}</i>",
                f"{tags_str}",
            ]
        return "\n".join(lines)

    def _format_x(self, ins: InsightObject) -> str:
        """280-char post for X/Twitter."""
        cat_emoji  = CATEGORY_EMOJI.get(ins.category, "📌")
        act_emoji  = ACTION_EMOJI.get(ins.action, "🔄")
        prob_pct   = f"{ins.kalshi_prob * 100:.0f}%"
        change_str = self._fmt_change(ins.change_24h)
        tags_str   = " ".join(ins.tags[:2])

        # Truncate question to fit
        q = ins.question
        if len(q) > 80:
            q = q[:77] + "…"

        if ins.action == "resolution":
            result_word = "YES" if ins.resolved_yes else "NO"
            base = (
                f"{cat_emoji} SETTLED {result_word}\n"
                f"{q}\n"
                f"Final: {prob_pct} | MERID called {ins.swarm_prob*100:.0f}%\n"
                f"{ins.market_url}\n"
                f"{tags_str}"
            )
        elif ins.action == "new_market":
            base = (
                f"{cat_emoji} {act_emoji} NEW MARKET\n"
                f"{q}\n"
                f"Opens at {prob_pct} | MERID: {ins.swarm_prob*100:.0f}% ({ins.swarm_confidence*100:.0f}% conf)\n"
                f"{ins.market_url}\n"
                f"{tags_str}"
            )
        else:
            base = (
                f"{cat_emoji} {act_emoji} {ins.category.upper()}\n"
                f"{q}\n"
                f"Now: {prob_pct} {change_str} | MERID: {ins.swarm_prob*100:.0f}%\n"
                f"{ins.market_url}\n"
                f"{tags_str}"
            )

        # Hard truncate to 280
        if len(base) > 280:
            base = base[:277] + "…"
        return base

    def _fmt_change(self, change_24h: float) -> str:
        if abs(change_24h) < 0.005:
            return ""
        pts = change_24h * 100
        arrow = "▲" if pts > 0 else "▼"
        return f"{arrow}{abs(pts):.0f}pts"

    # ── Senders ───────────────────────────────────────────────────────────────

    async def _send_telegram(self, ins: InsightObject, text: str) -> bool:
        try:
            from agents.telegram_agent import get_telegram_agent
            agent = get_telegram_agent()
            msg = await agent.send_message(text, parse_mode="HTML")
            if msg:
                self._stats["total_telegram"] += 1
                return True
        except Exception as exc:
            self._stats["errors"] += 1
            logger.warning("Telegram send failed for %s: %s", ins.ticker, exc)
        return False

    async def _send_x(self, ins: InsightObject, text: str) -> Optional[str]:
        """Post to X/Twitter. Returns tweet_id or None."""
        try:
            from agents.twitter_agent import get_twitter_agent
            agent = get_twitter_agent()
            if not agent.enabled:
                logger.debug("Twitter agent disabled — dry-run for %s", ins.ticker)
                return None

            # Check if we should thread (reply to previous tweet on same ticker)
            reply_to = self._thread_ids.get(ins.ticker)

            loop = asyncio.get_event_loop()
            if reply_to:
                tweet = await loop.run_in_executor(
                    None,
                    lambda: agent.post_tweet_reply(text, reply_to_id=reply_to),
                )
            else:
                tweet = await loop.run_in_executor(None, lambda: agent.post_tweet(text))

            if tweet and tweet.tweet_id:
                self._stats["total_x"] += 1
                return tweet.tweet_id
        except Exception as exc:
            self._stats["errors"] += 1
            logger.warning("X post failed for %s: %s", ins.ticker, exc)
        return None

    # ── Status ────────────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        return {
            "recent_posts": [
                {
                    "ticker": r.ticker,
                    "category": r.category,
                    "action": r.action,
                    "telegram": r.telegram_sent,
                    "tweet_id": r.x_tweet_id,
                    "preview": r.text_preview,
                    "ts": r.ts,
                }
                for r in self._post_history[-20:]
            ],
            "category_cooldowns": {
                cat: max(0, int(CATEGORY_POST_COOLDOWN.get(cat, 600) - (time.time() - ts)))
                for cat, ts in self._last_post_ts.items()
            },
            **self._stats,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_news_agent: Optional[KalshiNewsAgent] = None


def get_kalshi_news_agent() -> KalshiNewsAgent:
    global _news_agent
    if _news_agent is None:
        _news_agent = KalshiNewsAgent()
    return _news_agent
