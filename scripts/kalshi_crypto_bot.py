"""Standalone Telegram bot for Kalshi crypto markets.

Runs as a long-lived process with:
  - /crypto command  — manual trigger for full snapshot
  - /crypto changes  — manual trigger for delta-only
  - JobQueue         — polls every 15 min, posts only changes
                       (full snapshot every 4th cycle = hourly)

Usage:
    py scripts/kalshi_crypto_bot.py

Requires env vars:
    TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN   — Telegram bot token
    TELEGRAM_CHAT_ID   / TG_CHAT_ID     — Target chat/channel ID
    KALSHI_API_KEY_ID                    — Kalshi API key
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.logger import get_logger

logger = get_logger("scripts.kalshi_crypto_bot")

# ── Config ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TG_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TG_CHAT_ID", "")
POLL_INTERVAL_S = int(os.environ.get("CRYPTO_BOT_INTERVAL", "900"))  # default 15 min
FULL_EVERY = int(os.environ.get("CRYPTO_BOT_FULL_EVERY", "4"))       # full snapshot every N cycles


def _require_env():
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN")
    if not CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID / TG_CHAT_ID")
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


# ── Bot handlers ──────────────────────────────────────────────────────────

async def _cmd_crypto(update, context):
    """Handle /crypto command — post full snapshot."""
    from core.telegram_bot import post_crypto_markets_to_telegram

    args = context.args or []
    changes_only = "changes" in args or "delta" in args

    try:
        await post_crypto_markets_to_telegram(changes_only=changes_only)
    except Exception as exc:
        logger.error("cmd_crypto_error", error=str(exc))
        await update.message.reply_text(f"Error fetching crypto markets: {exc}")


async def _cmd_help(update, context):
    """Handle /help command."""
    text = (
        "<b>Kalshi Crypto Bot</b>\n\n"
        "/crypto — Post all open crypto markets\n"
        "/crypto changes — Post only new/updated markets\n"
        "/help — This message\n\n"
        f"Auto-posting every {POLL_INTERVAL_S // 60} min (changes only), "
        f"full snapshot every {FULL_EVERY} cycles."
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Scheduled job with adaptive backoff ───────────────────────────────────

_cycle_count = 0
_no_change_streak = 0       # consecutive polls with no changes
_MAX_BACKOFF_MULT = 4       # at most 4x the base interval on quiet periods


async def _scheduled_poll(context):
    """JobQueue callback — runs every POLL_INTERVAL_S seconds.

    Includes adaptive backoff: when repeated polls find no changes the
    effective interval doubles (up to 4x), saving API calls during quiet
    hours.  Any change resets to the base interval immediately.
    """
    global _cycle_count, _no_change_streak
    _cycle_count += 1

    from core.telegram_bot import post_crypto_markets_to_telegram, _crypto_cache

    force_full = FULL_EVERY > 0 and (_cycle_count % FULL_EVERY == 0)

    # Adaptive backoff: skip this cycle if we're in a quiet period
    if _no_change_streak > 0 and not force_full:
        backoff_mult = min(2 ** _no_change_streak, _MAX_BACKOFF_MULT)
        if _cycle_count % backoff_mult != 0:
            logger.debug(
                "Adaptive backoff: skipping cycle %d (no-change streak=%d, mult=%dx)",
                _cycle_count, _no_change_streak, backoff_mult,
            )
            return

    cache_before = len(_crypto_cache)

    try:
        ok = await post_crypto_markets_to_telegram(
            changes_only=not force_full,
        )
        # Detect if there were actually changes by checking if we got
        # "no_changes" (the function returns True silently in that case
        # and logs crypto_poster_no_changes)
        cache_after = len(_crypto_cache)
        if ok and not force_full and cache_before == cache_after:
            _no_change_streak += 1
        else:
            _no_change_streak = 0
    except Exception as exc:
        logger.error("scheduled_poll_error", error=str(exc))
        _no_change_streak = 0  # reset on error to avoid stalling


async def _cmd_status(update, context):
    """Handle /status — show bot health."""
    from core.telegram_bot import _crypto_cache

    text = (
        f"<b>Kalshi Crypto Bot Status</b>\n\n"
        f"Cycle: {_cycle_count}\n"
        f"Cached markets: {len(_crypto_cache)}\n"
        f"No-change streak: {_no_change_streak}\n"
        f"Poll interval: {POLL_INTERVAL_S}s\n"
        f"Effective backoff: {min(2 ** _no_change_streak, _MAX_BACKOFF_MULT)}x\n"
        f"Full snapshot every: {FULL_EVERY} cycles"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Startup calibration ──────────────────────────────────────────────────

async def _calibrate_on_startup(app):
    """Post-init hook: calibrate rate limiter from GET /account/limits."""
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        info = await catalog._client.calibrate_rate_limiter(headroom=0.7)
        logger.info("Startup calibration: %s", info)
    except Exception as exc:
        logger.warning("Startup calibration failed (using defaults): %s", exc)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    _require_env()

    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except ImportError:
        print(
            "ERROR: python-telegram-bot not installed.\n"
            "  pip install python-telegram-bot==21.7",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info(
        "Starting Kalshi Crypto Bot (interval=%ds, full_every=%d)",
        POLL_INTERVAL_S, FULL_EVERY,
    )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("crypto", _cmd_crypto))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("start", _cmd_help))

    # Post-init: calibrate rate limiter from Kalshi API limits
    app.post_init = _calibrate_on_startup

    # Scheduled polling job — every 15 min (first run after 10s startup delay)
    job_queue = app.job_queue
    job_queue.run_repeating(
        _scheduled_poll,
        interval=POLL_INTERVAL_S,
        first=10,
        name="crypto-poll",
    )

    logger.info("Bot running — polling every %d seconds", POLL_INTERVAL_S)
    app.run_polling()


if __name__ == "__main__":
    main()
