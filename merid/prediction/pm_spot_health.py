"""PM crypto spot + vol bridge diagnostics for operator dashboards.

``PredictionMarketModel.get_spot_price`` reads the same :class:`data.live_price_feed.LivePriceFeed`
singleton the API uses: ``get_current_price`` tries ``ASSET/USD`` (the only key emitted after
the Coinbase Advanced Trade poll → stored as ``BTC/USD``; USDT mirror removed).

This module aggregates status without importing Kalshi agents.
"""

from __future__ import annotations

from typing import Any, Dict, List

from utils.logger import get_logger

logger = get_logger("merid.prediction.pm_spot_health")


def _pm_spot_detail_when_spot_none(asset: str, model: Any) -> str:
    """Classify failure after ``get_spot_price`` already returned None (single get_spot_price call per asset)."""
    au = (asset or "").strip().upper()
    if not au:
        return "no_asset"
    if not getattr(model, "_price_feed", None):
        return "no_price_feed"
    try:
        from merid.prediction.model import pm_spot_feed_symbol_candidates

        pd = None
        for sym in pm_spot_feed_symbol_candidates(au):
            pd = model._price_feed.get_current_price(sym)
            if pd:
                break
        if not pd:
            return "no_quote_or_feed_ttl_expired"
        from merid.prediction.model import max_spot_age_seconds
        from data.live_price_feed import _utc_age_seconds

        _age = _utc_age_seconds(pd.timestamp)
        if _age > float(max_spot_age_seconds()):
            return "pm_max_age_exceeded"
    except Exception as exc:
        logger.debug("pm_spot_detail_when_spot_none: %s", exc)
        return "unknown"
    return "unknown"


def _feed_row(asset: str) -> Dict[str, Any]:
    """Raw cache row for PM spot pair (USD primary) — age vs LivePriceFeed TTL, separate from PM staleness."""
    out: Dict[str, Any] = {
        "asset": asset.upper(),
        "symbol": f"{asset.upper()}/USD",
        "cache_hit": False,
        "price": None,
        "cache_age_seconds": None,
        "feed_ttl_expired": False,
    }
    try:
        from data.live_price_feed import CACHE_TTL_SECONDS, _utc_age_seconds, get_live_price_feed
        from merid.prediction.model import pm_spot_feed_symbol_candidates

        feed = get_live_price_feed()
        raw = None
        sym = f"{asset.upper()}/USD"
        for cand in pm_spot_feed_symbol_candidates(asset):
            raw = feed.price_cache.get(cand)
            if raw is not None:
                sym = cand
                break
        out["symbol"] = sym
        if raw is None:
            return out
        out["cache_hit"] = True
        out["price"] = float(raw.price) if raw.price is not None else None
        ts = getattr(raw, "timestamp", None)
        if ts is not None:
            age = _utc_age_seconds(ts)
            out["cache_age_seconds"] = round(age, 1)
            out["feed_ttl_expired"] = age > float(CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.debug("pm_spot_health feed row skipped: %s", exc)
    return out


def get_operator_pm_spot_block() -> Dict[str, Any]:
    """Snapshot for ``/operator/risk-state`` — active crypto assets + PM spot + cached vol context."""
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        from merid.prediction.model import PredictionMarketModel, max_spot_age_seconds
        from merid.signals.crypto_pm_vol_bridge import get_cached_pm_vol_context

        model = PredictionMarketModel()
        max_age = max_spot_age_seconds()
        assets: List[str] = list(ACTIVE_CRYPTO_ASSETS)
        from data.live_price_feed import get_live_price_feed

        feed = get_live_price_feed()
        feed_snap = feed.get_pm_feed_health_snapshot(assets)
        per: Dict[str, Any] = {}
        all_ok = True
        for a in assets:
            sp = model.get_spot_price(a, "")
            if sp is not None:
                reason = "ok"
            else:
                reason = _pm_spot_detail_when_spot_none(a, model)
            sym_usd = f"{a.upper()}/USD"
            fh = (feed_snap.get("per_asset") or {}).get(sym_usd, {})
            lf_healthy = bool(fh.get("live_price_feed_healthy", True))
            warming = bool(fh.get("warming", False))
            tick_age = fh.get("last_stream_tick_age_seconds")
            if (
                reason == "no_quote_or_feed_ttl_expired"
                and not lf_healthy
                and not warming
            ):
                reason = "live_price_feed_unhealthy"
            pm_effective = reason == "ok"
            if not pm_effective:
                all_ok = False
            row = _feed_row(a)
            row["live_price_feed_healthy"] = lf_healthy
            row["last_stream_tick_age_seconds"] = tick_age
            row["live_feed_warming"] = warming
            vctx = get_cached_pm_vol_context().get(a.upper()) or {}
            per[a.upper()] = {
                # Back-compat: same as ``pm_spot_effective_ok`` (usable for PM / MM gate).
                "pm_spot_ok": pm_effective,
                "pm_spot_effective_ok": pm_effective,
                "pm_spot_unusable_reason": reason,
                "pm_spot_usd": float(sp) if sp is not None else None,
                "pm_max_spot_age_seconds": max_age,
                "live_price_feed_healthy": lf_healthy,
                "last_stream_tick_age_seconds": tick_age,
                "live_price_feed": row,
                "vol_bridge": {
                    "vol_band": vctx.get("vol_band"),
                    "vol_size_mult": vctx.get("vol_size_mult"),
                    "realized_vol_annualized": vctx.get("realized_vol_annualized"),
                    "bars_available": vctx.get("bars_available"),
                },
            }
        kalshi_only = False
        try:
            from merid.settings import settings

            kalshi_only = bool(getattr(settings, "KALSHI_ONLY", False))
        except Exception:
            pass

        return {
            "summary": {
                "all_pm_assets_have_spot": all_ok,
                "kalshi_only_mode": kalshi_only,
                "live_price_feed_running": feed_snap.get("live_price_feed_running"),
                "live_feed_warming": feed_snap.get("live_feed_warming"),
                "last_global_stream_tick_age_seconds": feed_snap.get(
                    "last_global_stream_tick_age_seconds"
                ),
                "note": (
                    "PM spot usability = PredictionMarketModel.get_spot_price (not raw cache alone): "
                    "LivePriceFeed.get_current_price must return a row younger than CACHE_TTL_SECONDS "
                    f"(see data.live_price_feed), then quote timestamp must be within MERID_PM_MAX_SPOT_AGE_SECONDS "
                    f"(currently {max_age}s). If PM max age is stricter than cache age, feed_ttl_expired may be false "
                    "while pm_spot_effective_ok is false (pm_spot_unusable_reason=pm_max_age_exceeded). "
                    "CRYPTO_15M_MM hard gate uses the same get_spot_price path as snapshot.spot_price_usd. "
                    "Primary feed: Coinbase Advanced HTTP → price_cache; in KALSHI_ONLY mode CCXT exchanges are not "
                    "initialized — Coinbase is the usual PM spot path. "
                    "live_price_feed_healthy / last_stream_tick_age_seconds reflect stream liveness (see "
                    "LIVE_FEED_HEALTH_MAX_AGE_SECONDS in data.live_price_feed); pm_max_age_exceeded means the quote "
                    "exists and the stream is OK but MERID_PM_MAX_SPOT_AGE_SECONDS is stricter."
                ),
            },
            "assets": per,
        }
    except Exception as exc:
        logger.debug("get_operator_pm_spot_block failed: %s", exc)
        return {
            "summary": {"all_pm_assets_have_spot": False, "error": str(exc)},
            "assets": {},
        }
