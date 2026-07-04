"""
Kalshi Continuous BTC Trader
============================
⚠️  PRODUCTION HARDENING: THIS SCRIPT IS DISABLED  ⚠️

This script contains a DIRECT HTTP BYPASS to Kalshi API that circumvents the
canonical order_router and ALL risk guards (GlobalRiskGuard 1-2% cap, Top-3 batch
gate, PreTradeGate, execution gate, kill switches).

To enable this bypass (NOT RECOMMENDED): set MERID_ALLOW_CT_SCRIPT_BYPASS=1
See: kalshi_continuous_trader.py.DISABLED for full documentation.

If you need continuous trading, use the canonical path:
  - merid/trading/kalshi_continuous_trader.py (async server module)
  - This routes through order_router and enforces all risk guards
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING — CRITICAL BYPASS DISABLED
# ═══════════════════════════════════════════════════════════════════════════
import os
if os.getenv("MERID_ALLOW_CT_SCRIPT_BYPASS", "").lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "[PRODUCTION HARDENING] scripts/kalshi_continuous_trader.py is DISABLED. "
        "This script contains direct HTTP bypasses to Kalshi API that circumvent "
        "the canonical order_router and ALL risk guards. "
        "Use merid/trading/kalshi_continuous_trader.py (async module) instead, "
        "which routes through the hardened order_router with proper risk controls. "
        "To bypass (NOT RECOMMENDED): MERID_ALLOW_CT_SCRIPT_BYPASS=1"
    )
# ═══════════════════════════════════════════════════════════════════════════

import argparse
import base64
import collections
import json
import math
import os
import re
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TraderConfig:
    """All tunable knobs for the continuous trader."""
    # Cycle
    interval_seconds: int = 60
    max_cycles: int = 0          # 0 = infinite
    dry_run: bool = False

    # ── Bankroll management (capital-preservation-first) ──────────────
    initial_bankroll_cents: int = 100000  # $1000 starting capital (increased from $10 for reasonable trade sizes)
    max_risk_per_trade_pct: float = 0.02 # risk max 2% of bankroll per trade
    kelly_fraction: float = 0.25         # quarter-Kelly (survival-first)
    max_contract_price_cents: int = 35   # NEVER buy contracts above 35¢
    min_contract_price_cents: int = 2    # skip penny contracts (no liquidity)
    max_position_per_market: int = 3     # max contracts held per ticker
    max_open_positions: int = 5          # max simultaneous markets
    max_total_exposure_pct: float = 0.20 # never have >20% of bankroll at risk

    # ── Drawdown protection ──────────────────────────────────────────
    drawdown_halt_pct: float = 0.20      # HALT if bankroll drops 20% from peak
    drawdown_reduce_pct: float = 0.10    # reduce sizing at 10% drawdown
    min_balance_cents: int = 200         # never trade below $2.00 reserve

    # ── Edge requirements (very strict) ──────────────────────────────
    min_edge: Decimal = Decimal("0.08")  # 8% net edge after fees+slippage
    fee_per_contract: Decimal = Decimal("0.02")  # ~2¢ Kalshi taker fee (= 0.07 * P*(1-P) at 50¢)
    slippage: Decimal = Decimal("0.01")  # 1% slippage

    # ── Market selection ─────────────────────────────────────────────
    series_tickers: List[str] = field(default_factory=lambda: ["KXBTUPDOWN-15M", "KXBTC", "KXBTCD"])
    max_markets_to_scan: int = 10
    max_strike_distance_pct: float = 0.25

    # ── Fee-aware edge scaling ───────────────────────────────────────
    fee_edge_multiplier_midcurve: float = 1.5  # 1.5x min_edge for 40-60¢ contracts
    fee_edge_multiplier_penny: float = 2.0     # 2x min_edge for ≤5¢ contracts

    # ── Anti-churn hysteresis ────────────────────────────────────────
    churn_cooldown_cycles: int = 3       # don't flip direction on same ticker for 3 cycles
    churn_edge_improvement: float = 0.05 # unless edge improved by 5% absolute

    # ── Fee drag monitoring ──────────────────────────────────────────
    max_fee_drag_pct: float = 0.30       # tighten filters if fees > 30% of gross edge
    fee_drag_lookback: int = 30          # base rolling window (overridden by vol-adaptive)

    # ── Volatility-adaptive fee-drag window ────────────────────────
    vol_lookback_bars: int = 20          # bars of spot history for vol calc
    vol_low_threshold: float = 0.40      # annualized vol < 40% = calm
    vol_high_threshold: float = 0.80     # annualized vol > 80% = stressed
    fee_window_low_vol: int = 50         # calm: longer window, smooth
    fee_window_mid_vol: int = 30         # typical: balanced
    fee_window_high_vol: int = 20        # stressed: fast adaptation

    # ── Order management ─────────────────────────────────────────────
    stale_order_seconds: int = 120       # cancel stale orders after 2 min
    max_orders_per_cycle: int = 1        # conservative: 1 order per cycle


# ═══════════════════════════════════════════════════════════════════════════
# Credentials & Auth
# ═══════════════════════════════════════════════════════════════════════════

def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v

_load_env()

_kalshi_env = os.environ.get("KALSHI_ENV", "demo").lower()
if _kalshi_env == "live":
    BASE_URL = os.environ.get(
        "KALSHI_API_BASE_URL",
        "https://external-api.kalshi.com/trade-api/v2",
    )
else:
    BASE_URL = os.environ.get(
        "KALSHI_API_BASE_URL",
        "https://demo-api.kalshi.co/trade-api/v2",
    )
API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "")
_key_file = Path(os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem"))
if not _key_file.is_absolute():
    _key_file = Path(__file__).resolve().parent.parent / _key_file

_private_key = serialization.load_pem_private_key(_key_file.read_bytes(), password=None)


def _sign(method: str, path: str) -> dict:
    ts_ms = str(int(time.time() * 1000))
    full_path = "/trade-api/v2" + path
    msg = ts_ms + method.upper() + full_path
    sig = _private_key.sign(
        msg.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }


def api_get(path: str, params: dict | None = None) -> requests.Response:
    return requests.get(BASE_URL + path, headers=_sign("GET", path), params=params, timeout=15)


def api_post(path: str, data: dict) -> requests.Response:
    return requests.post(BASE_URL + path, headers=_sign("POST", path), json=data, timeout=15)


def api_delete(path: str) -> requests.Response:
    return requests.delete(BASE_URL + path, headers=_sign("DELETE", path), timeout=15)


# ═══════════════════════════════════════════════════════════════════════════
# Directional bias indicator stack
# ═══════════════════════════════════════════════════════════════════════════

_indicator_stack = None
try:
    # Add project root to path so merid.signals is importable from scripts/
    import sys as _sys
    _proj_root = str(Path(__file__).resolve().parent.parent)
    if _proj_root not in _sys.path:
        _sys.path.insert(0, _proj_root)
    from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack
    _indicator_stack = Crypto15mIndicatorStack()
except Exception as _ie:
    pass  # flat 50/50 fallback when indicator stack is unavailable


# ═══════════════════════════════════════════════════════════════════════════
# Data helpers
# ═══════════════════════════════════════════════════════════════════════════

def get_btc_spot() -> Optional[float]:
    """Fetch BTC/USD spot from CoinGecko."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10,
        )
        return r.json()["bitcoin"]["usd"]
    except Exception as e:
        log(f"  ⚠ CoinGecko spot fetch failed: {e}")
        return None


def get_balance() -> Tuple[int, int]:
    """Return (balance_cents, portfolio_value_cents)."""
    r = api_get("/portfolio/balance")
    if r.status_code == 200:
        d = r.json()
        return d.get("balance", 0), d.get("portfolio_value", 0)
    return 0, 0


def get_positions() -> Dict[str, int]:
    """Return {ticker: position_count} for all open positions."""
    r = api_get("/portfolio/positions")
    positions = {}
    if r.status_code == 200:
        data = r.json()
        items = data.get("market_positions", data.get("positions", []))
        if isinstance(items, list):
            for p in items:
                ticker = p.get("ticker", "")
                pos = p.get("position_fp", p.get("position", 0))
                positions[ticker] = int(float(pos))
        elif isinstance(items, dict):
            for ticker, p in items.items():
                pos = p.get("position_fp", p.get("position", 0))
                positions[ticker] = int(float(pos))
    return positions


def get_resting_orders() -> List[dict]:
    """Return list of resting orders."""
    r = api_get("/portfolio/orders", params={"status": "resting"})
    if r.status_code == 200:
        return r.json().get("orders", [])
    return []


def fetch_markets(series: str, limit: int = 200) -> List[dict]:
    """Fetch open markets for a series."""
    r = api_get("/markets", params={"limit": limit, "status": "open", "series_ticker": series})
    if r.status_code == 200:
        return r.json().get("markets", [])
    return []


def fetch_orderbook(ticker: str) -> Optional[dict]:
    """Fetch orderbook for a market."""
    r = api_get(f"/markets/{ticker}/orderbook", params={"depth": 5})
    if r.status_code == 200:
        return r.json().get("orderbook", r.json())
    return None


def parse_strike(ticker: str) -> Optional[float]:
    """Extract strike price from ticker like KXBTCD-26MAR2003-T79299.99."""
    m = re.search(r"-T(\d+(?:\.\d+)?)$", ticker)
    return float(m.group(1)) if m else None


def is_directional_market(ticker: str) -> bool:
    """Return True for up/down directional markets (no strike price)."""
    t = ticker.upper()
    return "UPDOWN" in t or "UP-DOWN" in t or "DIRECTION" in t


# ═══════════════════════════════════════════════════════════════════════════
# Bankroll manager — capital preservation + compounding
#
# Prefer the canonical KalshiRiskEngine from the merid package when
# available so sizing/risk logic stays in sync with the server module.
# Falls back to the local _LocalBankrollManager when running standalone.
# ═══════════════════════════════════════════════════════════════════════════

try:
    from merid.event_venues.kalshi.kalshi_risk import KalshiRiskEngine as BankrollManager  # noqa: F811
    _USING_CANONICAL_BANKROLL = True
except ImportError:
    _USING_CANONICAL_BANKROLL = False


class _LocalBankrollManager:
    """Capital-preservation-first bankroll manager.

    Rules enforced:
     1. NEVER risk more than max_risk_per_trade_pct of current bankroll on one trade
     2. NEVER buy contracts priced above max_contract_price_cents
     3. Use quarter-Kelly sizing — mathematically optimal growth with huge safety margin
     4. HALT all trading if drawdown from peak exceeds drawdown_halt_pct
     5. REDUCE sizing by 50% if drawdown exceeds drawdown_reduce_pct
     6. Compound: position sizes grow as bankroll grows (balance-relative)
     7. Cap total exposure so no single bad run wipes us out
     8. Fee-aware edge: require higher edge at mid-curve prices where fee drag is worst
     9. Anti-churn hysteresis: block direction flips on same ticker within N cycles
    10. Fee drag monitor: auto-tighten filters when fees exceed % of gross edge
    """

    def __init__(self, config: TraderConfig):
        self.config = config
        # CRITICAL: Initialize peak from live bankroll if available, otherwise use static reference
        # Static reference (initial_bankroll_cents) is for reporting only, not for risk calculations
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            live_equity = get_equity_for_risk_calc_sync()
            if live_equity is not None and live_equity > 0:
                self._peak_balance_cents = int(live_equity * 100)
            else:
                # Fallback to static reference (may be 0 if not set)
                self._peak_balance_cents = config.initial_bankroll_cents
        except Exception:
            # Fallback to static reference
            self._peak_balance_cents = config.initial_bankroll_cents
        self._halted = False
        self._halt_reason = ""
        self._total_trades = 0
        self._total_wins = 0
        self._total_losses = 0
        self._total_pnl_cents = 0
        self._total_fees_cents = 0
        self._last_trade: Dict[str, Tuple[str, float, int]] = {}
        self._current_cycle = 0
        self._fee_history: collections.deque = collections.deque(
            maxlen=config.fee_drag_lookback,
        )
        self._fee_drag_tightening = False
        self._spot_history: collections.deque = collections.deque(
            maxlen=config.vol_lookback_bars + 1,
        )
        self._current_vol_band = "mid"
        self._annualized_vol = 0.0
        self._cycle_history: collections.deque = collections.deque(maxlen=60)
        log(
            f"BankrollManager: bankroll=${config.initial_bankroll_cents/100:.2f}, "
            f"risk/trade={config.max_risk_per_trade_pct*100:.1f}%, "
            f"kelly={config.kelly_fraction*100:.0f}%, "
            f"max_price={config.max_contract_price_cents}¢, "
            f"dd_halt={config.drawdown_halt_pct*100:.0f}%, "
            f"dd_reduce={config.drawdown_reduce_pct*100:.0f}%, "
            f"fee_mult_mid={config.fee_edge_multiplier_midcurve:.1f}x, "
            f"fee_mult_penny={config.fee_edge_multiplier_penny:.1f}x, "
            f"churn_cooldown={config.churn_cooldown_cycles}"
        )

    def advance_cycle(self) -> None:
        self._current_cycle += 1

    def record_cycle_snapshot(self, balance_cents: int) -> None:
        """Append a per-cycle data point for sparkline rendering."""
        self._cycle_history.append({
            "cycle": self._current_cycle,
            "drawdown_pct": round(self.get_drawdown_pct(balance_cents) * 100, 2),
            "fee_drag_pct": round(self.get_fee_drag_pct() * 100, 1),
            "pnl_cents": self._total_pnl_cents,
            "balance_cents": balance_cents,
            "vol_pct": round(self._annualized_vol * 100, 1),
        })

    # ── Volatility-adaptive fee-drag window ───────────────────────

    def record_spot(self, spot: float) -> None:
        if spot <= 0:
            return
        self._spot_history.append(spot)
        if len(self._spot_history) >= 3:
            self._compute_vol()
            self._update_vol_band()

    def _compute_vol(self) -> None:
        spots = list(self._spot_history)
        if len(spots) < 3:
            return
        log_returns = [
            math.log(spots[i] / spots[i - 1])
            for i in range(1, len(spots))
            if spots[i - 1] > 0
        ]
        if len(log_returns) < 2:
            return
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        bar_vol = math.sqrt(var)
        bars_per_year = 365.25 * 24 * 3600 / max(1, self.config.interval_seconds)
        self._annualized_vol = bar_vol * math.sqrt(bars_per_year)

    def _update_vol_band(self) -> None:
        cfg = self.config
        vol = self._annualized_vol
        if vol < cfg.vol_low_threshold:
            new_band = "low"
            new_window = cfg.fee_window_low_vol
        elif vol > cfg.vol_high_threshold:
            new_band = "high"
            new_window = cfg.fee_window_high_vol
        else:
            new_band = "mid"
            new_window = cfg.fee_window_mid_vol
        if new_band != self._current_vol_band:
            old_band = self._current_vol_band
            self._current_vol_band = new_band
            old_data = list(self._fee_history)
            self._fee_history = collections.deque(
                old_data[-new_window:], maxlen=new_window,
            )
            log(f"  VOL BAND: {old_band} → {new_band} "
                f"(ann_vol={vol*100:.0f}%, window {len(old_data)} → {new_window})")

    @property
    def vol_band(self) -> str:
        return self._current_vol_band

    @property
    def annualized_vol(self) -> float:
        return self._annualized_vol

    def update_peak(self, balance_cents: int) -> None:
        if balance_cents > self._peak_balance_cents:
            self._peak_balance_cents = balance_cents
            log(f"  NEW PEAK: ${balance_cents/100:.2f}")

    def check_drawdown(self, balance_cents: int) -> bool:
        if self._peak_balance_cents <= 0:
            return False
        drawdown = 1.0 - (balance_cents / self._peak_balance_cents)
        if drawdown >= self.config.drawdown_halt_pct:
            self._halted = True
            self._halt_reason = (
                f"Drawdown {drawdown:.1%} >= halt threshold {self.config.drawdown_halt_pct:.0%}. "
                f"Peak=${self._peak_balance_cents/100:.2f}, now=${balance_cents/100:.2f}"
            )
            log(f"  ⛔ DRAWDOWN HALT: {self._halt_reason}")
            return False
        if drawdown >= self.config.drawdown_reduce_pct:
            log(f"  ⚠ Drawdown {drawdown:.1%} — reduced sizing active")
        return True

    @property
    def is_halted(self) -> bool:
        return self._halted

    def get_drawdown_pct(self, balance_cents: int) -> float:
        if self._peak_balance_cents <= 0:
            return 0.0
        return 1.0 - (balance_cents / self._peak_balance_cents)

    # ── Fee-aware minimum edge by price band ───────────────────────

    def min_edge_for_price(self, contract_price_cents: int) -> Decimal:
        """Dynamic minimum edge required for a given contract price.

        Price bands:
          ≤ 5¢   → 2.0x base (rounding kills small contracts)
          6-39¢  → 1.0x base (sweet spot)
          40-60¢ → 1.5x base (highest absolute fee per contract)
          61-99¢ → 1.0x base (symmetric)
        """
        cfg = self.config
        base = cfg.min_edge
        if self._fee_drag_tightening:
            base = Decimal(str(float(base) * 1.25))
        if contract_price_cents <= 5:
            return Decimal(str(float(base) * cfg.fee_edge_multiplier_penny))
        elif 40 <= contract_price_cents <= 60:
            return Decimal(str(float(base) * cfg.fee_edge_multiplier_midcurve))
        else:
            return base

    @staticmethod
    def kalshi_fee_cents(contracts: int, price_cents: int) -> int:
        """Compute Kalshi taker fee using unified fees module."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        return calculate_kalshi_fee_cents(contracts=contracts, price_cents=price_cents)

    # ── Anti-churn hysteresis ──────────────────────────────────────

    def check_churn(self, ticker: str, side: str, edge: float) -> bool:
        """Return True if trade is allowed (not a churn flip)."""
        cfg = self.config
        prev = self._last_trade.get(ticker)
        if prev is None:
            return True
        prev_side, prev_edge, prev_cycle = prev
        if side == prev_side:
            return True
        cycles_since = self._current_cycle - prev_cycle
        if cycles_since < cfg.churn_cooldown_cycles:
            edge_improvement = edge - prev_edge
            if edge_improvement < cfg.churn_edge_improvement:
                log(f"    CHURN BLOCK: {ticker} flip {prev_side}→{side} after "
                    f"{cycles_since} cycles (need {cfg.churn_cooldown_cycles}), "
                    f"edge_improve={edge_improvement:.4f} (need {cfg.churn_edge_improvement:.4f})")
                return False
        return True

    def record_trade_direction(self, ticker: str, side: str, edge: float) -> None:
        self._last_trade[ticker] = (side, edge, self._current_cycle)

    # ── Fee drag monitor ───────────────────────────────────────────

    def record_fee(self, fee_cents: int, gross_edge_cents: int) -> None:
        self._fee_history.append((fee_cents, max(1, gross_edge_cents)))
        self._total_fees_cents += fee_cents
        self._update_fee_drag_state()

    def _update_fee_drag_state(self) -> None:
        if len(self._fee_history) < 5:
            return
        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)
        if total_edge <= 0:
            return
        fee_drag = total_fees / total_edge
        was_tightening = self._fee_drag_tightening
        self._fee_drag_tightening = fee_drag > self.config.max_fee_drag_pct
        if self._fee_drag_tightening and not was_tightening:
            log(f"  ⚠ FEE DRAG WARNING: fees={fee_drag:.0%} of gross edge "
                f"(threshold={self.config.max_fee_drag_pct:.0%}) — tightening 1.25x")
        elif not self._fee_drag_tightening and was_tightening:
            log("  ✓ Fee drag normalized — relaxing edge requirements")

    def get_fee_drag_pct(self) -> float:
        if len(self._fee_history) < 2:
            return 0.0
        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)
        if total_edge <= 0:
            return 0.0
        return total_fees / total_edge

    # ── Effective limits (auto-reduce under fee stress) ─────────────

    def effective_max_orders_per_cycle(self) -> int:
        """When fee drag is high, cut max orders per cycle in half (min 1)."""
        base = self.config.max_orders_per_cycle
        if self._fee_drag_tightening:
            return max(1, base // 2)
        return base

    def effective_max_exposure_pct(self) -> float:
        """When fee drag is high, reduce max exposure by 25%."""
        base = self.config.max_total_exposure_pct
        if self._fee_drag_tightening:
            return base * 0.75
        return base

    # ── Core sizing logic ──────────────────────────────────────────

    def calculate_order_size(
        self,
        balance_cents: int,
        edge: Decimal,
        contract_price_cents: int,
        existing_position: int,
        total_open_positions: int,
    ) -> int:
        """Calculate safe order size using fractional Kelly + hard caps.
        Returns 0 if the trade should be skipped.
        """
        cfg = self.config

        # Gate 1: hard halts
        if self._halted:
            return 0
        if balance_cents < cfg.min_balance_cents:
            return 0
        if existing_position >= cfg.max_position_per_market:
            return 0
        if total_open_positions >= cfg.max_open_positions:
            return 0

        # Gate 2: contract price filter
        if contract_price_cents > cfg.max_contract_price_cents:
            return 0
        if contract_price_cents < cfg.min_contract_price_cents:
            return 0

        # Gate 3: fee-aware minimum edge
        required_edge = self.min_edge_for_price(contract_price_cents)
        if edge < required_edge:
            log(f"    REJECTED_BY_FEE: price={contract_price_cents}¢ "
                f"edge={float(edge):.4f} < required={float(required_edge):.4f} "
                f"(band={'penny' if contract_price_cents <= 5 else 'midcurve' if 40 <= contract_price_cents <= 60 else 'sweet'}, "
                f"tight={self._fee_drag_tightening})")
            return 0

        # Gate 4: total exposure cap (auto-reduced under fee stress)
        max_exposure_cents = int(balance_cents * self.effective_max_exposure_pct())

        # Kelly sizing
        edge_f = float(edge)
        win_prob = min(0.95, max(0.05, 0.5 + edge_f))
        payout_ratio = (100 - contract_price_cents) / max(1, contract_price_cents)

        q = 1.0 - win_prob
        raw_kelly = (win_prob * payout_ratio - q) / payout_ratio
        raw_kelly = max(0.0, raw_kelly)

        frac_kelly = raw_kelly * cfg.kelly_fraction

        # Drawdown multiplier
        dd = self.get_drawdown_pct(balance_cents)
        if dd >= cfg.drawdown_reduce_pct:
            frac_kelly *= 0.5

        # Dollar amount to risk
        kelly_risk_cents = int(balance_cents * frac_kelly)
        max_risk_cents = int(balance_cents * cfg.max_risk_per_trade_pct)
        risk_cents = min(kelly_risk_cents, max_risk_cents, max_exposure_cents)

        # Convert to contracts
        if contract_price_cents <= 0:
            return 0
        contracts = risk_cents // contract_price_cents
        contracts = max(0, min(contracts, cfg.max_position_per_market - existing_position))

        if contracts == 0 and risk_cents >= contract_price_cents and frac_kelly > 0:
            contracts = 1

        # Final fee sanity: reject if fee would eat >50% of expected profit
        if contracts > 0:
            expected_profit = int(float(edge) * contracts * contract_price_cents)
            fee = self.kalshi_fee_cents(contracts, contract_price_cents)
            if expected_profit > 0 and fee > expected_profit * 0.5:
                log(f"    REJECTED_BY_FEE: price={contract_price_cents}¢ size={contracts} "
                    f"fee={fee}¢ > 50% of expected_profit={expected_profit}¢ "
                    f"(fee_pct={fee/expected_profit*100:.0f}%)")
                return 0

        return contracts

    def record_trade_result(self, pnl_cents: int) -> None:
        self._total_trades += 1
        self._total_pnl_cents += pnl_cents
        if pnl_cents >= 0:
            self._total_wins += 1
        else:
            self._total_losses += 1

    def summary(self, balance_cents: int) -> str:
        wr = (self._total_wins / max(1, self._total_trades)) * 100
        dd = self.get_drawdown_pct(balance_cents)
        fee_drag = self.get_fee_drag_pct()
        tight = " [TIGHT]" if self._fee_drag_tightening else ""
        return (
            f"Bankroll: ${balance_cents/100:.2f} | Peak: ${self._peak_balance_cents/100:.2f} | "
            f"DD: {dd:.1%} | Trades: {self._total_trades} (W:{self._total_wins} L:{self._total_losses} "
            f"WR:{wr:.0f}%) | PnL: {self._total_pnl_cents:+d}¢ | "
            f"Fees: {self._total_fees_cents}¢ | FeeDrag: {fee_drag:.0%}{tight}"
        )


if not _USING_CANONICAL_BANKROLL:
    BankrollManager = _LocalBankrollManager  # noqa: F811


# ═══════════════════════════════════════════════════════════════════════════
# Edge computation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MarketCandidate:
    """A market we might trade."""
    ticker: str
    strike: float
    close_time: str
    spot: float
    is_directional: bool = False  # True for up/down markets (no strike)
    # Orderbook
    best_yes_bid: Optional[float] = None   # in dollars (0.01 = 1c)
    best_yes_ask: Optional[float] = None
    best_no_bid: Optional[float] = None
    best_no_ask: Optional[float] = None
    # Computed
    model_yes_prob: Optional[Decimal] = None
    implied_yes_prob: Optional[Decimal] = None
    yes_edge: Optional[Decimal] = None
    no_edge: Optional[Decimal] = None
    best_side: str = ""
    best_edge: Decimal = Decimal("0")
    limit_price_cents: int = 0


def compute_edge(candidate: MarketCandidate, config: TraderConfig) -> MarketCandidate:
    """Compute model probability and edge for a candidate market.

    Threshold markets: spot-distance heuristic — 1% distance shifts YES prob ~10%.
    Directional (up/down) markets: model_yes_prob = 0.50 (no bias), edge comes
    from mispriced orderbook levels below fair value.
    """
    spot = Decimal(str(candidate.spot))
    strike = Decimal(str(candidate.strike))

    if candidate.is_directional:
        # Directional market: tilt the 50/50 baseline using live technical bias.
        # Max tilt ±15% of confidence so yes_prob stays in [0.35, 0.65].
        # Falls back to flat 0.50 when indicator stack is cold or unavailable.
        yes_prob = Decimal("0.50")
        if _indicator_stack is not None:
            try:
                snap = _indicator_stack.snapshot()
                confidence = Decimal(str(snap.bias_confidence))
                max_tilt = Decimal("0.15")
                if snap.bias == "up":
                    yes_prob = Decimal("0.50") + confidence * max_tilt
                elif snap.bias == "down":
                    yes_prob = Decimal("0.50") - confidence * max_tilt
            except Exception:
                pass
    elif strike <= 0:
        return candidate
    else:
        dist_pct = (spot - strike) / strike
        yes_prob = Decimal("0.5") + (dist_pct * 10)
        yes_prob = min(max(yes_prob, Decimal("0.05")), Decimal("0.95"))
    candidate.model_yes_prob = yes_prob

    # Implied prob from orderbook
    # YES implied prob ≈ midpoint of yes bid/ask, or from NO side: 1 - no_mid
    if candidate.best_no_bid is not None:
        # If NO bids exist at X, implied YES ask = 1 - X
        implied_yes = Decimal("1") - Decimal(str(candidate.best_no_bid))
    elif candidate.best_yes_ask is not None:
        implied_yes = Decimal(str(candidate.best_yes_ask))
    else:
        implied_yes = Decimal("0.5")

    candidate.implied_yes_prob = implied_yes

    # YES edge: buy YES when model_prob > implied_price
    yes_edge = yes_prob - implied_yes - config.fee_per_contract - config.slippage
    # NO edge: buy NO when (1 - model_yes_prob) > implied_no_price
    no_prob = Decimal("1") - yes_prob
    if candidate.best_no_ask is not None:
        implied_no = Decimal(str(candidate.best_no_ask))
    elif candidate.best_yes_bid is not None:
        implied_no = Decimal("1") - Decimal(str(candidate.best_yes_bid))
    else:
        implied_no = Decimal("0.5")
    no_edge = no_prob - implied_no - config.fee_per_contract - config.slippage

    candidate.yes_edge = yes_edge
    candidate.no_edge = no_edge

    # Pick the better side
    if yes_edge > no_edge and yes_edge > Decimal("0"):
        candidate.best_side = "yes"
        candidate.best_edge = yes_edge
        # Limit price = implied YES price in cents (we bid at model value)
        # CRITICAL FIX: Clamp to 15-70 cents to prevent $0.99 purchases
        # This aligns with order_router.py _check_intent_risk validation [15, 70]
        candidate.limit_price_cents = max(15, min(70, int(implied_yes * 100)))
    elif no_edge > Decimal("0"):
        candidate.best_side = "no"
        candidate.best_edge = no_edge
        # CRITICAL FIX: Clamp to 15-70 cents to prevent $0.99 purchases
        # This aligns with order_router.py _check_intent_risk validation [15, 70]
        candidate.limit_price_cents = max(15, min(70, int(implied_no * 100)))
    else:
        candidate.best_side = ""
        candidate.best_edge = max(yes_edge, no_edge)

    return candidate


# ═══════════════════════════════════════════════════════════════════════════
# Order state tracking
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OrderTracker:
    """Tracks lifetime order state."""
    total_spent_cents: int = 0
    total_fees_cents: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    resting_orders: Dict[str, dict] = field(default_factory=dict)  # order_id -> info

    def record_order(self, order: dict, cost_cents: int) -> None:
        oid = order.get("order_id", "?")
        status = order.get("status", "")
        self.orders_placed += 1
        self.total_spent_cents += cost_cents
        fee = int(float(order.get("taker_fees_dollars", "0")) * 100)
        self.total_fees_cents += fee
        if status == "executed":
            self.orders_filled += 1
        elif status == "resting":
            self.resting_orders[oid] = {
                "ticker": order.get("ticker"),
                "placed_at": time.time(),
                "price_cents": cost_cents,
            }

    def record_cancel(self, order_id: str) -> None:
        self.orders_cancelled += 1
        self.resting_orders.pop(order_id, None)

    def summary(self) -> str:
        return (
            f"Orders: {self.orders_placed} placed, {self.orders_filled} filled, "
            f"{self.orders_cancelled} cancelled | "
            f"Spent: {self.total_spent_cents}c + {self.total_fees_cents}c fees"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════

_SHUTDOWN = False


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def handle_shutdown(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    log("⚠ Shutdown signal received, finishing current cycle...")


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ═══════════════════════════════════════════════════════════════════════════
# Main trading loop
# ═══════════════════════════════════════════════════════════════════════════

def run_cycle(config: TraderConfig, tracker: OrderTracker, bankroll: BankrollManager, cycle: int) -> None:
    """Run one trading cycle."""
    bankroll.advance_cycle()
    log(f"═══ Cycle {cycle} ═══")
    tight = " [TIGHT]" if bankroll._fee_drag_tightening else ""
    log(f"  Config: churn={config.churn_cooldown_cycles} cyc/"
        f"{config.churn_edge_improvement*100:.0f}% | "
        f"fee_drag={bankroll.get_fee_drag_pct()*100:.0f}% window={bankroll._fee_history.maxlen} | "
        f"eff_orders={bankroll.effective_max_orders_per_cycle()} "
        f"eff_exposure={bankroll.effective_max_exposure_pct()*100:.0f}% | "
        f"vol={bankroll.vol_band} {bankroll.annualized_vol*100:.0f}%{tight}")

    # 1. BTC spot
    spot = get_btc_spot()
    if spot is None:
        log("  ✗ No spot price — skipping cycle")
        return
    log(f"  BTC spot: ${spot:,.2f}")
    bankroll.record_spot(spot)
    if _indicator_stack is not None:
        _indicator_stack.update(spot)

    # 2. Account state + bankroll management
    balance_cents, portfolio_cents = get_balance()
    total_value_cents = balance_cents + portfolio_cents
    log(f"  Balance: ${balance_cents/100:.2f} | Portfolio: ${portfolio_cents/100:.2f} | Total: ${total_value_cents/100:.2f}")

    # Update peak for drawdown tracking (compounding uses total value)
    bankroll.update_peak(total_value_cents)
    bankroll.record_cycle_snapshot(total_value_cents)

    # Drawdown check — HALT if we've lost too much from peak
    if bankroll.is_halted:
        log(f"  ⛔ HALTED: {bankroll._halt_reason}")
        return
    if not bankroll.check_drawdown(total_value_cents):
        return

    if balance_cents < config.min_balance_cents:
        log(f"  ✗ Balance ${balance_cents/100:.2f} below ${config.min_balance_cents/100:.2f} reserve — skipping")
        return

    # 3. Existing positions
    positions = get_positions()
    btc_positions = {k: v for k, v in positions.items()
                     if "KXBTC" in k.upper() or "KXBTUPDOWN" in k.upper()}
    total_open = sum(1 for v in btc_positions.values() if v != 0)
    if btc_positions:
        log(f"  Existing BTC positions: {btc_positions} (total={total_open})")

    # 4. Discover markets
    all_markets = []
    for series in config.series_tickers:
        all_markets.extend(fetch_markets(series))

    # Accept both threshold markets (with -T strike) and directional markets
    candidates = []
    for m in all_markets:
        ticker = m.get("ticker", "")
        strike = parse_strike(ticker)
        if strike is not None:
            # Threshold market — filter by distance to spot
            dist_pct = abs(spot - strike) / spot
            if dist_pct > config.max_strike_distance_pct:
                continue
            candidates.append(MarketCandidate(
                ticker=ticker, strike=strike,
                close_time=m.get("close_time", m.get("expiration_time", "?")),
                spot=spot, is_directional=False,
            ))
        elif is_directional_market(ticker):
            # Up/down directional market — always eligible
            candidates.append(MarketCandidate(
                ticker=ticker, strike=0.0,
                close_time=m.get("close_time", m.get("expiration_time", "?")),
                spot=spot, is_directional=True,
            ))

    # Directional markets first (15m), then threshold sorted by proximity
    dir_candidates = [c for c in candidates if c.is_directional]
    thr_candidates = sorted([c for c in candidates if not c.is_directional],
                            key=lambda c: abs(c.spot - c.strike))
    candidates = (dir_candidates + thr_candidates)[:config.max_markets_to_scan]

    if not candidates:
        log(f"  ✗ No tradeable BTC markets found")
        return

    log(f"  Scanning {len(candidates)} markets near spot...")

    # 5. Fetch orderbooks and compute edge
    tradeable = []
    for c in candidates:
        ob = fetch_orderbook(c.ticker)
        if ob is None:
            continue

        fp = ob.get("orderbook_fp", ob)
        yes_levels = fp.get("yes_dollars", [])
        no_levels = fp.get("no_dollars", [])

        if yes_levels:
            c.best_yes_bid = float(yes_levels[0][0])
        if no_levels:
            c.best_no_bid = float(no_levels[0][0])

        # Derive asks from opposite side bids
        # YES ask ≈ 1 - best NO bid; NO ask ≈ 1 - best YES bid
        if c.best_no_bid is not None:
            c.best_yes_ask = round(1.0 - c.best_no_bid, 4)
        if c.best_yes_bid is not None:
            c.best_no_ask = round(1.0 - c.best_yes_bid, 4)

        compute_edge(c, config)

        if c.is_directional:
            log(f"    {c.ticker}  [directional]  "
                f"model_yes={c.model_yes_prob}  impl_yes={c.implied_yes_prob}  "
                f"yes_edge={c.yes_edge}  no_edge={c.no_edge}")
        else:
            dist_pct = (c.spot - c.strike) / c.spot * 100
            log(f"    {c.ticker}  strike=${c.strike:,.0f}  dist={dist_pct:+.1f}%  "
                f"model_yes={c.model_yes_prob}  impl_yes={c.implied_yes_prob}  "
                f"yes_edge={c.yes_edge}  no_edge={c.no_edge}")

        if c.best_edge >= config.min_edge and c.best_side:
            tradeable.append(c)
            time.sleep(0.1)  # Rate limit between orderbook fetches

    if not tradeable:
        log("  ✗ No markets with sufficient edge")
        return

    # Sort by edge descending
    tradeable.sort(key=lambda c: c.best_edge, reverse=True)
    log(f"  ✓ {len(tradeable)} tradeable market(s)")

    # 6. Place orders — BankrollManager controls sizing
    orders_this_cycle = 0
    for c in tradeable:
        if _SHUTDOWN or orders_this_cycle >= bankroll.effective_max_orders_per_cycle():
            break

        # Anti-churn: block direction flips within cooldown window
        if not bankroll.check_churn(c.ticker, c.best_side, float(c.best_edge)):
            continue

        existing = btc_positions.get(c.ticker, 0)

        # BankrollManager decides how many contracts (or 0 = skip)
        order_count = bankroll.calculate_order_size(
            balance_cents=balance_cents,
            edge=c.best_edge,
            contract_price_cents=c.limit_price_cents,
            existing_position=existing,
            total_open_positions=total_open,
        )

        if order_count <= 0:
            log(f"    Skip {c.ticker}: bankroll says 0 (price={c.limit_price_cents}¢, "
                f"edge={c.best_edge:.4f}, pos={existing}, open={total_open})")
            continue

        cost_cents = c.limit_price_cents * order_count
        if cost_cents + 1 > balance_cents:
            log(f"    Skip {c.ticker}: can't afford {cost_cents}¢")
            continue

        # Compute expected fee for logging
        expected_fee = BankrollManager.kalshi_fee_cents(order_count, c.limit_price_cents)

        order_data = {
            "ticker": c.ticker,
            "action": "buy",
            "side": c.best_side,
            "count": order_count,
            "type": "limit",
            f"{c.best_side}_price": c.limit_price_cents,
            "client_order_id": str(uuid.uuid4()),
        }

        log(f"  → ORDER: {c.best_side.upper()} {order_count}x {c.ticker} "
            f"@ {c.limit_price_cents}¢  edge={c.best_edge:.4f}  cost={cost_cents}¢  est_fee={expected_fee}¢")

        if config.dry_run:
            log(f"    [DRY RUN] {json.dumps(order_data)}")
            bankroll.record_trade_direction(c.ticker, c.best_side, float(c.best_edge))
            orders_this_cycle += 1
            continue

        resp = api_post("/portfolio/orders", order_data)
        if resp.status_code == 201:
            order = resp.json().get("order", resp.json())
            status = order.get("status", "?")
            oid = order.get("order_id", "?")
            fill = order.get("fill_count_fp", "0")
            log(f"    ✅ {status.upper()} | id={oid} | filled={fill}/{order_count}")
            tracker.record_order(order, cost_cents)
            bankroll.record_trade_direction(c.ticker, c.best_side, float(c.best_edge))
            orders_this_cycle += 1
            total_open += order_count
            balance_cents -= cost_cents
            if status == "executed":
                fee = int(float(order.get("taker_fees_dollars", "0")) * 100)
                balance_cents -= fee
                # Record fee vs gross edge for fee drag monitoring
                gross_edge_cents = int(float(c.best_edge) * order_count * c.limit_price_cents)
                bankroll.record_fee(fee, gross_edge_cents)
        else:
            log(f"    ❌ {resp.status_code}: {resp.text[:200]}")

    # 7. Manage resting orders (cancel stale ones)
    stale_ids = []
    for oid, info in tracker.resting_orders.items():
        age = time.time() - info["placed_at"]
        if age > config.stale_order_seconds:
            stale_ids.append(oid)

    for oid in stale_ids:
        log(f"  Cancelling stale order {oid[:12]}...")
        r = api_delete(f"/portfolio/orders/{oid}")
        if r.status_code in (200, 204):
            tracker.record_cancel(oid)
            log(f"    ✅ Cancelled")
        else:
            log(f"    ❌ Cancel failed: {r.status_code}")

    log(f"  {bankroll.summary(balance_cents)}")


def main():
    parser = argparse.ArgumentParser(description="Kalshi Continuous BTC Trader (Capital-Preservation Mode)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles (default: 60)")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles, 0=infinite (default: 0)")
    parser.add_argument("--dry-run", action="store_true", help="Log only, don't place orders")
    parser.add_argument("--bankroll", type=int, default=1000, help="Starting bankroll in cents (default: 1000 = $10)")
    parser.add_argument("--max-position", type=int, default=3, help="Max contracts per market (default: 3)")
    parser.add_argument("--min-edge", type=float, default=0.08, help="Min edge to trade (default: 0.08)")
    parser.add_argument("--max-price", type=int, default=35, help="Max contract price in cents (default: 35)")
    parser.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (default: 0.25 = quarter-Kelly)")
    parser.add_argument("--dd-halt", type=float, default=0.20, help="Drawdown halt threshold (default: 0.20)")
    parser.add_argument("--max-distance", type=float, default=0.25, help="Max strike distance from spot (default: 0.25)")
    args = parser.parse_args()

    config = TraderConfig(
        interval_seconds=args.interval,
        max_cycles=args.max_cycles,
        dry_run=args.dry_run,
        initial_bankroll_cents=args.bankroll,
        max_position_per_market=args.max_position,
        min_edge=Decimal(str(args.min_edge)),
        max_contract_price_cents=args.max_price,
        kelly_fraction=args.kelly,
        drawdown_halt_pct=args.dd_halt,
        max_strike_distance_pct=args.max_distance,
    )

    tracker = OrderTracker()
    bankroll = BankrollManager(config)

    log("═══════════════════════════════════════════════════════")
    log("  Kalshi Continuous BTC Trader — Capital Preservation")
    log(f"  RSA key: {_key_file.name}")
    log(f"  API Key: {API_KEY_ID[:8]}...{API_KEY_ID[-4:]}")
    log(f"  Bankroll: ${config.initial_bankroll_cents/100:.2f}")
    log(f"  Kelly fraction: {config.kelly_fraction:.0%}")
    log(f"  Max risk/trade: {config.max_risk_per_trade_pct:.0%}")
    log(f"  Max contract price: {config.max_contract_price_cents}¢")
    log(f"  Min edge: {config.min_edge}")
    log(f"  Drawdown halt: {config.drawdown_halt_pct:.0%}")
    log(f"  Drawdown reduce: {config.drawdown_reduce_pct:.0%}")
    log(f"  Min balance reserve: ${config.min_balance_cents/100:.2f}")
    log(f"  Max open positions: {config.max_open_positions}")
    log(f"  Max exposure: {config.max_total_exposure_pct:.0%}")
    log(f"  Series: {config.series_tickers}")
    log(f"  Dry run: {config.dry_run}")
    log("═══════════════════════════════════════════════════════")

    cycle = 0
    while not _SHUTDOWN:
        cycle += 1
        try:
            run_cycle(config, tracker, bankroll, cycle)
        except Exception as e:
            log(f"  ✗ Cycle error: {e}")
            import traceback
            traceback.print_exc()

        # Stop if bankroll manager halted due to drawdown
        if bankroll.is_halted:
            log("Bankroll manager halted trading — stopping.")
            break

        if config.max_cycles > 0 and cycle >= config.max_cycles:
            log(f"Max cycles ({config.max_cycles}) reached.")
            break

        if _SHUTDOWN:
            break

        log(f"  Sleeping {config.interval_seconds}s...")
        for _ in range(config.interval_seconds):
            if _SHUTDOWN:
                break
            time.sleep(1)

    log("═══ SHUTDOWN ═══")
    bal, port = get_balance()
    log(bankroll.summary(bal))
    positions = get_positions()
    btc_pos = {k: v for k, v in positions.items()
               if "KXBTC" in k.upper() or "KXBTUPDOWN" in k.upper()}
    if btc_pos:
        log(f"Final BTC positions: {btc_pos}")
    log(f"Final balance: ${bal/100:.2f} | Portfolio: ${port/100:.2f} | Total: ${(bal+port)/100:.2f}")


if __name__ == "__main__":
    main()
