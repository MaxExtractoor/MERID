"""
Structured Telegram notifications for the Kalshi Continuous Trader.

Design goals:
  1. **Useful, not spammy** — batch fills per cycle into one message; send
     cycle digests only every N cycles (configurable).
  2. **Actionable detail** — show ticker, side, price, contracts, fees, edge,
     running PnL, drawdown, positions, and vol band.
  3. **Anti-spam** — uses the existing rate-limited ``tg_send`` from
     ``merid.alerts.webhook_client`` (10 s buffer + backoff).
  4. **Lifecycle events** — start, stop, halt, resume sent immediately.

Usage (from KalshiContinuousTrader):
    from merid.alerts.trade_notifier import TradeNotifier
    self._notifier = TradeNotifier(digest_every_n_cycles=4)
    ...
    self._notifier.record_fill(...)
    self._notifier.flush_cycle(cycle, bankroll_snapshot)
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FillRecord:
    """One order fill within a cycle."""
    ticker: str
    side: str            # "yes" / "no"
    contracts: int
    price_cents: int
    fee_cents: int
    edge: float
    status: str          # "executed" / "resting"
    order_id: str = ""


@dataclass
class CycleDigest:
    """Aggregated stats for a single trading cycle."""
    cycle: int
    balance_cents: int
    portfolio_cents: int
    total_value_cents: int
    peak_cents: int
    drawdown_pct: float
    pnl_cents: int
    fee_drag_pct: float
    vol_band: str
    annualized_vol_pct: float
    orders_placed: int
    orders_filled: int
    positions: Dict[str, int] = field(default_factory=dict)
    fills: List[FillRecord] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""
    dry_run: bool = False
    fee_drag_tightening: bool = False


# ---------------------------------------------------------------------------
# Formatters (HTML for Telegram)
# ---------------------------------------------------------------------------

def _cents_to_usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _format_fill(f: FillRecord) -> str:
    icon = "📈" if f.side.lower() == "yes" else "📉"
    status_icon = "✅" if f.status == "executed" else "⏳"
    return (
        f"  {status_icon}{icon} <b>{f.side.upper()}</b> {f.contracts}x "
        f"<code>{f.ticker}</code> @ {f.price_cents}¢  "
        f"edge={f.edge:.3f}  fee={f.fee_cents}¢"
    )


def _format_cycle_digest(d: CycleDigest) -> str:
    """Format a cycle digest into a compact Telegram message."""
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    mode = "🧪 DRY" if d.dry_run else "🟢 LIVE"
    halt_str = f"\n⛔ <b>HALTED:</b> {d.halt_reason}" if d.halted else ""
    tight_str = " ⚡TIGHT" if d.fee_drag_tightening else ""

    pnl_icon = "🟢" if d.pnl_cents >= 0 else "🔴"
    dd_icon = "⚠️" if d.drawdown_pct > 3.0 else ""

    lines = [
        f"📊 <b>Cycle {d.cycle}</b> — {mode} ({ts})",
        f"",
        f"💰 Balance: <b>{_cents_to_usd(d.balance_cents)}</b> "
        f"| Total: <b>{_cents_to_usd(d.total_value_cents)}</b> "
        f"(peak {_cents_to_usd(d.peak_cents)})",
        f"{pnl_icon} PnL: <b>{_cents_to_usd(d.pnl_cents)}</b> "
        f"| {dd_icon}DD: {d.drawdown_pct:.1f}%",
        f"📉 Fee drag: {d.fee_drag_pct:.1f}%{tight_str} "
        f"| Vol: {d.vol_band} ({d.annualized_vol_pct:.0f}%)",
    ]

    # Fills this cycle
    if d.fills:
        executed = [f for f in d.fills if f.status == "executed"]
        resting = [f for f in d.fills if f.status == "resting"]
        lines.append("")
        lines.append(
            f"📋 <b>Orders:</b> {d.orders_placed} placed, "
            f"{d.orders_filled} filled"
        )
        for f in executed[:10]:
            lines.append(_format_fill(f))
        if resting:
            lines.append(f"  ⏳ +{len(resting)} resting")
    else:
        lines.append("")
        lines.append(f"📋 No orders this cycle")

    # Positions
    if d.positions:
        lines.append("")
        lines.append(f"💼 <b>Positions</b> ({sum(d.positions.values())} contracts)")
        for ticker, qty in sorted(d.positions.items()):
            if qty != 0:
                lines.append(f"  • <code>{ticker}</code>: {qty}")
    else:
        lines.append("")
        lines.append("💼 No open positions")

    lines.append(halt_str)

    return "\n".join(lines)


def _format_fill_batch(fills: List[FillRecord], cycle: int, dry_run: bool) -> str:
    """Compact fill-only message for cycles between digests."""
    if not fills:
        return ""
    mode = "🧪 DRY" if dry_run else "🟢 LIVE"
    ts = datetime.now(timezone.utc).strftime("%H:%M")
    executed = [f for f in fills if f.status == "executed"]
    resting = [f for f in fills if f.status == "resting"]
    total_cost = sum(f.price_cents * f.contracts for f in executed)
    total_fees = sum(f.fee_cents for f in executed)

    lines = [
        f"📋 <b>C{cycle}</b> {mode} — "
        f"{len(executed)} filled, {len(resting)} resting "
        f"(cost {_cents_to_usd(total_cost)}, fees {total_fees}¢) [{ts}]",
    ]
    for f in executed[:8]:
        lines.append(_format_fill(f))
    if len(executed) > 8:
        lines.append(f"  <i>... +{len(executed) - 8} more</i>")
    if resting:
        lines.append(f"  ⏳ {len(resting)} resting orders")
    return "\n".join(lines)


def _format_lifecycle(event: str, detail: str, cycle: int = 0) -> str:
    """Format a lifecycle event (start, stop, halt, resume)."""
    icons = {
        "start": "🚀",
        "stop": "🛑",
        "halt": "⛔",
        "resume": "▶️",
        "error": "❌",
    }
    icon = icons.get(event, "ℹ️")
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    cycle_str = f" (cycle {cycle})" if cycle else ""
    return f"{icon} <b>Continuous Trader {event.upper()}</b>{cycle_str}\n{detail}\n🕐 {ts}"


# ---------------------------------------------------------------------------
# TradeNotifier — accumulates fills, flushes per cycle
# ---------------------------------------------------------------------------

class TradeNotifier:
    """Accumulates trade events and sends structured Telegram messages.

    Args:
        digest_every_n_cycles: Full digest every N cycles (default 4 = ~1 hour
            at 15-min cadence).  Between digests, only fill summaries are sent
            (and only when there are actual fills).
        quiet_cycles:  If True, skip sending anything on cycles with zero fills
            between digest cycles.  Digests are always sent.
    """

    def __init__(
        self,
        digest_every_n_cycles: int = 4,
        quiet_cycles: bool = True,
    ):
        self.digest_every = max(1, digest_every_n_cycles)
        self.quiet_cycles = quiet_cycles

        # Per-cycle accumulator
        self._pending_fills: List[FillRecord] = []

    # ── Recording (call from _run_cycle) ─────────────────────────────

    def record_fill(
        self,
        ticker: str,
        side: str,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        edge: float,
        status: str,
        order_id: str = "",
    ) -> None:
        """Record a fill/order for the current cycle."""
        self._pending_fills.append(FillRecord(
            ticker=ticker,
            side=side,
            contracts=contracts,
            price_cents=price_cents,
            fee_cents=fee_cents,
            edge=edge,
            status=status,
            order_id=order_id,
        ))

    # ── Flush (call at end of _run_cycle) ────────────────────────────

    def flush_cycle(self, digest: CycleDigest) -> None:
        """Flush accumulated fills and optionally send a cycle digest.

        Sends via ``tg_send`` (rate-limited, buffered).  Never blocks the
        trading loop — fires and forgets.
        """
        fills = list(self._pending_fills)
        self._pending_fills.clear()
        digest.fills = fills

        is_digest_cycle = digest.cycle % self.digest_every == 0

        if is_digest_cycle:
            msg = _format_cycle_digest(digest)
        elif fills:
            msg = _format_fill_batch(fills, digest.cycle, digest.dry_run)
        elif self.quiet_cycles:
            return  # Nothing to report
        else:
            return

        _fire_and_forget(msg)

    # ── Lifecycle events (immediate) ─────────────────────────────────

    def notify_start(self, config_summary: str, cycle: int = 0) -> None:
        """Send trader start notification."""
        _fire_and_forget(
            _format_lifecycle("start", config_summary, cycle),
            immediate=True,
        )

    def notify_stop(self, summary: str, cycle: int = 0) -> None:
        """Send trader stop notification."""
        _fire_and_forget(
            _format_lifecycle("stop", summary, cycle),
            immediate=True,
        )

    def notify_halt(self, reason: str, cycle: int = 0) -> None:
        """Send halt notification (immediate — critical)."""
        _fire_and_forget(
            _format_lifecycle("halt", reason, cycle),
            immediate=True,
        )

    def notify_state_change(
        self, from_state: str, to_state: str, reason: str, cycle: int = 0
    ) -> None:
        """Send state machine transition notification.

        Args:
            from_state: Previous trading state (e.g., "scalp_only")
            to_state: New trading state (e.g., "scalp_hedge")
            reason: Transition reason code (e.g., "drawdown_hedge_active")
            cycle: Current cycle number
        """
        icons = {
            "scalp_only": "📈",
            "scalp_hedge": "🛡️",
            "hedge_only": "⚠️",
            "flat": "🛑",
        }
        from_icon = icons.get(from_state, "ℹ️")
        to_icon = icons.get(to_state, "ℹ️")
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        cycle_str = f" (cycle {cycle})" if cycle else ""

        # Format reason for readability
        reason_display = reason.replace("_", " ").upper()

        text = (
            f"{to_icon} <b>STATE CHANGE</b>{cycle_str}\n"
            f"{from_icon} {from_state} → {to_icon} {to_state}\n"
            f"<i>Reason: {reason_display}</i>\n"
            f"🕐 {ts}"
        )
        _fire_and_forget(text, immediate=True)

    def notify_hedge_fill(
        self,
        ticker: str,
        side: str,
        count: int,
        price_cents: int,
        hedge_reason: str,
        related_alpha_ticker: Optional[str] = None,
        cycle: int = 0,
    ) -> None:
        """Send hedge fill notification with differentiated formatting (Task 4).
        
        Hedge fills are visually distinct from alpha fills to prevent confusion.
        
        Args:
            ticker: Market ticker (e.g., "KXBTC-15M")
            side: "yes" or "no"
            count: Number of contracts filled
            price_cents: Fill price in cents
            hedge_reason: Reason for hedge (e.g., "cross_asset_SOL_to_BTC")
            related_alpha_ticker: The alpha position being hedged (optional)
            cycle: Current cycle number
        """
        from datetime import timezone
        
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        cycle_str = f" (cycle {cycle})" if cycle else ""
        
        # Format price as dollars.cents
        price_dollars = price_cents / 100.0
        
        # Determine direction emoji
        if side == "yes":
            direction = "📈 LONG"  # Buying YES = bullish hedge
        else:
            direction = "📉 SHORT"  # Buying NO = bearish hedge
        
        # Format reason for readability
        reason_display = hedge_reason.replace("_", " ").upper()
        
        text = (
            f"🛡️ <b>HEDGE FILL</b>{cycle_str}\n"
            f"{direction} {ticker}\n"
            f"Size: {count} @ ${price_dollars:.2f}\n"
            f"<i>Reason: {reason_display}</i>\n"
        )
        
        if related_alpha_ticker:
            text += f"<i>Hedging: {related_alpha_ticker}</i>\n"
        
        text += f"🕐 {ts}"
        
        _fire_and_forget(text, immediate=True)

    def notify_error(self, error: str, cycle: int = 0) -> None:
        """Send error notification."""
        _fire_and_forget(
            _format_lifecycle("error", error, cycle),
            immediate=True,
        )


# ---------------------------------------------------------------------------
# Fire-and-forget helper
# ---------------------------------------------------------------------------

def _fire_and_forget(text: str, immediate: bool = False) -> None:
    """Schedule a Telegram send without blocking the caller."""
    try:
        from merid.alerts.webhook_client import tg_send
    except ImportError:
        logger.debug("trade_notifier: webhook_client not available")
        return

    def _on_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.debug("trade_notifier: tg_send failed: %s", exc)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(tg_send(text, force_immediate=immediate), name="tg-notify")
        task.add_done_callback(_on_done)
    except RuntimeError:
        # No running loop (sync context) — try sync fallback
        try:
            from merid.alerts.webhook_client import tg_send_sync
            tg_send_sync(text)
        except Exception:
            logger.debug("trade_notifier: sync fallback failed")
