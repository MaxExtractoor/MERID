"""BTC/ETH/SOL/XRP/DOGE AgentGrid helpers — matrix logs, capability checks, filters."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Protocol

from merid.prediction.strategy import StrategyConfig

if TYPE_CHECKING:
    from merid.prediction.agent_grid_config import AgentConfig
    from merid.prediction.trading_agent import KalshiTradingAgent

CORE_CRYPTO_ASSETS = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})

# AgentGrid timeframe label → KALSHI_CRYPTO_PRODUCTS key suffix
_TIMEFRAME_TO_PRODUCT_SUFFIX = {
    "15m": "15M",
    "1h": "1H",
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "annual": "ANNUAL",
}


def crypto_product_key(asset: str, timeframe: str) -> str:
    """Build key into ``KALSHI_CRYPTO_PRODUCTS`` (e.g. ``BTC``, ``15m`` → ``BTC_15M``)."""
    suf = _TIMEFRAME_TO_PRODUCT_SUFFIX.get(timeframe)
    if not suf:
        raise ValueError(f"Unknown AgentGrid timeframe for crypto products: {timeframe!r}")
    return f"{asset}_{suf}"


def market_id_matches_series(market_id: str, series_tickers: List[str]) -> bool:
    """True if Kalshi ``market_id`` belongs to one of the series roots (e.g. KXBTC15M-...)."""
    if not market_id:
        return False
    for s in series_tickers:
        if market_id == s or market_id.startswith(f"{s}-"):
            return True
    return False


class _SupportsPmCryptoAgent(Protocol):
    config: Any
    agent_id: str


def is_core_crypto_pm_config(config: "AgentConfig") -> bool:
    """True for single-asset core crypto directional agents (grid PM stack)."""
    if getattr(config, "category", None) != "crypto":
        return False
    if getattr(config, "archetype", None) != "directional":
        return False
    assets = list(getattr(config, "assets", None) or [])
    if len(assets) != 1 or assets[0] not in CORE_CRYPTO_ASSETS:
        return False
    return True


def is_core_crypto_pm_agent(agent: _SupportsPmCryptoAgent) -> bool:
    return is_core_crypto_pm_config(agent.config)


def default_strategy_min_edge_floor_bps() -> float:
    """Approximate early-phase min edge as bps (strategy uses fraction of contract)."""
    sc = StrategyConfig()
    return float(sc.min_edge_early) * 10000.0


def log_crypto_pm_agent_matrix(
    agents: List[_SupportsPmCryptoAgent],
    logger: Any,
    *,
    tag: str = "[CRYPTO-PM-MATRIX]",
) -> None:
    """One structured startup line per core crypto PM agent."""
    floor_bps = default_strategy_min_edge_floor_bps()
    rows = [a for a in agents if is_core_crypto_pm_agent(a)]
    logger.info(
        "%s count=%d strategy_min_edge_floor≈%.0fbps",
        tag,
        len(rows),
        floor_bps,
    )
    for a in sorted(rows, key=lambda x: (x.config.assets[0], x.config.name)):
        c = a.config
        asset = c.assets[0] if c.assets else "?"
        tf = c.timeframes[0] if c.timeframes else "?"
        ew = c.entry_window
        logger.info(
            "%s agent=%s agent_id=%s asset=%s tf=%s enabled=%s min_edge_early_bps≈%.0f ew_before=%s ew_cutoff=%s",
            tag,
            c.name,
            a.agent_id,
            asset,
            tf,
            getattr(c, "enabled", True),
            floor_bps,
            ew.minutes_before_expiry,
            ew.cutoff_minutes_before_expiry,
        )


def warn_missing_kalshi_pm_capabilities(
    agents: List[_SupportsPmCryptoAgent],
    logger: Any,
) -> None:
    """Log WARNING if any core crypto agent lacks kalshi_pm / live scope."""
    try:
        from merid.guardrails.capabilities import get_capability_store
    except Exception as exc:
        logger.debug("capability store unavailable: %s", exc)
        return
    store = get_capability_store()
    for a in agents:
        if not is_core_crypto_pm_agent(a):
            continue
        cap = store.get(a.agent_id)
        if cap is None:
            logger.warning(
                "[CRYPTO-PM-CAP] missing capability map for agent_id=%s name=%s — register kalshi_pm",
                a.agent_id,
                a.config.name,
            )
            continue
        if getattr(cap, "max_scope", "") != "live":
            logger.warning(
                "[CRYPTO-PM-CAP] agent_id=%s name=%s max_scope=%r — expected live for PM production",
                a.agent_id,
                a.config.name,
                cap.max_scope,
            )


def collect_crypto_pm_risk_summary() -> Dict[str, Any]:
    """Structured crypto PM risk view: Kalshi risk state, feed staleness, per-(asset,tf) notionals.

    Safe to call from scripts or ops endpoints without starting the full web stack.
    """
    out: Dict[str, Any] = {"assets": {}}
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

        risk = get_kalshi_risk()
        st = risk.state
        crypto_cat_notional = float(st.category_notional.get("crypto", 0.0))
        out["kalshi_risk"] = {
            "daily_pnl_usd": st.daily_pnl_usd,
            "daily_fees_usd": st.daily_fees_usd,
            "total_notional_usd": st.total_notional_usd,
            "kill_switch_active": st.kill_switch_active,
            "kill_switch_reason": st.kill_switch_reason,
            "category_notional_crypto_usd": crypto_cat_notional,
            "category_notional_all": dict(st.category_notional),
        }
        per_asset: Dict[str, Dict[str, Any]] = {a: {} for a in CORE_CRYPTO_ASSETS}
        for (ast, tf), notional in st.asset_horizon_notional.items():
            if ast not in per_asset:
                continue
            per_asset[ast][tf] = {"notional_usd": float(notional)}
        for ast in CORE_CRYPTO_ASSETS:
            exposure = sum(
                float(v)
                for (a, _), v in st.asset_horizon_notional.items()
                if a == ast
            )
            entry = per_asset.setdefault(ast, {})
            entry["aggregated_horizon_notional_usd"] = exposure
            out["assets"][ast] = entry
    except Exception as exc:
        out["kalshi_risk_error"] = repr(exc)

    try:
        from core.execution_gate import check_price_feed_staleness

        stale = check_price_feed_staleness()
        out["feed_staleness"] = {
            "safe_to_trade": stale.get("safe_to_trade"),
            "critical_count": stale.get("critical_count"),
            "stale_symbols": stale.get("stale_symbols", []),
        }
        tokens = ("BTC", "ETH", "SOL", "XRP", "DOGE")
        stale_crypto = []
        for row in stale.get("stale_symbols", []) or []:
            sym = str(row.get("symbol", "")).upper()
            if any(t in sym for t in tokens):
                stale_crypto.append(row)
        out["feed_staleness"]["stale_crypto_related"] = stale_crypto
    except Exception as exc:
        out["feed_staleness_error"] = repr(exc)

    return out


async def reconcile_crypto_pm_positions(asset: str, timeframe: str) -> Dict[str, Any]:
    """Compare REST positions vs position cache vs KalshiRiskManager for one asset/timeframe."""
    from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
    from merid.event_venues.kalshi.position_cache import get_position_cache
    from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter

    asset_u = asset.upper().strip()
    if asset_u not in CORE_CRYPTO_ASSETS:
        raise ValueError(f"asset must be one of {sorted(CORE_CRYPTO_ASSETS)}")
    key = crypto_product_key(asset_u, timeframe)
    series = list(KALSHI_CRYPTO_PRODUCTS.get(key, []) or [])
    if not series:
        raise ValueError(f"No KALSHI_CRYPTO_PRODUCTS entry for {key!r}")

    adapter = get_kalshi_venue_adapter()
    rest_positions = await adapter.get_positions()
    matched_rest = [p for p in rest_positions if market_id_matches_series(p.market_id, series)]
    rest_matches = [
        {
            "market_id": p.market_id,
            "size": str(p.size),
            "avg": str(p.average_entry_price),
        }
        for p in matched_rest
    ]
    rest_contracts = sum(int(abs(Decimal(str(p.size)))) for p in matched_rest)

    cache = get_position_cache().get_all_positions()
    cache_matches = {
        mid: {"contracts": cp.contracts, "side": cp.side}
        for mid, cp in cache.items()
        if market_id_matches_series(mid, series)
    }
    cache_total = sum(abs(v["contracts"]) for v in cache_matches.values())

    risk = get_kalshi_risk()
    notion = float(risk.state.asset_horizon_notional.get((asset_u, timeframe), 0.0))

    rest_ids = {p.market_id for p in matched_rest}
    cache_ids = set(cache_matches.keys())
    discrepancies: List[str] = []
    if rest_ids != cache_ids:
        discrepancies.append(
            f"market_id set mismatch only_rest={sorted(rest_ids - cache_ids)} only_cache={sorted(cache_ids - rest_ids)}"
        )
    if rest_contracts != cache_total:
        discrepancies.append(
            f"contract_count rest={rest_contracts} cache={cache_total}"
        )

    return {
        "asset": asset_u,
        "timeframe": timeframe,
        "product_key": key,
        "series_tickers": series,
        "rest_positions": rest_matches,
        "cache_positions": cache_matches,
        "risk_asset_tf_notional_usd": notion,
        "discrepancies": discrepancies,
    }
