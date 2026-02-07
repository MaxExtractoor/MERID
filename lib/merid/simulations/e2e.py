from __future__ import annotations

import random
from typing import Dict, List, Optional

from db.audit_store import list_audit
from db.order_store import clear_store
from trading.execution import place_order


class E2ESimulation:
    """Simple E2E trading simulation harness.

    This simulates two data sources emitting prices and places an order when
    the spread exceeds a threshold. It uses the real `place_order` logic so
    validations and audit hooks get exercised.
    """

    def __init__(self, steps: int = 20, threshold: float = 50.0, actor: Optional[str] = "sim") -> None:
        self.steps = steps
        self.threshold = threshold
        self.actor = actor
        self.orders: List[Dict] = []

    def _generate_prices(self):
        # deterministic-seeded generator for reproducibility
        seed = 42
        rnd = random.Random(seed)
        base = 50_000
        for i in range(self.steps):
            a = base + rnd.gauss(0, 10) + i * 2
            b = base + rnd.gauss(0, 10) - i * 2
            yield a, b

    def run(self) -> Dict[str, object]:
        clear_store()
        # run the generator and place orders when opportunity found
        for a, b in self._generate_prices():
            spread = abs(a - b)
            if spread >= self.threshold:
                # place an order on the cheaper side
                side = "buy" if a > b else "sell"
                price = min(a, b)
                order = {"symbol": "BTCUSD", "side": side, "quantity": 1, "price": price}
                try:
                    # Provide a test account so pre-trade checks can run in integration tests
                    r = place_order(order, idempotency_key=None, actor=self.actor, account={"balance": 100_000, "max_notional_pct": 0.5})
                    self.orders.append(r)
                except Exception:
                    # swallow to continue sim; audits will record failures
                    continue

        audits = list_audit()
        return {"orders": self.orders, "audit_count": len(audits), "audits": audits}
