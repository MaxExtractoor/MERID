#!/usr/bin/env python3
"""MERID Kalshi Execution Readiness Check.

Run BEFORE starting KalshiContinuousTrader (or uvicorn) to confirm the system is
configured and reachable.  Exits 0 on full green, 1 on any FAIL.

Recommended operator sequence before restart
    1. Load the correct environment (demo vs live): merge ``.env`` with the
       appropriate profile (e.g. ``.env.kalshi-sim`` for demo, ``.env.kalshi-live-prod``
       for live — never commit secrets).
    2. Run ``python scripts/kalshi_go_live_preflight.py`` (add ``--reset-kill-switch``
       if you must clear persisted kill state on disk).
    3. Restart the server.
    4. Allow one reconciliation / catalog warmup cycle; some WARN rows are normal
       until the first venue reconciliation completes.

``--strict`` exits 1 on any WARN (use for a "all green" go-live). Routine restarts
often report READY WITH WARNINGS (cold catalog, first-run reconciliation).

Usage::

    python MERID_KALSHI_EXECUTION_READINESS_CHECK.py
    python MERID_KALSHI_EXECUTION_READINESS_CHECK.py --strict   # WARN → exit 1

Checks (8 stages × all cells):
    1. ENV           — required env vars present and sane
    2. KILL_SWITCH   — data/risk_kill_switch.json not active=true
    3. IMPORTS       — critical modules importable
    4. GRID          — expected 5-asset × 5-timeframe series tickers defined
    5. EXECUTION_GATE — gate state is not permanently BLOCKED
    6. RISK_CAPS     — TraderConfig min_edge / max_risk / bankroll sane
    7. CATALOG       — market_catalog accessible, counts per series
    8. LOG           — log file path writable

Each check is printed as  [PASS] / [WARN] / [FAIL] with a reason.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from decimal import Decimal
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Colour helpers (no external deps)
# ---------------------------------------------------------------------------
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _g(s: str) -> str: return f"{_GREEN}{s}{_RESET}"
def _y(s: str) -> str: return f"{_YELLOW}{s}{_RESET}"
def _r(s: str) -> str: return f"{_RED}{s}{_RESET}"
def _b(s: str) -> str: return f"{_BOLD}{s}{_RESET}"


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------
class CheckResult:
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"

    def __init__(self) -> None:
        self._rows: List[Tuple[str, str, str]] = []  # (stage, level, detail)

    def add(self, stage: str, level: str, detail: str) -> None:
        self._rows.append((stage, level, detail))

    def ok(self, stage: str, detail: str) -> None:
        self.add(stage, self.PASS, detail)

    def warn(self, stage: str, detail: str) -> None:
        self.add(stage, self.WARN, detail)

    def fail(self, stage: str, detail: str) -> None:
        self.add(stage, self.FAIL, detail)

    def print_report(self) -> None:
        print()
        print(_b("=" * 66))
        print(_b("  MERID Kalshi Execution Readiness Report"))
        print(_b("=" * 66))
        for stage, level, detail in self._rows:
            if level == self.PASS:
                badge = _g("[PASS]")
            elif level == self.WARN:
                badge = _y("[WARN]")
            else:
                badge = _r("[FAIL]")
            stage_padded = f"{stage:<22}"
            print(f"  {badge}  {stage_padded}  {detail}")
        print(_b("=" * 66))
        fails  = sum(1 for _, l, _ in self._rows if l == self.FAIL)
        warns  = sum(1 for _, l, _ in self._rows if l == self.WARN)
        passes = sum(1 for _, l, _ in self._rows if l == self.PASS)
        if fails:
            print(_r(_b(f"  RESULT: NOT READY  ({fails} FAIL, {warns} WARN, {passes} PASS)")))
        elif warns:
            print(_y(_b(f"  RESULT: READY WITH WARNINGS  ({warns} WARN, {passes} PASS)")))
        else:
            print(_g(_b(f"  RESULT: FULLY READY  ({passes} PASS)")))
        print(_b("=" * 66))
        print()

    @property
    def has_failures(self) -> bool:
        return any(l == self.FAIL for _, l, _ in self._rows)

    @property
    def has_warnings(self) -> bool:
        return any(l == self.WARN for _, l, _ in self._rows)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_env(res: CheckResult) -> None:
    """1. ENV — required env vars present and sane."""
    # Kalshi environment
    api_url = os.getenv("KALSHI_API_URL", "")
    if not api_url:
        res.warn("ENV/KALSHI_API_URL", "not set — will fall back to demo endpoint default")
    elif "trading-api.kalshi.com" in api_url:
        live_confirm = os.getenv("KALSHI_CONFIRM_LIVE", "")
        if live_confirm != "1":
            res.fail(
                "ENV/KALSHI_CONFIRM_LIVE",
                "LIVE endpoint detected but KALSHI_CONFIRM_LIVE!=1 — startup will abort",
            )
        else:
            res.ok("ENV/KALSHI_API_URL", f"LIVE endpoint confirmed ({api_url[:60]})")
    else:
        res.ok("ENV/KALSHI_API_URL", f"demo/staging endpoint ({api_url[:60]})")

    # Demo mode guard
    use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower()
    if use_demo == "true":
        res.ok("ENV/KALSHI_USE_DEMO", "demo mode ON (safe default)")
    else:
        res.warn("ENV/KALSHI_USE_DEMO", "demo mode OFF — live order submission enabled")

    # Auth
    key_id   = os.getenv("KALSHI_API_KEY_ID", "")
    key_file = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_id:
        res.warn("ENV/KALSHI_API_KEY_ID", "not set — unauthenticated requests will fail")
    else:
        res.ok("ENV/KALSHI_API_KEY_ID", f"set ({key_id[:8]}…)")

    if key_file and not Path(key_file).exists():
        res.fail("ENV/KALSHI_PRIVATE_KEY_PATH", f"file not found: {key_file}")
    elif not key_file:
        res.warn("ENV/KALSHI_PRIVATE_KEY_PATH", "not set — RSA signing unavailable")
    else:
        res.ok("ENV/KALSHI_PRIVATE_KEY_PATH", f"file exists ({key_file})")

    # Bankroll
    bankroll = os.getenv("KALSHI_TRADER_BANKROLL", "")
    if not bankroll:
        res.warn("ENV/KALSHI_TRADER_BANKROLL", "not set — CT will warn and use 0 as floor")
    else:
        try:
            v = Decimal(bankroll)
            if v <= 0:
                res.fail("ENV/KALSHI_TRADER_BANKROLL", f"must be positive, got {v}")
            else:
                res.ok("ENV/KALSHI_TRADER_BANKROLL", f"${v:,.2f}")
        except Exception:
            res.fail("ENV/KALSHI_TRADER_BANKROLL", f"not a valid decimal: {bankroll!r}")

    # Price bands mode
    pb_mode = os.getenv("KALSHI_PRICE_BANDS_MODE", "off")
    if pb_mode == "off":
        res.ok("ENV/KALSHI_PRICE_BANDS_MODE", "off (disabled — all strikes admitted to edge filter)")
    elif pb_mode == "enforce":
        res.ok("ENV/KALSHI_PRICE_BANDS_MODE", "enforce (safe-fallback active — no bucket will be zeroed)")
    else:
        res.warn("ENV/KALSHI_PRICE_BANDS_MODE", f"unknown value {pb_mode!r} — will treat as 'off'")

    # Loop lag thresholds
    degrade_ms = os.getenv("KALSHI_LOOP_LAG_DEGRADE_MS", "500")
    halt_ms    = os.getenv("KALSHI_LOOP_LAG_HALT_MS", "2000")
    try:
        d, h = int(degrade_ms), int(halt_ms)
        if d >= h:
            res.fail("ENV/LOOP_LAG_THRESHOLDS", f"DEGRADE_MS ({d}) must be < HALT_MS ({h})")
        else:
            res.ok("ENV/LOOP_LAG_THRESHOLDS", f"degrade={d}ms halt={h}ms")
    except ValueError:
        res.fail("ENV/LOOP_LAG_THRESHOLDS", "non-integer KALSHI_LOOP_LAG_DEGRADE_MS or HALT_MS")


def check_kill_switch_persistence(res: CheckResult) -> None:
    """Fail fast if persisted kill-switch file would arm a halt on next process start.

    ``data/risk_kill_switch.json`` is runtime state (see ``data/README_risk_kill_switch.txt``),
    not a config knob. If it contains ``active: true``, ``RiskController`` restores a global
    kill at import time and the execution gate stays BLOCKED until an operator clears it
    (dashboard or ``risk_controller.reset('operator')``). CI also enforces that the
    committed JSON is never ``active: true``.
    """
    path = Path(os.environ.get("MERID_RISK_KS_FILE", "data/risk_kill_switch.json"))
    if not path.exists():
        res.ok("KILL_SWITCH/FILE", f"no file at {path} — starts disarmed")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("active"):
            res.fail(
                "KILL_SWITCH/FILE",
                f"{path} has active=true — execution gate will BLOCK on startup. "
                "Clear via dashboard (Mode & Safety) or run: "
                "py -c \"from merid.risk.kill_switches import risk_controller; "
                "risk_controller.reset('operator')\"",
            )
        else:
            res.ok("KILL_SWITCH/FILE", f"{path.name} active=false")
    except Exception as exc:
        res.fail("KILL_SWITCH/FILE", f"cannot read {path}: {exc}")


def check_imports(res: CheckResult) -> None:
    """2. IMPORTS — critical modules importable."""
    critical = [
        ("merid.formulas",                         "generate_correlation_id"),
        ("merid.event_venues.kalshi.market_filter", "select_near_spot_best_edge"),
        ("merid.event_venues.kalshi.market_catalog","get_market_catalog"),
        ("merid.event_venues.kalshi.client",        "KalshiVenueClient"),
        ("core.execution_gate",                     "check_execution_gate"),
        ("config.kalshi_universe",                  "KALSHI_CRYPTO_PRODUCTS"),
        ("config.kalshi_universe",                  "kalshi_ct_default_series_tickers"),
        ("merid.prediction.ua_ct_metrics",          "snapshot"),
    ]
    for mod, attr in critical:
        try:
            m = importlib.import_module(mod)
            if not hasattr(m, attr):
                res.fail(f"IMPORT/{mod}", f"module imported but missing {attr!r}")
            else:
                res.ok(f"IMPORT/{mod}", f"{attr} present")
        except Exception as exc:
            res.fail(f"IMPORT/{mod}", f"{type(exc).__name__}: {exc}")


def check_grid(res: CheckResult) -> None:
    """3. GRID — 5×5 asset/timeframe series tickers defined in config."""
    try:
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_ct_default_series_tickers

        ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        TFS    = ["15M", "1H", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL"]

        missing: List[str] = []
        for asset in ASSETS:
            for tf in TFS:
                key = f"{asset}_{tf}"
                if key not in KALSHI_CRYPTO_PRODUCTS:
                    missing.append(key)
                elif not KALSHI_CRYPTO_PRODUCTS[key]:
                    missing.append(f"{key}(empty)")

        if missing:
            res.fail("GRID/KALSHI_CRYPTO_PRODUCTS", f"missing cells: {missing}")
        else:
            total = len(KALSHI_CRYPTO_PRODUCTS)
            res.ok("GRID/KALSHI_CRYPTO_PRODUCTS", f"{total} cells defined (5 assets × 6 timeframes)")

        # CT default tickers (monthly/annual excluded intentionally)
        default_tickers = kalshi_ct_default_series_tickers()
        if len(default_tickers) < 20:
            res.warn(
                "GRID/CT_DEFAULT_TICKERS",
                f"only {len(default_tickers)} default tickers (<20) — some cells may be missing",
            )
        else:
            res.ok("GRID/CT_DEFAULT_TICKERS", f"{len(default_tickers)} active tickers (monthly/annual excluded)")

    except Exception as exc:
        res.fail("GRID", f"{type(exc).__name__}: {exc}")


def check_execution_gate(res: CheckResult) -> None:
    """4. EXECUTION_GATE — gate is not hard-BLOCKED."""
    try:
        from core.execution_gate import check_execution_gate
        gate = check_execution_gate()
        state = gate.gate_state
        reasons = "; ".join(r.message for r in (gate.reasons or [])) or "none"
        if state == "blocked":
            res.fail("EXECUTION_GATE", f"BLOCKED — reasons: {reasons}")
        elif state == "limited":
            res.warn("EXECUTION_GATE", f"LIMITED (reduce-only) — reasons: {reasons}")
        else:
            res.ok("EXECUTION_GATE", f"state={state} — {reasons}")
    except Exception as exc:
        res.warn("EXECUTION_GATE", f"could not query gate: {type(exc).__name__}: {exc}")


def check_risk_caps(res: CheckResult) -> None:
    """5. RISK_CAPS — active 15m profile risk parameters sane."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        adapter = get_active_profile()
        if adapter is None or not hasattr(adapter, "_profile"):
            res.warn("RISK_CAPS", "no active profile — skipping cap checks")
            return

        p = adapter._profile
        issues: List[str] = []

        # strategy_policy.min_edge sanity (profile stores as fraction, e.g. 0.05 = 5%)
        # kalshi_crypto_15m_v2 uses 1.5% as the global minimum edge, so allow >=1%.
        min_edge_floor = Decimal("0.01")
        min_edge = Decimal(str(getattr(p, "strategy_policy_min_edge", 0.0)))
        if min_edge < min_edge_floor:
            issues.append(f"strategy_policy_min_edge={min_edge} below floor {min_edge_floor}")

        # Kelly hard cap (fraction, e.g. 0.02 = 2%)
        kelly_hard_cap = float(getattr(p, "kelly_hard_cap", 0.0))
        if kelly_hard_cap <= 0 or kelly_hard_cap > 1.0:
            issues.append(f"kelly_hard_cap={kelly_hard_cap} out of (0,1]")

        # Global notional cap (fraction of bankroll)
        global_cap = float(getattr(p, "kelly_global_notional_cap_pct", 0.0))
        if global_cap <= 0 or global_cap > 0.10:
            issues.append(f"kelly_global_notional_cap_pct={global_cap:.1%} — should be in (0, 10%]")

        if issues:
            res.warn("RISK_CAPS", "; ".join(issues))
        else:
            res.ok(
                "RISK_CAPS",
                f"min_edge={min_edge} kelly_hard_cap={kelly_hard_cap} "
                f"global_notional_cap={global_cap:.1%}",
            )
    except Exception as exc:
        res.warn("RISK_CAPS", f"could not inspect active profile: {type(exc).__name__}: {exc}")


def check_catalog(res: CheckResult) -> None:
    """6. CATALOG — market_catalog accessible, counts per series."""
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        all_markets = catalog.get_all_markets()

        if not all_markets:
            res.warn(
                "CATALOG/TOTAL",
                "0 markets in catalog — catalog may not be bootstrapped yet (OK at startup)",
            )
            return

        res.ok("CATALOG/TOTAL", f"{len(all_markets)} markets in catalog")

        # Per series breakdown
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
        series_counts: dict = {}
        for m in all_markets:
            ticker = getattr(m, "series_ticker", None) or getattr(m, "ticker", "")
            # Match to series prefix (e.g. KXBTC15M → KXBTC15M series)
            for series_list in KALSHI_CRYPTO_PRODUCTS.values():
                for s in series_list:
                    if ticker.startswith(s):
                        series_counts[s] = series_counts.get(s, 0) + 1
                        break

        dead_series = [
            s
            for series_list in KALSHI_CRYPTO_PRODUCTS.values()
            for s in series_list
            if series_counts.get(s, 0) == 0
        ]
        if dead_series:
            res.warn(
                "CATALOG/PER_SERIES",
                f"{len(dead_series)} series with 0 markets: {dead_series[:10]}",
            )
        else:
            res.ok(
                "CATALOG/PER_SERIES",
                f"all series have markets; sample counts: {dict(list(series_counts.items())[:6])}",
            )
    except Exception as exc:
        res.warn("CATALOG", f"catalog query failed (OK if CT not started): {type(exc).__name__}: {exc}")


def check_log_path(res: CheckResult) -> None:
    """7. LOG — log file directory writable."""
    log_dir = Path("logs")
    try:
        log_dir.mkdir(exist_ok=True)
        test_file = log_dir / ".readiness_probe"
        test_file.write_text("ok")
        test_file.unlink()
        res.ok("LOG/WRITABLE", f"{log_dir.resolve()} is writable")
    except Exception as exc:
        res.fail("LOG/WRITABLE", f"{log_dir.resolve()} not writable: {exc}")

    merid_log = log_dir / "merid.log"
    if merid_log.exists():
        size_kb = merid_log.stat().st_size // 1024
        res.ok("LOG/merid.log", f"exists, {size_kb} KB")
    else:
        res.warn("LOG/merid.log", "not yet created (OK before first run)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="MERID Kalshi execution readiness check (env, kill switch, gate, catalog).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Typical flow: load .env → run this script → fix any FAIL → restart server.\n"
            "Use --strict before a production cutover (treats WARN as failure).\n"
            "See also: scripts/kalshi_go_live_preflight.py"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any WARN as well as FAIL (demand all-green; routine restarts often warn)",
    )
    args = parser.parse_args()

    # Ensure project root on sys.path
    project_root = Path(__file__).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Load .env / merid.settings so os.getenv sees the same environment as the server.
    try:
        import merid.settings  # noqa: F401
    except Exception:
        pass

    res = CheckResult()

    stages = [
        check_env,
        check_kill_switch_persistence,
        check_imports,
        check_grid,
        check_execution_gate,
        check_risk_caps,
        check_catalog,
        check_log_path,
    ]

    for stage_fn in stages:
        try:
            stage_fn(res)
        except Exception:
            res.fail(stage_fn.__name__, f"check crashed:\n{traceback.format_exc()[:400]}")

    res.print_report()

    if res.has_failures:
        return 1
    if args.strict and res.has_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
