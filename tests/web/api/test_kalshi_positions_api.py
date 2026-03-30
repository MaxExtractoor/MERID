"""Tests for /api/v1/kalshi/positions — reconciled position cache as primary source.

Validates:
  - Reconciled position cache is the primary source of truth.
  - REST positions are included under diagnostics.raw_rest_positions only.
  - When REST returns 0 and cache has 2, the endpoint returns 2.
  - Discrepancy metadata (reconciled_count, rest_count, in_sync) is present.
  - When both sources agree, in_sync == True.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_cached_position(market_id: str, contracts: int = 5, side: str = "yes",
                          avg_price_cents: int = 40) -> MagicMock:
    """Build a MagicMock that looks like a CachedPosition."""
    pos = MagicMock()
    pos.market_id = market_id
    pos.contracts = contracts
    pos.side = side
    pos.avg_price_cents = avg_price_cents
    pos.unrealized_pnl_usd = Decimal("0.10")
    pos.realized_pnl_usd = Decimal("0.00")
    return pos


def _make_app() -> FastAPI:
    app = FastAPI()
    from web.api.kalshi_api import router
    app.include_router(router)
    return app


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(_make_app())


# ── Tests ─────────────────────────────────────────────────────────────────

class TestPositionsEndpointUsesReconciliationCache:
    """Primary source-of-truth behaviour."""

    def test_cache_positions_returned_when_rest_empty(self, client: TestClient) -> None:
        """REST returns 0 positions; reconciled cache has 2 → endpoint returns 2."""
        pos1 = _make_cached_position("KXBTC-15M-T95000", contracts=3)
        pos2 = _make_cached_position("KXETH-1H-T3500", contracts=7)

        mock_cache = MagicMock()
        mock_cache.get_all_positions.return_value = {
            "KXBTC-15M-T95000": pos1,
            "KXETH-1H-T3500": pos2,
        }

        with (
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=None),
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                return_value=mock_cache,
            ),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        tickers = {p["ticker"] for p in data["positions"]}
        assert "KXBTC-15M-T95000" in tickers
        assert "KXETH-1H-T3500" in tickers

    def test_reconciled_positions_marked_with_source(self, client: TestClient) -> None:
        """Positions from cache carry source='reconciled'."""
        pos = _make_cached_position("KXBTC-15M-T95000")
        mock_cache = MagicMock()
        mock_cache.get_all_positions.return_value = {"KXBTC-15M-T95000": pos}

        with (
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=None),
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                return_value=mock_cache,
            ),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        data = resp.json()
        assert data["positions"][0]["source"] == "reconciled"

    def test_diagnostics_rest_positions_present(self, client: TestClient) -> None:
        """REST positions appear under diagnostics.raw_rest_positions."""
        mock_cache = MagicMock()
        mock_cache.get_all_positions.return_value = {}

        rest_pos = {
            "ticker": "KXBTC-15M-T95000",
            "side": "yes",
            "total_traded": 2,
            "average_price": 4500,
            "market_exposure": 0,
            "realized_pnl": 0,
        }
        mock_rest = MagicMock()
        mock_rest.get_positions.return_value = [rest_pos]

        with (
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=mock_rest),
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                return_value=mock_cache,
            ),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        data = resp.json()
        assert "diagnostics" in data
        assert data["diagnostics"]["rest_count"] == 1
        assert len(data["diagnostics"]["raw_rest_positions"]) == 1


class TestPositionsDiscrepancy:
    """Discrepancy detection between reconciled cache and REST."""

    def test_in_sync_true_when_counts_match(self, client: TestClient) -> None:
        pos = _make_cached_position("KXBTC-15M-T95000")
        mock_cache = MagicMock()
        mock_cache.get_all_positions.return_value = {"KXBTC-15M-T95000": pos}

        rest_pos = {"ticker": "KXBTC-15M-T95000", "side": "yes", "total_traded": 3,
                    "average_price": 4000}
        mock_rest = MagicMock()
        mock_rest.get_positions.return_value = [rest_pos]

        with (
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=mock_rest),
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                return_value=mock_cache,
            ),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        data = resp.json()
        assert data["diagnostics"]["in_sync"] is True

    def test_in_sync_false_when_counts_differ(self, client: TestClient) -> None:
        pos1 = _make_cached_position("KXBTC-15M-T95000")
        pos2 = _make_cached_position("KXETH-1H-T3500")
        mock_cache = MagicMock()
        mock_cache.get_all_positions.return_value = {
            "KXBTC-15M-T95000": pos1, "KXETH-1H-T3500": pos2
        }

        mock_rest = MagicMock()
        mock_rest.get_positions.return_value = []  # REST sees nothing

        with (
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=mock_rest),
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                return_value=mock_cache,
            ),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        data = resp.json()
        assert data["diagnostics"]["in_sync"] is False
        assert data["diagnostics"]["reconciled_count"] == 2
        assert data["diagnostics"]["rest_count"] == 0

    def test_cache_error_still_returns_200(self, client: TestClient) -> None:
        """Even when the cache import fails, the endpoint returns 200 with REST data."""
        with (
            patch(
                "merid.event_venues.kalshi.position_cache.get_position_cache",
                side_effect=RuntimeError("cache unavailable"),
            ),
            patch("web.api.kalshi_api._get_executor", return_value=None),
            patch("web.api.kalshi_api._get_rest_client", return_value=None),
        ):
            resp = client.get("/api/v1/kalshi/positions")

        assert resp.status_code == 200
        data = resp.json()
        assert "cache_error" in data
