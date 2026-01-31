"""Adapter registry for unified trading router."""

from __future__ import annotations

from typing import Dict, Optional

from trading.adapters.base import TradingVenueAdapter


_adapters: Dict[str, TradingVenueAdapter] = {}


def register_adapter(adapter: TradingVenueAdapter) -> None:
    """Register/replace an adapter for its venue id."""
    _adapters[adapter.venue] = adapter


def get_adapter(venue_id: str) -> Optional[TradingVenueAdapter]:
    return _adapters.get(venue_id)


def list_adapters() -> Dict[str, TradingVenueAdapter]:
    return dict(_adapters)


def clear_adapters() -> None:  # pragma: no cover - convenience for tests
    _adapters.clear()
