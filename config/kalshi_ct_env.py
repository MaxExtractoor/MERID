"""KalshiCTEnvConfig — Centralized environment-variable configuration for the
Continuous Trader (CT) and related Kalshi components.

All ``os.getenv()`` calls for CT configuration are consolidated here.  Import
``KalshiCTEnvConfig.from_env()`` instead of scattering ``os.getenv()`` calls
throughout the codebase.

AUDIT-18 fix: single source of truth for CT env vars.
AUDIT-01  fix: ``KALSHI_TRADER_BANKROLL`` required; fail-fast with clear error.
AUDIT-02..08 fix: protect/size hardcodes are env-driven and validated.
AUDIT-12 fix: minimum viable bankroll floor is env-configurable and enforced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("config.kalshi_ct_env")

# ── Minimum sane bankroll ─────────────────────────────────────────────────────
# Below this value CT refuses to start.
# Default: 50000 cents = $500.00.  Override via MERID_CT_BANKROLL_MIN_CENTS.
# AUDIT-12: floor is now env-configurable so test environments can use lower values.
# NOTE: $500 minimum is required for viable trading given:
#   - Per-trade fees of ~2¢ at 50¢ prices require ~4% edge to break even
#   - Multi-asset diversification (5 assets) fragments small bankrolls
#   - Kelly sizing with 1% per-trade risk needs meaningful capital base
# For testing/development, set MERID_CT_BANKROLL_MIN_CENTS=100 to allow $1.00 minimum.
BANKROLL_MIN_CENTS: int = int(os.getenv("MERID_CT_BANKROLL_MIN_CENTS", "50000"))


@dataclass
class KalshiCTEnvConfig:
    """All environment-driven configuration consumed by KalshiContinuousTrader.

    Fields are populated from environment variables via :meth:`from_env`.
    Default values are *code-level defaults*, i.e. what the system uses when
    the operator has not set the variable.  They are documented in
    ``.env.example``.

    Attributes
    ----------
    bankroll_cents:
        Session bankroll in cents.  Source: ``KALSHI_TRADER_BANKROLL`` (required
        in live mode; defaults to ``0`` which triggers a fail-fast check).
    group_notional_cap:
        Per-(asset, timeframe) group notional cap in dollars.
        Source: ``MERID_GROUP_NOTIONAL_CAP`` (default 50.0).
    min_confidence:
        Minimum clamped confidence to proceed to execution.
        Source: ``MERID_MIN_CONFIDENCE`` (default 0.55).
    bankroll_fraction:
        Max fraction of bankroll per individual trade.
        Source: ``MERID_BANKROLL_FRACTION`` (default 0.01).
    max_yes_price:
        Hard price cap (dollars) on YES contracts.
        Source: ``MERID_MAX_YES_PRICE`` (default 0.50).
    kelly_fraction:
        Fractional-Kelly multiplier.
        Source: ``MERID_KELLY_FRACTION`` (default 0.25).
    min_edge:
        Global fallback minimum edge fraction.
        Source: ``MERID_MIN_EDGE`` (default 0.02).
    edge_profile:
        ``"initial_live"`` (permissive) or ``"production"`` (conservative).
        Source: ``KALSHI_CT_EDGE_PROFILE`` (default ``"initial_live"``).
    min_edge_overrides:
        Per-(asset, timeframe) edge override map, populated from
        ``KALSHI_CT_MIN_EDGE_{ASSET}_{TF}`` env vars (AUDIT-09).
        Keys are upper-cased, e.g. ``("BTC", "15M")``.
    trade_mode:
        ``MERID_TRADE_MODE`` value (default ``"paper"``).
    pm_trading_mode:
        ``MERID_PM_TRADING_MODE`` value (default ``""``).
    allow_live_trades:
        ``MERID_ALLOW_LIVE_TRADES`` boolean flag (default ``False``).
    smoke_test:
        ``MERID_SMOKE_TEST`` boolean flag.  When ``True``, live modes are
        blocked at startup (AUDIT-15).
    dry_run:
        ``MERID_CT_DRY_RUN`` — when ``True``, no orders are placed even in
        live mode (AUDIT-14).
    vol_anchor_asset:
        Per-asset volatility anchor override map.
        Source: ``KALSHI_CT_VOL_ANCHOR_{ASSET}`` (default: self-anchor; AUDIT-22).
    max_candidates_per_asset:
        Discovery cap: maximum candidates to pass through per (asset, timeframe).
        Source: ``MERID_CT_MAX_CANDIDATES`` (default 5).  AUDIT-02.
    max_spread_cents:
        Filter: reject candidates whose bid/ask spread exceeds this value in cents.
        Source: ``MERID_CT_MAX_SPREAD_CENTS`` (default 12).  AUDIT-03.
    min_volume:
        Filter: reject candidates with volume below this threshold.
        Source: ``MERID_CT_MIN_VOLUME`` (default 50).  AUDIT-04.
    max_position_contracts:
        Hard cap on the number of contracts for a single order.  0 = no cap.
        Source: ``MERID_CT_MAX_POSITION_CONTRACTS`` (default 0).  AUDIT-06.
    exposure_multiplier:
        Multiplier applied to computed Kelly size (use <1 to scale back exposure).
        Source: ``MERID_CT_EXPOSURE_MULTIPLIER`` (default 1.0).  AUDIT-07.
    per_asset_cooldown_seconds:
        Minimum seconds between consecutive trades for the same asset.  0 = off.
        Source: ``MERID_CT_COOLDOWN_SECONDS`` (default 0).  AUDIT-08.
    agent_stagger_seconds:
        Stagger delay (seconds) between agent starts in the agent grid.
        Source: ``MERID_AGENT_STAGGER_SECONDS`` (default 0.5).  AUDIT-11.
    """

    bankroll_cents: int = 0
    group_notional_cap: float = 50.0
    min_confidence: float = 0.55
    bankroll_fraction: float = 0.01
    max_yes_price: float = 0.50
    kelly_fraction: float = 0.25
    min_edge: float = 0.02
    edge_profile: str = "initial_live"
    min_edge_overrides: Dict[Tuple[str, str], float] = field(default_factory=dict)
    trade_mode: str = "paper"
    pm_trading_mode: str = ""
    allow_live_trades: bool = False
    smoke_test: bool = False
    dry_run: bool = False
    vol_anchor_asset: Dict[str, str] = field(default_factory=dict)
    # AUDIT-02..08: protect/size caps — all env-driven with sane defaults
    max_candidates_per_asset: int = 5
    max_spread_cents: int = 12
    min_volume: int = 50
    max_position_contracts: int = 0       # 0 = no hard cap
    exposure_multiplier: float = 1.0
    per_asset_cooldown_seconds: float = 0.0  # 0 = no cooldown
    # AUDIT-11: agent-grid stagger
    agent_stagger_seconds: float = 0.5

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "KalshiCTEnvConfig":
        """Read all CT env vars and return a populated config instance.

        Raises ``ValueError`` if ``KALSHI_TRADER_BANKROLL`` is absent (AUDIT-01)
        or below the minimum sane threshold (AUDIT-12).
        """
        bankroll_cents = _read_bankroll_cents()

        min_edge_overrides = _read_min_edge_overrides()
        vol_anchor_asset = _read_vol_anchor_overrides()

        cfg = cls(
            bankroll_cents=bankroll_cents,
            group_notional_cap=float(os.getenv("MERID_GROUP_NOTIONAL_CAP", "50.0")),
            min_confidence=float(os.getenv("MERID_MIN_CONFIDENCE", "0.55")),
            bankroll_fraction=float(os.getenv("MERID_BANKROLL_FRACTION", "0.01")),
            max_yes_price=float(os.getenv("MERID_MAX_YES_PRICE", "0.50")),
            kelly_fraction=float(os.getenv("MERID_KELLY_FRACTION", "0.25")),
            min_edge=float(os.getenv("MERID_MIN_EDGE", "0.02")),
            edge_profile=os.getenv("KALSHI_CT_EDGE_PROFILE", "initial_live"),
            min_edge_overrides=min_edge_overrides,
            trade_mode=os.getenv("MERID_TRADE_MODE", "paper").lower().strip(),
            pm_trading_mode=os.getenv("MERID_PM_TRADING_MODE", "").lower().strip(),
            allow_live_trades=_env_bool("MERID_ALLOW_LIVE_TRADES", False),
            smoke_test=_env_bool("MERID_SMOKE_TEST", False),
            dry_run=_env_bool("MERID_CT_DRY_RUN", False),
            vol_anchor_asset=vol_anchor_asset,
            # AUDIT-02..08: protect/size caps
            max_candidates_per_asset=int(os.getenv("MERID_CT_MAX_CANDIDATES", "5")),
            max_spread_cents=int(os.getenv("MERID_CT_MAX_SPREAD_CENTS", "12")),
            min_volume=int(os.getenv("MERID_CT_MIN_VOLUME", "50")),
            max_position_contracts=int(os.getenv("MERID_CT_MAX_POSITION_CONTRACTS", "0")),
            exposure_multiplier=float(os.getenv("MERID_CT_EXPOSURE_MULTIPLIER", "1.0")),
            per_asset_cooldown_seconds=float(os.getenv("MERID_CT_COOLDOWN_SECONDS", "0.0")),
            # AUDIT-11: agent-grid stagger
            agent_stagger_seconds=float(os.getenv("MERID_AGENT_STAGGER_SECONDS", "0.5")),
        )
        cfg.validate()
        return cfg

    # ── Helpers ─────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Validate config consistency.  Raises ``ValueError`` on invalid combos.

        AUDIT-02..08: Catches problematic configuration such as:
        - exposure_multiplier outside (0, 2] range
        - per_asset_cooldown_seconds < 0
        - bankroll_fraction + exposure_multiplier combination exceeding 100%
        - max_candidates_per_asset or max_spread_cents unreasonably low
        """
        errors: List[str] = []
        if self.exposure_multiplier <= 0 or self.exposure_multiplier > 2.0:
            errors.append(
                f"MERID_CT_EXPOSURE_MULTIPLIER={self.exposure_multiplier} must be in (0, 2.0]"
            )
        if self.per_asset_cooldown_seconds < 0:
            errors.append(
                f"MERID_CT_COOLDOWN_SECONDS={self.per_asset_cooldown_seconds} must be >= 0"
            )
        if self.bankroll_fraction <= 0 or self.bankroll_fraction > 1.0:
            errors.append(
                f"MERID_BANKROLL_FRACTION={self.bankroll_fraction} must be in (0, 1.0]"
            )
        if self.kelly_fraction <= 0 or self.kelly_fraction > 1.0:
            errors.append(
                f"MERID_KELLY_FRACTION={self.kelly_fraction} must be in (0, 1.0]"
            )
        effective_max_pct = self.bankroll_fraction * self.kelly_fraction * self.exposure_multiplier
        if effective_max_pct > 0.10:
            logger.warning(
                "CT config: effective max per-trade exposure is %.1f%% of bankroll "
                "(bankroll_fraction=%.4f × kelly_fraction=%.4f × exposure_multiplier=%.2f). "
                "Consider reducing exposure_multiplier or bankroll_fraction.",
                effective_max_pct * 100,
                self.bankroll_fraction,
                self.kelly_fraction,
                self.exposure_multiplier,
            )
        if self.max_candidates_per_asset < 1:
            errors.append(
                f"MERID_CT_MAX_CANDIDATES={self.max_candidates_per_asset} must be >= 1"
            )
        if self.max_spread_cents < 1:
            errors.append(
                f"MERID_CT_MAX_SPREAD_CENTS={self.max_spread_cents} must be >= 1"
            )
        if self.agent_stagger_seconds < 0:
            errors.append(
                f"MERID_AGENT_STAGGER_SECONDS={self.agent_stagger_seconds} must be >= 0"
            )
        if errors:
            raise ValueError(
                "KalshiCTEnvConfig validation failed:\n  " + "\n  ".join(errors)
            )
        logger.debug(
            "KalshiCTEnvConfig validated: bankroll=$%.2f max_candidates=%d "
            "max_spread=%d¢ min_volume=%d cooldown=%.0fs exposure_mult=%.2f stagger=%.1fs",
            self.bankroll_dollars(),
            self.max_candidates_per_asset,
            self.max_spread_cents,
            self.min_volume,
            self.per_asset_cooldown_seconds,
            self.exposure_multiplier,
            self.agent_stagger_seconds,
        )

    def assert_live_safe(self) -> None:
        """Raise RuntimeError if live trading is requested while smoke-test is on.

        AUDIT-15: smoke_test flag must block all live modes.
        """
        if not self.smoke_test:
            return
        live_flags: list[str] = []
        if self.trade_mode == "live":
            live_flags.append("MERID_TRADE_MODE=live")
        if self.pm_trading_mode == "live":
            live_flags.append("MERID_PM_TRADING_MODE=live")
        if self.allow_live_trades:
            live_flags.append("MERID_ALLOW_LIVE_TRADES=true")
        if live_flags:
            raise RuntimeError(
                "CT smoke-test mode (MERID_SMOKE_TEST=true) is incompatible with "
                f"live trading: {', '.join(live_flags)}.  Disable smoke-test or "
                "remove live flags before deploying."
            )

    def get_min_edge(self, asset: str, timeframe: str, default: float) -> float:
        """Return env-overridden min edge for (asset, timeframe), else *default*.

        AUDIT-09: ``KALSHI_CT_MIN_EDGE_{ASSET}_{TF}`` takes precedence.
        """
        key = (asset.upper(), timeframe.upper())
        return self.min_edge_overrides.get(key, default)

    def get_vol_anchor(self, asset: str) -> str:
        """Return the vol-anchor asset for *asset*, defaulting to self.

        AUDIT-22: avoids routing everything through BTC vol.
        """
        return self.vol_anchor_asset.get(asset.upper(), asset.upper())

    def bankroll_dollars(self) -> float:
        """Return bankroll expressed in dollars."""
        return self.bankroll_cents / 100.0


# ── Private helpers ───────────────────────────────────────────────────────────

_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
_CRYPTO_TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly")


def _read_bankroll_cents() -> int:
    """Read ``KALSHI_TRADER_BANKROLL`` (cents).  Fail-fast if missing or invalid.

    AUDIT-01: bankroll must be explicitly configured; no silent fallback to a
    tiny default that silently allows misconfigured deployments.
    """
    raw = os.getenv("KALSHI_TRADER_BANKROLL", "")
    if not raw:
        raise ValueError(
            "KALSHI_TRADER_BANKROLL is not set.  "
            "Set it to your session bankroll in cents, e.g. "
            "KALSHI_TRADER_BANKROLL=50000 for a $500 bankroll.  "
            "CT refuses to start without an explicit bankroll."
        )
    try:
        cents = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"KALSHI_TRADER_BANKROLL={raw!r} is not a valid integer (cents)."
        ) from exc
    if cents < BANKROLL_MIN_CENTS:
        raise ValueError(
            f"KALSHI_TRADER_BANKROLL={cents}¢ is below the minimum "
            f"{BANKROLL_MIN_CENTS}¢ (${BANKROLL_MIN_CENTS / 100:.2f}).  "
            "Raise the bankroll or set MERID_CT_DRY_RUN=true for testing."
        )
    return cents


def _read_min_edge_overrides() -> Dict[Tuple[str, str], float]:
    """Scan for ``KALSHI_CT_MIN_EDGE_{ASSET}_{TF}`` env vars.

    AUDIT-09: per-(asset, timeframe) edge overrides.

    Example: ``KALSHI_CT_MIN_EDGE_BTC_15M=0.005``
    """
    overrides: Dict[Tuple[str, str], float] = {}
    for asset in _CRYPTO_ASSETS:
        for tf in _CRYPTO_TIMEFRAMES:
            tf_key = tf.upper().replace("-", "_")
            env_key = f"KALSHI_CT_MIN_EDGE_{asset}_{tf_key}"
            raw = os.getenv(env_key)
            if raw is not None:
                try:
                    overrides[(asset, tf.upper())] = float(raw)
                    logger.debug("min_edge override %s=%s → (%.4f)", env_key, raw, float(raw))
                except ValueError:
                    logger.warning("Invalid %s=%r — skipping override", env_key, raw)
    return overrides


def _read_vol_anchor_overrides() -> Dict[str, str]:
    """Scan for ``KALSHI_CT_VOL_ANCHOR_{ASSET}`` env vars.

    AUDIT-22: per-asset vol anchor (instead of always using BTC vol).

    Example: ``KALSHI_CT_VOL_ANCHOR_ETH=ETH`` (use ETH's own vol)
    """
    overrides: Dict[str, str] = {}
    for asset in _CRYPTO_ASSETS:
        env_key = f"KALSHI_CT_VOL_ANCHOR_{asset}"
        raw = os.getenv(env_key)
        if raw is not None:
            anchor = raw.strip().upper()
            if anchor in _CRYPTO_ASSETS or anchor == asset:
                overrides[asset] = anchor
            else:
                logger.warning(
                    "%s=%r is not a recognised asset — ignored; valid: %s",
                    env_key, raw, _CRYPTO_ASSETS,
                )
    return overrides


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.lower().strip() in ("1", "true", "yes")
