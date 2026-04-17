"""
Async webhook client for ATR regime alerts and other lane notifications.

Reads MERID_ALERT_WEBHOOK_URL from settings/env.  If unset, alerts are
logged only (no HTTP call).  Falls back gracefully on any network error
so it never blocks the trading loop.

Usage:
    from merid.alerts.webhook_client import send_alert

    await send_alert("ATR regime: HIGH volatility on BTC:15m")

Or use the typed helper:
    from merid.alerts.webhook_client import send_atr_alert

    await send_atr_alert(regime="high_vol", atr_value=0.042, asset="BTC", timeframe="15m")
"""

from __future__ import annotations

import collections
import threading
import time as _time

from utils.logger import get_logger
from utils.http_client import get_shared_ssl_context
import os
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _tg_creds() -> tuple[Optional[str], Optional[str]]:
    """Return (token, chat_id) from settings or env."""
    try:
        from merid.settings import settings as _s
        token   = getattr(_s, "TELEGRAM_TOKEN", None) or os.getenv("TG_BOT_TOKEN")
        chat_id = getattr(_s, "TELEGRAM_CHAT_ID", None) or os.getenv("TG_CHAT_ID")
    except Exception as _se:
        logger.debug("_tg_creds: settings unavailable, falling back to env: %s", _se)
        token   = os.getenv("TG_BOT_TOKEN")
        chat_id = os.getenv("TG_CHAT_ID")
    return token or None, chat_id or None


async def tg_send(text: str, timeout: float = 5.0, force_immediate: bool = False) -> bool:
    """
    Send a Telegram message via the Bot API.

    Reads TG_BOT_TOKEN / TG_CHAT_ID from merid.settings or env.
    Returns True on success, False otherwise.  Never raises.

    Args:
        force_immediate: Accepted for API compatibility (no-op; all sends are immediate).
    """
    # Check circuit breaker before attempting any network call
    _cb_trip = None
    try:
        from merid.alerts.tg_circuit_breaker import is_open as _cb_is_open, trip as _cb_trip
        if _cb_is_open():
            logger.debug("tg_send: circuit breaker open — skipping")
            return False
    except ImportError:
        pass

    token, chat_id = _tg_creds()
    if not token or not chat_id:
        logger.debug("tg_send: no Telegram credentials configured — skipping")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, verify=get_shared_ssl_context()) as client:
            resp = await client.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            if resp.status_code < 300:
                return True
            # Trip circuit breaker on Telegram 429 (flood control)
            if resp.status_code == 429 and _cb_trip is not None:
                retry_after = 30.0
                try:
                    retry_after = float(resp.json().get("parameters", {}).get("retry_after", 30))
                except Exception as e:
                    logger.debug(f"Retry-after parse failed: {e}")
                _cb_trip(retry_after, source="tg_send_429")
            logger.warning("tg_send: HTTP %d — %s", resp.status_code, resp.text[:120])
            return False
    except ImportError:
        logger.debug("tg_send: httpx not installed")
        return False
    except Exception as exc:
        # Trip breaker on timeout so subsequent sends in the same storm are suppressed
        if _cb_trip is not None and ("timed out" in str(exc).lower() or "timeout" in str(exc).lower()):
            _cb_trip(60.0, source="tg_send")
        logger.warning("tg_send failed: %s", exc)
        return False


def tg_send_sync(text: str, timeout: float = 5.0) -> bool:
    """Synchronous wrapper for tg_send. Cannot be called from a running event loop."""
    import asyncio
    try:
        return asyncio.run(tg_send(text, timeout=timeout))
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _get_webhook_url() -> Optional[str]:
    """Resolve alert webhook URL from settings or env."""
    try:
        from merid.settings import settings as _s
        url = getattr(_s, "MERID_ALERT_WEBHOOK_URL", None) or os.getenv("MERID_ALERT_WEBHOOK_URL")
    except Exception as _se:
        logger.debug("_get_webhook_url: settings unavailable, falling back to env: %s", _se)
        url = os.getenv("MERID_ALERT_WEBHOOK_URL")
    return url or None


# ---------------------------------------------------------------------------
# Core send
# ---------------------------------------------------------------------------

async def send_alert(
    message: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0,
) -> bool:
    """
    POST an alert to the configured webhook endpoint.

    Args:
        message: Human-readable alert text.
        payload: Optional extra fields merged into the POST body.
        timeout: HTTP timeout in seconds.

    Returns:
        True if the POST succeeded (2xx), False otherwise.
        Never raises — all errors are logged and swallowed.
    """
    url = _get_webhook_url()
    if not url:
        logger.info("ALERT (no webhook configured): %s", message)
        return False

    body: Dict[str, Any] = {"text": message}
    if payload:
        body.update(payload)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, verify=get_shared_ssl_context()) as client:
            resp = await client.post(url, json=body)
            if resp.status_code < 300:
                logger.debug("Alert sent (%d): %s", resp.status_code, message)
                return True
            else:
                logger.warning(
                    "Alert webhook returned %d for message: %s",
                    resp.status_code, message,
                )
                return False
    except ImportError:
        logger.warning("httpx not installed — alert not sent: %s", message)
        return False
    except Exception as exc:
        logger.warning("Alert send failed (%s): %s", exc, message)
        return False


# ---------------------------------------------------------------------------
# Typed helpers
# ---------------------------------------------------------------------------

async def send_atr_alert(
    regime: str,
    atr_value: float,
    asset: str = "BTC",
    timeframe: str = "15m",
) -> bool:
    """Send a structured ATR regime-change alert."""
    emoji = "🔴" if regime == "high_vol" else "🔵"
    msg = f"{emoji} ATR regime: {regime.upper()} on {asset}:{timeframe} (atr={atr_value:.4f})"
    return await send_alert(
        msg,
        payload={
            "event": "atr_regime_alert",
            "regime": regime,
            "atr_value": atr_value,
            "asset": asset,
            "timeframe": timeframe,
        },
    )


async def send_lifecycle_alert(
    from_state: str,
    to_state: str,
    reason: str,
    asset: str = "BTC",
) -> bool:
    """Send a bot lifecycle state-transition alert."""
    msg = f"🔄 Lifecycle: {from_state} → {to_state} ({reason}) [{asset}]"
    return await send_alert(
        msg,
        payload={
            "event": "lifecycle_transition",
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "asset": asset,
        },
    )


async def send_portfolio_dashboard(state: Dict[str, Any]) -> bool:
    """
    Send a compact Kalshi portfolio status snapshot to Telegram.

    Designed to accept lane.get_status() directly.  All keys are optional.

    Example:
        await send_portfolio_dashboard(lane.get_status())
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── Mode line (unambiguous) ───────────────────────────────────────────
    effective_mode = state.get("effective_mode", state.get("mode", "paper")).upper()
    trade_mode     = state.get("trade_mode", "?").upper()
    lane_live      = state.get("lane_live", False)
    kill_active    = state.get("kill_switch_active", False)
    mode_icon      = "🟢" if effective_mode == "LIVE" else "🟡"
    kill_str       = " ⛔KILL" if kill_active else ""

    # ── Lifecycle ─────────────────────────────────────────────────────────
    lifecycle      = state.get("lifecycle") or {}
    lc_state       = lifecycle.get("state", "?") if isinstance(lifecycle, dict) else "?"

    # ── Equity / PnL ─────────────────────────────────────────────────────
    equity         = state.get("equity", 0.0)
    daily_pnl      = state.get("daily_pnl", state.get("realised_pnl", 0.0))
    dd             = state.get("max_drawdown", state.get("drawdown", 0.0))
    consec_losses  = state.get("consec_losses", 0)

    # ── Sentiment / risk ─────────────────────────────────────────────────
    cached_sent    = state.get("cached_sentiment") or {}
    fg             = cached_sent.get("fg_index", state.get("fg_index", 50))
    sent_raw       = cached_sent.get("combined_raw", state.get("sentiment", 0.0))
    sent_kalman    = cached_sent.get("combined_smoothed", sent_raw)
    kalman_gain    = cached_sent.get("kalman_gain")

    # ── ATR ───────────────────────────────────────────────────────────────
    atr_mon        = state.get("atr_monitor") or {}
    atr_regime     = atr_mon.get("regime", "?") if isinstance(atr_mon, dict) else "?"
    atr_val        = atr_mon.get("last_atr", 0.0) if isinstance(atr_mon, dict) else 0.0

    # ── Metrics (block rate, orders) ─────────────────────────────────────
    metrics        = state.get("metrics") or {}
    block_rate     = metrics.get("block_rate", 0.0) if isinstance(metrics, dict) else 0.0
    orders_paper   = metrics.get("orders_paper", 0) if isinstance(metrics, dict) else 0
    orders_live    = metrics.get("orders_live", 0) if isinstance(metrics, dict) else 0

    lines = [
        f"📊 <b>Kalshi Portfolio</b> ({ts})",
        f"{mode_icon} Mode: <b>{effective_mode}</b> (TradeMode={trade_mode} lane_live={lane_live}){kill_str}",
        f"Lifecycle: <b>{lc_state}</b>",
        f"Equity: <b>${equity:.2f}</b> | PnL: <b>${daily_pnl:+.2f}</b> | DD: {dd*100:.1f}%",
        f"Losses streak: {consec_losses} | Block rate: {block_rate*100:.0f}%",
        f"FG: {fg} | Sent raw: {sent_raw:+.2f} | Kalman: {sent_kalman:+.2f}"
        + (f" (gain={kalman_gain:.2f})" if kalman_gain is not None else ""),
        f"ATR regime: <b>{atr_regime}</b>" + (f" ({atr_val:.4f})" if atr_val else ""),
        f"Orders: paper={orders_paper} live={orders_live}",
    ]

    # ── Open positions ────────────────────────────────────────────────────
    positions = state.get("positions", [])
    if positions:
        lines.append("")
        lines.append("Open positions:")
        for p in positions:
            lines.append(
                f"  • {p.get('ticker','?')} {p.get('side','?')} "
                f"size=${p.get('size', 0):.2f} pnl=${p.get('pnl', 0):+.2f}"
            )

    # ── Phase ─────────────────────────────────────────────────────────────
    phase = state.get("phase")
    if phase:
        lines.append(f"Phase: {phase}")

    return await send_alert("\n".join(lines))


async def dashboard_loop(
    state_provider,
    interval_sec: float = 60.0,
) -> None:
    """
    Periodically call state_provider() and send a Telegram dashboard.

    Args:
        state_provider: Zero-arg callable returning a state dict.
                        Can be synchronous or async.
        interval_sec:   Seconds between snapshots (default 60).

    Usage:
        import asyncio
        asyncio.create_task(dashboard_loop(lane.get_status, interval_sec=120))
    """
    import asyncio
    import inspect
    while True:
        try:
            state = state_provider()
            if inspect.isawaitable(state):
                state = await state
            await send_portfolio_dashboard(state)
        except Exception as exc:
            logger.warning("dashboard_loop error: %s", exc)
        await asyncio.sleep(interval_sec)


async def send_circuit_breaker_alert(
    reason: str,
    consec_losses: int,
    asset: str = "BTC",
    timeframe: str = "15m",
) -> bool:
    """Send a loss-streak circuit-breaker alert."""
    msg = (
        f"⛔ Circuit breaker: {asset}:{timeframe} paused — "
        f"{consec_losses} consecutive losses ({reason})"
    )
    return await send_alert(
        msg,
        payload={
            "event": "circuit_breaker",
            "reason": reason,
            "consec_losses": consec_losses,
            "asset": asset,
            "timeframe": timeframe,
        },
    )
