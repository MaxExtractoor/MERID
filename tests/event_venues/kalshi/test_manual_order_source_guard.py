"""Regression: protective-exit order sources must pass the client manual-order guard.

2026-10-03 incident: every stop-candidate exit order was rejected at the wire
with ``Manual order placement blocked`` because ``client.py``'s
``_allowed_sources`` never got ``stop_candidate`` (the router-side whitelist
was updated 2026-09-25; the client copy was not).  Stop exits fired correctly
upstream — detection, pricing, firewall approval — then died at the lowest
guard, turning bounded stop losses into full-settlement losses
(XRP yes@80 -> -82c vs ~-17c if the stop had executed).

The guard must admit the pipeline's exit-family sources while still blocking
genuinely manual/unknown sources.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from merid.event_venues.base import VenueOrder
from merid.event_venues.kalshi import client as kalshi_client_module
from merid.event_venues.kalshi.client import KalshiVenueClient

_MANUAL_BLOCK_SUBSTR = "Manual order placement blocked"

# Sources the live pipeline actually stamps on orders that reach the client.
_EXIT_FAMILY_SOURCES = (
    "stop_candidate",
    "stop_candidate_reducer",
    "position_monitor_exit",
    "position_monitor_exit_retry",
    "resting_bracket_take_profit",
    "resting_bracket_stop_loss",
)


def _make_order(source, *, sell: bool = True) -> VenueOrder:
    return VenueOrder(
        market_id="KXTEST15M-26OCT031200-00",
        side="sell" if sell else "buy",
        size=Decimal("1"),
        price=Decimal("0.20"),
        order_type="limit",
        outcome_id="no",
        client_order_id="test_guard_order",
        source=source,
    )


def _client() -> KalshiVenueClient:
    """Bare client — the source guard precedes any network/credential use."""
    return KalshiVenueClient.__new__(KalshiVenueClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", _EXIT_FAMILY_SOURCES)
async def test_exit_family_sources_pass_manual_guard(source: str, monkeypatch) -> None:
    """Exit-family sources must not be rejected as manual orders.

    They may fail downstream (invalid test ticker is fine) — the assertion is
    only that the failure is NOT the manual-placement block.
    """
    monkeypatch.delenv("DEBUG_ALLOW_MANUAL_ORDERS", raising=False)

    async def _fake_validate(ticker):
        return False, f"test: invalid ticker {ticker}"

    monkeypatch.setattr(
        kalshi_client_module, "_validate_ticker_exists", _fake_validate
    )

    result = await _client().place_order_result(_make_order(source))
    assert not result.success
    assert _MANUAL_BLOCK_SUBSTR not in (result.error_message or ""), (
        f"source={source!r} was rejected as a manual order — the same class "
        f"of bug that silently refused every stop-candidate exit on 2026-10-02/03"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["totally_manual", "qa_script", None])
async def test_unknown_sources_still_blocked(source, monkeypatch) -> None:
    """Unknown/absent sources remain blocked — the guard keeps its teeth."""
    monkeypatch.delenv("DEBUG_ALLOW_MANUAL_ORDERS", raising=False)
    result = await _client().place_order_result(_make_order(source, sell=False))
    assert not result.success
    assert _MANUAL_BLOCK_SUBSTR in (result.error_message or "")


@pytest.mark.asyncio
async def test_entry_pipeline_source_passes(monkeypatch) -> None:
    """Positive control: the normal agent-grid source keeps passing."""
    monkeypatch.delenv("DEBUG_ALLOW_MANUAL_ORDERS", raising=False)

    async def _fake_validate(ticker):
        return False, f"test: invalid ticker {ticker}"

    monkeypatch.setattr(
        kalshi_client_module, "_validate_ticker_exists", _fake_validate
    )

    result = await _client().place_order_result(
        _make_order("merid.prediction.agent_grid_15m", sell=False)
    )
    assert not result.success
    assert _MANUAL_BLOCK_SUBSTR not in (result.error_message or "")
