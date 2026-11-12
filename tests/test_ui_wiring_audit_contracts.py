"""UI wiring audit (2026-11) — backend contract regressions.

Pins the endpoint shapes the React seven-view UI consumes:

1. GET /api/v1/kalshi/market-states — executable BBO + book trust metadata
   (yes_bid_cents/yes_ask_cents/no_bid_cents/no_ask_cents, book_age_ms,
   book_health, executable, data_source, quote_owner, ...).
2. GET /api/v1/kalshi/positions — position_cache path must surface
   unrealized_pnl/realized_pnl (USD) instead of dropping them (UI showed $0).
3. GET /api/v1/kalshi/markets — catalog outcomes carry real bid/ask in
   dollars derived from CatalogMarket.yes_bid/yes_ask (never the
   price-backfilled EventOutcome.best_bid/best_ask).
4. POST /api/v1/kalshi/orders — fractional contract counts (0.01 grid) and
   the KXSOL 15m prefix parity fix.
5. GET /api/v1/kalshi-grid/summary — per-agent enabled/running flags so the
   UI blotter/ribbon show real agent counts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException


# ── 1. /market-states ────────────────────────────────────────────────────

def test_market_states_emits_executable_bbo_and_trust_fields():
    from web.api.kalshi_api import get_market_states

    state = SimpleNamespace(
        book_initialized=True,
        best_bid_cents=61,
        best_ask_cents=64,
        best_no_bid_cents=36,
        best_no_ask_cents=39,
        mid_cents=62,
        spread_cents=3.0,
        depth_10c=1500,
        top_of_book_size=400,
        volume_24h=42000,
        open_interest=9000,
        seconds_to_expiry=512.4,
        expiration_time="2026-11-14T05:15:00+00:00",
        status="open",
        underlying="BTC",
        strike_price=97000.5,
        floor_strike=97000.0,
        external_spot=97012.3,
        last_price_cents=63,
        book_health="LIVE",
        executable=True,
        data_source="WS_LIVE",
        quote_owner="WS_FRESH_VERIFIED",
        data_quality="GOOD",
        last_book_update_wall_ts=1_700_000_000.0,
        last_update=datetime(2026, 11, 14, 5, 0, 0, tzinfo=timezone.utc),
        last_updated=None,
    )
    store = SimpleNamespace(
        get_all_states=lambda: {"KXBTC15M-TEST": state},
        get_last_update_timestamp=lambda: 1_700_000_000.0,
    )

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        out = asyncio.run(get_market_states(tickers=None))

    row = out["states"]["KXBTC15M-TEST"]
    assert row["book_initialized"] is True
    assert row["yes_bid_cents"] == 61
    assert row["yes_ask_cents"] == 64
    assert row["no_bid_cents"] == 36
    assert row["no_ask_cents"] == 39
    assert row["mid_cents"] == 62
    assert row["spread_cents"] == 3.0
    assert row["book_health"] == "LIVE"
    assert row["executable"] is True
    assert row["data_source"] == "WS_LIVE"
    assert row["quote_owner"] == "WS_FRESH_VERIFIED"
    assert row["underlying"] == "BTC"
    assert row["strike_price"] == 97000.5
    assert row["floor_strike"] == 97000.0
    assert row["external_spot"] == 97012.3
    assert row["last_price_cents"] == 63
    assert row["seconds_to_expiry"] == 512.4
    # book_age_ms is wall-clock derived — must be a non-negative number.
    assert isinstance(row["book_age_ms"], float)
    assert row["book_age_ms"] >= 0
    assert row["last_update_ts"] == "2026-11-14T05:00:00+00:00"


def test_market_states_tolerates_sparse_state_objects():
    """Older/partial state objects must emit None, never raise."""
    from web.api.kalshi_api import get_market_states

    state = SimpleNamespace(book_initialized=False)  # nothing else present
    store = SimpleNamespace(
        get_all_states=lambda: {"KXXRP15M-SPARSE": state},
        get_last_update_timestamp=lambda: None,
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        out = asyncio.run(get_market_states(tickers=None))
    row = out["states"]["KXXRP15M-SPARSE"]
    assert row["book_initialized"] is False
    assert row["yes_bid_cents"] is None
    assert row["book_age_ms"] is None
    assert row["book_health"] is None


# ── 2. /positions — cache path PnL ───────────────────────────────────────

def test_ensure_fresh_positions_surfaces_cache_pnl():
    """position_cache rows carry unrealized/realized PnL in USD — the API
    must pass them through (previously dropped -> UI showed $0.00)."""
    from web.api.kalshi_api import _ensure_fresh_positions

    pos = SimpleNamespace(
        side="yes",
        contracts=Decimal("2.50"),
        avg_price_cents=63,
        unrealized_pnl_usd=Decimal("0.42"),
        realized_pnl_usd=Decimal("-0.10"),
    )
    cache = SimpleNamespace(
        _last_sync=datetime.now(timezone.utc),  # fresh -> no REST sync
        get_all_positions=lambda validate_freshness=True: {"KXBTC15M-P": pos},
    )
    with patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        return_value=cache,
    ):
        positions, meta = asyncio.run(_ensure_fresh_positions())

    assert len(positions) == 1
    row = positions[0]
    assert row["ticker"] == "KXBTC15M-P"
    assert row["outcome"] == "yes"
    assert abs(row["avg_price"] - 0.63) < 1e-9
    assert abs(row["unrealized_pnl"] - 0.42) < 1e-9
    assert abs(row["realized_pnl"] - (-0.10)) < 1e-9
    assert row["source"] == "position_cache"


# ── 3. /markets catalog outcomes ─────────────────────────────────────────

def _cm(**kw: Any) -> Any:
    base = dict(
        market=SimpleNamespace(
            market_id="KXBTC15M-T",
            question="BTC up?",
            active=True,
            volume=Decimal("1000"),
            outcomes=[],
        ),
        category="crypto",
        asset="BTC",
        timeframe="15m",
        market_type="binary",
        expires_at=None,
        minutes_to_expiry=300.0,
        yes_bid=0.62,
        yes_ask=0.65,
        yes_bid_size=10.0,
        yes_ask_size=12.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _outcome(oid: str, name: str, price: str) -> Any:
    return SimpleNamespace(outcome_id=oid, outcome_name=name, price=Decimal(price))


def test_catalog_outcome_row_yes_no_quotes():
    from web.api.kalshi_api import _catalog_outcome_row

    cm = _cm()
    yes = _catalog_outcome_row(cm, _outcome("yes", "Yes", "0.63"))
    no = _catalog_outcome_row(cm, _outcome("no", "No", "0.37"))

    assert yes["price"] == pytest.approx(0.63)
    assert yes["bid"] == pytest.approx(0.62)
    assert yes["ask"] == pytest.approx(0.65)
    # NO side is the YES-book complement: bid = 1 - yes_ask, ask = 1 - yes_bid.
    assert no["price"] == pytest.approx(0.37)
    assert no["bid"] == pytest.approx(0.35)
    assert no["ask"] == pytest.approx(0.38)


def test_catalog_outcome_row_missing_quotes_stay_none():
    from web.api.kalshi_api import _catalog_outcome_row

    cm = _cm(yes_bid=None, yes_ask=None)
    yes = _catalog_outcome_row(cm, _outcome("yes", "Yes", "0.63"))
    no = _catalog_outcome_row(cm, _outcome("no", "No", "0.37"))
    assert yes["bid"] is None and yes["ask"] is None
    assert no["bid"] is None and no["ask"] is None
    # price still flows through — it is the venue last-price, not a quote.
    assert yes["price"] == pytest.approx(0.63)


def test_list_markets_catalog_shape_includes_quotes():
    from web.api.kalshi_api import list_markets

    cm = _cm()
    cm.market.outcomes = [
        _outcome("yes", "Yes", "0.63"),
        _outcome("no", "No", "0.37"),
    ]
    catalog = SimpleNamespace(get_all_markets=lambda: [cm])
    with patch("web.api.kalshi_api._get_catalog", return_value=catalog):
        out = asyncio.run(list_markets(
            category=None, asset=None, timeframe=None, search=None,
            sort=None, live=None, limit=100,
        ))
    assert out["count"] == 1
    m = out["markets"][0]
    assert m["yes_bid"] == pytest.approx(0.62)
    assert m["yes_ask"] == pytest.approx(0.65)
    assert m["outcomes"][0]["bid"] == pytest.approx(0.62)
    assert m["outcomes"][1]["ask"] == pytest.approx(0.38)


# ── 4. place_order count + KXSOL prefix ──────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_place_order_rejects_sub_centicontract_counts():
    from web.api.kalshi_api import place_order

    for bad in (0, -1, 0.005, 0.009):
        with pytest.raises(HTTPException) as ei:
            _run(place_order(
                ticker="KXTEST-1", side="yes", action="buy",
                count=bad, price_cents=50, mode="paper",
            ))
        assert ei.value.status_code == 400


def test_place_order_rejects_non_finite_count():
    from web.api.kalshi_api import place_order

    with pytest.raises(HTTPException) as ei:
        _run(place_order(
            ticker="KXTEST-1", side="yes", action="buy",
            count=float("nan"), price_cents=50, mode="paper",
        ))
    assert ei.value.status_code == 400


def test_place_order_accepts_fractional_count():
    """0.15 contracts must pass validation (router decides the rest)."""
    from web.api.kalshi_api import place_order

    try:
        res = _run(place_order(
            ticker="KXTEST-1", side="yes", action="buy",
            count=0.15, price_cents=50, mode="paper",
        ))
        assert isinstance(res, dict)
    except HTTPException as exc:
        # Routing-layer failures (503) are fine — validation already passed.
        assert exc.status_code != 400, exc.detail


def test_place_order_kxsol_enters_crypto_exit_policy_branch():
    """KXSOL15M buys must hit the same exit-policy gate as the other 15m
    crypto series (previously KXSOL was missing from the prefix tuple)."""
    import web.api.kalshi_api as api

    # Isolate the exit-policy contract: approve the risk pre-check so the
    # order reaches the crypto 15m branch (test env has $0 bankroll, which
    # would otherwise reject upstream of the gate under test).
    class _ApproveAll:
        @staticmethod
        def check_order(*a, **k):
            return True, "ok"

    # MERID_PROFIT_ONLY_EXITS defaults on -> an explicit stop_loss on a
    # 15m-crypto buy is a contract violation (400).  A non-crypto ticker
    # skips the branch entirely.
    with patch.object(api, "_get_risk", return_value=_ApproveAll()):
        with pytest.raises(HTTPException) as ei:
            _run(api.place_order(
                ticker="KXSOL15M-TEST", side="yes", action="buy",
                count=1, price_cents=50, mode="paper",
                stop_loss_price_cents=40,
            ))
    assert ei.value.status_code == 400
    assert "profit_only_v1" in str(ei.value.detail)

    # Non-crypto ticker must NOT raise that specific violation.
    try:
        with patch.object(api, "_get_risk", return_value=_ApproveAll()):
            _run(api.place_order(
                ticker="KXTEST-1", side="yes", action="buy",
                count=1, price_cents=50, mode="paper",
                stop_loss_price_cents=40,
            ))
    except HTTPException as exc:
        assert "profit_only_v1" not in str(exc.detail)


# ── 5. grid /summary per-agent flags ─────────────────────────────────────

def test_grid_summary_emits_agent_running_flags():
    import asyncio as _aio
    from web.api.kalshi_agent_grid_api import get_grid_summary

    def _agent(name: str, asset: str, enabled: bool) -> Any:
        return SimpleNamespace(
            config=SimpleNamespace(name=name, series_tickers=[f"KX{asset}15M"]),
            enabled=enabled,
            _cycle_decision={},
            _running=True,
        )

    grid = SimpleNamespace(
        _running=True,
        _agents=[
            _agent("BTC_15M", "BTC", True),
            _agent("SOL_15M", "SOL", False),
        ],
        _executed_candidates=set(),
        _last_exchange_positions=[],
        _last_open_orders=[],
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(agent_grid_15m=grid)),
    )
    out = _aio.run(get_grid_summary(request))

    assert out["available"] is True
    assert out["running"] is True
    assert out["agent_count"] == 2
    rows = {a["name"]: a for a in out["agents"]}
    assert rows["BTC_15M"]["enabled"] is True
    assert rows["BTC_15M"]["running"] is True
    assert rows["SOL_15M"]["enabled"] is False
    assert rows["SOL_15M"]["running"] is False
