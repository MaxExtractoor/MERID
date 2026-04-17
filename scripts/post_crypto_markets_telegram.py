"""Post Kalshi crypto markets to Telegram — with change tracking.

Usage:
    # One-shot: post ALL open crypto markets
    py scripts/post_crypto_markets_telegram.py

    # Repeating every 15 minutes, only post new/updated markets
    py scripts/post_crypto_markets_telegram.py --repeat 900 --changes-only

    # Only BTC and ETH, minimum 100 volume
    py scripts/post_crypto_markets_telegram.py --assets BTC ETH --min-volume 100

    # Full snapshot every hour, changes every 15 min
    py scripts/post_crypto_markets_telegram.py --repeat 900 --changes-only --full-every 4

Requires env vars:
    TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN   — Telegram bot token
    TELEGRAM_CHAT_ID   / TG_CHAT_ID     — Target chat/channel ID
    KALSHI_API_KEY_ID                    — Kalshi API key (for catalog fetch)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from merid.event_venues.kalshi.market_catalog import (
    CatalogMarket,
    get_market_catalog,
)
from merid.alerts.webhook_client import tg_send
from utils.logger import get_logger

logger = get_logger("scripts.post_crypto_markets_telegram")


# ── Change Tracker ────────────────────────────────────────────────────────

class CryptoMarketTracker:
    """Track new/updated crypto markets between polling cycles.

    Keyed by market ticker. A market is "updated" when any of the tracked
    fields change (yes_bid, no_bid, volume, open_interest, status).
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _snapshot(cm: CatalogMarket) -> Dict[str, Any]:
        """Extract the fields we track for change detection."""
        raw = cm.market.raw_data or {}
        return {
            "yes_bid": raw.get("yes_bid"),
            "no_bid": raw.get("no_bid"),
            "yes_ask": raw.get("yes_ask"),
            "no_ask": raw.get("no_ask"),
            "last_price": raw.get("last_price"),
            "volume": str(cm.market.volume) if cm.market.volume else None,
            "open_interest": str(cm.market.open_interest) if cm.market.open_interest else None,
            "status": raw.get("status"),
        }

    def diff(
        self, markets: List[CatalogMarket]
    ) -> Tuple[List[CatalogMarket], List[CatalogMarket], List[str]]:
        """Compare current markets against cache.

        Returns:
            (new_markets, updated_markets, removed_tickers)
        """
        new: List[CatalogMarket] = []
        updated: List[CatalogMarket] = []
        current_tickers: set = set()
        next_cache: Dict[str, Dict[str, Any]] = {}

        for cm in markets:
            ticker = cm.market.market_id
            current_tickers.add(ticker)
            snap = self._snapshot(cm)
            next_cache[ticker] = snap

            if ticker not in self._cache:
                new.append(cm)
            elif snap != self._cache[ticker]:
                updated.append(cm)

        removed = [t for t in self._cache if t not in current_tickers]
        self._cache = next_cache
        return new, updated, removed

    @property
    def cached_count(self) -> int:
        return len(self._cache)


# Global tracker instance
_tracker = CryptoMarketTracker()


# ── Formatting ────────────────────────────────────────────────────────────

ASSET_EMOJI = {
    "BTC": "₿",
    "ETH": "⟠",
    "SOL": "◎",
    "XRP": "✕",
    "DOGE": "🐕",
}


def _format_market(cm: CatalogMarket, prefix: str = "") -> str:
    """Format a single CatalogMarket into a compact HTML line for Telegram."""
    mkt = cm.market
    raw = mkt.raw_data or {}

    ticker = mkt.market_id or ""
    title = (mkt.question or mkt.description or ticker)[:80]

    # Prices
    yes_bid = raw.get("yes_bid")
    no_bid = raw.get("no_bid")
    yes_str = f"Y:{yes_bid}¢" if yes_bid is not None else "Y:—"
    no_str = f"N:{no_bid}¢" if no_bid is not None else "N:—"

    # Volume + OI
    vol = mkt.volume
    vol_str = f"vol {int(float(vol)):,}" if vol else "vol —"
    oi = mkt.open_interest
    oi_str = f"OI {int(float(oi)):,}" if oi else ""

    # Expiry
    expiry_str = ""
    if cm.minutes_to_expiry is not None and cm.minutes_to_expiry > 0:
        mins = cm.minutes_to_expiry
        if mins < 60:
            expiry_str = f"⏱{int(mins)}m"
        elif mins < 1440:
            expiry_str = f"⏱{mins / 60:.1f}h"
        else:
            expiry_str = f"⏱{mins / 1440:.0f}d"

    # Asset emoji
    emoji = ASSET_EMOJI.get(cm.asset or "", "🪙")

    # Timeframe tag
    tf = f"[{cm.timeframe}]" if cm.timeframe else ""

    # Build line
    pfx = f"{prefix} " if prefix else ""
    meta_parts = [p for p in [yes_str, no_str, vol_str, oi_str, expiry_str, tf] if p]
    meta = "  |  ".join(meta_parts)

    return f"{pfx}{emoji} <b>{title}</b>\n   <code>{ticker}</code>  {meta}"


def format_full_message(markets: List[CatalogMarket]) -> str:
    """Full snapshot message for all open crypto markets."""
    if not markets:
        return "📭 No open Kalshi crypto markets found."

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    header = f"🪙 <b>Kalshi Crypto Markets</b> — {len(markets)} open ({now})\n"
    body = "\n\n".join(_format_market(m) for m in markets[:50])
    footer = ""
    if len(markets) > 50:
        footer = f"\n\n… and {len(markets) - 50} more"

    return f"{header}\n{body}{footer}"


def format_changes_message(
    new: List[CatalogMarket],
    updated: List[CatalogMarket],
    removed: List[str],
) -> Optional[str]:
    """Delta message for new/updated/removed markets. Returns None if no changes."""
    if not new and not updated and not removed:
        return None

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"🔄 <b>Kalshi Crypto Update</b> ({now})\n"]

    if new:
        lines.append(f"<b>🆕 New ({len(new)}):</b>")
        for cm in new[:20]:
            lines.append(_format_market(cm, prefix="🆕"))
        lines.append("")

    if updated:
        lines.append(f"<b>♻️ Updated ({len(updated)}):</b>")
        for cm in updated[:20]:
            lines.append(_format_market(cm, prefix="♻️"))
        lines.append("")

    if removed:
        lines.append(f"<b>❌ Closed ({len(removed)}):</b>")
        for t in removed[:10]:
            lines.append(f"   <code>{t}</code>")

    return "\n".join(lines)


# ── Telegram chunked sender ───────────────────────────────────────────────

_TG_MAX_LEN = 4000  # Telegram limit is 4096; leave margin for safety


async def _tg_send_chunked(text: str) -> bool:
    """Send a long message in chunks that respect Telegram's 4096-char limit."""
    if len(text) <= _TG_MAX_LEN:
        return await tg_send(text, force_immediate=True)

    # Split at double-newline boundaries to keep market blocks intact
    parts = text.split("\n\n")
    chunks: List[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n\n{part}" if current else part
        if len(candidate) > _TG_MAX_LEN and current:
            chunks.append(current)
            current = part
        else:
            current = candidate
    if current:
        chunks.append(current)

    ok = True
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(1.0)  # respect Telegram rate limit between chunks
        if not await tg_send(chunk, force_immediate=True):
            ok = False
    return ok


# ── Core logic ────────────────────────────────────────────────────────────

async def _fetch_crypto(
    assets: Optional[List[str]] = None,
    min_volume: float = 0,
    timeframe: Optional[str] = None,
) -> List[CatalogMarket]:
    """Refresh catalog and return filtered crypto markets."""
    catalog = get_market_catalog()
    count = await catalog.refresh()
    logger.info("Catalog refreshed: %d total markets", count)

    crypto = catalog.get_crypto_markets(
        min_volume=min_volume,
        timeframe=timeframe,
        assets=assets,
    )
    logger.info("Crypto markets after filter: %d", len(crypto))
    return crypto


async def fetch_and_post(
    assets: Optional[List[str]] = None,
    min_volume: float = 0,
    timeframe: Optional[str] = None,
    changes_only: bool = False,
) -> bool:
    """Refresh the catalog, filter to crypto, and post to Telegram.

    Args:
        changes_only: If True, only post new/updated markets (skip if no changes).

    Returns True if the message was sent (or buffered) successfully.
    """
    crypto = await _fetch_crypto(assets=assets, min_volume=min_volume, timeframe=timeframe)

    if changes_only:
        new, updated, removed = _tracker.diff(crypto)
        msg = format_changes_message(new, updated, removed)
        if msg is None:
            logger.info("No changes detected — skipping Telegram post")
            return True
    else:
        # Still update the tracker so future --changes-only runs have a baseline
        _tracker.diff(crypto)
        msg = format_full_message(crypto)

    ok = await _tg_send_chunked(msg)
    if ok:
        logger.info("Crypto markets posted to Telegram (%d markets)", len(crypto))
    else:
        logger.warning("Failed to post crypto markets to Telegram")
    return ok


async def run_repeating(
    interval_s: float,
    assets: Optional[List[str]] = None,
    min_volume: float = 0,
    timeframe: Optional[str] = None,
    changes_only: bool = False,
    full_every: int = 0,
) -> None:
    """Post crypto markets on a repeating schedule.

    Args:
        full_every: If >0 and changes_only is True, post a full snapshot
                    every N cycles (e.g. full_every=4 with 15min interval
                    means a full snapshot every hour).
    """
    logger.info(
        "Starting repeating poster every %ds (changes_only=%s, full_every=%d)",
        interval_s, changes_only, full_every,
    )
    cycle = 0
    while True:
        cycle += 1
        try:
            force_full = full_every > 0 and (cycle % full_every == 0)
            await fetch_and_post(
                assets=assets,
                min_volume=min_volume,
                timeframe=timeframe,
                changes_only=changes_only and not force_full,
            )
        except Exception as exc:
            logger.error("Repeating post failed: %s", exc)
        await asyncio.sleep(interval_s)


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post Kalshi crypto markets to Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # One-shot full snapshot
  py scripts/post_crypto_markets_telegram.py

  # Poll every 15 min, only post changes, full snapshot every hour
  py scripts/post_crypto_markets_telegram.py --repeat 900 --changes-only --full-every 4

  # Only BTC 15-minute markets
  py scripts/post_crypto_markets_telegram.py --assets BTC --timeframe 15m
""",
    )
    parser.add_argument(
        "--assets", nargs="+", default=None,
        help="Filter to specific assets (e.g. BTC ETH SOL)",
    )
    parser.add_argument(
        "--min-volume", type=float, default=0,
        help="Minimum volume filter (default: 0)",
    )
    parser.add_argument(
        "--timeframe", type=str, default=None,
        help="Timeframe filter (e.g. 15m, 1h, daily)",
    )
    parser.add_argument(
        "--repeat", type=float, default=0,
        help="Repeat interval in seconds (0 = one-shot, default: 0)",
    )
    parser.add_argument(
        "--changes-only", action="store_true",
        help="Only post new/updated markets (requires --repeat for useful behavior)",
    )
    parser.add_argument(
        "--full-every", type=int, default=0,
        help="With --changes-only: post full snapshot every N cycles (0 = never)",
    )
    args = parser.parse_args()

    if args.repeat > 0:
        asyncio.run(run_repeating(
            interval_s=args.repeat,
            assets=args.assets,
            min_volume=args.min_volume,
            timeframe=args.timeframe,
            changes_only=args.changes_only,
            full_every=args.full_every,
        ))
    else:
        ok = asyncio.run(fetch_and_post(
            assets=args.assets,
            min_volume=args.min_volume,
            timeframe=args.timeframe,
            changes_only=args.changes_only,
        ))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
