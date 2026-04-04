"""KalshiCTEnvConfig — Centralized environment-variable configuration for the
Continuous Trader (CT) and related Kalshi components.

All ``os.getenv()`` calls for CT configuration are consolidated here.  Import
``KalshiCTEnvConfig.from_env()`` instead of scattering ``os.getenv()`` calls
throughout the codebase.

AUDIT-18 fix: single source of truth for CT env vars.
AUDIT-01  fix: ``KALSHI_TRADER_BANKROLL`` required; fail-fast with clear error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("config.kalshi_ct_env")

# ── Minimum sane bankroll ─────────────────────────────────────────────────────
# Below this value CT refuses to start.  100 cents = $1.00.
BANKROLL_MIN_CENTS: int = 100


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

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "KalshiCTEnvConfig":
        """Read all CT env vars and return a populated config instance.

        Raises ``ValueError`` if ``KALSHI_TRADER_BANKROLL`` is absent (AUDIT-01)
        or below the minimum sane threshold.
        """
        bankroll_cents = _read_bankroll_cents()

        min_edge_overrides = _read_min_edge_overrides()
        vol_anchor_asset = _read_vol_anchor_overrides()

        return cls(
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
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

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
