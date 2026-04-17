"""
Kalshi filter pipeline (shared).

This module factors out the market-candidate filtering logic that was previously
embedded inside the continuous trader cycle so it can be reused by both:
  - KalshiContinuousTrader (continuous crypto runner)
  - KalshiTradingAgent (agent-grid market resolution)

NOW RETURNS: rich MarketCandidate from market_filter.py (unified type)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger
from merid.event_venues.kalshi.market_filter import MarketCandidate, group_id_from_ticker

_fp_logger = get_logger(__name__)


@dataclass(frozen=True)
class FilterLiquidityConfig:
    min_volume: int = 0
    min_open_interest: int = 0
    max_spread_cents: Optional[int] = None  # requires bid/ask fields to be present


@dataclass(frozen=True)
class FilterExpiryConfig:
    min_minutes_to_expiry: int = 0
    max_minutes_to_expiry: Optional[int] = None
    # Kalshi RTI crypto: exclude markets inside the final averaging minute (+1s buffer)
    min_seconds_to_expiry_rti_crypto: Optional[float] = 61.0


@dataclass(frozen=True)
class FilterPipelineConfig:
    assets: List[str] = field(default_factory=list)
    max_candidates_per_asset: int = 5
    max_candidates_global: int = 10

    # Distance band configuration - NO LONGER FILTERED AT PIPELINE LEVEL
    # Strike distance filtering is now handled exclusively by kalshi_strike_selector.evaluate()
    # to ensure a single source of truth (DEFAULT_MAX_DISTANCE) and avoid drift.
    # These fields are kept for backward compatibility but are no-ops (100% = allow all).
    # All distance filtering happens in the trading agent's strike selection gate.
    default_max_strike_distance_pct: float = 1.0  # No-op: 100% band allows all markets
    asset_timeframe_max_strike_distance_pct: Dict[Tuple[str, str], float] = field(default_factory=dict)

    liquidity: FilterLiquidityConfig = field(default_factory=FilterLiquidityConfig)
    expiry: FilterExpiryConfig = field(default_factory=FilterExpiryConfig)


@dataclass
class AssetFilterStats:
    raw: int = 0
    no_spot: int = 0
    parsed_strike: int = 0
    strike_too_far: int = 0
    directional: int = 0
    unknown_type: int = 0
    illiquid: int = 0
    expiry_out_of_bounds: int = 0
    rti_quarantined: int = 0  # excluded by CFB RTI quarantine (adapter != live)
    candidates_pre_cap: int = 0
    candidates_post_cap: int = 0
    total_ms: float = 0.0


@dataclass(frozen=True)
class MarketCandidateLite:
    """INTERNAL USE ONLY - Temporary holder before conversion to canonical MarketCandidate.
    
    This is an implementation detail of FilterPipeline. External callers should
    always use the rich MarketCandidate returned by filter_markets().
    """
    ticker: str
    asset: str
    spot: Optional[Decimal]
    strike: Optional[Decimal]
    is_directional: bool
    close_time: Optional[str] = None
    series_ticker: Optional[str] = None
    # Rich fields preserved from raw market
    volume: int = 0
    open_interest: int = 0
    best_bid_cents: int = 0
    best_ask_cents: int = 0
    mid_price_cents: int = 0


@dataclass
class FilterPipelineResult:
    per_asset: Dict[str, AssetFilterStats] = field(default_factory=dict)
    final_candidates: List[MarketCandidate] = field(default_factory=list)  # Rich type
    total_ms: float = 0.0


class FilterPipeline:
    def __init__(self, config: FilterPipelineConfig):
        self.config = config
        self._spot_prices: Dict[str, Decimal] = {}

    def set_spot_prices(self, spots: Dict[str, float]) -> None:
        """Set spot prices from canonical source (e.g., _get_all_spots).
        
        Accepts Dict[str, float] and converts to Decimal internally.
        """
        for asset, spot in spots.items():
            self._spot_prices[asset.upper()] = Decimal(str(spot))

    def get_spot_price(self, asset: str) -> Optional[Decimal]:
        return self._spot_prices.get(asset.upper())

    @staticmethod
    def _parse_strike(ticker: str) -> Optional[Decimal]:
        m = re.search(r"-[TB](\d+(?:\.\d+)?)$", (ticker or ""))
        if not m:
            return None
        try:
            return Decimal(m.group(1))
        except Exception:
            return None

    @staticmethod
    def _is_price_fractional(m: Dict[str, Any]) -> bool:
        """Detect if price data is in fractional (0-1) vs fixed-point cents (1-99) format.
        
        Kalshi uses different price representations:
        - WebSocket/live data: fractions (0-1, e.g., 0.55 for 55¢)
        - Catalog/REST data: fixed-point cents (1-99, e.g., 55 for 55¢)
        
        Heuristic: if any price value > 1.0, treat as already in cents.
        """
        yes_bid = m.get("yes_bid")
        yes_ask = m.get("yes_ask")
        
        # Check if any price is clearly in cents (> 1.0)
        for price in (yes_bid, yes_ask):
            if price is not None:
                try:
                    val = float(price)
                    if val > 1.0:  # Catalog data stores 55, not 0.55
                        return False  # Already in cents
                except (ValueError, TypeError):
                    continue
        
        # Default to fractional (WebSocket) - multiply by 100
        return True

    @staticmethod
    def _is_directional_market(ticker: str) -> bool:
        t = (ticker or "").upper()
        if "UPDOWN" in t or "UP-DOWN" in t or "DIRECTION" in t:
            return True
        if "15M" in t and not re.search(r"-[TB]\d", t):
            return True
        return False

    @staticmethod
    def _infer_timeframe_from_series(series_ticker: str) -> str:
        from config.kalshi_crypto_series_meta import SERIES_META_BY_TICKER
        s = (series_ticker or "").upper()
        # Exact lookup in canonical series registry (handles bare tickers like KXETH → "1h").
        meta = SERIES_META_BY_TICKER.get(s)
        if meta is not None:
            return meta.timeframe
        # When a full market ticker (e.g. "KXETH-26APR0323-B2050") is passed instead of the
        # series prefix, extract the prefix and try again.
        prefix = s.split("-")[0] if "-" in s else ""
        if prefix:
            meta = SERIES_META_BY_TICKER.get(prefix)
            if meta is not None:
                return meta.timeframe
        # Substring fallback for any non-canonical series names.
        if "15M" in s:
            return "15m"
        if "1H" in s or "H1" in s:
            return "1h"
        if "W" in s:
            return "weekly"
        if "D" in s:
            return "daily"
        return "UNK"

    def _max_strike_distance_pct(self, asset: str, timeframe: str) -> float:
        return self.config.asset_timeframe_max_strike_distance_pct.get(
            (asset.upper(), timeframe),
            self.config.default_max_strike_distance_pct,
        )

    @staticmethod
    def _seconds_to_expiry(close_time: Optional[str]) -> Optional[float]:
        if not close_time:
            return None
        try:
            dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return max(0.0, (dt - now).total_seconds())
        except Exception:
            return None

    @staticmethod
    def _minutes_to_expiry(close_time: Optional[str]) -> Optional[int]:
        s = FilterPipeline._seconds_to_expiry(close_time)
        if s is None:
            return None
        return int(s / 60)

    def _passes_liquidity(self, m: Dict[str, Any]) -> bool:
        liq = self.config.liquidity
        try:
            vol = int(m.get("volume") or 0)
            oi = int(m.get("open_interest") or 0)
        except Exception:
            vol = 0
            oi = 0
        if vol < liq.min_volume or oi < liq.min_open_interest:
            return False
        # Spread check only if fields exist; ignore otherwise.
        if liq.max_spread_cents is not None:
            bid = m.get("yes_bid_cents")
            ask = m.get("yes_ask_cents")
            if bid is not None and ask is not None:
                try:
                    if int(ask) - int(bid) > int(liq.max_spread_cents):
                        return False
                except Exception:
                    return False
        return True

    def _passes_expiry(self, m: Dict[str, Any]) -> bool:
        exp = self.config.expiry
        close_time = m.get("close_time") or m.get("expiration_time") or m.get("end_date")
        secs = self._seconds_to_expiry(close_time)
        mins = self._minutes_to_expiry(close_time)
        if mins is None:
            return True
        if mins < exp.min_minutes_to_expiry:
            return False
        if exp.max_minutes_to_expiry is not None and mins > exp.max_minutes_to_expiry:
            return False
        if exp.min_seconds_to_expiry_rti_crypto is not None and secs is not None:
            try:
                from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker

                tid = (m.get("ticker") or m.get("market_id") or "").strip()
                if tid and is_rti_settled_kalshi_crypto_ticker(tid):
                    if secs < float(exp.min_seconds_to_expiry_rti_crypto):
                        return False
            except Exception:
                pass
        return True

    def filter_markets(self, raw_markets: Dict[str, List[Dict[str, Any]]]) -> FilterPipelineResult:
        t0 = time.perf_counter()
        per_asset: Dict[str, AssetFilterStats] = {}
        all_candidates: List[MarketCandidateLite] = []

        for asset, markets in raw_markets.items():
            asset_u = asset.upper()
            st = AssetFilterStats(raw=len(markets))
            at0 = time.perf_counter()

            spot = self.get_spot_price(asset_u)
            _fp_logger.info(
                "Filter pipeline (asset=%s raw=%d spot_ok=%s)",
                asset_u,
                len(markets),
                spot is not None,
            )
            if spot is None:
                st.no_spot = len(markets)

            asset_candidates: List[MarketCandidateLite] = []
            for m in markets:
                ticker = m.get("ticker") or m.get("market_id") or ""
                if not ticker:
                    continue

                # CFB RTI quarantine: metadata-based exclusion when adapter is not live.
                try:
                    from merid.event_venues.kalshi.cfb_quarantine import (
                        is_cfb_anchored_market,
                        should_quarantine_rti_markets,
                    )
                    if should_quarantine_rti_markets() and is_cfb_anchored_market(m):
                        st.rti_quarantined += 1
                        continue
                except Exception:
                    pass

                if not self._passes_liquidity(m):
                    st.illiquid += 1
                    continue
                if not self._passes_expiry(m):
                    st.expiry_out_of_bounds += 1
                    continue

                strike = self._parse_strike(ticker)
                is_dir = False
                if strike is not None:
                    st.parsed_strike += 1
                    # Distance filtering DISABLED - moved to NearSpotSelector
                    # Keeping the code structure but always passing through
                    _ = spot  # for type checker, spot may be used for logging
                elif self._is_directional_market(ticker):
                    is_dir = True
                    st.directional += 1
                else:
                    st.unknown_type += 1
                    continue

                # Extract book/volume fields from raw market
                # BUG-FIX: Handle both fractional (WS) and fixed-point (catalog) prices
                try:
                    vol = int(m.get("volume") or 0)
                    oi = int(m.get("open_interest") or 0)
                    yes_bid = m.get("yes_bid")
                    yes_ask = m.get("yes_ask")

                    # Detect price format and convert to cents appropriately
                    is_fractional = self._is_price_fractional(m)

                    if is_fractional:
                        # WebSocket: fractions (0-1) → multiply by 100
                        best_bid = int(float(yes_bid) * 100) if yes_bid is not None else 0
                        best_ask = int(float(yes_ask) * 100) if yes_ask is not None else 0
                    else:
                        # Catalog/REST: already in cents (1-99) → use as-is
                        best_bid = int(float(yes_bid)) if yes_bid is not None else 0
                        best_ask = int(float(yes_ask)) if yes_ask is not None else 0

                    mid = (best_bid + best_ask) // 2 if (best_bid > 0 and best_ask > 0) else 0

                    # Fallback: REST /markets catalog often omits live book data but always
                    # provides last_price. Use it when both bid and ask are absent so that
                    # select_near_spot_best_edge does NOT drop the candidate as "degenerate book".
                    # (market_filter.py:1257 drops mid_price_cents==0 under the price_band counter.)
                    if mid == 0:
                        last_price_raw = m.get("last_price")
                        if last_price_raw is not None:
                            lp = float(last_price_raw)
                            # > 1.0 → catalog cents format; <= 1.0 → fractional WS format
                            mid = int(lp * 100) if 0 < lp <= 1.0 else int(lp) if lp > 1.0 else 0
                except Exception:
                    vol, oi, best_bid, best_ask, mid = 0, 0, 0, 0, 0

                asset_candidates.append(
                    MarketCandidateLite(
                        ticker=ticker,
                        asset=asset_u,
                        spot=spot,
                        strike=strike,
                        is_directional=is_dir,
                        close_time=m.get("close_time") or m.get("expiration_time") or m.get("end_date"),
                        series_ticker=m.get("series_ticker"),
                        volume=vol,
                        open_interest=oi,
                        best_bid_cents=best_bid,
                        best_ask_cents=best_ask,
                        mid_price_cents=mid,
                    )
                )

            st.candidates_pre_cap = len(asset_candidates)
            if self.config.max_candidates_per_asset > 0:
                # Deterministic preference: directional first, then closest-to-spot strikes.
                dir_c = [c for c in asset_candidates if c.is_directional]
                thr_c = [c for c in asset_candidates if not c.is_directional]
                thr_c.sort(
                    key=lambda c: (
                        Decimal("0")
                        if (c.spot is None or c.spot == 0 or c.strike is None)
                        else (abs(c.spot - c.strike) / c.spot)
                    )
                )
                asset_candidates = (dir_c + thr_c)[: self.config.max_candidates_per_asset]

            st.candidates_post_cap = len(asset_candidates)
            st.total_ms = (time.perf_counter() - at0) * 1000
            per_asset[asset_u] = st
            all_candidates.extend(asset_candidates)

        # Global cap: stable ordering by (is_directional desc, distance asc)
        dir_all = [c for c in all_candidates if c.is_directional]
        thr_all = [c for c in all_candidates if not c.is_directional]
        thr_all.sort(
            key=lambda c: (
                Decimal("0")
                if (c.spot is None or c.spot == 0 or c.strike is None)
                else (abs(c.spot - c.strike) / c.spot)
            )
        )
        final_lite = dir_all + thr_all
        if self.config.max_candidates_global > 0:
            final_lite = final_lite[: self.config.max_candidates_global]

        # Convert to canonical MarketCandidate for external use
        final: List[MarketCandidate] = []
        for c in final_lite:
            # Infer timeframe from series or ticker
            tf = self._infer_timeframe_from_series(c.series_ticker or "")
            if tf == "UNK":
                tf = self._infer_timeframe_from_series(c.ticker)
            
            # Calculate spread
            spread = c.best_ask_cents - c.best_bid_cents if c.best_ask_cents > c.best_bid_cents else 0
            
            # Parse expiry timestamp from close_time for group_id generation
            expiry_ts = 0.0
            if c.close_time:
                try:
                    # Try ISO format first
                    dt = datetime.fromisoformat(c.close_time.replace('Z', '+00:00'))
                    expiry_ts = dt.timestamp()
                except Exception:
                    try:
                        # Try common Kalshi formats
                        dt = datetime.strptime(c.close_time, "%Y-%m-%dT%H:%M:%S.%fZ")
                        expiry_ts = dt.timestamp()
                    except Exception:
                        pass
            
            # Generate canonical group_id for risk aggregation using canonical helper
            group_id = group_id_from_ticker(c.ticker, timeframe=tf, expiry_ts=expiry_ts) if c.asset else ""
            
            final.append(
                MarketCandidate(
                    ticker=c.ticker,
                    underlying=c.asset,  # asset -> underlying
                    timeframe=tf,
                    expiry_ts=expiry_ts,
                    volume=c.volume,
                    open_interest=c.open_interest,
                    best_bid_cents=c.best_bid_cents,
                    best_ask_cents=c.best_ask_cents,
                    spread_cents=spread,
                    mid_price_cents=c.mid_price_cents,
                    category="crypto",  # Default category
                    group_id=group_id,  # Canonical group ID for risk aggregation
                    # Pass through spot/strike/is_directional so _compute_edge can use them.
                    # Without these, _compute_edge sees strike=0 for all threshold markets and
                    # hits the `elif strike <= 0: return c` early exit, leaving model_yes_prob=None.
                    spot=float(c.spot) if c.spot is not None else 0.0,
                    strike=float(c.strike) if c.strike is not None else 0.0,
                    is_directional=c.is_directional,
                )
            )

        total_ms = (time.perf_counter() - t0) * 1000
        return FilterPipelineResult(per_asset=per_asset, final_candidates=final, total_ms=total_ms)

