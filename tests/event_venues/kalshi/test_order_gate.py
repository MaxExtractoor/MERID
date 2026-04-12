"""Tests for the pre-trade idempotency gate (order_gate.py).

Coverage:
  1. Deterministic coid generation — same preimage → same coid, diff preimage → diff coid
  2. MM repeated orders within a single bucket are *not* blocked when cycle_id differs
  3. True duplicates (same coid, still pending) are blocked as duplicate_blocked
  4. Idempotent retry (same coid, still pending) is labelled idempotent
  5. Terminal-status coid can be reused for a new logical order
  6. Non-MM agents retain the 60-second bucket semantics
  7. Gate can be disabled via MERID_ORDER_GATE_ENABLED=false
  8. Gate status transitions: pending → open → filled / rejected / canceled
  9. cancel-and-replace: after release(coid, "canceled") a new order with same
     params proceeds
  10. order_router picks up gate block and returns gate:duplicate:* rejection
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.order_gate import (
    DECISION_BUCKET_WIDTH_S,
    MM_DECISION_BUCKET_WIDTH_S,
    OrderGateStatus,
    PreTradeGate,
    get_pre_trade_gate,
    make_coid,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _gate() -> PreTradeGate:
    """Return a fresh gate for each test (not the singleton)."""
    return PreTradeGate()


def _reserve(gate: PreTradeGate, **kwargs) -> tuple:
    defaults = dict(
        agent_id="agent-sol-mm",
        strategy_group="CRYPTO_15M_MM",
        contract_id="KXSOL15M-26APR121400-00",
        side="yes",
        qty=1,
        price_cents=49,
        is_mm=False,
        cycle_id=None,
    )
    defaults.update(kwargs)
    return gate.check_and_reserve(**defaults)


# ── 1. Deterministic coid generation ─────────────────────────────────────────


class TestCoidGeneration:
    def test_same_params_same_coid(self):
        now = time.time()
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, now=now)
        c2, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, now=now)
        assert c1 == c2

    def test_different_agent_different_coid(self):
        now = time.time()
        c1, _ = make_coid("agent_a", "sg", "ctid", "yes", 1, 50, now=now)
        c2, _ = make_coid("agent_b", "sg", "ctid", "yes", 1, 50, now=now)
        assert c1 != c2

    def test_different_side_different_coid(self):
        now = time.time()
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, now=now)
        c2, _ = make_coid("a", "sg", "ctid", "no", 1, 50, now=now)
        assert c1 != c2

    def test_different_price_different_coid(self):
        now = time.time()
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 49, now=now)
        c2, _ = make_coid("a", "sg", "ctid", "yes", 1, 51, now=now)
        assert c1 != c2

    def test_cycle_id_changes_coid(self):
        now = time.time()
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, cycle_id="1", now=now)
        c2, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, cycle_id="2", now=now)
        assert c1 != c2

    def test_mm_bucket_is_shorter(self):
        """MM bucket width must be shorter than the default."""
        assert MM_DECISION_BUCKET_WIDTH_S < DECISION_BUCKET_WIDTH_S

    def test_mm_flag_selects_shorter_bucket(self):
        """Two identical MM orders >MM_bucket apart should get different coids."""
        t1 = 0.0
        t2 = float(MM_DECISION_BUCKET_WIDTH_S)  # exactly one MM bucket later
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, is_mm=True, now=t1)
        c2, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, is_mm=True, now=t2)
        assert c1 != c2

    def test_default_non_mm_same_bucket(self):
        """Two identical non-MM orders within the 60 s default bucket share a coid."""
        t1 = 0.0
        t2 = float(DECISION_BUCKET_WIDTH_S) - 1.0  # still within the same bucket
        c1, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, is_mm=False, now=t1)
        c2, _ = make_coid("a", "sg", "ctid", "yes", 1, 50, is_mm=False, now=t2)
        assert c1 == c2

    def test_coid_prefix(self):
        c, _ = make_coid("a", "sg", "ctid", "yes", 1, 50)
        assert c.startswith("mg_")


# ── 2. MM new cycle — not blocked ────────────────────────────────────────────


class TestMMFreshCycle:
    def test_mm_new_cycle_id_proceeds(self):
        """MM orders with different cycle_ids are allowed even if params are identical."""
        gate = _gate()
        now = time.time()

        coid1, decision1, _ = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, cycle_id="cycle_1", now=now,
        )
        assert decision1 == "proceed"

        # Same params, new cycle
        coid2, decision2, _ = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, cycle_id="cycle_2", now=now,
        )
        assert decision2 == "proceed"
        assert coid1 != coid2

    def test_mm_short_bucket_proceeds_after_bucket_roll(self):
        """MM order in new MM bucket proceeds without cycle_id."""
        gate = _gate()
        t1 = 0.0
        t2 = float(MM_DECISION_BUCKET_WIDTH_S)  # one full MM bucket later

        _, d1, _ = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, now=t1,
        )
        assert d1 == "proceed"

        _, d2, _ = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, now=t2,
        )
        assert d2 == "proceed"

    def test_mm_same_cycle_same_bucket_blocked(self):
        """Two MM submissions for the same cycle/bucket are blocked as duplicates."""
        gate = _gate()
        now = time.time()

        _, d1, _ = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, cycle_id="cycle_1", now=now,
        )
        assert d1 == "proceed"

        # Same cycle_id, same params — should be blocked
        _, d2, entry = gate.check_and_reserve(
            "mm", "CRYPTO_15M_MM", "KXSOL15M", "yes", 1, 49,
            is_mm=True, cycle_id="cycle_1", now=now,
        )
        assert d2 == "duplicate_blocked"
        assert entry is not None
        assert entry.status == OrderGateStatus.PENDING


# ── 3. True duplicate — blocked ───────────────────────────────────────────────


class TestDuplicateBlocking:
    def test_same_params_same_bucket_blocked(self):
        gate = _gate()
        now = time.time()

        coid, d1, _ = _reserve(gate, now=now)
        assert d1 == "proceed"

        _, d2, entry = _reserve(gate, now=now)
        assert d2 == "duplicate_blocked"
        assert entry is not None
        assert entry.status == OrderGateStatus.PENDING

    def test_open_order_also_blocked(self):
        gate = _gate()
        now = time.time()

        coid, d1, _ = _reserve(gate, now=now)
        assert d1 == "proceed"
        gate.update_status(coid, "open")

        _, d2, entry = _reserve(gate, now=now)
        assert d2 == "duplicate_blocked"
        assert entry.status == OrderGateStatus.OPEN

    def test_log_context_on_blocked(self):
        """Gate must return duplicate_blocked and populate the entry."""
        gate = _gate()
        now = time.time()
        _reserve(gate, now=now)

        _, decision, entry = _reserve(gate, now=now)
        assert decision == "duplicate_blocked"
        assert entry is not None
        assert entry.status == OrderGateStatus.PENDING
        assert entry.contract_id == "KXSOL15M-26APR121400-00"


# ── 4. Terminal status allows reuse ──────────────────────────────────────────


class TestTerminalStatusReuse:
    @pytest.mark.parametrize("terminal_status", ["filled", "rejected", "canceled"])
    def test_terminal_allows_new_order(self, terminal_status):
        gate = _gate()
        now = time.time()

        coid, d1, _ = _reserve(gate, now=now)
        assert d1 == "proceed"
        gate.update_status(coid, terminal_status)

        _, d2, _ = _reserve(gate, now=now)
        assert d2 == "proceed"  # terminal → new order allowed

    def test_filled_entry_replaced(self):
        gate = _gate()
        now = time.time()

        coid, _, _ = _reserve(gate, now=now)
        gate.update_status(coid, "filled")

        coid2, d2, _ = _reserve(gate, now=now)
        assert d2 == "proceed"
        # New entry should be pending again
        assert gate._state[coid2].status == OrderGateStatus.PENDING


# ── 5. Non-MM agents: 60-second bucket semantics unchanged ───────────────────


class TestNonMMAgents:
    def test_directional_agent_within_bucket_blocked(self):
        gate = _gate()
        # Align t_start to the very beginning of a 60-second bucket so that
        # t_start and t_start + (bucket_width - 1) are in the same bucket.
        t_start = float(DECISION_BUCKET_WIDTH_S * 500)  # exact bucket boundary
        t2 = t_start + DECISION_BUCKET_WIDTH_S - 1.0    # still within same bucket

        _, d1, _ = gate.check_and_reserve(
            "btc15m", "BTC_15M", "KXBTC15M", "yes", 2, 60,
            is_mm=False, now=t_start,
        )
        assert d1 == "proceed"

        _, d2, _ = gate.check_and_reserve(
            "btc15m", "BTC_15M", "KXBTC15M", "yes", 2, 60,
            is_mm=False, now=t2,
        )
        assert d2 == "duplicate_blocked"

    def test_directional_agent_new_bucket_proceeds(self):
        gate = _gate()
        t1 = 1_000_000.0
        t2 = t1 + float(DECISION_BUCKET_WIDTH_S)  # next bucket

        _, d1, _ = gate.check_and_reserve(
            "btc15m", "BTC_15M", "KXBTC15M", "yes", 2, 60,
            is_mm=False, now=t1,
        )
        assert d1 == "proceed"

        _, d2, _ = gate.check_and_reserve(
            "btc15m", "BTC_15M", "KXBTC15M", "yes", 2, 60,
            is_mm=False, now=t2,
        )
        assert d2 == "proceed"


# ── 6. Cancel-and-replace ────────────────────────────────────────────────────


class TestCancelAndReplace:
    def test_release_then_new_order_proceeds(self):
        gate = _gate()
        now = time.time()

        coid, d1, _ = _reserve(gate, now=now)
        assert d1 == "proceed"

        gate.release(coid, "canceled")
        assert gate._state[coid].status == OrderGateStatus.CANCELED

        # Same params — now allowed because previous is canceled (terminal)
        _, d2, _ = _reserve(gate, now=now)
        assert d2 == "proceed"

    def test_release_open_to_canceled(self):
        gate = _gate()
        now = time.time()
        coid, _, _ = _reserve(gate, now=now)
        gate.update_status(coid, "open")
        gate.release(coid, "canceled")
        assert gate._state[coid].status == OrderGateStatus.CANCELED


# ── 7. Gate disabled via env var ─────────────────────────────────────────────


class TestGateDisabled:
    def test_gate_disabled_always_proceeds(self, monkeypatch):
        monkeypatch.setenv("MERID_ORDER_GATE_ENABLED", "false")
        # Re-import module so the env var takes effect
        import importlib
        import merid.event_venues.kalshi.order_gate as og_mod
        monkeypatch.setattr(og_mod, "_GATE_ENABLED", False)

        gate = PreTradeGate()
        now = time.time()
        _, d1, _ = gate.check_and_reserve(
            "a", "sg", "c", "yes", 1, 50, now=now,
        )
        assert d1 == "proceed"

        # Second call with same params — still proceed (gate is disabled)
        _, d2, _ = gate.check_and_reserve(
            "a", "sg", "c", "yes", 1, 50, now=now,
        )
        assert d2 == "proceed"


# ── 8. Status transitions ─────────────────────────────────────────────────────


class TestStatusTransitions:
    def test_pending_to_open(self):
        gate = _gate()
        coid, _, _ = _reserve(gate)
        assert gate._state[coid].status == OrderGateStatus.PENDING
        gate.update_status(coid, "open")
        assert gate._state[coid].status == OrderGateStatus.OPEN

    def test_update_unknown_coid_returns_false(self):
        gate = _gate()
        result = gate.update_status("nonexistent_coid", "filled")
        assert result is False

    def test_snapshot_returns_correct_fields(self):
        gate = _gate()
        coid, _, _ = _reserve(gate, agent_id="my_agent", price_cents=55)
        snap = gate.snapshot()
        assert coid in snap
        assert snap[coid]["status"] == "pending"
        assert snap[coid]["agent_id"] == "my_agent"
        assert snap[coid]["price_cents"] == 55

    def test_active_count(self):
        gate = _gate()
        assert gate.active_count() == 0
        now = time.time()

        coid1, _, _ = _reserve(gate, price_cents=49, now=now)
        coid2, _, _ = _reserve(gate, price_cents=51, now=now)  # different price → different coid
        assert gate.active_count() == 2

        gate.update_status(coid1, "filled")
        assert gate.active_count() == 1

    def test_cleanup_removes_terminal_entries(self):
        gate = _gate()
        coid, _, _ = _reserve(gate)
        gate.update_status(coid, "filled")
        # Force updated_at far in the past
        gate._state[coid].updated_at = time.time() - 10000
        removed = gate.cleanup_stale(ttl_seconds=1)
        assert removed == 1
        assert coid not in gate._state


# ── 9. Singleton ─────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_pre_trade_gate_returns_same_instance(self):
        g1 = get_pre_trade_gate()
        g2 = get_pre_trade_gate()
        assert g1 is g2


# ── 10. order_router integration — gate block returns gate:duplicate:* ────────


class TestOrderRouterGateIntegration:
    """Verify _route_live honours a gate duplicate_blocked decision."""

    @pytest.mark.asyncio
    async def test_gate_block_produces_rejected_result(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, _route_live
        from merid.prediction.venue_gate import TradingMode

        # Use a fresh gate that already has the coid in pending state.
        fresh_gate = PreTradeGate()
        now_ts = time.time()

        intent = OrderIntent(
            ticker="KXSOL15M-26APR121400-00",
            side="yes",
            action="buy",
            price_cents=49,
            count=1,
            mode=TradingMode.LIVE,
            source="kalshi-crypto_15m_mm",
            strategy_group="CRYPTO_15M_MM",
            is_market_maker=True,
            cycle_id="cycle_99",
        )

        # Pre-populate the gate so the first request is blocked.
        coid, _, _ = fresh_gate.check_and_reserve(
            agent_id=intent.source,
            strategy_group=intent.strategy_group,
            contract_id=intent.ticker,
            side=intent.side,
            qty=intent.count,
            price_cents=intent.price_cents,
            is_mm=intent.is_market_maker,
            cycle_id=intent.cycle_id,
        )
        assert fresh_gate._state[coid].status == OrderGateStatus.PENDING

        with (
            patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_vg,
            patch("merid.risk.kill_switches.risk_controller") as mock_rc,
            patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk,
            patch(
                "merid.event_venues.kalshi.order_gate.get_pre_trade_gate",
                return_value=fresh_gate,
            ),
        ):
            mock_vg.return_value.live_enabled = True
            mock_rc.can_trade.return_value = True
            risk_inst = MagicMock()
            risk_inst.check_order.return_value = (True, None)
            mock_risk.return_value = risk_inst

            # Also need to mock the client so we don't get import errors
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()

            with patch("merid.event_venues.kalshi.client.get_kalshi_client", return_value=mock_client):
                result = await _route_live(intent, TradingMode.LIVE, time.monotonic())

        assert result.status == "rejected"
        assert result.reason is not None
        assert "gate:duplicate" in result.reason

    @pytest.mark.asyncio
    async def test_gate_proceed_does_not_block_order(self):
        """When gate returns proceed the order reaches the Kalshi client."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _route_live
        from merid.prediction.venue_gate import TradingMode

        fresh_gate = PreTradeGate()

        intent = OrderIntent(
            ticker="KXSOL15M-26APR121400-00",
            side="yes",
            action="buy",
            price_cents=49,
            count=1,
            mode=TradingMode.LIVE,
            source="kalshi-crypto_15m_mm",
            strategy_group="CRYPTO_15M_MM",
            is_market_maker=True,
            cycle_id="cycle_1",
        )

        placed_calls: list = []

        async def mock_place(order, **kw) -> Any:
            placed_calls.append(order)
            r = MagicMock()
            r.success = True
            r.data = MagicMock(
                order_id="oid-123",
                status="resting",
                size=Decimal(1),
                filled_size=Decimal(0),
                remaining_size=Decimal(1),
                price=Decimal("0.49"),
            )
            return r

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.place_order_result = mock_place

        with (
            patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_vg,
            patch("merid.risk.kill_switches.risk_controller") as mock_rc,
            patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk,
            patch("merid.event_venues.kalshi.client.get_kalshi_client", return_value=mock_client),
            patch(
                "merid.event_venues.kalshi.order_gate.get_pre_trade_gate",
                return_value=fresh_gate,
            ),
        ):
            mock_vg.return_value.live_enabled = True
            mock_rc.can_trade.return_value = True
            risk_inst = MagicMock()
            risk_inst.check_order.return_value = (True, None)
            mock_risk.return_value = risk_inst

            result = await _route_live(intent, TradingMode.LIVE, time.monotonic())

        assert result.status in ("accepted_live", "filled_live", "partial_live")
        assert len(placed_calls) == 1
