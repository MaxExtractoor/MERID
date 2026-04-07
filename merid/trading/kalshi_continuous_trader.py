"""KalshiContinuousTrader — Continuous prediction-market trading agent.

Architecture:
  - Discovers candidates via ``KalshiMarketCatalog`` and ``MarketFilter``.
  - Uses the canonical ``MarketCandidate`` from ``market_filter`` as the
    shared dataclass; no shadow copy is defined here.
  - Wraps each candidate as a ``TradingCandidate`` (a thin subclass that
    adds risk tracking fields) for use inside this module.
  - Routes consensus opinions through ``OpinionStrategy._apply_confidence_clamp``
    so the confidence passed to sizing is always ≤ ``max_confidence``.
  - Group-level risk is tracked using ``group_id`` derived directly from the
    canonical ``MarketCandidate`` data, not from any local guessing logic.

Key invariants:
  - No fills are counted without a Kalshi ``fill_id`` (all fills go through
    ``KalshiFillsLedger``).
  - Group-notional cap is enforced and fully reset on ``reset_daily()``.
  - All execution rejections emit an ``execution_rejected`` event with
    symbol, reason, intent_id, and timestamp.

Edge / edge_pct units
---------------------
Throughout this module, *edge* is represented in two forms:

  ``edge_pct`` (on ``MarketCandidate`` / ``TradingCandidate``)
      A **signed percentage** value, e.g. ``3.0`` means 3% edge.
      Populated by the signal/model layer before CT evaluates the candidate.
      Converted to a decimal fraction inside ``signal_to_sizing`` via
      ``edge = edge_pct / 100.0``.

  ``edge`` (on ``OpinionEstimate``, ``SizingResult``, intent dicts)
      A **decimal fraction**, e.g. ``0.03`` means 3% edge.

Strategy ``min_edge`` and CT ``EDGE_THRESHOLDS`` are both **decimal fractions**.
Kalshi binary-contract fees run ~4–5% of notional at typical 45–55¢ prices, so
the fee break-even edge is roughly 0.04 (4%).  ``EDGE_THRESHOLDS_INITIAL_LIVE``
uses 0.005–0.020 (0.5–2%) to allow intents through for initial live validation;
``EDGE_THRESHOLDS_PRODUCTION`` uses 0.02–0.08 (2–8%) for fee-profitable trading.

Sizing pipeline (single authoritative path)
-------------------------------------------
1. ``signal_to_sizing(candidate, bankroll, estimate=...)`` resolves edge from
   (in priority): ``edge_override`` → ``candidate.edge_pct`` → ``estimate.edge``
   (passed in from ``trade_cycle``) → 0.  Computes Kelly fraction and returns
   a ``SizingResult`` with ``size_contracts`` based on Kelly notional.
2. ``trade_cycle`` calls ``evaluate_candidate`` once per candidate, then passes
   the result into ``signal_to_sizing`` so the strategy is invoked exactly once.
3. After ``_apply_risk_checks`` and applying ``exposure_multiplier``, the final
   ``notional`` is recomputed into ``size_contracts`` so the two values stay
   consistent regardless of what scaling factors are applied.

Exposure multiplier
-------------------
``_exposure_multiplier`` (env: ``MERID_CT_EXPOSURE_MULTIPLIER``, default 1.0)
scales the Kelly-computed ``notional`` in every ``trade_cycle`` call.  After
scaling, ``size_contracts`` is recomputed from the final ``notional``, so the
intent's ``size_contracts`` always reflects the post-multiplier position size.
"""

from __future__ import annotations

import asyncio
import math
import os
import pathlib
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
from merid.event_venues.kalshi.market_filter import MarketCandidate, MarketFilter, MarketFilterConfig, get_spot_band
from merid.formulas import generate_correlation_id
from merid.prediction.edge_calibration_tracker import get_edge_calibration_tracker
from merid.prediction.opinion_strategy import OpinionStrategy, OpinionEstimate, OpinionExplanation
from utils.logger import get_logger

# AUDIT-16: import canonical asset/timeframe universe so CT stays aligned with
# config.crypto_universe.  Never redefine these lists locally.
from config.crypto_universe import CRYPTO_ASSETS_ORDERED as _CRYPTO_ASSETS_LIST
from config.crypto_universe import CRYPTO_TIMEFRAMES_ORDERED as _CRYPTO_TIMEFRAMES_LIST

logger = get_logger("merid.trading.kalshi_continuous_trader")

# AUDIT-16: Use canonical universe — these are tuples for backward-compat with existing
# iteration code that expects a sequence.
_CRYPTO_ASSETS: tuple = tuple(_CRYPTO_ASSETS_LIST)
_CRYPTO_TIMEFRAMES: tuple = tuple(_CRYPTO_TIMEFRAMES_LIST)

# Hard-dollar group notional cap (legacy).  When MERID_GROUP_NOTIONAL_PCT is
# also set the percentage-based cap takes precedence and this value is ignored.
_DEFAULT_MAX_GROUP_NOTIONAL = float(os.getenv("MERID_GROUP_NOTIONAL_CAP", "50.0"))
# Percentage-of-bankroll group notional cap.  When non-zero, the effective cap
# per group each cycle is bankroll * _GROUP_NOTIONAL_PCT (e.g. 0.05 = 5%).
# Set MERID_GROUP_NOTIONAL_PCT=0 to use only the hard-dollar cap above.
_GROUP_NOTIONAL_PCT: float = float(os.getenv("MERID_GROUP_NOTIONAL_PCT", "0.05"))
# Total aggregate crypto-risk cap across ALL asset groups in a single cycle.
# When non-zero, no further intents are approved once the running notional total
# exceeds bankroll * _TOTAL_CRYPTO_RISK_PCT.  Set to 0 to disable.
_TOTAL_CRYPTO_RISK_PCT: float = float(os.getenv("MERID_TOTAL_CRYPTO_RISK_PCT", "0.15"))
_DEFAULT_MIN_CONFIDENCE = float(os.getenv("MERID_MIN_CONFIDENCE", "0.55"))
_DEFAULT_BANKROLL_FRACTION = float(os.getenv("MERID_BANKROLL_FRACTION", "0.01"))
_DEFAULT_MAX_YES_PRICE = float(os.getenv("MERID_MAX_YES_PRICE", "0.50"))
_DEFAULT_KELLY_FRACTION = float(os.getenv("MERID_KELLY_FRACTION", "0.25"))
_DEFAULT_MIN_EDGE = float(os.getenv("MERID_MIN_EDGE", "0.02"))

# ── Configurable defaults (env overrides) ─────────────────────────────────
# AUDIT-02..08: protect/size hardcodes are env-driven via MERID_CT_* vars.
_DEFAULT_MAX_CANDIDATES_PER_ASSET = int(os.getenv("MERID_CT_MAX_CANDIDATES", "5"))
_DEFAULT_MAX_SPREAD_CENTS = int(os.getenv("MERID_CT_MAX_SPREAD_CENTS", "12"))
_DEFAULT_MIN_VOLUME = int(os.getenv("MERID_CT_MIN_VOLUME", "50"))
_DEFAULT_MAX_POSITION_CONTRACTS = int(os.getenv("MERID_CT_MAX_POSITION_CONTRACTS", "0"))
_DEFAULT_EXPOSURE_MULTIPLIER = float(os.getenv("MERID_CT_EXPOSURE_MULTIPLIER", "1.0"))
_DEFAULT_COOLDOWN_SECONDS = float(os.getenv("MERID_CT_COOLDOWN_SECONDS", "0.0"))

# Daily loss limit — when realized losses exceed this fraction of the session-start
# bankroll, CT flips into OBSERVE-ONLY mode for the rest of the day.
# Defaults to 5%.  Set MERID_DAILY_LOSS_LIMIT_PCT=0 to disable.
_DEFAULT_DAILY_LOSS_LIMIT_PCT = float(os.getenv("MERID_DAILY_LOSS_LIMIT_PCT", "0.05"))

# Canary diagnostic mode — when enabled, CT must emit ≥1 tiny intent per asset
# per day to prove end-to-end execution is wired for all 5 assets.
# Set MERID_CT_CANARY_MODE=true to enable.
# Set MERID_CT_CANARY_NOTIONAL to override the canary notional (default 1.0 USD).
# Set MERID_CT_CANARY_INTERVAL_SECS to override the per-asset canary interval
# (default 86400 = once per day).
_CANARY_MODE: bool = os.getenv("MERID_CT_CANARY_MODE", "false").lower().strip() in ("1", "true", "yes")
_CANARY_NOTIONAL: float = float(os.getenv("MERID_CT_CANARY_NOTIONAL", "1.0"))
_CANARY_INTERVAL_SECS: float = float(os.getenv("MERID_CT_CANARY_INTERVAL_SECS", str(86400.0)))

# Edge profile selection: "initial_live" (permissive) or "production" (conservative).
#
# Defaults to "initial_live" (0.5–2% thresholds) so that CT can generate trade
# intents in typical live Kalshi books.  Switch to "production" (2–8%) only after
# validating that the model delivers consistent edge above those thresholds.
#
# Override via environment variable:
#   KALSHI_CT_EDGE_PROFILE=production   → conservative 2-8% thresholds
#   KALSHI_CT_EDGE_PROFILE=initial_live → permissive  0.5-2% thresholds (default)
_EDGE_PROFILE = os.getenv("KALSHI_CT_EDGE_PROFILE", "initial_live")

# ── Per-asset, per-timeframe minimum edge thresholds ──────────────────────
#
# Minimum net edge (after fees) required for a candidate to be tradable.
# Keys are (asset, timeframe) tuples; values are edge fractions (e.g. 0.03 = 3%).
#
# Two profiles:
#   - "initial_live": Low-threshold validation profile (0.5-1.5%) used while
#     establishing baseline statistics.  Kelly sizing is unchanged.
#   - "production": Conservative thresholds for fee-profitable trading (2-8%).
#
# If a specific (asset, timeframe) is not found, falls back to _DEFAULT_MIN_EDGE.
#

# INITIAL_LIVE profile: Permissive edge thresholds for live validation.
# Sizes are still fully Kelly-scaled; only the minimum-edge admission gate is lower.
EDGE_THRESHOLDS_INITIAL_LIVE: Dict[Tuple[str, str], float] = {
    # BTC - most liquid, tightest spreads
    ("BTC", "15m"): 0.005,    # 0.5% - very permissive for initial live
    ("BTC", "1h"): 0.008,     # 0.8%
    ("BTC", "daily"): 0.012,  # 1.2%
    ("BTC", "weekly"): 0.015, # 1.5%
    ("BTC", "monthly"): 0.015,
    # Annual — regime bets only; require meaningful edge vs terminal distribution
    ("BTC", "annual"): 0.020,
    # ETH - second most liquid
    ("ETH", "15m"): 0.008,
    ("ETH", "1h"): 0.010,
    ("ETH", "daily"): 0.015,
    ("ETH", "weekly"): 0.018,
    ("ETH", "monthly"): 0.018,
    ("ETH", "annual"): 0.025,
    # SOL/XRP/DOGE - wider spreads, more volatile
    ("SOL", "15m"): 0.010,
    ("SOL", "1h"): 0.012,
    ("SOL", "daily"): 0.015,
    ("SOL", "weekly"): 0.020,
    ("SOL", "monthly"): 0.020,
    ("SOL", "annual"): 0.030,
    ("XRP", "15m"): 0.010,
    ("XRP", "1h"): 0.012,
    ("XRP", "daily"): 0.015,
    ("XRP", "weekly"): 0.020,
    ("XRP", "monthly"): 0.020,
    ("XRP", "annual"): 0.030,
    ("DOGE", "15m"): 0.010,
    ("DOGE", "1h"): 0.012,
    ("DOGE", "daily"): 0.015,
    ("DOGE", "weekly"): 0.020,
    ("DOGE", "monthly"): 0.020,
    ("DOGE", "annual"): 0.030,
}

# PRODUCTION profile: Conservative thresholds (original values)
EDGE_THRESHOLDS_PRODUCTION: Dict[Tuple[str, str], float] = {
    # BTC
    ("BTC", "15m"): 0.02,
    ("BTC", "1h"): 0.03,
    ("BTC", "daily"): 0.04,
    ("BTC", "weekly"): 0.05,
    ("BTC", "monthly"): 0.05,
    ("BTC", "annual"): 0.08,
    # ETH
    ("ETH", "15m"): 0.03,
    ("ETH", "1h"): 0.04,
    ("ETH", "daily"): 0.05,
    ("ETH", "weekly"): 0.06,
    ("ETH", "monthly"): 0.06,
    ("ETH", "annual"): 0.10,
    # SOL
    ("SOL", "15m"): 0.04,
    ("SOL", "1h"): 0.06,
    ("SOL", "daily"): 0.06,
    ("SOL", "weekly"): 0.08,
    ("SOL", "monthly"): 0.08,
    ("SOL", "annual"): 0.12,
    # XRP
    ("XRP", "15m"): 0.04,
    ("XRP", "1h"): 0.06,
    ("XRP", "daily"): 0.06,
    ("XRP", "weekly"): 0.08,
    ("XRP", "monthly"): 0.08,
    ("XRP", "annual"): 0.12,
    # DOGE
    ("DOGE", "15m"): 0.04,
    ("DOGE", "1h"): 0.06,
    ("DOGE", "daily"): 0.06,
    ("DOGE", "weekly"): 0.08,
    ("DOGE", "monthly"): 0.08,
    ("DOGE", "annual"): 0.12,
}

# Select active thresholds based on profile
EDGE_THRESHOLDS: Dict[Tuple[str, str], float] = (
    EDGE_THRESHOLDS_INITIAL_LIVE if _EDGE_PROFILE == "initial_live"
    else EDGE_THRESHOLDS_PRODUCTION
)

# Fallback YES price (cents) when a candidate has no best_ask or mid price data.
# Used only in the max-price guard inside trade_cycle().
_FALLBACK_YES_PRICE_CENTS = 50

# Number of past scan cycles to retain for the rolling volume-band block-rate average.
# At the default ~60s candidate refresh interval this covers roughly 20 minutes.
_VOLUME_BAND_RATE_HISTORY_MAXLEN = 20

# CoinGecko IDs for each Kalshi crypto asset (AUDIT-21)
_COINGECKO_IDS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}

# Last-known spot prices: updated by _fetch_spot_prices_with_fallback().
# Used as final fallback when all live feeds fail (AUDIT-21).
_last_known_spot: Dict[str, float] = {}
_last_known_spot_ts: Dict[str, float] = {}
_LAST_KNOWN_SPOT_MAX_AGE_SECONDS = float(
    os.getenv("MERID_SPOT_MAX_STALENESS_SECONDS", "600")
)  # default: 10 minutes

# ── Strategy catalog per-cell parameter loading ───────────────────────────
#
# The strategy_catalog.yaml declares per-(asset, timeframe) parameters:
#   enabled              — gating flag for _refresh_candidates
#   kelly_fraction       — per-cell fractional Kelly multiplier
#   max_risk_per_trade_pct — hard cap per trade as % of bankroll
#
# These are loaded once at module import and used by:
#   _CATALOG_ENABLED[(asset, tf)]         → bool
#   _CATALOG_KELLY_FRACTION[(asset, tf)]  → float
#   _CATALOG_MAX_RISK_PCT[(asset, tf)]    → float
#
# Missing keys fall back to global defaults (_DEFAULT_KELLY_FRACTION, etc.).

def _load_strategy_catalog_lookups() -> Tuple[
    Dict[Tuple[str, str], bool],
    Dict[Tuple[str, str], float],
    Dict[Tuple[str, str], float],
]:
    """Load per-cell parameters from config/strategy_catalog.yaml.

    Returns three dicts keyed by (asset, timeframe):
      enabled_map      — bool (True by default when key is absent)
      kelly_map        — float kelly_fraction
      max_risk_map     — float max_risk_per_trade_pct
    """
    import yaml  # lazy import — yaml is only needed at module load time

    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent / "config" / "strategy_catalog.yaml"
    )
    enabled_map: Dict[Tuple[str, str], bool] = {}
    kelly_map: Dict[Tuple[str, str], float] = {}
    max_risk_map: Dict[Tuple[str, str], float] = {}
    try:
        with open(yaml_path, "r") as fh:
            doc = yaml.safe_load(fh)
        assets_block = (doc or {}).get("assets", {})
        for asset, asset_cfg in assets_block.items():
            if not isinstance(asset_cfg, dict):
                continue
            for tf, tf_cfg in asset_cfg.items():
                if tf == "tier" or not isinstance(tf_cfg, dict):
                    continue
                key = (str(asset).upper(), str(tf).lower())
                enabled_map[key] = bool(tf_cfg.get("enabled", True))
                kf = tf_cfg.get("kelly_fraction")
                if kf is not None:
                    try:
                        kelly_map[key] = float(kf)
                    except (TypeError, ValueError):
                        pass
                mrp = tf_cfg.get("max_risk_per_trade_pct")
                if mrp is not None:
                    try:
                        max_risk_map[key] = float(mrp) / 100.0  # convert % → fraction
                    except (TypeError, ValueError):
                        pass
    except FileNotFoundError:
        logger.warning(
            "strategy_catalog.yaml not found at %s; using global defaults for all cells.",
            yaml_path,
        )
    except Exception as exc:
        logger.error(
            "Failed to load strategy_catalog.yaml: %s — using global defaults for all cells.",
            exc,
        )
    return enabled_map, kelly_map, max_risk_map


_CATALOG_ENABLED: Dict[Tuple[str, str], bool]
_CATALOG_KELLY_FRACTION: Dict[Tuple[str, str], float]
_CATALOG_MAX_RISK_PCT: Dict[Tuple[str, str], float]
_CATALOG_ENABLED, _CATALOG_KELLY_FRACTION, _CATALOG_MAX_RISK_PCT = _load_strategy_catalog_lookups()




# ── Module-level safety guards ─────────────────────────────────────────────


def _check_smoke_test_live_mode_conflict() -> None:
    """AUDIT-15: Raise RuntimeError if smoke-test mode is active alongside live flags.

    Checks ``MERID_SMOKE_TEST``, ``MERID_TRADE_MODE``, ``MERID_PM_TRADING_MODE``,
    and ``MERID_ALLOW_LIVE_TRADES``.
    """
    smoke = os.getenv("MERID_SMOKE_TEST", "").lower().strip() in ("1", "true", "yes")
    if not smoke:
        return
    live_flags: list[str] = []
    trade_mode = os.getenv("MERID_TRADE_MODE", "paper").lower().strip()
    pm_trading_mode = os.getenv("MERID_PM_TRADING_MODE", "").lower().strip()
    allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower().strip()
    if trade_mode == "live":
        live_flags.append("MERID_TRADE_MODE=live")
    if pm_trading_mode == "live":
        live_flags.append("MERID_PM_TRADING_MODE=live")
    if allow_live in ("1", "true", "yes"):
        live_flags.append("MERID_ALLOW_LIVE_TRADES=true")
    if live_flags:
        raise RuntimeError(
            "KalshiContinuousTrader: MERID_SMOKE_TEST=true is incompatible with "
            f"live trading flags: {', '.join(live_flags)}.  "
            "Either disable smoke-test (MERID_SMOKE_TEST=false) or remove the live "
            "flags before starting CT in live mode."
        )


def _assert_kalshi_credentials_present() -> None:
    """AUDIT-14: Fail fast if Kalshi credentials are not configured.

    In live (non-dry-run) mode, at least one of the following must be set:
    - ``KALSHI_PRIVATE_KEY_PATH`` (path to RSA PEM file)
    - ``KALSHI_PRIVATE_KEY_PEM`` (raw RSA PEM string)
    - ``KALSHI_EMAIL`` + ``KALSHI_PASSWORD`` (email/password fallback)

    Raises ``RuntimeError`` with a clear diagnostic if credentials are absent.
    """
    has_rsa = bool(
        os.getenv("KALSHI_PRIVATE_KEY_PATH") or os.getenv("KALSHI_PRIVATE_KEY_PEM")
    )
    has_email = bool(os.getenv("KALSHI_EMAIL") and os.getenv("KALSHI_PASSWORD"))
    if not has_rsa and not has_email:
        raise RuntimeError(
            "KalshiContinuousTrader: No Kalshi credentials found.  "
            "Set KALSHI_PRIVATE_KEY_PATH (or KALSHI_PRIVATE_KEY_PEM) for RSA auth, "
            "or KALSHI_EMAIL + KALSHI_PASSWORD for email/password auth.  "
            "If this is a dry-run or test, set MERID_CT_DRY_RUN=true to bypass "
            "this check."
        )


def can_trade(*, dry_run: bool = False) -> bool:
    """AUDIT-14: Return True only if credentials are present (or dry_run is True).

    Convenience guard for callers that want a bool check rather than an exception.
    """
    if dry_run:
        return True
    try:
        _assert_kalshi_credentials_present()
        return True
    except RuntimeError:
        return False


async def _fetch_spot_prices_with_fallback(
    assets: tuple,
    *,
    http_session: Optional[Any] = None,
) -> Dict[str, float]:
    """Fetch spot prices with Coinbase → CoinGecko → Binance → last-known fallback.

    Coinbase is the primary source because Kalshi uses Coinbase as their reference
    exchange for crypto index prices.  Using Coinbase first keeps our internal spot
    prices aligned with Kalshi's reference and eliminates systematic drift (e.g. the
    ~$20 BTC offset observed when CoinGecko was used as primary).


    Returns a dict mapping asset symbols to USD prices.
    Assets whose price cannot be fetched (and have no recent last-known value)
    are omitted from the result.

    Parameters
    ----------
    assets:
        Tuple of asset symbols to fetch (e.g. ``("BTC", "ETH", "SOL")``).
    http_session:
        Optional ``aiohttp.ClientSession``; a new one is created if not provided.
    """
    import aiohttp

    prices: Dict[str, float] = {}
    remaining = list(assets)

    async def _fetch(session: aiohttp.ClientSession) -> None:
        nonlocal remaining

        # ── Coinbase (PRIMARY — single source of truth for Kalshi alignment) ──
        # Coinbase is Kalshi's reference exchange for crypto markets.  Using
        # it first keeps our spot prices aligned with Kalshi's reference price
        # and eliminates the ~$20 drift that CoinGecko aggregation can introduce.
        cb_remaining = list(remaining)
        for sym in list(cb_remaining):
            try:
                url = f"https://api.coinbase.com/v2/prices/{sym}-USD/spot"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        amount = data.get("data", {}).get("amount")
                        if amount:
                            prices[sym] = float(amount)
                            remaining = [a for a in remaining if a != sym]
                            logger.debug("Coinbase spot %s=%.4f", sym, prices[sym])
            except Exception as exc:
                logger.warning("Coinbase spot fetch failed for %s: %s", sym, exc)

        if not remaining:
            return

        # ── CoinGecko (SECONDARY fallback) ─────────────────────────────────
        ids = [_COINGECKO_IDS[a] for a in remaining if a in _COINGECKO_IDS]
        if ids:
            try:
                url = (
                    "https://api.coingecko.com/api/v3/simple/price"
                    f"?ids={','.join(ids)}&vs_currencies=usd"
                )
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        id_to_symbol = {v: k for k, v in _COINGECKO_IDS.items()}
                        for coin_id, vals in data.items():
                            sym = id_to_symbol.get(coin_id)
                            if sym and "usd" in vals:
                                prices[sym] = float(vals["usd"])
                                logger.debug(
                                    "CoinGecko fallback spot %s=%.4f (Coinbase unavailable)",
                                    sym, prices[sym],
                                )
                        remaining = [a for a in remaining if a not in prices]
                    else:
                        logger.warning("CoinGecko returned HTTP %d", resp.status)
            except Exception as exc:
                logger.warning("CoinGecko spot fetch failed: %s", exc)

        if not remaining:
            return

        # ── Binance (TERTIARY fallback) ────────────────────────────────────
        for sym in list(remaining):
            try:
                pair = f"{sym}USDT"
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price_str = data.get("price")
                        if price_str:
                            prices[sym] = float(price_str)
                            remaining = [a for a in remaining if a != sym]
                            logger.debug(
                                "Binance fallback spot %s=%.4f (Coinbase+CoinGecko unavailable)",
                                sym, prices[sym],
                            )
            except Exception as exc:
                logger.warning("Binance spot fetch failed for %s: %s", sym, exc)

    if http_session is not None:
        await _fetch(http_session)
    else:
        async with aiohttp.ClientSession() as session:
            await _fetch(session)

    # ── Last-known spot fallback ───────────────────────────────────────────
    now = time.monotonic()
    for sym in remaining:
        if sym in _last_known_spot:
            age = now - _last_known_spot_ts.get(sym, 0)
            if age <= _LAST_KNOWN_SPOT_MAX_AGE_SECONDS:
                logger.warning(
                    "Using last-known spot for %s (age=%.0fs) — all live feeds failed",
                    sym, age,
                )
                prices[sym] = _last_known_spot[sym]
            else:
                logger.error(
                    "Dropping %s from spot prices — all feeds failed and "
                    "last-known spot is too stale (age=%.0fs > %.0fs). "
                    "Markets for this asset will be filtered out.",
                    sym, age, _LAST_KNOWN_SPOT_MAX_AGE_SECONDS,
                )
        else:
            logger.error(
                "No spot price available for %s — all feeds failed, no last-known value. "
                "Markets for this asset will be filtered out.",
                sym,
            )

    # Update last-known cache for successful fetches
    for sym, price in prices.items():
        _last_known_spot[sym] = price
        _last_known_spot_ts[sym] = time.monotonic()

    return prices


# ── TradingCandidate (thin subclass of canonical MarketCandidate) ──────────

@dataclass
class TradingCandidate(MarketCandidate):
    """Extends the canonical MarketCandidate with trader-specific fields.

    ``group_id`` is the key used for group-level notional cap tracking.
    It is derived from the event_ticker / underlying / timeframe stored in
    the base ``MarketCandidate`` — never guessed locally.
    """

    group_id: str = ""
    tags: List[str] = field(default_factory=list)  # risk / sizing tags

    @classmethod
    def from_candidate(cls, candidate: MarketCandidate, group_id: str = "", tags: Optional[List[str]] = None) -> "TradingCandidate":
        """Promote a plain MarketCandidate to a TradingCandidate."""
        return cls(
            ticker=candidate.ticker,
            underlying=candidate.underlying,
            timeframe=candidate.timeframe,
            expiry_ts=candidate.expiry_ts,
            volume=candidate.volume,
            open_interest=candidate.open_interest,
            best_bid_cents=candidate.best_bid_cents,
            best_ask_cents=candidate.best_ask_cents,
            spread_cents=candidate.spread_cents,
            mid_price_cents=candidate.mid_price_cents,
            category=candidate.category,
            strike_price=candidate.strike_price,
            spot_price=candidate.spot_price,
            best_yes_bid=candidate.best_yes_bid,
            best_yes_ask=candidate.best_yes_ask,
            best_no_bid=candidate.best_no_bid,
            best_no_ask=candidate.best_no_ask,
            edge_pct=candidate.edge_pct,
            model_prob=candidate.model_prob,
            group_id=group_id or f"{candidate.underlying}_{candidate.timeframe}",
            tags=tags or [],
        )


# ── Risk state ────────────────────────────────────────────────────────────

@dataclass
class DailyRiskState:
    """Intra-day risk accounting for the continuous trader.

    ``group_notional`` maps group_id → total notional traded today.
    Fully reset by ``reset_daily()``.
    """

    group_notional: Dict[str, float] = field(default_factory=dict)
    daily_loss: float = 0.0
    trade_count: int = 0
    execution_rejections: int = 0

    def add_notional(self, group_id: str, amount: float) -> None:
        self.group_notional[group_id] = self.group_notional.get(group_id, 0.0) + amount

    def group_used(self, group_id: str) -> float:
        return self.group_notional.get(group_id, 0.0)

    def reset(self) -> None:
        """Clear all intra-day accumulators.  Called at daily rollover."""
        self.group_notional.clear()
        self.daily_loss = 0.0
        self.trade_count = 0
        self.execution_rejections = 0


# ── Sizing result ─────────────────────────────────────────────────────────

@dataclass
class SizingResult:
    """Output of ``signal_to_sizing`` — captures Kelly and sizing arithmetic."""
    edge: float = 0.0
    win_prob: float = 0.5
    payout_cents: float = 0.0
    kelly_raw: float = 0.0
    kelly_frac: float = 0.0
    size_contracts: int = 0
    notional_usd: float = 0.0
    source: str = "none"      # "signal" | "strategy" | "none"


# ── Trader ────────────────────────────────────────────────────────────────

class KalshiContinuousTrader:
    """Continuously discovers and trades Kalshi crypto prediction markets.

    Parameters
    ----------
    catalog:
        ``KalshiMarketCatalog`` instance; defaults to the process singleton.
    strategy:
        An ``OpinionStrategy`` used to generate swarm consensus opinions.
        ``_apply_confidence_clamp`` is always called before sizing.
    max_group_notional:
        Per-group notional cap ($) for daily risk.  Exceeded groups are
        skipped until ``reset_daily()`` is called.
    min_confidence:
        Minimum clamped confidence to proceed to execution.
    bankroll_fraction:
        Maximum fraction of bankroll per individual trade.
    max_yes_price:
        Hard cap (in dollars, e.g. 0.50 = 50¢) on the YES price the trader
        will pay per contract.  Any YES intent whose implied price exceeds
        this cap is dropped with a ``max_yes_price_cap`` rejection log.
        Configurable via ``MERID_MAX_YES_PRICE`` env var; default 0.50.
    """

    def __init__(
        self,
        catalog: Optional[KalshiMarketCatalog] = None,
        strategy: Optional[OpinionStrategy] = None,
        max_group_notional: float = _DEFAULT_MAX_GROUP_NOTIONAL,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        bankroll_fraction: float = _DEFAULT_BANKROLL_FRACTION,
        max_yes_price: float = _DEFAULT_MAX_YES_PRICE,
        kelly_fraction: float = _DEFAULT_KELLY_FRACTION,
        min_edge: float = _DEFAULT_MIN_EDGE,
        dry_run: bool = False,
        # AUDIT-02..08: protect/size caps
        max_candidates_per_asset: int = _DEFAULT_MAX_CANDIDATES_PER_ASSET,
        max_spread_cents: int = _DEFAULT_MAX_SPREAD_CENTS,
        min_volume: int = _DEFAULT_MIN_VOLUME,
        min_price_cents: Optional[int] = None,
        max_price_cents: Optional[int] = None,
        max_position_contracts: int = _DEFAULT_MAX_POSITION_CONTRACTS,
        exposure_multiplier: float = _DEFAULT_EXPOSURE_MULTIPLIER,
        per_asset_cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
        daily_loss_limit_pct: float = _DEFAULT_DAILY_LOSS_LIMIT_PCT,
    ) -> None:
        self._catalog = catalog or get_market_catalog()
        self._strategy = strategy
        self._max_group_notional = max_group_notional
        self._min_confidence = min_confidence
        self._bankroll_fraction = bankroll_fraction
        self._max_yes_price = max_yes_price
        self._kelly_fraction = kelly_fraction
        self._min_edge = min_edge
        # AUDIT-02..08: protect/size caps
        self._max_candidates_per_asset = max_candidates_per_asset
        self._max_spread_cents = max_spread_cents
        self._min_volume = min_volume
        self._min_price_cents = (
            int(os.getenv("MERID_CT_MIN_PRICE_CENTS", "2"))
            if min_price_cents is None
            else int(min_price_cents)
        )
        self._max_price_cents = (
            int(os.getenv("MERID_CT_MAX_PRICE_CENTS", "98"))
            if max_price_cents is None
            else int(max_price_cents)
        )
        self._max_position_contracts = max_position_contracts
        self._exposure_multiplier = exposure_multiplier
        self._per_asset_cooldown_seconds = per_asset_cooldown_seconds
        self._last_trade_ts: Dict[str, float] = {}  # asset → last trade timestamp
        # Daily loss limit: stop trading for the rest of the day when realized
        # losses exceed this fraction of the session-start bankroll.
        # 0.0 means "disabled" — no daily loss cap is applied.
        self._daily_loss_limit_pct: float = max(0.0, daily_loss_limit_pct)

        # ── Canary mode state ────────────────────────────────────────────────
        # When MERID_CT_CANARY_MODE=true, CT emits a tiny ($1) diagnostic intent
        # once per interval per asset to prove end-to-end execution is wired.
        # Tracks the timestamp of the last canary intent emitted per asset.
        self._canary_last_ts: Dict[str, float] = {a: 0.0 for a in _CRYPTO_ASSETS}
        self._canary_mode: bool = _CANARY_MODE
        self._canary_notional: float = _CANARY_NOTIONAL
        self._canary_interval_secs: float = _CANARY_INTERVAL_SECS

        if not 0 <= self._min_price_cents < self._max_price_cents <= 99:
            raise ValueError(
                "CT price band must satisfy 0 <= min_price_cents < max_price_cents <= 99"
            )

        # AUDIT-14: dry_run flag; when False, credentials are verified before
        # any live order submission.
        self._dry_run: bool = dry_run or (
            os.getenv("MERID_CT_DRY_RUN", "false").lower().strip() in ("1", "true", "yes")
        )

        # AUDIT-14: Fail fast if live Kalshi credentials are absent and not dry-run.
        if not self._dry_run:
            _assert_kalshi_credentials_present()

        self._risk = DailyRiskState()
        self._filter_config = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            allowed_timeframes=list(_CRYPTO_TIMEFRAMES),
            # Disable the pre-CT dead zone filter.  The dead zone check rejects
            # markets whose mid price is within ±N¢ of 50¢ — but short-term crypto
            # binary options routinely trade at 47-53¢ when the outcome is uncertain.
            # CT has its own per-asset/timeframe edge thresholds (EDGE_THRESHOLDS) so
            # the pre-filter version is both redundant and counterproductive here.
            min_edge_dead_zone_pct=0.0,
            # AUDIT-02..08: wire env-driven filter caps
            max_candidates_per_asset=self._max_candidates_per_asset,
            max_spread_cents=self._max_spread_cents,
            min_volume=self._min_volume,
            # Keep the prefilter broad and let max_yes_price enforce execution-side caps.
            min_price_cents=self._min_price_cents,
            max_price_cents=self._max_price_cents,
        )
        self._filter = MarketFilter(self._filter_config)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._candidates: List[TradingCandidate] = []

        # ── Filter telemetry ────────────────────────────────────────────────
        # Aggregated filter stats from the most recent _refresh_candidates() call.
        # Empty dict until the first scan completes.
        self._last_scan_filter_stats: Dict[str, Any] = {}
        # Per-asset/timeframe candidate counts from the most recent scan.
        # Shape: {asset: {timeframe: count}}.  Used by trade_cycle() to populate
        # scan_by_asset_timeframe in _last_cycle_stats for the pipeline audit.
        self._last_scan_asset_counts: Dict[str, Dict[str, int]] = {}
        # Rolling history of per-scan volume_band_block_rate values (oldest first).
        # Capped at _VOLUME_BAND_RATE_HISTORY_MAXLEN entries.
        self._volume_band_rate_history: Deque[float] = deque(
            maxlen=_VOLUME_BAND_RATE_HISTORY_MAXLEN
        )

        # ── Cycle diagnostics ────────────────────────────────────────────────
        # Per-cycle stats from the most recent trade_cycle() call.
        # Empty dict until the first cycle completes.
        self._last_cycle_stats: Dict[str, Any] = {}
        # LEAK-010: Track consecutive zero-intent cycles for alerting
        self._consecutive_zero_intent_cycles: int = 0

        # ── Bankroll invariant state ─────────────────────────────────────────
        # Accumulated realized PnL (in cents) across all CT-owned settled markets.
        # Updated by record_trade_result() at settlement time via reconciliation.
        # Never updated at fill time — PnL is only realized when a market resolves.
        self._total_pnl_cents: int = 0
        # Accumulated fees (in cents) charged across all CT orders.
        # Updated at fill time via record_fee().  Used in bankroll invariant check.
        self._total_fees_cents: int = 0
        # Balance snapshot (cents) captured on the first check_bankroll_invariant()
        # call each session.  Used as the baseline for measuring actual PnL.
        self._session_start_balance_cents: Optional[int] = None
        # Canonical bankroll snapshot (cash + portfolio mark - fees) captured on the
        # first invariant check. This is the authoritative baseline for comparing
        # snapshot bankroll vs internally-accounted realized PnL.
        self._session_start_bankroll_cents: Optional[int] = None
        # Result from the most recent check_bankroll_invariant() call.
        # Empty dict until the first cycle that supplies balance/portfolio data.
        self._last_invariant_status: Dict[str, Any] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        # ── DEPRECATION WARNING ───────────────────────────────────────────────
        # KalshiContinuousTrader is DEPRECATED and NOT started by main.py.
        # The production system uses AgentGrid (merid/prediction/agent_grid.py)
        # which is started in web/main.py _app_lifespan Phase 0.5.
        #
        # This class remains for:
        # - API compatibility (/api/v1/ct/* endpoints)
        # - Reconciliation hooks (merid/reconciliation.py)
        # - Manual/CLI usage (scripts, debugging)
        #
        # DO NOT call this method in production startup code.
        logger.warning(
            "⚠️  KalshiContinuousTrader.start() called — this is DEPRECATED. "
            "Production uses AgentGrid (merid.prediction.agent_grid). "
            "CT is kept for API/reconciliation compatibility only."
        )

        # ── AUDIT-15: smoke-test mode guard ──────────────────────────────────
        # Reject startup if MERID_SMOKE_TEST=true is set alongside any live-mode
        # flag.  This prevents accidental live trading during smoke tests.
        _check_smoke_test_live_mode_conflict()

        self._running = True
        logger.info(
            "KalshiContinuousTrader starting — assets=%s timeframes=%s "
            "max_yes_price=%.2f min_confidence=%.2f bankroll_fraction=%.4f "
            "prefilter_price_band=%d-%d¢",
            _CRYPTO_ASSETS, _CRYPTO_TIMEFRAMES,
            self._max_yes_price, self._min_confidence, self._bankroll_fraction,
            self._min_price_cents, self._max_price_cents,
        )
        await self._refresh_candidates()

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("KalshiContinuousTrader stopped")

    # ── Candidate discovery ───────────────────────────────────────────────

    async def _refresh_candidates(self) -> List[TradingCandidate]:
        """Pull fresh candidates from catalog + filter pipeline."""
        new_candidates: List[TradingCandidate] = []
        asset_counts: Dict[str, Dict[str, int]] = {}
        spot_prices = await _fetch_spot_prices_with_fallback(_CRYPTO_ASSETS)

        # Accumulators for cross-asset/timeframe filter telemetry for this scan run.
        scan_total_input: int = 0
        scan_rejected_volume_band: int = 0
        scan_rejected_edge_deadzone: int = 0
        scan_rejected_distance: int = 0
        scan_rejected_price: int = 0
        scan_rejected_spread: int = 0
        scan_rejected_volume: int = 0
        scan_rejected_missing_spot: int = 0

        for asset in _CRYPTO_ASSETS:
            asset_spot = spot_prices.get(asset)
            if asset_spot is None:
                logger.warning(
                    "ContinuousTrader: no spot price for %s during candidate refresh; "
                    "distance-based filtering may reject this asset's markets",
                    asset,
                )
            for tf in _CRYPTO_TIMEFRAMES:
                # Gate on strategy_catalog.yaml enabled flags.
                # _CATALOG_ENABLED[(asset, tf)] == False → skip this cell.
                # A missing key means the cell is implicitly enabled.
                if _CATALOG_ENABLED.get((asset, tf)) is False:
                    logger.debug(
                        "ContinuousTrader: (%s, %s) disabled in strategy_catalog.yaml — skipping",
                        asset, tf,
                    )
                    continue

                catalog_markets = self._catalog.get_markets_by_asset(asset, timeframe=tf)
                if not catalog_markets:
                    logger.debug("ContinuousTrader: no catalog markets for %s %s", asset, tf)
                    continue

                # Convert catalog → base MarketCandidate list for filter.
                # Try to extract real bid/ask/mid prices from the EventMarket outcomes
                # so that the spread filter and CT's signal_to_sizing work with real
                # book data instead of fallback constants.
                raw_candidates = []
                for cm in catalog_markets:
                    best_bid_cents: int = 0
                    best_ask_cents: int = 0
                    mid_price_cents: int = 0

                    try:
                        outcomes = getattr(cm.market, "outcomes", None) or []
                        yes_outcome = next(
                            (o for o in outcomes if getattr(o, "outcome_id", "").lower() == "yes"),
                            None,
                        )
                        if yes_outcome is not None:
                            raw_bid = getattr(yes_outcome, "best_bid", None)
                            raw_ask = getattr(yes_outcome, "best_ask", None)
                            # Kalshi API prices are in cents (1-99 integer range).
                            # Guard against 0.0-1.0 decimal format by checking magnitude.
                            if raw_bid is not None and raw_ask is not None:
                                bid_float = float(raw_bid)
                                ask_float = float(raw_ask)
                                # Convert decimal (0-1) to cents if needed
                                if bid_float <= 1.0 and bid_float > 0.0:
                                    bid_float *= 100
                                    ask_float *= 100
                                best_bid_cents = int(round(bid_float))
                                best_ask_cents = int(round(ask_float))
                                if best_bid_cents > 0 and best_ask_cents > 0:
                                    mid_price_cents = (best_bid_cents + best_ask_cents) // 2
                    except Exception as exc:
                        logger.debug(
                            "ContinuousTrader price enrichment best-effort skip for %s; "
                            "candidate will continue without mid-price context: %s",
                            getattr(cm.market, "market_id", "unknown"),
                            exc,
                        )

                    raw_candidates.append(
                        MarketCandidate(
                            ticker=cm.market.market_id,
                            underlying=asset,
                            timeframe=tf,
                            expiry_ts=cm.expires_at.timestamp() if cm.expires_at else 0.0,
                            volume=int(cm.market.volume) if cm.market.volume else 0,
                            open_interest=int(cm.market.open_interest) if cm.market.open_interest else 0,
                            category=cm.category or "",
                            strike_price=cm.strike_price,
                            spot_price=asset_spot,
                            best_bid_cents=best_bid_cents,
                            best_ask_cents=best_ask_cents,
                            mid_price_cents=mid_price_cents,
                        )
                    )

                filter_result = self._filter.filter_markets(raw_candidates)
                if filter_result.rejected_price > 0:
                    priced_candidates = [c for c in raw_candidates if c.mid_price_cents > 0]
                    price_reject_samples: List[str] = []
                    for candidate in priced_candidates:
                        passed, reason = self._filter.evaluate(candidate)
                        if passed or not reason.startswith("price "):
                            continue
                        price_reject_samples.append(
                            f"{candidate.ticker}(bid={candidate.best_bid_cents}¢ "
                            f"ask={candidate.best_ask_cents}¢ mid={candidate.mid_price_cents}¢)"
                        )
                        if len(price_reject_samples) >= 5:
                            break
                    if priced_candidates:
                        mid_prices = [c.mid_price_cents for c in priced_candidates]
                        logger.warning(
                            "ContinuousTrader price-band rejects %s %s: band=%d-%d¢ "
                            "priced=%d rejected=%d mid_range=%d-%d¢ samples=%s",
                            asset,
                            tf,
                            self._min_price_cents,
                            self._max_price_cents,
                            len(priced_candidates),
                            filter_result.rejected_price,
                            min(mid_prices),
                            max(mid_prices),
                            price_reject_samples or ["none"],
                        )
                for c in filter_result.candidates:
                    new_candidates.append(
                        TradingCandidate.from_candidate(c)
                    )

                counts = asset_counts.setdefault(asset, {})
                counts[tf] = len(filter_result.candidates)

                # Log per-asset/timeframe filter drops at DEBUG so individual filter
                # vetoes are visible in logs without flooding INFO.
                if filter_result.total_input > 0 and filter_result.passed < filter_result.total_input:
                    logger.debug(
                        "ContinuousTrader filter %s %s: "
                        "input=%d passed=%d | "
                        "vol_band=%d spread=%d price=%d distance=%d dead_zone=%d vol=%d oi=%d cap=%d",
                        asset, tf,
                        filter_result.total_input, filter_result.passed,
                        filter_result.rejected_volume_band,
                        filter_result.rejected_spread,
                        filter_result.rejected_price,
                        filter_result.rejected_distance,
                        filter_result.rejected_edge_deadzone,
                        filter_result.rejected_volume,
                        filter_result.rejected_oi,
                        filter_result.capped_per_asset,
                    )

                # Accumulate filter telemetry across all (asset, timeframe) loops.
                scan_total_input += filter_result.total_input
                scan_rejected_volume_band += filter_result.rejected_volume_band
                scan_rejected_edge_deadzone += filter_result.rejected_edge_deadzone
                scan_rejected_distance += filter_result.rejected_distance
                scan_rejected_price += filter_result.rejected_price
                scan_rejected_spread += filter_result.rejected_spread
                scan_rejected_volume += filter_result.rejected_volume
                scan_rejected_missing_spot += filter_result.rejected_missing_spot

                # Yield to event loop after processing each asset-timeframe combination
                await asyncio.sleep(0)

        # Compute per-scan volume-band block rate and update rolling history.
        scan_block_rate = (
            scan_rejected_volume_band / scan_total_input
            if scan_total_input > 0
            else 0.0
        )
        self._volume_band_rate_history.append(scan_block_rate)

        # Store aggregated stats for the most recent scan so status() can expose them.
        rolling_avg = (
            sum(self._volume_band_rate_history) / len(self._volume_band_rate_history)
            if self._volume_band_rate_history
            else 0.0
        )
        self._last_scan_filter_stats = {
            "scan_total_input": scan_total_input,
            "scan_rejected_volume_band": scan_rejected_volume_band,
            "scan_rejected_edge_deadzone": scan_rejected_edge_deadzone,
            "scan_rejected_distance": scan_rejected_distance,
            "scan_rejected_price": scan_rejected_price,
            "scan_rejected_spread": scan_rejected_spread,
            "scan_rejected_volume": scan_rejected_volume,
            "scan_rejected_missing_spot": scan_rejected_missing_spot,
            "volume_band_block_rate": round(scan_block_rate, 4),
            "volume_band_block_rate_rolling_avg": round(rolling_avg, 4),
            "rolling_window_scans": len(self._volume_band_rate_history),
        }
        # Build a concise summary of ALL non-zero filter drops for the INFO log line.
        drops = []
        if scan_rejected_edge_deadzone:
            drops.append(f"dead_zone={scan_rejected_edge_deadzone}")
        if scan_rejected_distance:
            drops.append(f"distance={scan_rejected_distance}")
        if scan_rejected_price:
            drops.append(f"price={scan_rejected_price}")
        if scan_rejected_spread:
            drops.append(f"spread={scan_rejected_spread}")
        if scan_rejected_volume:
            drops.append(f"volume={scan_rejected_volume}")
        if scan_rejected_volume_band:
            drops.append(f"vol_band={scan_rejected_volume_band}")
        if scan_rejected_missing_spot:
            drops.append(f"missing_spot={scan_rejected_missing_spot}")
        drop_summary = " ".join(drops) if drops else "none"
        logger.info(
            "ContinuousTrader filter: total_input=%d volume_band_rejected=%d "
            "block_rate=%.3f rolling_avg=%.3f (window=%d scans) drops=[%s]",
            scan_total_input, scan_rejected_volume_band,
            scan_block_rate, rolling_avg, len(self._volume_band_rate_history),
            drop_summary,
        )
        if scan_rejected_edge_deadzone > 0:
            logger.warning(
                "ContinuousTrader: %d candidates dropped by dead-zone filter "
                "(mid_price within ±%.1f¢ of 50¢).  "
                "Consider lowering min_edge_dead_zone_pct or enriching book prices.",
                scan_rejected_edge_deadzone,
                self._filter_config.min_edge_dead_zone_pct,
            )

        if scan_rejected_distance > 0:
            # Build a per-(asset, timeframe) spot-band map so operators can see
            # which specific band thresholds are dropping candidates.
            band_info = {
                f"{a}/{tf}": get_spot_band(a, tf, default=self._filter_config.spot_band_pct)
                for a in _CRYPTO_ASSETS
                for tf in _CRYPTO_TIMEFRAMES
            }
            logger.warning(
                "ContinuousTrader: %d candidates dropped by distance/edge filters "
                "(strike too far from spot). "
                "Default spot_band_pct=%.1f%%. "
                "Per-(asset/tf) effective bands: %s. "
                "Consider widening SPOT_BANDS or checking spot-price feed.",
                scan_rejected_distance,
                self._filter_config.spot_band_pct,
                ", ".join(f"{k}=±{v:.1f}%" for k, v in sorted(band_info.items())),
            )

        # Log per-asset/timeframe counts at INFO level
        for asset, tfs in asset_counts.items():
            for tf, cnt in tfs.items():
                logger.info(
                    "ContinuousTrader candidates: %s %s = %d", asset, tf, cnt
                )

        # 15m observability — explicitly log the state of every 15m cell so
        # silent blocking is immediately visible in the logs.
        fifteen_min_cells = [
            (a, "15m") for a in _CRYPTO_ASSETS
        ]
        fifteen_min_summary = []
        for a, tf in fifteen_min_cells:
            if _CATALOG_ENABLED.get((a, tf)) is False:
                fifteen_min_summary.append(f"{a}=catalog_disabled")
            else:
                cnt = asset_counts.get(a, {}).get(tf, 0)
                fifteen_min_summary.append(f"{a}={cnt}")
        logger.info(
            "CT-15M-SCAN candidates_by_asset: %s",
            " ".join(fifteen_min_summary),
        )

        self._candidates = new_candidates
        # Persist per-asset/timeframe counts so trade_cycle() can include them in
        # _last_cycle_stats["scan_by_asset_timeframe"] for the pipeline audit.
        self._last_scan_asset_counts = {
            asset: dict(tfs) for asset, tfs in asset_counts.items()
        }
        logger.info(
            "ContinuousTrader: %d total candidates across %d asset/timeframe pairs",
            len(new_candidates), sum(len(v) for v in asset_counts.values()),
        )

        # AUDIT-20: When CT resolves zero candidates for all assets, log CRITICAL
        # and stop the trader rather than silently continuing with no markets.
        if len(new_candidates) == 0 and scan_total_input == 0:
            logger.critical(
                "ContinuousTrader: zero candidates found across ALL assets and timeframes. "
                "The catalog may be empty, unauthenticated, or all markets are filtered out. "
                "Halting CT to avoid running a no-op loop.  "
                "Check catalog connectivity and filter config."
            )
            self._running = False

        return new_candidates

    # ── Sizing / risk ─────────────────────────────────────────────────────

    def _get_min_edge(self, candidate: TradingCandidate) -> float:
        """Get the minimum edge threshold for a candidate based on asset and timeframe.

        Priority:
          1. ``KALSHI_CT_MIN_EDGE_{ASSET}_{TF}`` env var override (AUDIT-09).
          2. Active EDGE_THRESHOLDS grid (profile-selected).
          3. ``self._min_edge`` global fallback.

        Args:
            candidate: The trading candidate to evaluate.

        Returns:
            Minimum edge threshold as a decimal (e.g., 0.03 for 3%).
        """
        asset = candidate.underlying.upper()
        tf = candidate.timeframe.lower()

        # AUDIT-09: env-var override takes highest priority
        env_key = f"KALSHI_CT_MIN_EDGE_{asset}_{tf.upper().replace('-', '_')}"
        env_raw = os.getenv(env_key)
        if env_raw is not None:
            try:
                return float(env_raw)
            except ValueError:
                logger.warning("Invalid %s=%r — using grid value", env_key, env_raw)

        key = (asset, tf)
        return EDGE_THRESHOLDS.get(key, self._min_edge)

    def signal_to_sizing(
        self,
        candidate: TradingCandidate,
        bankroll: float,
        *,
        edge_override: Optional[float] = None,
        win_prob_override: Optional[float] = None,
        estimate: Optional[OpinionEstimate] = None,
    ) -> SizingResult:
        """Compute Kelly-based sizing from candidate edge and market data.

        Sources edge from (in priority order):
          1. ``edge_override`` parameter (for testing / manual injection).
          2. ``candidate.edge_pct`` (enriched from signal layer; percentage units,
             e.g. 3.0 → 3% edge; converted to decimal via ``/ 100.0``).
          3. ``estimate.edge`` — pass the ``OpinionEstimate`` from the caller to
             reuse a pre-computed strategy result and avoid a second evaluation.
             If ``estimate`` is not provided, falls back to calling
             ``evaluate_candidate`` internally.
          4. Fallback to 0 (no edge → no trade).

        Uses the binary Kelly formula::

            implied_prob  = mid_price / 100
            win_prob      = implied_prob + edge
            payout        = 100 - price_cents
            b             = payout / price_cents
            kelly_raw     = (p * b - q) / b
            kelly_frac    = kelly_raw * kelly_fraction

        BUG-010 FIX: Uses execution price (best_ask for YES, best_bid for NO)
        instead of mid_price when available. Direction is inferred from edge sign.

        Note: ``size_contracts`` returned here is based purely on Kelly notional.
        The caller (``trade_cycle``) must recompute ``size_contracts`` from the
        final ``notional`` after applying ``exposure_multiplier`` and any other
        caps, to keep the two values consistent.

        Returns a ``SizingResult`` with all intermediate values for audit.
        """
        # BUG-010: Determine execution price based on trade direction
        # If we have positive edge, we're buying YES (use best_ask)
        # If we have negative edge, we're buying NO (use best_bid)
        # Fall back to mid_price if book data unavailable
        mid_price_cents = candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS

        # 1. Resolve edge first to determine direction (priority: override > candidate signal > strategy > 0)
        edge = 0.0
        source = "none"

        # Need implied_prob for estimate evaluation, use mid_price temporarily
        temp_implied_prob = mid_price_cents / 100.0

        if edge_override is not None:
            edge = edge_override
            source = "override"
        elif candidate.edge_pct is not None and candidate.edge_pct != 0.0:
            # edge_pct is in percentage units (e.g. 3.0 = 3% edge); convert to fraction
            edge = candidate.edge_pct / 100.0
            source = "signal"
        else:
            # Try strategy-based edge.  Reuse caller-provided estimate to avoid
            # invoking evaluate_candidate a second time per candidate (single
            # sizing pipeline — see module docstring).
            if estimate is None:
                mid_prob = temp_implied_prob if temp_implied_prob > 0 else 0.5
                estimate = self.evaluate_candidate(candidate, market_prob=mid_prob)
            if estimate is not None and estimate.edge != 0.0:
                edge = estimate.edge
                source = "strategy"

        # BUG-010: Now that we know the edge, determine execution price
        # Positive edge with estimate means we think YES is underpriced → buy YES at best_ask
        # Negative edge or estimate.agent_prob < mid means buy NO at best_bid
        if estimate is not None and estimate.agent_prob > temp_implied_prob:
            # Buying YES - use best_ask
            price_cents = candidate.best_ask_cents or mid_price_cents
        else:
            # Buying NO - use best_bid (inverted: we pay 100 - best_bid for a NO contract)
            # For NO contracts, our cost is (100 - bid_for_yes)
            # But for Kelly sizing we still use the YES-side price as reference
            price_cents = candidate.best_bid_cents or mid_price_cents

        # Recompute implied_prob from execution price
        implied_prob = price_cents / 100.0

        # 2. Compute win probability
        if win_prob_override is not None:
            win_prob = win_prob_override
        else:
            win_prob = max(0.01, min(0.99, implied_prob + edge))

        # 3. Kelly formula for binary contract
        payout_cents = 100 - price_cents
        if price_cents <= 0 or price_cents >= 100 or payout_cents <= 0:
            result = SizingResult(edge=edge, win_prob=win_prob, source=source)
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) source=%s",
                candidate.ticker, edge, win_prob, 0.0, 0.0, 0.0,
                self._kelly_fraction * 100, source,
            )
            return result

        b = payout_cents / price_cents  # net odds ratio
        p = win_prob
        q = 1.0 - p
        kelly_raw = (p * b - q) / b if b > 0 else 0.0

        # Get the appropriate minimum edge threshold for this candidate
        min_edge_threshold = self._get_min_edge(candidate)

        # Fee profitability gate: reject if edge doesn't cover fee impact
        # Import fee calculation from order router
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents

        fee_cents = _kalshi_fee_cents(price_cents, 1)  # Fee for 1 contract
        fee_impact = fee_cents / payout_cents if payout_cents > 0 else 1.0

        if edge < fee_impact:
            result = SizingResult(
                edge=edge, win_prob=win_prob, payout_cents=float(payout_cents),
                kelly_raw=kelly_raw, source=source,
            )
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f fee=%d¢ fee_impact=%.4f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) source=%s REJECTED (edge < fee_impact)",
                candidate.ticker, edge, win_prob, float(payout_cents), fee_cents, fee_impact,
                kelly_raw, 0.0, self._kelly_fraction * 100, source,
            )
            return result

        # Clamp negative Kelly → no trade; negative edge always skips regardless of magnitude
        if kelly_raw <= 0 or edge < min_edge_threshold:
            result = SizingResult(
                edge=edge, win_prob=win_prob, payout_cents=float(payout_cents),
                kelly_raw=kelly_raw, source=source,
            )
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) source=%s min_edge_threshold=%.4f [%s/%s] REJECTED",
                candidate.ticker, edge, win_prob, float(payout_cents),
                kelly_raw, 0.0, self._kelly_fraction * 100, source,
                min_edge_threshold, candidate.underlying, candidate.timeframe,
            )
            return result

        # Resolve per-cell Kelly fraction: catalog overrides the global default.
        # Priority: catalog per-cell > self._kelly_fraction (global default).
        _cell_key = (candidate.underlying.upper(), candidate.timeframe.lower())
        effective_kelly_fraction = _CATALOG_KELLY_FRACTION.get(_cell_key, self._kelly_fraction)

        kelly_frac = kelly_raw * effective_kelly_fraction
        notional = bankroll * kelly_frac
        price_dollars = price_cents / 100.0
        size_contracts = int(math.floor(notional / price_dollars))

        # Minimum viable notional check: reject if trade is too small to be profitable
        # Given typical fees of 2¢ per contract at 50¢ prices, we need at least
        # ~$1.00 notional (2 contracts) to have any chance of profitability.
        MIN_VIABLE_NOTIONAL_USD = 1.00
        if notional < MIN_VIABLE_NOTIONAL_USD or size_contracts == 0:
            result = SizingResult(
                edge=edge,
                win_prob=win_prob,
                payout_cents=float(payout_cents),
                kelly_raw=kelly_raw,
                kelly_frac=kelly_frac,
                size_contracts=0,  # Force to 0 to signal rejection
                notional_usd=notional,
                source=source,
            )
            logger.info(
                "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) notional=$%.4f size=%d source=%s "
                "REJECTED (notional < $%.2f minimum or size=0)",
                candidate.ticker, edge, win_prob, float(payout_cents),
                kelly_raw, kelly_frac, effective_kelly_fraction * 100,
                notional, size_contracts, source, MIN_VIABLE_NOTIONAL_USD,
            )
            return result

        result = SizingResult(
            edge=edge,
            win_prob=win_prob,
            payout_cents=float(payout_cents),
            kelly_raw=kelly_raw,
            kelly_frac=kelly_frac,
            size_contracts=size_contracts,
            notional_usd=notional,
            source=source,
        )
        logger.info(
            "signal_to_sizing: %s edge=%.4f win_prob=%.4f payout=%.2f | "
            "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) size=%d source=%s "
            "min_edge_threshold=%.4f [%s/%s] ACCEPTED",
            candidate.ticker, edge, win_prob, float(payout_cents),
            kelly_raw, kelly_frac, effective_kelly_fraction * 100,
            size_contracts, source,
            min_edge_threshold, candidate.underlying, candidate.timeframe,
        )
        return result

    def _apply_risk_checks(
        self,
        candidate: TradingCandidate,
        estimate: OpinionEstimate,
        bankroll: float,
    ) -> Optional[float]:
        """Return approved max notional ($) or None if any risk check fails.

        Enforces the following constraints in order:
          1. **Group notional cap** — logged when blocked.
             Production threshold: MERID_GROUP_NOTIONAL_PCT × bankroll (default 5%).
          2. **Confidence gate** — logged when blocked.
             Production threshold: MERID_MIN_CONFIDENCE (default 0.55).
          3. **Per-cell max risk cap** — limits each trade to the catalog's
             max_risk_per_trade_pct fraction of bankroll (e.g. 0.5–2%).

        Returns the maximum permitted notional for this trade; callers further
        cap to ``min(returned_cap, kelly_notional)`` so Kelly drives actual size.

        Uses group_id from the canonical TradingCandidate (never a local guess).
        """
        # Resolve effective group notional cap.
        # Use the more conservative of: percentage-based cap and hard-dollar cap.
        # This ensures explicitly configured hard caps are always respected while
        # allowing the percentage-based cap to automatically scale with bankroll.
        if _GROUP_NOTIONAL_PCT > 0 and bankroll > 0:
            pct_cap = bankroll * _GROUP_NOTIONAL_PCT
            effective_group_cap = min(pct_cap, self._max_group_notional) \
                if self._max_group_notional > 0 else pct_cap
        else:
            effective_group_cap = self._max_group_notional

        # Group notional cap
        group_used = self._risk.group_used(candidate.group_id)
        if group_used >= effective_group_cap:
            logger.debug(
                "ContinuousTrader: group_notional_cap hit group=%s used=%.2f cap=%.2f",
                candidate.group_id, group_used, effective_group_cap,
            )
            self._risk.execution_rejections += 1
            self._emit_rejection(candidate.ticker, "group_notional_cap")
            return None

        # Confidence gate (post-clamp)
        if estimate.confidence < self._min_confidence:
            self._risk.execution_rejections += 1
            self._emit_rejection(candidate.ticker, "low_confidence")
            return None

        # Per-cell max risk cap: catalog overrides global bankroll_fraction.
        # This caps notional at max_risk_per_trade_pct of bankroll regardless of
        # what Kelly suggests, providing a hard upper bound per trade.
        _cell_key = (candidate.underlying.upper(), candidate.timeframe.lower())
        cell_max_risk = _CATALOG_MAX_RISK_PCT.get(_cell_key, self._bankroll_fraction)
        notional = bankroll * cell_max_risk
        remaining_cap = effective_group_cap - group_used
        notional = min(notional, remaining_cap)
        return notional if notional > 0 else None

    # ── Consensus / estimate ──────────────────────────────────────────────

    def evaluate_candidate(
        self,
        candidate: TradingCandidate,
        market_prob: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        """Run the wired strategy, applying confidence clamp.

        Returns None if no strategy is wired or if the strategy declines.
        """
        if self._strategy is None:
            logger.debug(
                "[CT-UPSTREAM] ticker=%s asset=%s tf=%s veto=no_strategy_wired",
                candidate.ticker, candidate.underlying, candidate.timeframe,
            )
            return None

        explanation = OpinionExplanation(inputs_used=[], contributions={}, rationale="")
        estimate = self._strategy.estimate(
            agent_id="continuous_trader",
            ticker=candidate.ticker,
            market_prob=market_prob,
            category=candidate.category,
            context=context,
        )

        if estimate is None:
            logger.info(
                "[CT-UPSTREAM] ticker=%s asset=%s tf=%s strategy=%s market_prob=%.4f "
                "veto=strategy_declined reason=min_edge_or_extreme_prob",
                candidate.ticker, candidate.underlying, candidate.timeframe,
                getattr(self._strategy, 'name', 'unknown'), market_prob,
            )
            return None

        # Log successful estimate with strategy details
        logger.info(
            "[CT-UPSTREAM] ticker=%s asset=%s tf=%s strategy=%s market_prob=%.4f "
            "model_prob=%.4f edge=%.4f confidence=%.4f reasoning=%s sources=%s",
            candidate.ticker, candidate.underlying, candidate.timeframe,
            getattr(self._strategy, 'name', 'unknown'), market_prob,
            estimate.agent_prob, estimate.edge, estimate.confidence,
            estimate.reasoning_tag, ','.join(estimate.signal_sources),
        )

        # Always apply the confidence clamp from the wired strategy
        clamped_conf = self._strategy._apply_confidence_clamp(estimate.confidence, explanation)
        if clamped_conf != estimate.confidence:
            logger.debug(
                "[CT-UPSTREAM] ticker=%s confidence_clamped from=%.4f to=%.4f",
                candidate.ticker, estimate.confidence, clamped_conf,
            )

        return OpinionEstimate(
            agent_prob=estimate.agent_prob,
            confidence=clamped_conf,
            edge=estimate.edge,
            reasoning_tag=estimate.reasoning_tag,
            signal_sources=estimate.signal_sources,
        )

    # ── Trade cycle ───────────────────────────────────────────────────────

    def _inject_canary_intents(
        self,
        intents: List[Dict[str, Any]],
        bankroll: float,
        per_asset_stats: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Inject tiny canary intents for assets that have been silent too long.

        When canary mode is enabled (``MERID_CT_CANARY_MODE=true``), CT must emit
        at least one intent per asset every ``_canary_interval_secs``.  When an
        asset has no real intents and its canary timer has elapsed, a synthetic
        $1 diagnostic intent is added to the output list.

        The canary intent is flagged with ``"canary": True`` so the caller can
        submit it to Kalshi REST (proving the execution path is wired) and report
        it separately from normal intents.

        If no candidate for the asset is available in ``_candidates``, the canary
        is skipped for this cycle (the signal would be meaningless without a real
        market to target).
        """
        now = time.time()
        assets_with_intents: set = {i["underlying"] for i in intents}

        for asset in _CRYPTO_ASSETS:
            if asset in assets_with_intents:
                # Already have a real intent — reset canary timer and skip.
                self._canary_last_ts[asset] = now
                continue

            elapsed = now - self._canary_last_ts.get(asset, 0.0)
            if elapsed < self._canary_interval_secs:
                continue  # Still within interval — no canary needed yet.

            # Find the first available candidate for this asset.
            candidate = next(
                (c for c in self._candidates if c.underlying == asset),
                None,
            )
            if candidate is None:
                logger.warning(
                    "[CANARY] asset=%s: no candidate available for canary intent — skip.",
                    asset,
                )
                continue

            mid_price_cents = candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
            mid_price_dollars = mid_price_cents / 100.0
            canary_contracts = max(1, int(math.floor(self._canary_notional / mid_price_dollars)))

            canary_intent = {
                "ticker": candidate.ticker,
                "underlying": candidate.underlying,
                "timeframe": candidate.timeframe,
                "group_id": candidate.group_id,
                "direction": "yes",
                "notional": self._canary_notional,
                "confidence": 0.0,
                "edge": 0.0,
                "kelly_raw": 0.0,
                "kelly_frac": 0.0,
                "size_contracts": canary_contracts,
                "sizing_source": "canary",
                "canary": True,
                "intent_id": generate_correlation_id(
                    datetime.now(timezone.utc), prefix="kalshi-canary"
                ),
                "ts": now,
            }
            intents.append(canary_intent)
            self._canary_last_ts[asset] = now

            logger.info(
                "[CANARY] asset=%s ticker=%s notional=%.2f contracts=%d — "
                "canary intent injected (%.0fs since last intent for this asset)",
                asset, candidate.ticker, self._canary_notional, canary_contracts, elapsed,
            )

        return intents

    async def trade_cycle(
        self,
        bankroll: float,
        spot_prices: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Run one trade evaluation cycle across all current candidates.

        Cycle skeleton:
          1. Refresh universe — pull fresh candidates from catalog + filter.
          2. Evaluate each candidate: edge, Kelly sizing, risk checks, price cap.
          3. Return approved intent dicts (caller submits orders).

        For each candidate:
          1. Enrich with spot price (if available).
          2. Compute edge and Kelly sizing via ``signal_to_sizing``.
          3. Fall back to strategy-based edge if no signal edge.
          4. Apply risk checks (group cap, confidence gate).
          5. Apply max-YES-price guard.

        Returns list of approved intent dicts (does NOT submit orders).
        """
        # Step 1: refresh universe — build candidates via catalog + filter pipeline.
        # This must run every cycle so that newly-listed markets are discovered and
        # expired / illiquid markets are dropped without restarting the trader.
        await self._refresh_candidates()

        # Snapshot execution gate once per tick — all entry decisions in this
        # cycle read from this snapshot. Components only READ from the gate;
        # they never set gate state.
        # Lazy import: core.execution_gate lives outside the merid package and
        # pulling it at module level creates a circular-import risk across the
        # broader monorepo. Importing inside the method is intentional and safe
        # because Python caches the module after the first import.
        # Fail-open (gate_view=None → assume clear): if the gate module itself
        # is broken the CT should continue with its own layered risk guards
        # (kill switch, risk caps, daily-loss limit) rather than silently halt
        # all trading. The gate snapshot failure is logged as a WARNING so
        # operators are alerted immediately.
        gate_view = None
        try:
            from core.execution_gate import check_execution_gate as _check_gate
            gate_view = _check_gate()
            # Log gate status at INFO only when not fully clear, so operators see it
            # without generating noise every cycle. "limited" (warnings only) does NOT
            # block CT entries — see entry-check comment below.
            if gate_view is not None and gate_view.gate_state != "clear":
                reasons_str = "; ".join(r.message for r in gate_view.reasons) if gate_view.reasons else "none"
                logger.info(
                    "[CT-GATE] execution_gate: state=%s blocked=%s safe_to_trade=%s reasons=[%s]",
                    gate_view.gate_state, gate_view.blocked, gate_view.safe_to_trade, reasons_str,
                )
        except Exception as _gate_exc:
            logger.warning(
                "[CT-GATE] Execution gate snapshot failed: %s — "
                "entries are NOT blocked by gate this cycle (fail-open fallback). "
                "Investigate gate module health.",
                _gate_exc,
            )

        intents = []
        candidates_seen = 0
        markets_with_any_edge = 0
        vetoed_by_reason: Dict[str, int] = {}
        ticker_diagnostics: List[Dict[str, Any]] = []

        # Per-asset tracking for pipeline audit and per-asset cycle summary.
        # {asset: {candidates_seen, evaluated, approved, vetoed, kelly_zero_count,
        #          veto_reasons, approved_orders_intent, orders_blocked_by_risk,
        #          orders_blocked_by_kill_switch}}
        per_asset_stats: Dict[str, Dict[str, Any]] = {
            a: {
                "candidates_seen": 0,
                "evaluated": 0,
                "approved": 0,
                "vetoed": 0,
                "kelly_zero_count": 0,
                "veto_reasons": {},
                "approved_orders_intent": 0,
                "orders_submitted": 0,
                "orders_blocked_by_risk": 0,
                "orders_blocked_by_kill_switch": 0,
            }
            for a in _CRYPTO_ASSETS
        }

        # Daily loss limit guard: if realized losses this session exceed the
        # configured fraction of the starting bankroll, flip into OBSERVE-ONLY
        # mode for the rest of the cycle (return empty intents but keep scanning).
        if self._daily_loss_limit_pct > 0.0 and bankroll > 0.0:
            _loss_limit_usd = bankroll * self._daily_loss_limit_pct
            if self._risk.daily_loss >= _loss_limit_usd:
                logger.warning(
                    "[CT-OBSERVE-ONLY] Daily loss limit reached: daily_loss=%.4f >= "
                    "limit=%.4f (%.1f%% of bankroll=%.2f). "
                    "Switching to OBSERVE-ONLY for this cycle — no new orders will be placed.",
                    self._risk.daily_loss,
                    _loss_limit_usd,
                    self._daily_loss_limit_pct * 100,
                    bankroll,
                )
                # Still build scan_by_asset_timeframe so the pipeline audit has data.
                self._last_cycle_stats = {
                    "candidates_seen": 0,
                    "markets_with_any_edge": 0,
                    "markets_after_risk_veto": 0,
                    "vetoed_total": 0,
                    "vetoed_by_reason": {"daily_loss_limit": len(self._candidates)},
                    "ticker_diagnostics": [],
                    "cycle_ts": time.time(),
                    "per_asset_stats": dict(per_asset_stats),
                    "scan_by_asset_timeframe": dict(self._last_scan_asset_counts),
                    "observe_only": True,
                    "observe_only_reason": "daily_loss_limit",
                }
                return []

        # BUG-011: Track remaining bankroll within cycle
        # Initialize with full bankroll, subtract approved notional after each intent
        remaining_bankroll = bankroll

        # Total aggregate crypto risk cap: stop approving further intents in this
        # cycle once cumulative notional exceeds bankroll × _TOTAL_CRYPTO_RISK_PCT.
        # Tracks notional committed across ALL groups and assets in this cycle.
        _cycle_total_notional: float = 0.0
        _total_crypto_risk_cap: float = (
            bankroll * _TOTAL_CRYPTO_RISK_PCT if _TOTAL_CRYPTO_RISK_PCT > 0 and bankroll > 0
            else float("inf")
        )

        for candidate in self._candidates:
            # Yield to event loop periodically during candidate processing
            await asyncio.sleep(0)

            candidates_seen += 1
            _asset = candidate.underlying
            _pas = per_asset_stats.get(_asset)
            if _pas is not None:
                _pas["candidates_seen"] += 1

            if spot_prices:
                candidate.spot_price = spot_prices.get(candidate.underlying)

            mid_prob = candidate.mid_price_cents / 100.0 if candidate.mid_price_cents else 0.5

            veto_reason = None
            # ── Execution gate entry check ──────────────────────────────
            # CT entries (new risk positions) are blocked ONLY when gate_state=blocked
            # (critical issues: kill switch, critical recon discrepancies, dead price feed).
            # gate_state=limited (warnings only: pnl_consistency drift, recon never-ran on
            # fresh start, paper recon issues) does NOT block entries — warnings are
            # informational and safe_to_trade=True means trading can proceed.
            # This is more permissive than the original entries_allowed check (which blocked
            # on both blocked AND limited), because limited-state warnings should not
            # prevent Kalshi crypto trading.
            if gate_view is not None and gate_view.blocked:
                veto_reason = "execution_gate_entries_disabled"
                logger.debug(
                    "[CT-GATE] Entries blocked by execution gate (gate_state=%s) — "
                    "vetoing ticker=%s asset=%s tf=%s",
                    gate_view.gate_state, candidate.ticker,
                    candidate.underlying, candidate.timeframe,
                )
                vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                if _pas is not None:
                    _pas["vetoed"] += 1
                    _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                ticker_diagnostics.append({
                    "ticker": candidate.ticker,
                    "asset": candidate.underlying,
                    "timeframe": candidate.timeframe,
                    "implied_yes_prob": mid_prob,
                    "model_win_prob": 0.0,
                    "edge_bps": 0.0,
                    "side": "none",
                    "kelly_raw": 0.0,
                    "kelly_frac": 0.0,
                    "veto_reason": veto_reason,
                })
                continue

            # Build context so strategy grid can apply the correct asset-tier
            # Kelly multiplier, min-liquidity gate, and timeframe-specific
            # signal logic.  Without this context, _CryptoGridStrategy.estimate
            # defaults to asset="BTC"/timeframe="1h" and the liquidity gate
            # (volume=0.0 < min_volume) always fails, producing zero intents.
            _eval_context: Dict[str, Any] = {
                "asset": candidate.underlying,
                "timeframe": candidate.timeframe,
                "volume": float(candidate.volume),
                "open_interest": float(candidate.open_interest),
            }
            if candidate.spot_price is not None:
                _eval_context["spot_price"] = candidate.spot_price
            estimate = self.evaluate_candidate(candidate, market_prob=mid_prob, context=_eval_context)

            if estimate is None:
                veto_reason = "no_estimate"
                logger.info(
                    "[CT-TRACE] ticker=%s asset=%s side=%s win_prob=%.4f payout=%.2f edge_bps=%.1f "
                    "kelly_raw=%.4f kelly_frac=%.4f size=%s veto=%s",
                    candidate.ticker, candidate.underlying, "none", 0.0, 0.0, 0.0,
                    0.0, 0.0, 0, veto_reason,
                )
                vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                if _pas is not None:
                    _pas["vetoed"] += 1
                    _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                ticker_diagnostics.append({
                    "ticker": candidate.ticker,
                    "asset": candidate.underlying,
                    "timeframe": candidate.timeframe,
                    "implied_yes_prob": mid_prob,
                    "model_win_prob": 0.0,
                    "edge_bps": 0.0,
                    "side": "none",
                    "kelly_raw": 0.0,
                    "kelly_frac": 0.0,
                    "veto_reason": veto_reason,
                })
                continue

            if _pas is not None:
                _pas["evaluated"] += 1

            # Use signal_to_sizing for Kelly-based notional.
            # Pass the pre-computed estimate so the strategy is invoked exactly
            # once per candidate (single sizing pipeline — see module docstring).
            # BUG-011: Use remaining_bankroll to prevent over-allocation
            sizing = self.signal_to_sizing(candidate, remaining_bankroll, estimate=estimate)

            # Determine side based on estimate vs market probability
            side = "YES" if estimate.agent_prob > mid_prob else "NO"

            # Convert edge to basis points
            edge_bps = sizing.edge * 10000.0

            if edge_bps > 0:
                markets_with_any_edge += 1

            # Check if sizing was rejected (size = 0)
            if sizing.size_contracts == 0:
                # Determine veto reason from sizing
                min_edge = self._get_min_edge(candidate)
                if sizing.edge < min_edge:
                    veto_reason = "edge_too_low"
                elif sizing.kelly_raw <= 0:
                    veto_reason = "negative_kelly"
                else:
                    veto_reason = "bankroll_says_0"

                logger.info(
                    "[CT-TRACE] ticker=%s asset=%s side=%s win_prob=%.4f payout=%.2f edge_bps=%.1f "
                    "kelly_raw=%.4f kelly_frac=%.4f size=%s veto=%s",
                    candidate.ticker, candidate.underlying, side, sizing.win_prob,
                    sizing.payout_cents, edge_bps, sizing.kelly_raw, sizing.kelly_frac,
                    sizing.size_contracts, veto_reason,
                )
                vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                if _pas is not None:
                    _pas["vetoed"] += 1
                    _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                    if sizing.kelly_raw <= 0 or sizing.size_contracts == 0:
                        _pas["kelly_zero_count"] += 1
                ticker_diagnostics.append({
                    "ticker": candidate.ticker,
                    "asset": candidate.underlying,
                    "timeframe": candidate.timeframe,
                    "implied_yes_prob": mid_prob,
                    "model_win_prob": sizing.win_prob,
                    "edge_bps": edge_bps,
                    "side": side,
                    "kelly_raw": sizing.kelly_raw,
                    "kelly_frac": sizing.kelly_frac,
                    "veto_reason": veto_reason,
                })
                continue

            notional = self._apply_risk_checks(candidate, estimate, bankroll)
            if notional is None:
                # Determine which risk check failed
                group_used = self._risk.group_used(candidate.group_id)
                _pct_cap2 = bankroll * _GROUP_NOTIONAL_PCT if _GROUP_NOTIONAL_PCT > 0 and bankroll > 0 else float("inf")
                _eff_group_cap = (
                    min(_pct_cap2, self._max_group_notional)
                    if self._max_group_notional > 0
                    else _pct_cap2
                )
                if group_used >= _eff_group_cap:
                    veto_reason = "group_notional_cap"
                elif estimate.confidence < self._min_confidence:
                    veto_reason = "low_confidence"
                else:
                    veto_reason = "risk_check_failed"

                logger.info(
                    "[CT-TRACE] ticker=%s asset=%s side=%s win_prob=%.4f payout=%.2f edge_bps=%.1f "
                    "kelly_raw=%.4f kelly_frac=%.4f size=%s veto=%s",
                    candidate.ticker, candidate.underlying, side, sizing.win_prob,
                    sizing.payout_cents, edge_bps, sizing.kelly_raw, sizing.kelly_frac,
                    sizing.size_contracts, veto_reason,
                )
                vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                if _pas is not None:
                    _pas["vetoed"] += 1
                    _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                    _pas["orders_blocked_by_risk"] += 1
                ticker_diagnostics.append({
                    "ticker": candidate.ticker,
                    "asset": candidate.underlying,
                    "timeframe": candidate.timeframe,
                    "implied_yes_prob": mid_prob,
                    "model_win_prob": sizing.win_prob,
                    "edge_bps": edge_bps,
                    "side": side,
                    "kelly_raw": sizing.kelly_raw,
                    "kelly_frac": sizing.kelly_frac,
                    "veto_reason": veto_reason,
                })
                continue

            # When Kelly sizing produces a positive notional, prefer it
            if sizing.notional_usd > 0:
                notional = min(notional, sizing.notional_usd)

            # AUDIT-07: apply exposure multiplier (scale down/up computed Kelly notional)
            if self._exposure_multiplier != 1.0:
                notional *= self._exposure_multiplier

            # AUDIT-06: enforce hard cap on number of contracts.
            # sizing.size_contracts is the pre-multiplier Kelly count; we use it
            # only as a reference denominator for the proportional notional reduction.
            # The cap is applied to the already-multiplied notional (not the raw
            # Kelly contracts), so the resulting notional stays proportional to
            # max_position_contracts / kelly_contracts.
            if self._max_position_contracts > 0 and sizing.size_contracts > self._max_position_contracts:
                logger.debug(
                    "ContinuousTrader: contracts capped %s → %d (MERID_CT_MAX_POSITION_CONTRACTS)",
                    sizing.size_contracts, self._max_position_contracts,
                )
                # Recompute notional proportionally
                if sizing.size_contracts > 0:
                    notional = notional * (self._max_position_contracts / sizing.size_contracts)

            # Recompute size_contracts from the final adjusted notional so that
            # exposure_multiplier and position-cap changes are reflected in the intent.
            # (AUDIT-07/05: size_contracts must be consistent with notional.)
            _final_price_cents = candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
            _final_price_dollars = _final_price_cents / 100.0
            final_size_contracts = (
                int(math.floor(notional / _final_price_dollars))
                if _final_price_dollars > 0
                else 0
            )

            # AUDIT-08: per-asset cooldown — skip if traded too recently
            if self._per_asset_cooldown_seconds > 0:
                asset_key = candidate.underlying.upper()
                last_ts = self._last_trade_ts.get(asset_key, 0.0)
                elapsed = time.time() - last_ts
                if elapsed < self._per_asset_cooldown_seconds:
                    remaining = self._per_asset_cooldown_seconds - elapsed
                    veto_reason = "cooldown"
                    logger.debug(
                        "ContinuousTrader: %s on cooldown, %.0fs remaining",
                        asset_key, remaining,
                    )
                    vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                    ticker_diagnostics.append({
                        "ticker": candidate.ticker,
                        "asset": candidate.underlying,
                        "timeframe": candidate.timeframe,
                        "implied_yes_prob": mid_prob,
                        "model_win_prob": sizing.win_prob,
                        "edge_bps": edge_bps,
                        "side": side,
                        "kelly_raw": sizing.kelly_raw,
                        "kelly_frac": sizing.kelly_frac,
                        "veto_reason": veto_reason,
                    })
                    continue

            intent = {
                "ticker": candidate.ticker,
                "underlying": candidate.underlying,
                "timeframe": candidate.timeframe,
                "group_id": candidate.group_id,
                "direction": "yes" if estimate.agent_prob > mid_prob else "no",
                "notional": notional,
                "confidence": estimate.confidence,
                "edge": sizing.edge,
                "kelly_raw": sizing.kelly_raw,
                "kelly_frac": sizing.kelly_frac,
                # Use size_contracts recomputed from final notional (post exposure_multiplier
                # and position cap) so this value is always consistent with "notional".
                "size_contracts": final_size_contracts,
                "sizing_source": sizing.source,
                "intent_id": generate_correlation_id(datetime.now(timezone.utc), prefix="kalshi-trader"),
                "ts": time.time(),
            }

            # Max YES price guard — drop YES intents whose implied price exceeds cap
            if intent["direction"] == "yes":
                yes_price_cents = candidate.best_ask_cents or candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
                max_cents = int(self._max_yes_price * 100)
                if yes_price_cents > max_cents:
                    veto_reason = "max_yes_price_cap"
                    logger.info(
                        "[CT-TRACE] ticker=%s asset=%s side=%s win_prob=%.4f payout=%.2f edge_bps=%.1f "
                        "kelly_raw=%.4f kelly_frac=%.4f size=%s veto=%s",
                        candidate.ticker, candidate.underlying, side, sizing.win_prob,
                        sizing.payout_cents, edge_bps, sizing.kelly_raw, sizing.kelly_frac,
                        sizing.size_contracts, veto_reason,
                    )
                    logger.info(
                        "ContinuousTrader: MAX_YES_PRICE_CAP dropped YES intent "
                        "ticker=%s price=%d¢ cap=%d¢",
                        candidate.ticker, yes_price_cents, max_cents,
                    )
                    self._risk.execution_rejections += 1
                    self._emit_rejection(candidate.ticker, "max_yes_price_cap", intent["intent_id"])
                    vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                    if _pas is not None:
                        _pas["vetoed"] += 1
                        _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                    ticker_diagnostics.append({
                        "ticker": candidate.ticker,
                        "asset": candidate.underlying,
                        "timeframe": candidate.timeframe,
                        "implied_yes_prob": mid_prob,
                        "model_win_prob": sizing.win_prob,
                        "edge_bps": edge_bps,
                        "side": side,
                        "kelly_raw": sizing.kelly_raw,
                        "kelly_frac": sizing.kelly_frac,
                        "veto_reason": veto_reason,
                    })
                    continue

            # Log successful intent with no veto
            logger.info(
                "[CT-TRACE] ticker=%s asset=%s side=%s win_prob=%.4f payout=%.2f edge_bps=%.1f "
                "kelly_raw=%.4f kelly_frac=%.4f size=%s veto=%s",
                candidate.ticker, candidate.underlying, side, sizing.win_prob,
                sizing.payout_cents, edge_bps, sizing.kelly_raw, sizing.kelly_frac,
                final_size_contracts, "none",
            )

            # Total aggregate crypto risk cap: veto if this intent would exceed the
            # cycle-wide notional budget (bankroll × _TOTAL_CRYPTO_RISK_PCT).
            if _cycle_total_notional + notional > _total_crypto_risk_cap:
                veto_reason = "total_crypto_risk_cap"
                logger.info(
                    "[CT-RISK-CAP] ticker=%s VETOED: aggregate notional %.2f + %.2f "
                    "would exceed total_crypto_risk_cap=%.2f",
                    candidate.ticker, _cycle_total_notional, notional, _total_crypto_risk_cap,
                )
                vetoed_by_reason[veto_reason] = vetoed_by_reason.get(veto_reason, 0) + 1
                if _pas is not None:
                    _pas["vetoed"] += 1
                    _pas["veto_reasons"][veto_reason] = _pas["veto_reasons"].get(veto_reason, 0) + 1
                    _pas["orders_blocked_by_risk"] += 1
                ticker_diagnostics.append({
                    "ticker": candidate.ticker,
                    "asset": candidate.underlying,
                    "timeframe": candidate.timeframe,
                    "implied_yes_prob": mid_prob,
                    "model_win_prob": sizing.win_prob,
                    "edge_bps": edge_bps,
                    "side": side,
                    "kelly_raw": sizing.kelly_raw,
                    "kelly_frac": sizing.kelly_frac,
                    "veto_reason": veto_reason,
                })
                continue

            self._risk.add_notional(candidate.group_id, notional)
            self._risk.trade_count += 1
            # AUDIT-08: record trade timestamp for per-asset cooldown tracking
            if self._per_asset_cooldown_seconds > 0:
                self._last_trade_ts[candidate.underlying.upper()] = time.time()
            if _pas is not None:
                _pas["approved"] += 1
                _pas["approved_orders_intent"] += 1
                _pas["orders_submitted"] += 1
            intents.append(intent)

            # BUG-011: Subtract approved notional from remaining bankroll
            remaining_bankroll = max(0.0, remaining_bankroll - notional)
            # Update cycle-wide aggregate notional for the total_crypto_risk_cap check
            _cycle_total_notional += notional

            # Record forecast edge for calibration tracking
            try:
                tracker = get_edge_calibration_tracker()
                # Get the strategy name from the wired strategy
                strategy_name = getattr(self._strategy, 'name', 'unknown')
                # Use best_ask for YES, best_bid for NO, fallback to mid_price
                if intent["direction"] == "yes":
                    fill_price_cents = candidate.best_ask_cents or candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS
                else:
                    fill_price_cents = candidate.best_bid_cents or candidate.mid_price_cents or _FALLBACK_YES_PRICE_CENTS

                tracker.record_forecast(
                    ticker=candidate.ticker,
                    forecast_edge=intent["edge"],
                    confidence=intent["confidence"],
                    strategy_name=strategy_name,
                    asset=candidate.underlying,
                    timeframe=candidate.timeframe,
                    fill_price_cents=fill_price_cents,
                )
            except Exception as exc:
                logger.debug(
                    "EdgeCalibration: record_forecast failed for %s: %s",
                    candidate.ticker, exc,
                )

            ticker_diagnostics.append({
                "ticker": candidate.ticker,
                "asset": candidate.underlying,
                "timeframe": candidate.timeframe,
                "implied_yes_prob": mid_prob,
                "model_win_prob": sizing.win_prob,
                "edge_bps": edge_bps,
                "side": side,
                "kelly_raw": sizing.kelly_raw,
                "kelly_frac": sizing.kelly_frac,
                "veto_reason": None,
            })
            logger.info(
                "ContinuousTrader: INTENT %s %s notional=%.2f conf=%.3f edge=%.4f "
                "kelly_raw=%.4f kelly_frac=%.4f size=%d source=%s",
                intent["direction"], candidate.ticker, notional,
                estimate.confidence, intent["edge"],
                sizing.kelly_raw, sizing.kelly_frac,
                final_size_contracts, sizing.source,
            )

        # ── Canary diagnostic mode ────────────────────────────────────────────
        # When enabled, emit a tiny intent for each asset that has not had a live
        # intent in the past canary_interval_secs, to prove end-to-end execution.
        if self._canary_mode:
            intents = self._inject_canary_intents(intents, bankroll, per_asset_stats)

        # ── Per-asset summary log ─────────────────────────────────────────────
        for asset in _CRYPTO_ASSETS:
            s = per_asset_stats.get(asset, {})
            logger.info(
                "[CT-ASSET-SUMMARY] asset=%s candidates=%d evaluated=%d approved=%d "
                "vetoed=%d veto_reasons=%s approved_intent=%d blocked_risk=%d blocked_kill=%d",
                asset,
                s.get("candidates_seen", 0),
                s.get("evaluated", 0),
                s.get("approved", 0),
                s.get("vetoed", 0),
                s.get("veto_reasons", {}),
                s.get("approved_orders_intent", 0),
                s.get("orders_blocked_by_risk", 0),
                s.get("orders_blocked_by_kill_switch", 0),
            )

        # ── 15m cycle diagnostic — log why each 15m cell did/didn't trade ──────
        fifteen_min_traded: Dict[str, int] = {}
        fifteen_min_blocked: Dict[str, str] = {}
        for asset in _CRYPTO_ASSETS:
            if _CATALOG_ENABLED.get((asset, "15m")) is False:
                fifteen_min_blocked[asset] = "catalog_disabled"
                continue
            scan_cnt = self._last_scan_asset_counts.get(asset, {}).get("15m", 0)
            if scan_cnt == 0:
                fifteen_min_blocked[asset] = "no_candidates"
            else:
                # Count how many 15m tickers were approved this cycle
                approved_15m = sum(
                    1 for d in ticker_diagnostics
                    if d.get("asset") == asset
                    and d.get("timeframe") == "15m"
                    and d.get("veto_reason") is None
                )
                if approved_15m > 0:
                    fifteen_min_traded[asset] = approved_15m
                else:
                    # Collect all unique veto reasons for this asset's 15m candidates
                    veto_reasons_15m = list(dict.fromkeys(
                        d.get("veto_reason", "unknown")
                        for d in ticker_diagnostics
                        if d.get("asset") == asset and d.get("timeframe") == "15m"
                        and d.get("veto_reason")
                    ))
                    fifteen_min_blocked[asset] = (
                        ",".join(veto_reasons_15m) if veto_reasons_15m else "scanned_no_trade"
                    )
        logger.info(
            "[CT-15M-CYCLE] traded=%s blocked=%s",
            fifteen_min_traded,
            fifteen_min_blocked,
        )

        # Persist cycle summary for status() / API consumers
        self._last_cycle_stats = {
            "candidates_seen": candidates_seen,
            "markets_with_any_edge": markets_with_any_edge,
            "markets_after_risk_veto": len(intents),
            "vetoed_total": candidates_seen - len(intents),
            "vetoed_by_reason": vetoed_by_reason,
            "ticker_diagnostics": ticker_diagnostics,
            "cycle_ts": time.time(),
            # Per-asset breakdown for pipeline audit and diagnostics.
            "per_asset_stats": dict(per_asset_stats),
            # Per-asset/timeframe scan counts from _refresh_candidates() — used by
            # pipeline audit's UPSTREAM invariant check.
            "scan_by_asset_timeframe": dict(self._last_scan_asset_counts),
        }

        # LEAK-010: Track consecutive zero-intent cycles and alert if >= 50
        if len(intents) == 0:
            self._consecutive_zero_intent_cycles += 1
            if self._consecutive_zero_intent_cycles >= 50:
                logger.critical(
                    "[CT-ALERT] ZERO-INTENT STARVATION: %d consecutive cycles with no intents. "
                    "System may be misconfigured or markets unavailable. "
                    "candidates_seen=%d markets_with_edge=%d vetoed=%d",
                    self._consecutive_zero_intent_cycles,
                    candidates_seen,
                    markets_with_any_edge,
                    candidates_seen - len(intents),
                )
            elif self._consecutive_zero_intent_cycles % 10 == 0:
                # Warn every 10 cycles to track progression toward threshold
                logger.warning(
                    "[CT-ALERT] Zero-intent streak: %d consecutive cycles (threshold=50). "
                    "candidates_seen=%d markets_with_edge=%d vetoed=%d",
                    self._consecutive_zero_intent_cycles,
                    candidates_seen,
                    markets_with_any_edge,
                    candidates_seen - len(intents),
                )
        else:
            # Reset counter when we have at least one intent
            if self._consecutive_zero_intent_cycles > 0:
                logger.info(
                    "[CT-ALERT] Zero-intent streak ended after %d cycles. "
                    "Generated %d intents this cycle.",
                    self._consecutive_zero_intent_cycles,
                    len(intents),
                )
            self._consecutive_zero_intent_cycles = 0

        return intents

    # ── Bankroll invariant ────────────────────────────────────────────────

    def record_trade_result(self, pnl_cents: int) -> None:
        """Record realized PnL for a settled CT market.

        Must be called exactly once per resolved market, **after** settlement
        (not at fill time).  Typically wired from ``merid/reconciliation.py``
        ``_fire_settlement_hooks()`` so that PnL is only recorded when Kalshi
        removes the position from the portfolio.

        Args:
            pnl_cents: Net realized PnL in cents (positive = profit, negative = loss).
                       Computed as: sum over fills of
                       ``count × (settlement_cents - entry_price_cents)``  for YES buys, etc.
        """
        self._total_pnl_cents += pnl_cents
        # Track intra-day losses for the daily loss limit.  Only negative PnL
        # (realized losses) accumulates here; gains leave it unchanged.
        if pnl_cents < 0:
            self._risk.daily_loss += abs(pnl_cents) / 100.0
        logger.info(
            "CT bankroll: settled pnl_cents=%+d cumulative_pnl_cents=%d daily_loss=%.4f",
            pnl_cents,
            self._total_pnl_cents,
            self._risk.daily_loss,
        )

    def record_fee(self, fee_cents: int) -> None:
        """Record fee charged for a CT order fill.

        Must be called at fill time (not settlement time).  This accumulates
        total fees for the bankroll invariant check.

        Args:
            fee_cents: Fee amount in cents charged for this fill.
        """
        self._total_fees_cents += fee_cents
        logger.debug(
            "CT bankroll: fee charged fee_cents=%d cumulative_fees_cents=%d",
            fee_cents,
            self._total_fees_cents,
        )

    def check_bankroll_invariant(
        self,
        balance_cents: int,
        portfolio_cents: int,
        *,
        fee_cents: int = 0,
        epsilon_cents: int = 500,
    ) -> dict:
        """Check the CT bankroll invariant and return a status dict.

        Formula::

            actual_bankroll   = balance_cents + portfolio_cents - fee_cents
            expected_bankroll = session_start_bankroll_cents + _total_pnl_cents
            delta             = actual_bankroll - expected_bankroll

        ``balance_cents`` is the Kalshi cash balance; ``portfolio_cents`` is the
        current mark-to-market value of open positions.  Both the actual and
        expected sides use the **same bankroll definition** (cash + portfolio
        mark, net of fees) to avoid comparing incompatible notions such as
        ``cash + exposure`` vs ``cash + portfolio``.

        The invariant is **WARNING-only** until settlement wiring has been
        validated in live trading and deltas are consistently within epsilon.
        Do **not** trigger a kill switch based on this check until the kill-switch
        graduation criteria in ``docs/BANKROLL_INVARIANT_DESIGN.md`` are met.

        Args:
            balance_cents:  Kalshi cash balance in cents (from REST balance endpoint).
            portfolio_cents: Mark-to-market value of open CT positions in cents.
            fee_cents:       Fees already paid/charged against the snapshot bankroll.
            epsilon_cents:   Tolerance in cents before escalating to WARN (default 500¢ = $5).

        Returns:
            dict with keys: ``status`` ("ok" | "warn"), ``delta_cents``,
            and on WARN: ``actual_bankroll_cents``, ``expected_bankroll_cents``.
        """
        snapshot_bankroll_cents = balance_cents + portfolio_cents - fee_cents
        if self._session_start_balance_cents is None:
            self._session_start_balance_cents = balance_cents
        if self._session_start_bankroll_cents is None:
            self._session_start_bankroll_cents = snapshot_bankroll_cents
            logger.info(
                "CT bankroll: session start recorded balance=%d¢ portfolio=%d¢ fees=%d¢ bankroll=%d¢ ($%.2f)",
                balance_cents,
                portfolio_cents,
                fee_cents,
                snapshot_bankroll_cents,
                snapshot_bankroll_cents / 100.0,
            )

        expected_bankroll_cents = self._session_start_bankroll_cents + self._total_pnl_cents
        delta = snapshot_bankroll_cents - expected_bankroll_cents

        if abs(delta) <= epsilon_cents:
            result: Dict[str, Any] = {
                "status": "ok",
                "delta_cents": delta,
                "actual_bankroll_cents": snapshot_bankroll_cents,
                "expected_bankroll_cents": expected_bankroll_cents,
            }
        else:
            logger.warning(
                "CT bankroll invariant WARN: delta=%d¢ actual_bankroll=%d¢ expected_bankroll=%d¢ "
                "(balance=%d¢ portfolio=%d¢ fees=%d¢ start_bankroll=%d¢ realized_pnl=%d¢)",
                delta,
                snapshot_bankroll_cents,
                expected_bankroll_cents,
                balance_cents,
                portfolio_cents,
                fee_cents,
                self._session_start_bankroll_cents,
                self._total_pnl_cents,
            )
            result = {
                "status": "warn",
                "delta_cents": delta,
                "actual_bankroll_cents": snapshot_bankroll_cents,
                "expected_bankroll_cents": expected_bankroll_cents,
            }

        self._last_invariant_status = result
        return result

    # ── Daily reset ───────────────────────────────────────────────────────

    def reset_daily(self) -> None:
        """Reset all intra-day risk accumulators (group notional map, daily loss).

        Called at daily rollover or after testing a day's worth of activity.
        After this call, ``group_notional`` is guaranteed empty.
        """
        self._risk.reset()
        logger.info("ContinuousTrader: daily risk state reset")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _emit_rejection(self, symbol: str, reason: str, intent_id: str = "") -> None:
        """Publish execution_rejected event for audit trail."""
        try:
            from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
            event = StreamEvent(
                channel=EventChannel.EXECUTION,
                event_type="execution_rejected",
                data={
                    "symbol": symbol,
                    "reason": reason,
                    "intent_id": intent_id or f"reject-{symbol}-{int(time.time())}",
                    "timestamp": time.time(),
                },
                source="continuous_trader",
            )
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    streaming_bus.publish(event)
                )
            )
        except Exception as exc:
            logger.debug("ContinuousTrader execution_rejected event emit skipped: %s", exc)

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self._running,
            "candidate_count": len(self._candidates),
            "risk": {
                "group_notional": dict(self._risk.group_notional),
                "daily_loss": self._risk.daily_loss,
                "daily_loss_limit_pct": self._daily_loss_limit_pct,
                "observe_only": self._last_cycle_stats.get("observe_only", False),
                "trade_count": self._risk.trade_count,
                "execution_rejections": self._risk.execution_rejections,
            },
            "config": {
                "max_group_notional": self._max_group_notional,
                "min_confidence": self._min_confidence,
                "bankroll_fraction": self._bankroll_fraction,
                "max_yes_price": self._max_yes_price,
                "kelly_fraction": self._kelly_fraction,
                "min_edge": self._min_edge,
                "edge_profile": _EDGE_PROFILE,  # Show which profile is active
                # Surface the pre-CT filter's dead zone setting so the dashboard can
                # warn when it would drop near-50¢ candidates.
                "filter_dead_zone_pct": self._filter_config.min_edge_dead_zone_pct,
                "filter_spot_band_pct": self._filter_config.spot_band_pct,
            },
            # ── Filter telemetry (populated after first _refresh_candidates call) ──
            # Use these to audit the relative-volume band: a healthy block_rate is
            # 15–40% of input candidates.  Below 10% the band may be too loose;
            # above 60% it may be too restrictive.  rolling_avg smooths scan noise.
            # Also includes per-filter rejection counts:
            #   scan_rejected_edge_deadzone: markets dropped because mid was in dead zone
            #   scan_rejected_distance:      markets dropped because strike too far from spot
            #   scan_rejected_price:         markets dropped by price range gate
            #   scan_rejected_spread:        markets dropped by spread gate
            "filter": dict(self._last_scan_filter_stats),
            # ── Per-cycle diagnostics (populated after each trade_cycle() call) ──
            # candidates_seen:       total candidates evaluated this cycle
            # markets_with_any_edge: how many had edge_bps > 0 before risk checks
            # markets_after_risk_veto: how many intents were approved (no veto)
            # vetoed_total:          candidates_seen - markets_after_risk_veto
            # vetoed_by_reason:      breakdown dict {reason: count}
            # ticker_diagnostics:    per-ticker list with full edge/veto detail
            "last_cycle": dict(self._last_cycle_stats),
            # ── Bankroll invariant state ──────────────────────────────────────
            # total_pnl_cents:              accumulated realized PnL since process start
            # total_fees_cents:             accumulated fees charged since process start
            # session_start_balance_cents:  Kalshi balance at session open (None until
            #                               first check_bankroll_invariant() call)
            # last_invariant_status:        most recent invariant result dict
            #   {"status": "ok"|"warn", "delta_cents": int, ...}
            "bankroll": {
                "total_pnl_cents": self._total_pnl_cents,
                "total_pnl_usd": round(self._total_pnl_cents / 100.0, 4),
                "total_fees_cents": self._total_fees_cents,
                "total_fees_usd": round(self._total_fees_cents / 100.0, 4),
                "session_start_balance_cents": self._session_start_balance_cents,
                "session_start_bankroll_cents": self._session_start_bankroll_cents,
                "last_invariant": dict(self._last_invariant_status),
            },
        }

    @property
    def candidates(self) -> List[TradingCandidate]:
        return list(self._candidates)

    @property
    def risk_state(self) -> DailyRiskState:
        return self._risk


# ── Singleton ─────────────────────────────────────────────────────────────

_trader: Optional[KalshiContinuousTrader] = None


def get_continuous_trader(
    catalog: Optional[KalshiMarketCatalog] = None,
    strategy: Optional[OpinionStrategy] = None,
) -> KalshiContinuousTrader:
    """Return the process-singleton KalshiContinuousTrader.

    If no strategy is provided, creates a default HashBiasStrategy with
    min_edge=0.005 (0.5%) to align with CT's initial_live edge thresholds.
    The fee profitability gate will reject trades below breakeven regardless.
    Note: there is no explicit fee-profitability gate in this module; fee
    drag is managed entirely through the EDGE_THRESHOLDS grid (0.5–8%
    depending on profile and asset).  At typical 45–55¢ YES prices, Kalshi
    fees are ~4–5% of notional, so the ``production`` thresholds (≥2%) are
    needed for consistent fee profitability.  The ``initial_live`` thresholds
    (0.5–1.5%) allow intents through for initial validation at micro sizes.
    """
    global _trader
    if _trader is None:
        # FEE_DRAG_FIX: Provide default strategy with 0.5% min_edge to align
        # with CT's initial_live profile. Fee profitability gate will handle
        # rejection of trades below breakeven (~4% at typical prices).
        if strategy is None:
            from merid.prediction.opinion_strategy import HashBiasStrategy
            strategy = HashBiasStrategy(min_edge=0.005)
            logger.info(
                "KalshiContinuousTrader: No strategy provided, using default "
                "HashBiasStrategy(min_edge=0.005)"
            )
        _trader = KalshiContinuousTrader(catalog=catalog, strategy=strategy)
    return _trader
