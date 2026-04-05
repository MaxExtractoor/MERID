"""CryptoKalshiRisk — Unified risk + sizing + routing layer for Kalshi crypto markets.

Supports BTC, ETH, SOL, XRP, DOGE across all timeframes (15m, 1h, daily, weekly, monthly).

Key design principles:
- Risk is always a **percentage of bankroll** — no hardcoded dollar amounts.
- Portfolio-level drawdown is capped (default 40%).
- Per-trade and per-asset exposure are tightly bounded.
- All sizing derives from bankroll + config, never from literal values.

Components:
    CryptoKalshiRiskConfig   — Global risk parameters + per-asset bankroll slices.
    CryptoKalshiStrategyConfig — Timeframe profiles per (asset, timeframe) pair.
    StrategyProfile           — Per-(asset, timeframe) trading constraints.
    KalshiCryptoRiskEngine    — Core risk / sizing / routing logic.

Usage::

    engine = KalshiCryptoRiskEngine()
    contracts = engine.compute_contracts_for_order(
        bankroll=1000.0, price=0.40, asset="BTC"
    )
    ok, reason = engine.check_can_add_order(
        bankroll=1000.0, current_equity=950.0,
        open_positions=ledger, asset="BTC",
        price=0.50, contracts=contracts,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.crypto_kalshi_risk")

# ── Supported assets and timeframes ──────────────────────────────────────

CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
# Canonical timeframes - using standard format from config.crypto_universe
TIMEFRAMES: List[str] = ["15m", "1h", "daily", "weekly", "monthly"]

# Legacy timeframe aliases for backward compatibility
LEGACY_TIMEFRAMES: List[str] = ["scalp", "intraday", "swing"]
TIMEFRAME_ALIASES: Dict[str, str] = {
    "scalp": "15m",
    "intraday": "1h",
    "swing": "daily",
}


# ── Per-asset risk profile ────────────────────────────────────────────────

@dataclass
class AssetRiskProfile:
    """Per-asset risk limits expressed as fractions of the asset's bankroll slice."""

    # Fraction of the *total* crypto bankroll allocated to this asset.
    bankroll_share_pct: float

    # Max fraction of the asset slice at risk per individual trade.
    max_risk_pct_trade: float

    # Cushion subtracted from max_risk_pct_trade before sizing.
    cushion_pct_trade: float

    # Max aggregate portfolio risk (of the asset slice) across all open positions.
    max_risk_pct_portfolio: float

    # AUDIT-22: Vol anchor for this asset.
    # ``None`` means use the asset's own volatility (self-anchor — the preferred default).
    # Set to ``"BTC"`` only as an explicit fallback if this asset's own vol is unavailable.
    # Override per-asset via ``KALSHI_CT_VOL_ANCHOR_{ASSET}`` env var.
    vol_anchor_asset: Optional[str] = None


# ── Global risk configuration ─────────────────────────────────────────────

@dataclass
class CryptoKalshiRiskConfig:
    """Global risk parameters for the Kalshi crypto book.

    All limits are expressed as fractions of bankroll — never dollar amounts.
    """

    # ── Drawdown ─────────────────────────────────────────────────────────
    # Halt all new orders when equity falls below this fraction of initial bankroll.
    max_total_drawdown_pct: float = 0.40  # 40% max drawdown stop-out

    # ── Per-trade limits ─────────────────────────────────────────────────
    # Default per-trade risk cap (fraction of bankroll).  Asset overrides take precedence.
    max_risk_pct_trade: float = 0.01     # 1.0%
    cushion_pct_trade: float = 0.0025    # 0.25% cushion

    # ── Portfolio-wide limit ─────────────────────────────────────────────
    # Max aggregate open risk across ALL crypto Kalshi positions (fraction of bankroll).
    max_risk_pct_portfolio: float = 0.03  # 3%

    # ── Per-asset profiles ────────────────────────────────────────────────
    # Keyed by asset symbol.  Populated with sensible defaults in __post_init__.
    asset_profiles: Dict[str, AssetRiskProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_profiles:
            self.asset_profiles = {
                "BTC": AssetRiskProfile(
                    bankroll_share_pct=0.25,
                    max_risk_pct_trade=0.010,
                    cushion_pct_trade=0.0025,
                    max_risk_pct_portfolio=0.03,
                ),
                "ETH": AssetRiskProfile(
                    bankroll_share_pct=0.25,
                    max_risk_pct_trade=0.010,
                    cushion_pct_trade=0.0025,
                    max_risk_pct_portfolio=0.03,
                ),
                "SOL": AssetRiskProfile(
                    bankroll_share_pct=0.10,
                    max_risk_pct_trade=0.0075,
                    cushion_pct_trade=0.0025,
                    max_risk_pct_portfolio=0.02,
                ),
                "XRP": AssetRiskProfile(
                    bankroll_share_pct=0.10,
                    max_risk_pct_trade=0.0075,
                    cushion_pct_trade=0.0025,
                    max_risk_pct_portfolio=0.02,
                ),
                "DOGE": AssetRiskProfile(
                    bankroll_share_pct=0.10,
                    max_risk_pct_trade=0.005,
                    cushion_pct_trade=0.0025,
                    max_risk_pct_portfolio=0.015,
                ),
            }

    def asset_bankroll(self, total_bankroll: float, asset: str) -> float:
        """Return the bankroll slice allocated to *asset*."""
        profile = self.asset_profiles.get(asset)
        if profile is None:
            raise ValueError(f"Unknown asset: {asset!r}")
        return total_bankroll * profile.bankroll_share_pct


# ── Per-(asset, timeframe) strategy profile ───────────────────────────────

@dataclass
class StrategyProfile:
    """Trading constraints for a specific (asset, timeframe) combination."""

    asset_symbol: str
    timeframe: str  # "15m" | "1h" | "daily" | "weekly" | "monthly"

    # Fraction of the *asset's* bankroll slice allocated to this timeframe lane.
    bankroll_share_pct: float

    # Maximum number of new orders that may be placed in a single calendar day.
    max_trades_per_day: int

    # Kalshi contract price must fall within this band [low, high] (decimal 0-1).
    allowed_price_band: Tuple[float, float]

    # Minimum expected edge in basis points (100 bp = 1%).
    min_expected_edge_bp: float

    # Maximum number of simultaneously open positions for this lane.
    max_open_positions: int


# ── Strategy configuration (all assets × timeframes) ──────────────────────

@dataclass
class CryptoKalshiStrategyConfig:
    """Collection of StrategyProfile entries keyed by (asset, timeframe)."""

    profiles: Dict[Tuple[str, str], StrategyProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profiles:
            self.profiles = _build_default_profiles()

    def get(self, asset: str, timeframe: str) -> Optional[StrategyProfile]:
        """Get strategy profile for (asset, timeframe).

        Supports both canonical timeframes (15m, 1h, daily, weekly, monthly)
        and legacy aliases (scalp, intraday, swing).
        """
        # Try canonical timeframe first
        profile = self.profiles.get((asset, timeframe))
        if profile is not None:
            return profile

        # Try legacy alias mapping
        canonical_tf = TIMEFRAME_ALIASES.get(timeframe)
        if canonical_tf:
            return self.profiles.get((asset, canonical_tf))

        return None

    def get_profile(self, asset: str, timeframe: str) -> Optional[StrategyProfile]:
        """Alias for get() method for backward compatibility."""
        return self.get(asset, timeframe)


def _build_default_profiles() -> Dict[Tuple[str, str], StrategyProfile]:
    """Build sensible default strategy profiles for all (asset, timeframe) pairs.

    Covers all 5 assets × 5 timeframes = 25 profiles.
    Timeframes: 15m, 1h, daily, weekly, monthly
    """
    # (asset, timeframe): (bankroll_share, max_trades/day, price_band, min_edge_bp, max_open)
    #
    # allowed_price_band is expressed in decimal probability (0.0–1.0).
    # E.g. 0.35 means a contract trading at 35¢ (i.e. 35% implied probability for YES).
    # These tight bands filter contracts at trade execution time based on market
    # price, ensuring we only trade contracts with reasonable implied probabilities
    # that reflect near-spot strikes. Tighter bands for short-term markets (15m/1h)
    # focus on higher-probability near-the-money contracts, while longer-term markets
    # use wider bands to capture a broader range of strikes.
    spec: Dict[Tuple[str, str], tuple] = {
        # ── BTC ──────────────────────────────────────────────────────────
        ("BTC", "15m"):      (0.20, 5,  (0.35, 0.75), 50.0, 3),
        ("BTC", "1h"):       (0.25, 10, (0.35, 0.75), 40.0, 5),
        ("BTC", "daily"):    (0.25, 3,  (0.65, 0.85), 30.0, 2),
        ("BTC", "weekly"):   (0.15, 2,  (0.65, 0.85), 25.0, 2),
        ("BTC", "monthly"):  (0.15, 1,  (0.70, 0.85), 20.0, 1),
        # ── ETH ──────────────────────────────────────────────────────────
        ("ETH", "15m"):      (0.20, 5,  (0.35, 0.75), 50.0, 3),
        ("ETH", "1h"):       (0.25, 10, (0.35, 0.75), 40.0, 5),
        ("ETH", "daily"):    (0.25, 3,  (0.65, 0.85), 30.0, 2),
        ("ETH", "weekly"):   (0.15, 2,  (0.65, 0.85), 25.0, 2),
        ("ETH", "monthly"):  (0.15, 1,  (0.70, 0.85), 20.0, 1),
        # ── SOL ──────────────────────────────────────────────────────────
        ("SOL", "15m"):      (0.20, 4,  (0.25, 0.75), 60.0, 2),
        ("SOL", "1h"):       (0.25, 8,  (0.25, 0.75), 50.0, 4),
        ("SOL", "daily"):    (0.25, 2,  (0.55, 0.80), 40.0, 2),
        ("SOL", "weekly"):   (0.15, 1,  (0.60, 0.80), 35.0, 1),
        ("SOL", "monthly"):  (0.15, 1,  (0.65, 0.80), 30.0, 1),
        # ── XRP ──────────────────────────────────────────────────────────
        ("XRP", "15m"):      (0.20, 4,  (0.25, 0.75), 60.0, 2),
        ("XRP", "1h"):       (0.25, 8,  (0.25, 0.75), 50.0, 4),
        ("XRP", "daily"):    (0.25, 2,  (0.55, 0.80), 40.0, 2),
        ("XRP", "weekly"):   (0.15, 1,  (0.60, 0.80), 35.0, 1),
        ("XRP", "monthly"):  (0.15, 1,  (0.65, 0.80), 30.0, 1),
        # ── DOGE ─────────────────────────────────────────────────────────
        ("DOGE", "15m"):     (0.20, 3,  (0.25, 0.70), 75.0, 2),
        ("DOGE", "1h"):      (0.25, 6,  (0.25, 0.70), 60.0, 3),
        ("DOGE", "daily"):   (0.25, 2,  (0.50, 0.75), 50.0, 2),
        ("DOGE", "weekly"):  (0.15, 1,  (0.55, 0.75), 45.0, 1),
        ("DOGE", "monthly"): (0.15, 1,  (0.60, 0.75), 40.0, 1),
    }
    profiles: Dict[Tuple[str, str], StrategyProfile] = {}
    for (asset, tf), (bshare, max_td, band, edge_bp, max_open) in spec.items():
        profiles[(asset, tf)] = StrategyProfile(
            asset_symbol=asset,
            timeframe=tf,
            bankroll_share_pct=bshare,
            max_trades_per_day=max_td,
            allowed_price_band=band,
            min_expected_edge_bp=edge_bp,
            max_open_positions=max_open,
        )
    return profiles


# ── Open-position ledger type hint ─────────────────────────────────────────

# A minimal dict representation of open positions:
#   {ticker: {"asset": str, "contracts": int, "entry_price": float}}
OpenPositions = Dict[str, Dict]


# ── Core risk engine ──────────────────────────────────────────────────────

class KalshiCryptoRiskEngine:
    """Risk engine for Kalshi crypto markets.

    All sizing and limit logic derives from bankroll + config only.  No
    hardcoded dollar amounts are used.

    Args:
        risk_config:     Global risk parameters.
        strategy_config: Per-(asset, timeframe) trading constraints.
    """

    def __init__(
        self,
        risk_config: Optional[CryptoKalshiRiskConfig] = None,
        strategy_config: Optional[CryptoKalshiStrategyConfig] = None,
    ) -> None:
        self._risk_cfg = risk_config or CryptoKalshiRiskConfig()
        self._strat_cfg = strategy_config or CryptoKalshiStrategyConfig()

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def risk_config(self) -> CryptoKalshiRiskConfig:
        return self._risk_cfg

    @property
    def strategy_config(self) -> CryptoKalshiStrategyConfig:
        return self._strat_cfg

    # ── Asset bankroll helper ─────────────────────────────────────────────

    def asset_bankroll(self, total_bankroll: float, asset: str) -> float:
        """Return the bankroll slice allocated to *asset*."""
        return self._risk_cfg.asset_bankroll(total_bankroll, asset)

    # ── Vol anchor helper (AUDIT-22) ──────────────────────────────────────

    def get_vol_anchor(self, asset: str) -> str:
        """Return the volatility anchor asset for *asset*.

        AUDIT-22: Each asset defaults to its own vol (self-anchor), unless the
        operator has explicitly set ``KALSHI_CT_VOL_ANCHOR_{ASSET}`` or the
        asset's ``AssetRiskProfile.vol_anchor_asset`` field.

        Fallback order:
          1. ``KALSHI_CT_VOL_ANCHOR_{ASSET}`` env var.
          2. ``AssetRiskProfile.vol_anchor_asset`` (if non-None).
          3. ``asset`` itself (self-anchor default).
        """
        import os
        env_val = os.getenv(f"KALSHI_CT_VOL_ANCHOR_{asset.upper()}", "").strip().upper()
        if env_val and env_val in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            return env_val
        profile = self._risk_cfg.asset_profiles.get(asset.upper())
        if profile and profile.vol_anchor_asset:
            return profile.vol_anchor_asset.upper()
        return asset.upper()

    # ── Core sizing ───────────────────────────────────────────────────────

    def compute_trade_risk_usd(
        self,
        bankroll: float,
        *,
        max_risk_pct_trade: Optional[float] = None,
        cushion_pct_trade: Optional[float] = None,
        asset: Optional[str] = None,
    ) -> float:
        """Return the maximum dollar amount at risk for a single trade.

        Uses asset-specific overrides when *asset* is provided, falling back
        to the global config values.

        Formula::

            risk_usd = bankroll * (max_risk_pct_trade - cushion_pct_trade)
        """
        max_r, cushion = self._resolve_trade_params(
            asset, max_risk_pct_trade, cushion_pct_trade
        )
        return bankroll * (max_r - cushion)

    def compute_contracts_for_order(
        self,
        bankroll: float,
        price: float,
        *,
        max_risk_pct_trade: Optional[float] = None,
        cushion_pct_trade: Optional[float] = None,
        asset: Optional[str] = None,
    ) -> int:
        """Compute how many contracts to buy given bankroll and contract price.

        On a Kalshi binary market the maximum loss per contract equals *price*
        (for a YES buy) or *(1 - price)* (for a NO buy).  The caller should
        pass the relevant side price.

        Formula::

            risk_usd = bankroll * (max_risk_pct_trade - cushion_pct_trade)
            contracts = floor(risk_usd / price)

        Returns 0 if the resulting size is non-positive.
        """
        if price <= 0:
            return 0
        risk_usd = self.compute_trade_risk_usd(
            bankroll,
            max_risk_pct_trade=max_risk_pct_trade,
            cushion_pct_trade=cushion_pct_trade,
            asset=asset,
        )
        contracts = math.floor(risk_usd / price)
        return max(0, contracts)

    # ── Portfolio risk ────────────────────────────────────────────────────

    def compute_portfolio_risk(
        self,
        open_positions: OpenPositions,
        asset_filter: Optional[str] = None,
    ) -> float:
        """Return total open risk in USD across all (or one) crypto positions.

        Open risk for each position is: contracts × entry_price.

        Args:
            open_positions: Mapping of ticker → {"asset": str, "contracts": int,
                            "entry_price": float}.
            asset_filter:   When set, sum only positions whose ``asset`` matches.
        """
        total = 0.0
        for info in open_positions.values():
            if asset_filter and info.get("asset") != asset_filter:
                continue
            contracts = info.get("contracts", 0)
            entry_price = info.get("entry_price", 0.0)
            total += abs(contracts) * entry_price
        return total

    # ── Pre-trade gate ────────────────────────────────────────────────────

    def check_can_add_order(
        self,
        total_bankroll: float,
        current_equity: float,
        open_positions: OpenPositions,
        asset: str,
        price: float,
        contracts: int,
        initial_bankroll: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Determine whether a new order is permissible.

        Enforces three independent constraints in order:

        1. **Drawdown stop-out**: equity must not be below the drawdown floor.
        2. **Portfolio risk cap**: aggregate open risk after the new order must
           stay within ``max_risk_pct_portfolio`` of the *total* bankroll.
        3. **Per-asset exposure cap**: asset-level open risk after the new order
           must stay within the asset profile's ``max_risk_pct_portfolio`` of
           the *asset* bankroll slice.

        Args:
            total_bankroll:  Current total crypto strategy bankroll.
            current_equity:  Current marked-to-market equity.
            open_positions:  Live open positions (see ``compute_portfolio_risk``).
            asset:           Asset symbol for the new order.
            price:           Contract price (decimal 0-1).
            contracts:       Number of contracts to add.
            initial_bankroll: High-water bankroll used for drawdown calc.
                              Defaults to *total_bankroll* if not provided.

        Returns:
            ``(True, "OK")`` if the order is allowed, or
            ``(False, reason_string)`` explaining the rejection.
        """
        if contracts <= 0:
            return False, "zero_or_negative_contracts"

        ref_bankroll = initial_bankroll if initial_bankroll is not None else total_bankroll

        # 1. Drawdown stop-out ─────────────────────────────────────────────
        if ref_bankroll > 0:
            drawdown = (ref_bankroll - current_equity) / ref_bankroll
            if drawdown >= self._risk_cfg.max_total_drawdown_pct:
                return False, "max_drawdown_reached"

        # 2. Portfolio-wide risk cap ───────────────────────────────────────
        current_port_risk = self.compute_portfolio_risk(open_positions)
        new_order_risk = contracts * price
        port_risk_after = current_port_risk + new_order_risk
        port_cap = total_bankroll * self._risk_cfg.max_risk_pct_portfolio
        if port_risk_after > port_cap:
            return False, "portfolio_risk_limit"

        # 3. Per-asset exposure cap ────────────────────────────────────────
        profile = self._risk_cfg.asset_profiles.get(asset)
        if profile is not None:
            asset_bl = total_bankroll * profile.bankroll_share_pct
            asset_cap = asset_bl * profile.max_risk_pct_portfolio
            asset_risk_now = self.compute_portfolio_risk(open_positions, asset_filter=asset)
            asset_risk_after = asset_risk_now + new_order_risk
            if asset_risk_after > asset_cap:
                return False, f"asset_risk_limit:{asset}"

        return True, "OK"

    # ── Strategy-profile filters ──────────────────────────────────────────

    def check_strategy_filters(
        self,
        asset: str,
        timeframe: str,
        price: float,
        model_probability: float,
        market_probability: float,
        trades_today: int,
        current_open_positions: int,
        *,
        diagnostic_bypass_price_band: bool = False,
    ) -> Tuple[bool, str]:
        """Check that a potential trade satisfies all strategy-profile constraints.

        Args:
            asset:                 Asset symbol.
            timeframe:             Timeframe lane ("scalp", "intraday", "swing").
            price:                 Contract price (decimal 0-1) from the orderbook.
            model_probability:     Strategy's probability estimate (0-1).
            market_probability:    Kalshi implied probability (0-1).
            trades_today:          Number of trades already placed today for this lane.
            current_open_positions: Number of currently open positions in this lane.
            diagnostic_bypass_price_band: When True, skip price_band filter for diagnostics.

        Returns:
            ``(True, "OK")`` or ``(False, reason_string)``.
        """
        profile = self._strat_cfg.get(asset, timeframe)
        if profile is None:
            return False, f"no_profile:{asset}_{timeframe}"

        # Price band filter
        low, high = profile.allowed_price_band

        # Diagnostic bypass: allow operators to temporarily disable price_band checks
        # to verify that the rest of the trading loop is functional when all candidates
        # are being dropped by price_band logic. Set via env var MERID_CT_DIAGNOSTIC_BYPASS_PRICE_BAND=1
        import os
        env_bypass = os.getenv("MERID_CT_DIAGNOSTIC_BYPASS_PRICE_BAND", "").strip() == "1"
        bypass_active = diagnostic_bypass_price_band or env_bypass

        if bypass_active:
            logger.warning(
                "[STRAT-FILTER-DIAGNOSTIC] %s %s: price=%.3f band=(%.2f, %.2f) "
                "BYPASS_ACTIVE=True result=PASS_DIAGNOSTIC_MODE",
                asset, timeframe, price, low, high,
            )
        elif not (low <= price <= high):
            logger.info(
                "[STRAT-FILTER] %s %s: price=%.3f band=(%.2f, %.2f) result=REJECT_PRICE_BAND",
                asset, timeframe, price, low, high,
            )
            return False, "price_band_violation"

        # Edge filter (basis points) — must strictly exceed the minimum.
        edge_bp = (model_probability - market_probability) * 10_000
        if edge_bp <= profile.min_expected_edge_bp:
            logger.info(
                "[STRAT-FILTER] %s %s: edge_bp=%.1f min_edge_bp=%.1f result=REJECT_INSUFFICIENT_EDGE",
                asset, timeframe, edge_bp, profile.min_expected_edge_bp,
            )
            return False, "insufficient_edge"

        # Daily trade limit
        if trades_today >= profile.max_trades_per_day:
            return False, "max_trades_per_day_reached"

        # Concurrency limit
        if current_open_positions >= profile.max_open_positions:
            return False, "max_open_positions_reached"

        logger.info(
            "[STRAT-FILTER] %s %s: price=%.3f band=(%.2f,%.2f) edge_bp=%.1f result=PASS",
            asset, timeframe, price, low, high, edge_bp,
        )
        return True, "OK"

    # ── Helpers ───────────────────────────────────────────────────────────

    def _resolve_trade_params(
        self,
        asset: Optional[str],
        override_risk_pct: Optional[float],
        override_cushion: Optional[float],
    ) -> Tuple[float, float]:
        """Return (max_risk_pct_trade, cushion_pct_trade) with override priority."""
        if override_risk_pct is not None and override_cushion is not None:
            return override_risk_pct, override_cushion

        if asset is not None:
            profile = self._risk_cfg.asset_profiles.get(asset)
            if profile is not None:
                max_r = override_risk_pct if override_risk_pct is not None else profile.max_risk_pct_trade
                cushion = override_cushion if override_cushion is not None else profile.cushion_pct_trade
                return max_r, cushion

        max_r = override_risk_pct if override_risk_pct is not None else self._risk_cfg.max_risk_pct_trade
        cushion = override_cushion if override_cushion is not None else self._risk_cfg.cushion_pct_trade
        return max_r, cushion
