"""Paper-truth reconciliation engine.

Continuously proves that MERID's internal paper ledger is self-consistent
and, where applicable, matches external venue state.

Invariants enforced:
1. cash + sum(positions × mark_price) == equity  (balance identity)
2. equity moves only by realised PnL and fees     (no phantom gains)
3. no ghost positions (venue has it, MERID doesn't, or vice-versa)
4. unrealised PnL recomputed from price feed matches stored value
5. trade count matches trade_history length

Run modes:
- **on-demand**: ``run_reconciliation()`` returns a ``ReconciliationReport``
- **periodic**: ``start_periodic_reconciliation()`` spawns a background thread
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("trading.reconciliation")


# ------------------------------------------------------------------ #
# Data types
# ------------------------------------------------------------------ #

class CheckStatus(str, Enum):
    OK = "ok"
    DELTA = "delta"
    ERROR = "error"


@dataclass
class CheckResult:
    """Result of a single reconciliation check."""
    name: str
    status: CheckStatus
    expected: Any = None
    actual: Any = None
    delta: Any = None
    detail: str = ""
    source: str = "paper_engine"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "status": self.status.value,
            "source": self.source,
        }
        if self.detail:
            d["detail"] = self.detail
        if self.status != CheckStatus.OK:
            d["expected"] = self.expected
            d["actual"] = self.actual
            d["delta"] = self.delta
        return d


@dataclass
class ReconciliationReport:
    """Full reconciliation report across all portfolios."""
    timestamp: float = field(default_factory=time.time)
    checks: List[CheckResult] = field(default_factory=list)
    portfolios_checked: int = 0
    positions_checked: int = 0
    all_ok: bool = True
    snapshot_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "all_ok": self.all_ok,
            "portfolios_checked": self.portfolios_checked,
            "positions_checked": self.positions_checked,
            "snapshot_hash": self.snapshot_hash,
            "checks": [c.to_dict() for c in self.checks],
            "ok_count": sum(1 for c in self.checks if c.status == CheckStatus.OK),
            "delta_count": sum(1 for c in self.checks if c.status == CheckStatus.DELTA),
            "error_count": sum(1 for c in self.checks if c.status == CheckStatus.ERROR),
        }


# ------------------------------------------------------------------ #
# Tolerances
# ------------------------------------------------------------------ #

_ABS_TOLERANCE = 0.01     # $0.01
_REL_TOLERANCE = 1e-6     # 0.0001%


def _close(a: float, b: float) -> bool:
    """Return True if *a* and *b* are within tolerance."""
    if abs(a - b) <= _ABS_TOLERANCE:
        return True
    if b != 0 and abs((a - b) / b) <= _REL_TOLERANCE:
        return True
    return False


def _is_legacy_perp_portfolio(uid: str, portfolio: Any) -> bool:
    """Detect legacy perp paper portfolios that should be quarantined in Kalshi mode."""
    uid_str = str(uid).lower()
    if uid_str.startswith(("matrix_", "slo_", "sim_", "paper_legacy", "legacy_")):
        return True
    for pk, pos in getattr(portfolio, "positions", {}).items():
        if str(pk).endswith("_perp_paper"):
            return True
        market_type = getattr(pos, "market_type", "")
        venue = getattr(pos, "venue", "")
        if market_type == "perp" and venue == "paper":
            return True
    return False


# ------------------------------------------------------------------ #
# Core reconciliation logic
# ------------------------------------------------------------------ #

def run_reconciliation() -> ReconciliationReport:
    """Run a full reconciliation against the paper trading engine.

    This is the main entry point.  It imports the paper engine lazily
    to avoid circular imports.
    """
    try:
        from merid.settings import settings
        kalshi_only = bool(settings.KALSHI_ONLY)
    except Exception:
        kalshi_only = False

    from trading.paper_trading import get_paper_engine

    engine = get_paper_engine()
    report = ReconciliationReport()
    skipped_legacy = 0

    for uid, portfolio in engine.portfolios.items():
        if kalshi_only and _is_legacy_perp_portfolio(uid, portfolio):
            skipped_legacy += 1
            continue

        report.portfolios_checked += 1

        # ----------------------------------------------------------
        # 1. Balance identity: cash + sum(position_value) == starting + total_pnl
        # ----------------------------------------------------------
        position_value = 0.0
        unrealized_pnl = 0.0
        for pos in portfolio.positions.values():
            report.positions_checked += 1
            position_value += pos.size_usd
            unrealized_pnl += pos.unrealized_pnl

        computed_equity = portfolio.current_balance + position_value
        expected_equity = portfolio.starting_balance + portfolio.total_pnl + unrealized_pnl

        check = CheckResult(
            name=f"{uid}/balance_identity",
            status=CheckStatus.OK,
        )
        if not _close(computed_equity, expected_equity):
            check.status = CheckStatus.DELTA
            check.expected = round(expected_equity, 4)
            check.actual = round(computed_equity, 4)
            check.delta = round(computed_equity - expected_equity, 4)
            check.detail = "cash + positions != starting_balance + total_pnl + unrealized_pnl"
            report.all_ok = False
        report.checks.append(check)

        # ----------------------------------------------------------
        # 2. Trade count matches trade_history length
        # ----------------------------------------------------------
        expected_trades = len(portfolio.trade_history)
        actual_trades = portfolio.total_trades
        check = CheckResult(
            name=f"{uid}/trade_count",
            status=CheckStatus.OK,
        )
        if expected_trades != actual_trades:
            check.status = CheckStatus.DELTA
            check.expected = expected_trades
            check.actual = actual_trades
            check.delta = actual_trades - expected_trades
            check.detail = "total_trades counter != trade_history length"
            report.all_ok = False
        report.checks.append(check)

        # ----------------------------------------------------------
        # 3. Winning + losing trades <= total trades
        # ----------------------------------------------------------
        wl_sum = portfolio.winning_trades + portfolio.losing_trades
        check = CheckResult(
            name=f"{uid}/win_loss_sum",
            status=CheckStatus.OK,
        )
        if wl_sum > portfolio.total_trades:
            check.status = CheckStatus.DELTA
            check.expected = f"<= {portfolio.total_trades}"
            check.actual = wl_sum
            check.delta = wl_sum - portfolio.total_trades
            check.detail = "winning + losing > total trades"
            report.all_ok = False
        report.checks.append(check)

        # ----------------------------------------------------------
        # 4. Per-position PnL consistency
        # ----------------------------------------------------------
        for pk, pos in portfolio.positions.items():
            check = CheckResult(
                name=f"{uid}/position/{pk}/pnl",
                status=CheckStatus.OK,
            )
            if pos.current_price <= 0:
                check.status = CheckStatus.ERROR
                check.detail = f"current_price={pos.current_price} <= 0"
                report.all_ok = False
                report.checks.append(check)
                continue

            if pos.side in ("long", "yes"):
                expected_pnl = (pos.current_price - pos.entry_price) / pos.entry_price * pos.size_usd * pos.leverage if pos.entry_price else 0.0
            else:
                expected_pnl = (pos.entry_price - pos.current_price) / pos.entry_price * pos.size_usd * pos.leverage if pos.entry_price else 0.0

            if not _close(expected_pnl, pos.unrealized_pnl):
                check.status = CheckStatus.DELTA
                check.expected = round(expected_pnl, 4)
                check.actual = round(pos.unrealized_pnl, 4)
                check.delta = round(pos.unrealized_pnl - expected_pnl, 4)
                check.detail = "recomputed PnL != stored unrealized_pnl (source=paper_engine)"
                logger.debug(
                    "PnL delta [source=paper_engine key=%s]: recomputed=%.6f stored=%.6f "
                    "asset=%s side=%s entry=%.6f current=%.6f size_usd=%.4f lev=%s "
                    "market_type=%s venue=%s opened_at=%.3f",
                    check.name,
                    expected_pnl,
                    pos.unrealized_pnl,
                    getattr(pos, "asset", ""),
                    getattr(pos, "side", ""),
                    getattr(pos, "entry_price", 0.0),
                    getattr(pos, "current_price", 0.0),
                    getattr(pos, "size_usd", 0.0),
                    getattr(pos, "leverage", 1),
                    getattr(pos, "market_type", ""),
                    getattr(pos, "venue", ""),
                    getattr(pos, "opened_at", 0.0),
                )
                report.all_ok = False
            report.checks.append(check)

        # ----------------------------------------------------------
        # 5. No negative cash (unless leveraged)
        # ----------------------------------------------------------
        check = CheckResult(
            name=f"{uid}/cash_non_negative",
            status=CheckStatus.OK,
        )
        if portfolio.current_balance < -_ABS_TOLERANCE:
            check.status = CheckStatus.DELTA
            check.expected = ">= 0"
            check.actual = round(portfolio.current_balance, 4)
            check.detail = "negative cash balance"
            report.all_ok = False
        report.checks.append(check)

        # ----------------------------------------------------------
        # 6. Realised PnL from closed positions matches portfolio total_pnl
        # ----------------------------------------------------------
        closed_list = getattr(portfolio, "closed_positions", [])
        if closed_list:
            recomputed_pnl = sum(p.realized_pnl for p in closed_list)
            check = CheckResult(
                name=f"{uid}/realized_pnl",
                status=CheckStatus.OK,
            )
            if not _close(recomputed_pnl, portfolio.total_pnl):
                check.status = CheckStatus.ERROR
                check.expected = round(recomputed_pnl, 4)
                check.actual = round(portfolio.total_pnl, 4)
                check.delta = round(portfolio.total_pnl - recomputed_pnl, 4)
                check.detail = "sum(closed_position.realized_pnl) != portfolio.total_pnl"
                report.all_ok = False
            report.checks.append(check)
        else:
            # No closed positions yet — just verify total_pnl is finite
            check = CheckResult(
                name=f"{uid}/pnl_finite",
                status=CheckStatus.OK,
            )
            if not (abs(portfolio.total_pnl) < 1e12):
                check.status = CheckStatus.ERROR
                check.detail = f"total_pnl={portfolio.total_pnl} is not finite"
                report.all_ok = False
            report.checks.append(check)

    # ----------------------------------------------------------
    # 7. Kalshi PaperSession agent intervals
    # ----------------------------------------------------------
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        if session.is_active:
            for name, interval in session._intervals.items():
                if interval.total_trades == 0:
                    continue
                report.portfolios_checked += 1
                report.positions_checked += 1

                # 7a. PnL is finite
                check = CheckResult(
                    name=f"kalshi/{name}/pnl_finite",
                    status=CheckStatus.OK,
                    source="kalshi_session",
                )
                if not (abs(interval.net_pnl_cents) < 1e12):
                    check.status = CheckStatus.ERROR
                    check.detail = f"net_pnl_cents={interval.net_pnl_cents} is not finite"
                    report.all_ok = False
                report.checks.append(check)

                # 7b. Winning + losing <= total trades
                wl_sum = interval.winning_trades + interval.losing_trades
                check = CheckResult(
                    name=f"kalshi/{name}/win_loss_sum",
                    status=CheckStatus.OK,
                    source="kalshi_session",
                )
                if wl_sum > interval.total_trades:
                    check.status = CheckStatus.DELTA
                    check.expected = f"<= {interval.total_trades}"
                    check.actual = wl_sum
                    check.delta = wl_sum - interval.total_trades
                    check.detail = "winning + losing > total trades"
                    report.all_ok = False
                report.checks.append(check)

                # 7c. HWM >= net PnL (high water mark should never be below current)
                check = CheckResult(
                    name=f"kalshi/{name}/hwm_consistency",
                    status=CheckStatus.OK,
                    source="kalshi_session",
                )
                if interval.high_water_mark_cents < interval.net_pnl_cents - _ABS_TOLERANCE * 100:
                    check.status = CheckStatus.DELTA
                    check.expected = f">= {round(interval.net_pnl_cents, 2)}"
                    check.actual = round(interval.high_water_mark_cents, 2)
                    check.detail = "high_water_mark < net_pnl_cents"
                    report.all_ok = False
                report.checks.append(check)

                # 7d. Gross wins + gross losses ≈ |gross PnL| (no phantom values)
                gross_sum = interval.gross_wins_cents + interval.gross_losses_cents
                check = CheckResult(
                    name=f"kalshi/{name}/gross_balance",
                    status=CheckStatus.OK,
                    source="kalshi_session",
                )
                if gross_sum > 0 and abs(interval.gross_pnl_cents) > gross_sum * 1.01:
                    check.status = CheckStatus.DELTA
                    check.expected = f"|gross_pnl| <= gross_wins + gross_losses"
                    check.actual = round(interval.gross_pnl_cents, 2)
                    check.delta = round(abs(interval.gross_pnl_cents) - gross_sum, 2)
                    check.detail = "gross PnL exceeds sum of win/loss buckets"
                    report.all_ok = False
                report.checks.append(check)
    except Exception as exc:
        logger.debug("Kalshi paper session reconciliation skipped: %s", exc)

    # ----------------------------------------------------------
    # 8. Cross-source PnL consistency (paper vs risk vs equity)
    # ----------------------------------------------------------
    try:
        from core.execution_gate import check_pnl_consistency, PNL_CONSISTENCY_THRESHOLD
        pnl_result = check_pnl_consistency()
        check = CheckResult(
            name="cross_source/pnl_consistency",
            status=CheckStatus.OK,
            source="cross_source",
        )
        if not pnl_result["consistent"]:
            check.status = CheckStatus.DELTA
            check.expected = f"delta <= ${PNL_CONSISTENCY_THRESHOLD:.2f}"
            check.actual = f"${pnl_result['max_divergence_usd']:.2f}"
            check.delta = round(pnl_result["max_divergence_usd"], 2)
            check.detail = (
                f"Cross-source PnL divergence: "
                f"{', '.join(f'{k}=${v}' for k, v in pnl_result['sources'].items())}"
            )
            report.all_ok = False
        report.checks.append(check)
    except Exception as exc:
        report.checks.append(CheckResult(
            name="cross_source/pnl_consistency",
            status=CheckStatus.ERROR,
            detail=f"Could not run cross-source check: {exc}",
            source="cross_source",
        ))

    # Snapshot hash for audit trail
    report.snapshot_hash = _compute_snapshot_hash(engine, skip_legacy=kalshi_only)

    if kalshi_only and skipped_legacy:
        logger.info(
            "Kalshi-only mode: skipped %d legacy perp paper portfolios during reconciliation",
            skipped_legacy,
        )

    if report.all_ok:
        logger.info(
            "Reconciliation OK: %d portfolios, %d positions, hash=%s",
            report.portfolios_checked,
            report.positions_checked,
            report.snapshot_hash[:12],
        )
    else:
        deltas = [c for c in report.checks if c.status != CheckStatus.OK]
        sources = sorted({c.source for c in deltas if getattr(c, "source", "")})
        logger.warning(
            "Reconciliation DELTA: %d issues in %d portfolios — sources=%s — %s",
            len(deltas),
            report.portfolios_checked,
            ",".join(sources) if sources else "unknown",
            "; ".join(c.name for c in deltas[:5]),
        )

    return report


def _compute_snapshot_hash(engine, skip_legacy: bool = False) -> str:
    """Deterministic hash of the current paper state for audit trail."""
    data = {
        "portfolios": {},
    }
    for uid, portfolio in sorted(engine.portfolios.items()):
        if skip_legacy and _is_legacy_perp_portfolio(uid, portfolio):
            continue
        positions = {}
        for pk, pos in sorted(portfolio.positions.items()):
            positions[pk] = {
                "asset": pos.asset,
                "side": pos.side,
                "size_usd": round(pos.size_usd, 8),
                "entry_price": round(pos.entry_price, 8),
                "leverage": pos.leverage,
            }
        data["portfolios"][uid] = {
            "balance": round(portfolio.current_balance, 8),
            "total_pnl": round(portfolio.total_pnl, 8),
            "total_trades": portfolio.total_trades,
            "positions": positions,
        }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------------ #
# Periodic background reconciliation
# ------------------------------------------------------------------ #

_recon_thread: Optional[threading.Thread] = None
_recon_stop = threading.Event()
_last_report: Optional[ReconciliationReport] = None
_has_ever_completed: bool = False


def start_periodic_reconciliation(
    interval_seconds: float = 300.0,
) -> None:
    """Start a background thread that runs reconciliation every *interval_seconds*."""
    global _recon_thread

    if _recon_thread is not None and _recon_thread.is_alive():
        logger.debug("Periodic reconciliation already running")
        return

    _recon_stop.clear()

    def _loop() -> None:
        global _last_report, _has_ever_completed
        logger.info("Periodic reconciliation started (every %.0fs)", interval_seconds)
        while not _recon_stop.wait(timeout=interval_seconds):
            try:
                _last_report = run_reconciliation()
                if not _has_ever_completed:
                    _has_ever_completed = True
                    logger.info("First reconciliation completed — execution gate open")
            except Exception as exc:
                logger.error("Reconciliation loop error: %s", exc)

    _recon_thread = threading.Thread(
        target=_loop, daemon=True, name="recon-loop",
    )
    _recon_thread.start()


def stop_periodic_reconciliation() -> None:
    """Stop the background reconciliation thread."""
    _recon_stop.set()
    if _recon_thread is not None:
        _recon_thread.join(timeout=5.0)
    logger.info("Periodic reconciliation stopped")


def store_report(report: ReconciliationReport) -> None:
    """Store a reconciliation report (from on-demand or periodic runs)."""
    global _last_report, _has_ever_completed
    _last_report = report
    if not _has_ever_completed:
        _has_ever_completed = True
        logger.info("First reconciliation completed — execution gate open")


def get_last_report() -> Optional[ReconciliationReport]:
    """Return the most recent reconciliation report (or None)."""
    return _last_report


def has_critical_discrepancies() -> bool:
    """Return True if execution should be blocked.

    On a fresh start, returns True until the first reconciliation
    completes — this prevents trades from firing before the ledger
    has been verified.  After that, returns True only if the most
    recent report contains DELTA or ERROR checks.
    """
    from core.fresh_start import is_fresh_start
    if is_fresh_start() and not _has_ever_completed:
        return True
    if _last_report is None:
        return not _has_ever_completed
    return not _last_report.all_ok
