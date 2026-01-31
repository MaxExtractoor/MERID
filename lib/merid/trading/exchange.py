"""Exchange adapter interface and simple implementations.

Provides a small adapter contract and two implementations used by MERID:
- LocalAdapter: test-friendly adapter that simulates immediate fills (default)
- TestnetAdapter: feature-flagged, harmless testnet simulator (no external keys)

Production adapters (Alpaca, IBKR, on-chain adapters) should implement
`ExchangeAdapter` and be wired via config/DI.
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional


class ExchangeAdapter(ABC):
    """Adapter contract for placing and cancelling orders."""

    @abstractmethod
    def send_order(self, order: Dict, idempotency_key: Optional[str] = None) -> Dict:
        """Send an order to the venue and return an execution dict.

        Expected keys in result (example):
            {"status": "filled", "filled_at": 123456.0, "fill_qty": 1}
        or pending states like {"status": "submitted"}
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict:
        """Request cancellation of an outstanding order."""


class LocalAdapter(ExchangeAdapter):
    """Simple local adapter used in dev/tests that immediately fills orders."""

    def send_order(self, order: Dict, idempotency_key: Optional[str] = None) -> Dict:
        # Deterministic immediate fill: mimic latency and return filled
        now = time.time()
        return {"status": "filled", "filled_at": now, "fill_qty": order.get("quantity")}

    def cancel_order(self, order_id: str) -> Dict:
        return {"status": "cancelled", "order_id": order_id}


class TestnetAdapter(ExchangeAdapter):
    """Feature-flagged testnet adapter (simulates a remote testnet without secrets).

    This adapter is intentionally lightweight and safe: it simulates network
    delays and returns 'submitted' for orders to emulate asynchronous handling.
    """

    # Prevent pytest from collecting this adapter as a test class
    __test__ = False

    def __init__(self, latency: float = 0.05):
        self.latency = latency

    def send_order(self, order: Dict, idempotency_key: Optional[str] = None) -> Dict:
        # Simulate network delay
        time.sleep(self.latency)
        now = time.time()
        return {"status": "submitted", "submitted_at": now}

    def cancel_order(self, order_id: str) -> Dict:
        time.sleep(self.latency)
        return {"status": "cancelled", "order_id": order_id}


def get_default_adapter() -> ExchangeAdapter:
    """Return adapter based on environment flags; default to `LocalAdapter`.

    Environment variables:
      - MERID_USE_TESTNET=true -> returns `TestnetAdapter`
    """
    use_testnet = os.getenv("MERID_USE_TESTNET", "false").lower() == "true"
    if use_testnet:
        return TestnetAdapter()
    return LocalAdapter()
