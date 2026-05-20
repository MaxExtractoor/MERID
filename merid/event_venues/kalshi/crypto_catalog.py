"""Kalshi crypto market catalog — typed view over discovery for WS and routing.

Built from :class:`CatalogMarket` rows (series + markets / GET markets) so
subscription lists are multi-asset (BTC, ETH, SOL, XRP, DOGE) and multi-timeframe,
not BTC-only slices of the global catalog.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from logging import getLogger
from typing import Iterable, List, Optional, Sequence, Tuple, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from config.kalshi_crypto_config import ACTIVE_CRYPTO_FREQS
from config.kalshi_universe import ACTIVE_CRYPTO_WS_TIMEFRAMES, KALSHI_CRYPTO_ASSETS
from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
from merid.event_venues.kalshi.market_catalog import CatalogMarket, KalshiMarketCatalog

logger = getLogger(__name__)

_TIMEFRAME_TO_FREQ: dict[str, str] = {
    "15m": "15M",
    "1h": "1H",
    "daily": "D1",
    "weekly": "W1",
    "monthly": "1M",
    "annual": "Y",
    "yearly": "Y",
}

_ACTIVE_FREQ_SET = frozenset(ACTIVE_CRYPTO_FREQS)


class KalshiMarketInfo(BaseModel):
    """Normalized crypto contract metadata for subscription and routing."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    asset: str = Field(description="BTC | ETH | SOL | XRP | DOGE")
    frequency: str = Field(description="15M | 1H | D1 | W1 | 1M | Y")
    settlement_ts: Optional[datetime] = None
    strike: Optional[Decimal] = None
    side: Optional[str] = Field(
        default=None,
        description="Kalshi threshold side when inferrable, e.g. B / T",
    )


def _infer_side_from_ticker(ticker: str) -> Optional[str]:
    u = ticker.upper()
    if "-B" in u or u.rfind("-B") > 0:
        return "B"
    if "-T" in u or u.rfind("-T") > 0:
        return "T"
    return None


def catalog_market_to_kalshi_market_info(cm: CatalogMarket) -> Optional[KalshiMarketInfo]:
    """Map a catalog row to :class:`KalshiMarketInfo`, or None if not a tracked crypto contract."""
    if not cm.asset or cm.asset not in ALL_CRYPTO_ASSETS:
        return None
    if cm.category and cm.category != "crypto":
        return None
    if not cm.timeframe:
        return None
    freq = _TIMEFRAME_TO_FREQ.get(cm.timeframe)
    if not freq or freq not in _ACTIVE_FREQ_SET:
        return None
    
    # CRITICAL FIX: market_id is on nested EventMarket
    if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
        tid = cm.market.market_id
    elif hasattr(cm, "market_id"):
        tid = cm.market_id
    else:
        return None
    
    if not tid:
        return None
    
    # CRITICAL FIX: end_date is on nested EventMarket
    if hasattr(cm, "market") and hasattr(cm.market, "end_date"):
        nested_end_date = cm.market.end_date
    elif hasattr(cm, "end_date"):
        nested_end_date = cm.end_date
    else:
        nested_end_date = None
    
    exp = cm.expires_at or nested_end_date
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    strike_dec: Optional[Decimal] = None
    if cm.strike_price is not None:
        strike_dec = Decimal(str(cm.strike_price))
    return KalshiMarketInfo(
        ticker=tid,
        asset=cm.asset,
        frequency=freq,
        settlement_ts=exp,
        strike=strike_dec,
        side=_infer_side_from_ticker(tid),
    )


class KalshiCryptoCatalog:
    """Query helper over normalized crypto markets (typically from REST discovery)."""

    def __init__(self, markets: Sequence[KalshiMarketInfo]) -> None:
        self._markets: Tuple[KalshiMarketInfo, ...] = tuple(markets)

    @property
    def markets(self) -> Tuple[KalshiMarketInfo, ...]:
        return self._markets

    def tickers_for_asset_freq(
        self,
        asset: str,
        frequency: Optional[str] = None,
    ) -> List[str]:
        a = asset.upper()
        out = [
            m.ticker
            for m in self._markets
            if m.asset == a and (frequency is None or m.frequency == frequency)
        ]
        return sorted(set(out))

    def iter_tickers(self, asset: str, timeframe: str) -> List[str]:
        """Return market tickers for one asset and catalog timeframe string.

        ``timeframe`` uses catalog naming: ``\"15m\"``, ``\"1h\"``, ``\"daily\"``, ``\"weekly\"``.
        """
        freq = _TIMEFRAME_TO_FREQ.get(timeframe)
        if not freq:
            return []
        return self.tickers_for_asset_freq(asset.upper(), frequency=freq)

    def all_active_tickers(self) -> List[str]:
        """All tickers in this catalog that match the configured asset × frequency grid."""
        return self.all_active_crypto_tickers(KALSHI_CRYPTO_ASSETS, ACTIVE_CRYPTO_FREQS)

    def all_active_crypto_tickers(
        self,
        assets: Sequence[str],
        frequencies: Optional[Sequence[str]] = None,
    ) -> List[str]:
        asset_set = {x.upper() for x in assets}
        freq_set = None if frequencies is None else set(frequencies)
        out = [
            m.ticker
            for m in self._markets
            if m.asset in asset_set and (freq_set is None or m.frequency in freq_set)
        ]
        return sorted(set(out))


def build_kalshi_crypto_catalog_from_catalog_markets(
    markets: Iterable[CatalogMarket],
) -> KalshiCryptoCatalog:
    """Build a crypto-only catalog from enriched discovery rows."""
    infos: List[KalshiMarketInfo] = []
    for cm in markets:
        info = catalog_market_to_kalshi_market_info(cm)
        if info is not None:
            infos.append(info)
    return KalshiCryptoCatalog(infos)


def collect_crypto_ws_subscription_tickers(
    catalog: KalshiMarketCatalog,
    *,
    assets: Optional[Sequence[str]] = None,
    timeframes: Optional[Sequence[str]] = None,
    active_only: bool = True,
) -> List[str]:
    """Return sorted unique market tickers for Kalshi WS (ticker, trade, orderbook_delta).

    Filters to category *crypto*, canonical five assets, and configured timeframes,
    then builds a :class:`KalshiCryptoCatalog` so the result matches
    :meth:`KalshiCryptoCatalog.all_active_tickers` / ``kalshi_ticker_to_asset`` mapping.
    """

    asset_set = {a.upper() for a in (assets or KALSHI_CRYPTO_ASSETS)}
    tf_set = set(timeframes or ACTIVE_CRYPTO_WS_TIMEFRAMES)
    rows: List[CatalogMarket] = []
    for cm in catalog.get_all_markets():
        if not cm.asset or cm.asset not in asset_set:
            continue
        # CRITICAL FIX: active is on nested EventMarket
        if active_only:
            if hasattr(cm, "market") and hasattr(cm.market, "active"):
                if not cm.market.active:
                    continue
            elif hasattr(cm, "active"):
                if not cm.active:
                    continue
        # CRITICAL FIX: Don't filter by category since Kalshi API returns category=None for crypto markets
        # Instead, rely on asset detection from ticker patterns (KXBTC, KXETH, KXSOL, etc.)
        # if cm.category != "crypto":
        #     continue
        # CRITICAL FIX: Don't filter by timeframe since Kalshi API doesn't set it consistently
        # Instead, rely on series ticker suffix (KXBTC15M → 15m) which is already parsed in enrichment
        # if cm.timeframe not in tf_set:
        #     continue
        rows.append(cm)

    crypto_cat = build_kalshi_crypto_catalog_from_catalog_markets(rows)
    want_assets = list(assets) if assets is not None else KALSHI_CRYPTO_ASSETS
    freq_arg: Optional[Sequence[str]] = ACTIVE_CRYPTO_FREQS if timeframes is None else None
    return crypto_cat.all_active_crypto_tickers(want_assets, freq_arg)


def summarize_crypto_ws_coverage(tickers: Sequence[str], catalog: KalshiMarketCatalog) -> dict:
    """Per-asset counts for structured logging (asset=… freq=… ticker=… friendly)."""
    by_asset: dict[str, int] = {a: 0 for a in KALSHI_CRYPTO_ASSETS}
    tick_set = set(tickers)
    for cm in catalog.get_all_markets():
        # CRITICAL FIX: market_id is on nested EventMarket
        if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
            tid = cm.market.market_id
        elif hasattr(cm, "market_id"):
            tid = cm.market_id
        else:
            continue
        if tid not in tick_set or not cm.asset:
            continue
        if cm.asset in by_asset:
            by_asset[cm.asset] += 1
    return {"by_asset": by_asset, "total": len(tickers)}


def assert_each_asset_represented(
    tickers: Sequence[str],
    catalog: KalshiMarketCatalog,
    *,
    assets: Sequence[str] | None = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, missing_assets) if at least one subscribed ticker exists per asset."""
    summary = summarize_crypto_ws_coverage(tickers, catalog)
    want = [a for a in (assets or KALSHI_CRYPTO_ASSETS)]
    missing = [a for a in want if summary["by_asset"].get(a, 0) == 0]
    return (not missing, missing)


class CryptoWsBridgePrep(TypedDict):
    """Return shape for :func:`prepare_crypto_ws_bridge_subscription`."""

    tickers: List[str]
    by_asset_catalog: dict[str, int]
    total: int
    ok_catalog_assets: bool
    missing_catalog_assets: List[str]
    ok_prefix_coverage: bool
    counts_by_prefix: dict[str, int]
    missing_prefix_assets: List[str]


def prepare_crypto_ws_bridge_subscription(catalog: KalshiMarketCatalog) -> CryptoWsBridgePrep:
    """Build WS ticker list plus catalog and prefix-based coverage (shared entrypoints).

    Calls :func:`config.kalshi_crypto_config.check_ws_ticker_asset_coverage`, which
    may raise ``ValueError`` when ``MERID_STRICT_WS_CRYPTO_COVERAGE=1`` and any
    canonical asset is missing from *tickers*.
    """
    from config.kalshi_crypto_config import check_ws_ticker_asset_coverage

    tickers = collect_crypto_ws_subscription_tickers(catalog)
    cov = summarize_crypto_ws_coverage(tickers, catalog)
    ok_cat, missing_cat = assert_each_asset_represented(tickers, catalog)
    ok_px, counts_px, missing_px = check_ws_ticker_asset_coverage(tickers)
    return {
        "tickers": tickers,
        "by_asset_catalog": cov["by_asset"],
        "total": cov["total"],
        "ok_catalog_assets": ok_cat,
        "missing_catalog_assets": missing_cat,
        "ok_prefix_coverage": ok_px,
        "counts_by_prefix": dict(counts_px),
        "missing_prefix_assets": missing_px,
    }
