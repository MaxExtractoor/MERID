"""Canonical order-intent contract tests.

Tests the user-required invariants:
- Long YES: buy 61, sell 49 -> realized PnL = -12 cents per contract.
- Long YES: buy 61, sell 70 -> realized PnL = +9 cents per contract.
- Short YES (sell-to-open) is rejected unless allow_short=True.
- Buy NO at 70 and sell NO at 80 -> +10 cents, no accidental YES conversion.
- Duplicate fill replay is idempotent (covered in test_fills_ledger_v2_fractional_replay).
- Exit event after position closed is rejected.
- Every emitted order satisfies exchange_position_after == internal_position_after.
"""

import os
import types
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.order_intent_contract import (
    CanonicalOrderIntent,
    OrderIntentValidationError,
    compute_expected_realized_pnl_cents,
    max_adverse_pnl_cents,
    normalize_order,
    persist_order_decision,
    validate_canonical_intent,
)


def _make_intent(**kwargs) -> types.SimpleNamespace:
    """Build a duck-typed order intent with sensible defaults."""
    defaults = {
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "price_cents": 55,
        "count": 1,
        "source": "agent_grid_15m",
        "entry_or_exit": None,
        "reduce_only": False,
        "is_exit_order": False,
        "kalshi_side": None,
        "pre_position_size": None,
        "expected_post_position_size": None,
        "allow_short": None,
        "rationale": None,
        "exit_reason": None,
        "estimated_fee_cents": 0,
        "expected_realized_pnl_cents": None,
        "intent_id": "test-intent",
        "client_order_id": "test-coid",
        "time_to_expiry_seconds": 900.0,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


class TestNormalizeOrder:
    def test_buy_yes_open(self):
        intent = _make_intent(side="yes", action="buy", count=1)
        c = normalize_order(intent, exchange_position_cc=0)
        assert c.contract == "yes"
        assert c.action == "buy"
        assert c.purpose == "open"
        assert c.qty_cc == 100
        assert c.expected_position_before == 0
        assert c.expected_position_after == 100
        assert c.strategy_signal == "up"

    def test_buy_no_open(self):
        intent = _make_intent(side="no", action="buy", count=1)
        c = normalize_order(intent, exchange_position_cc=0)
        assert c.contract == "no"
        assert c.action == "buy"
        assert c.purpose == "open"
        assert c.qty_cc == 100
        assert c.expected_position_before == 0
        assert c.expected_position_after == -100
        assert c.strategy_signal == "down"

    def test_sell_no_open(self):
        intent = _make_intent(side="no", action="sell", count=1)
        c = normalize_order(intent, exchange_position_cc=0)
        assert c.contract == "no"
        assert c.action == "sell"
        assert c.purpose == "open"
        assert c.expected_position_after == 100
        assert c.strategy_signal == "up"

    def test_kalshi_side_parsing(self):
        intent = _make_intent(side="BUY_NO", action="", kalshi_side="BUY_NO")
        c = normalize_order(intent, exchange_position_cc=0)
        assert c.contract == "no"
        assert c.action == "buy"

    def test_price_validation(self):
        with pytest.raises(OrderIntentValidationError, match="invalid_price:price_cents=0"):
            normalize_order(_make_intent(price_cents=0), exchange_position_cc=0)

    def test_price_validation_non_integer(self):
        with pytest.raises(OrderIntentValidationError, match="invalid_price:price_not_integer"):
            normalize_order(_make_intent(price_cents=55.5), exchange_position_cc=0)

    def test_non_positive_size(self):
        with pytest.raises(OrderIntentValidationError, match="non_positive_size"):
            normalize_order(_make_intent(count=0), exchange_position_cc=0)


class TestValidateOrder:
    def test_long_yes_close_pnl(self):
        # Long YES at 61c, sell at 49c -> -12 cents for 1 contract.
        intent = _make_intent(
            side="yes",
            action="sell",
            price_cents=49,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=100, position_side="yes", position_avg_price_cents=61)
        assert c.purpose == "close"
        assert c.expected_position_before == 100
        assert c.expected_position_after == 0
        assert c.expected_realized_pnl_cents == -12
        validate_canonical_intent(c, exchange_position_cc=100, position_avg_price_cents=61)

    def test_long_yes_close_profitable(self):
        # Long YES at 61c, sell at 70c -> +9 cents.
        intent = _make_intent(
            side="yes",
            action="sell",
            price_cents=70,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=100, position_side="yes", position_avg_price_cents=61)
        assert c.expected_realized_pnl_cents == 9
        validate_canonical_intent(c, exchange_position_cc=100)

    def test_long_no_close_pnl(self):
        # Long NO at 70c, sell NO at 80c -> +10 cents.
        # Position is short YES / long NO, so position_before = -100, side = "no".
        intent = _make_intent(
            side="no",
            action="sell",
            price_cents=80,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=-100, position_side="no", position_avg_price_cents=70)
        assert c.purpose == "close"
        assert c.expected_position_before == -100
        assert c.expected_position_after == 0
        assert c.expected_realized_pnl_cents == 10
        validate_canonical_intent(c, exchange_position_cc=-100)

    def test_long_no_close_via_buy_yes(self):
        # Long NO at 70c, buy YES at 20c (NO equivalent 80c) -> +10 cents.
        intent = _make_intent(
            side="yes",
            action="buy",
            price_cents=20,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=-100, position_side="no", position_avg_price_cents=70)
        assert c.purpose == "close"
        assert c.expected_position_after == 0
        assert c.expected_realized_pnl_cents == 10
        validate_canonical_intent(c, exchange_position_cc=-100)

    def test_sell_yes_from_flat_blocked(self):
        intent = _make_intent(side="yes", action="sell", count=1, allow_short=False)
        c = normalize_order(intent, exchange_position_cc=0)
        assert c.expected_position_after == -100
        with pytest.raises(OrderIntentValidationError, match="sell_to_short_prohibited"):
            validate_canonical_intent(c, exchange_position_cc=0)

    def test_sell_yes_from_flat_allowed_with_allow_short(self):
        intent = _make_intent(side="yes", action="sell", count=1, allow_short=True)
        c = normalize_order(intent, exchange_position_cc=0)
        validate_canonical_intent(c, exchange_position_cc=0)

    def test_missing_time_to_expiry_rejected(self):
        intent = _make_intent(side="yes", action="buy", count=1, time_to_expiry_seconds=None)
        c = normalize_order(intent, exchange_position_cc=0)
        with pytest.raises(OrderIntentValidationError, match="missing_time_to_expiry"):
            validate_canonical_intent(c, exchange_position_cc=0)

    def test_over_close_flip_blocked(self):
        # Long YES 1 contract, sell 2 -> would flip to long NO.
        intent = _make_intent(
            side="yes",
            action="sell",
            count=2,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=100)
        assert c.expected_position_after == -100
        with pytest.raises(OrderIntentValidationError, match="over_close|position_flip_prohibited"):
            validate_canonical_intent(c, exchange_position_cc=100)

    def test_close_with_zero_position_blocked(self):
        intent = _make_intent(
            side="yes",
            action="sell",
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=0)
        with pytest.raises(OrderIntentValidationError, match="close_with_zero_position"):
            validate_canonical_intent(c, exchange_position_cc=0)

    def test_position_before_mismatch(self):
        intent = _make_intent(side="yes", action="sell", count=1, entry_or_exit="exit")
        c = normalize_order(intent, exchange_position_cc=100)
        with pytest.raises(OrderIntentValidationError, match="position_before_mismatch"):
            validate_canonical_intent(c, exchange_position_cc=200)

    def test_exchange_position_after_matches_internal(self):
        """Position math is consistent, but a second entry into a live position is rejected."""
        intent = _make_intent(side="yes", action="buy", count=1)
        c = normalize_order(intent, exchange_position_cc=100)
        assert c.expected_position_after == 200
        with pytest.raises(OrderIntentValidationError, match="entry_with_open_position"):
            validate_canonical_intent(c, exchange_position_cc=100)

    def test_add_to_long_no(self):
        # Long NO 1 contract, buy NO 1 -> short YES / long NO grows to 2 contracts.
        # Canonical math still works, but the one-open-unit-per-ticker guard rejects the add.
        intent = _make_intent(side="no", action="buy", count=1)
        c = normalize_order(intent, exchange_position_cc=-100)
        assert c.purpose == "open"
        assert c.expected_position_after == -200
        with pytest.raises(OrderIntentValidationError, match="entry_with_open_position"):
            validate_canonical_intent(c, exchange_position_cc=-100)

    def test_add_to_long_no_with_sell_yes(self):
        # SELL_YES is economically BUY_NO; canonical math adds to long NO.
        # The one-open-unit-per-ticker guard rejects the entry while a live position exists.
        intent = _make_intent(side="yes", action="sell", count=1)
        c = normalize_order(intent, exchange_position_cc=-100)
        assert c.purpose == "open"
        assert c.expected_position_after == -200
        with pytest.raises(OrderIntentValidationError, match="entry_with_open_position"):
            validate_canonical_intent(c, exchange_position_cc=-100)


class TestPnLGuard:
    def test_adverse_pnl_rejected(self):
        intent = _make_intent(
            side="yes",
            action="sell",
            price_cents=40,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=100, position_side="yes", position_avg_price_cents=61)
        assert c.expected_realized_pnl_cents == -21
        with pytest.raises(OrderIntentValidationError, match="adverse_pnl"):
            validate_canonical_intent(c, exchange_position_cc=100, max_adverse_pnl_cents=10)

    def test_adverse_pnl_allowed_within_budget(self):
        intent = _make_intent(
            side="yes",
            action="sell",
            price_cents=55,
            count=1,
            entry_or_exit="exit",
        )
        c = normalize_order(intent, exchange_position_cc=100, position_side="yes", position_avg_price_cents=61)
        assert c.expected_realized_pnl_cents == -6
        validate_canonical_intent(c, exchange_position_cc=100, max_adverse_pnl_cents=10)


class TestHelpers:
    def test_max_adverse_pnl_cents_env(self, monkeypatch):
        monkeypatch.setenv("MERID_MAX_ADVERSE_PNL_CENTS", "42")
        assert max_adverse_pnl_cents() == 42

    def test_persist_order_decision(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setenv("MERID_LOG_DIR", str(log_dir))
        # Patch the file output path inside the function via a simple write test.
        record = {"ticker": "TEST", "allowed": True}
        persist_order_decision(record)
        assert (Path(__file__).resolve().parents[1] / "logs" / "order_decisions.jsonl").exists()

    def test_compute_expected_realized_pnl_no_position(self):
        assert compute_expected_realized_pnl_cents(
            purpose="open", qty_cc=100, limit_cents=50, contract="yes",
            position_before=0, position_avg_price_cents=50, position_side="yes", fee_cents=0,
        ) is None


class TestFetchFreshSignedYesExposure:
    @pytest.mark.asyncio
    async def test_outcome_id_no_yields_negative_signed_yes(self):
        """A long NO position must produce negative signed-YES exposure."""
        from merid.event_venues.kalshi.order_intent_contract import fetch_fresh_signed_yes_exposure

        with patch("merid.event_venues.kalshi.client.get_kalshi_client") as mock_client_get:
            client = MagicMock()
            client.get_positions_result = AsyncMock(return_value=types.SimpleNamespace(success=True, data=[
                MagicMock(
                    market_id="KXBTC15M-TEST",
                    outcome_id="no",
                    size=Decimal("5"),
                    average_entry_price=Decimal("0.45"),
                )
            ]))
            mock_client_get.return_value = client

            signed, avg, side = await fetch_fresh_signed_yes_exposure("KXBTC15M-TEST")

        assert signed == -500, f"Expected -500 for long NO, got {signed}"
        assert side == "no"
        assert avg == 45

    @pytest.mark.asyncio
    async def test_outcome_id_yes_yields_positive_signed_yes(self):
        """A long YES position must produce positive signed-YES exposure."""
        from merid.event_venues.kalshi.order_intent_contract import fetch_fresh_signed_yes_exposure

        with patch("merid.event_venues.kalshi.client.get_kalshi_client") as mock_client_get:
            client = MagicMock()
            client.get_positions_result = AsyncMock(return_value=types.SimpleNamespace(success=True, data=[
                MagicMock(
                    market_id="KXBTC15M-TEST",
                    outcome_id="yes",
                    size=Decimal("5"),
                    average_entry_price=Decimal("0.55"),
                )
            ]))
            mock_client_get.return_value = client

            signed, avg, side = await fetch_fresh_signed_yes_exposure("KXBTC15M-TEST")

        assert signed == 500, f"Expected 500 for long YES, got {signed}"
        assert side == "yes"
        assert avg == 55

    @pytest.mark.asyncio
    async def test_signed_no_size_is_normalized(self):
        """A negative size with outcome_id=no still means long NO, not long YES."""
        from merid.event_venues.kalshi.order_intent_contract import fetch_fresh_signed_yes_exposure

        with patch("merid.event_venues.kalshi.client.get_kalshi_client") as mock_client_get:
            client = MagicMock()
            client.get_positions_result = AsyncMock(return_value=types.SimpleNamespace(success=True, data=[
                MagicMock(
                    market_id="KXBTC15M-TEST",
                    outcome_id="no",
                    size=Decimal("-5"),
                    average_entry_price=Decimal("0.45"),
                )
            ]))
            mock_client_get.return_value = client

            signed, avg, side = await fetch_fresh_signed_yes_exposure("KXBTC15M-TEST")

        assert signed == -500, f"Expected -500 for long NO (negative size), got {signed}"
        assert side == "no"

    @pytest.mark.asyncio
    async def test_missing_outcome_id_fails_closed(self):
        """A position with no outcome_id must not default to YES."""
        from merid.event_venues.kalshi.order_intent_contract import fetch_fresh_signed_yes_exposure

        with patch("merid.event_venues.kalshi.client.get_kalshi_client") as mock_client_get:
            client = MagicMock()
            client.get_positions_result = AsyncMock(return_value=types.SimpleNamespace(success=True, data=[
                MagicMock(
                    market_id="KXBTC15M-TEST",
                    outcome_id=None,
                    size=Decimal("5"),
                    average_entry_price=Decimal("0.55"),
                )
            ]))
            mock_client_get.return_value = client

            signed, avg, side = await fetch_fresh_signed_yes_exposure("KXBTC15M-TEST")

        assert signed is None
        assert side is None


class TestEntryIdempotencyTerminalRelease:
    """2026-10-05: venue-terminal expiry of an unfilled resting entry must
    release the canonical dedupe record (previously it stayed "submitted" for
    the 900s TTL -> one-shot-per-window), and the bounded re-quote budget
    caps re-entries at MERID_ENTRY_MAX_REQUOTES_PER_KEY per key."""

    def _canonical(self, coid: str, intent_id: str):
        from merid.event_venues.kalshi.order_intent_contract import normalize_order

        intent = _make_intent(
            side="yes", action="buy", count=1,
            client_order_id=coid, intent_id=intent_id,
        )
        return normalize_order(intent, exchange_position_cc=0)

    @pytest.fixture(autouse=True)
    def _dedup_on(self, monkeypatch):
        # conftest's _legacy_entry_guard_bypass forces the idempotency gate
        # OFF for legacy tests; this class exercises the gate itself.
        monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "1")
        yield

    def setup_method(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            clear_entry_idempotency_registry,
        )

        clear_entry_idempotency_registry()
        os.environ.pop("MERID_ENTRY_MAX_REQUOTES_PER_KEY", None)

    def teardown_method(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            clear_entry_idempotency_registry,
        )

        clear_entry_idempotency_registry()
        os.environ.pop("MERID_ENTRY_MAX_REQUOTES_PER_KEY", None)

    def test_submitted_record_blocks_fresh_intent(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            _enforce_entry_idempotency,
            mark_entry_idempotency_submitted,
        )

        c1 = self._canonical("coid-1", "intent-1")
        _enforce_entry_idempotency(c1)
        mark_entry_idempotency_submitted("KXBTC15M-TEST", "yes", "coid-1", "ord-1")

        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _enforce_entry_idempotency(self._canonical("coid-2", "intent-2"))

    def test_terminal_release_frees_slot_once(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            _enforce_entry_idempotency,
            mark_entry_idempotency_submitted,
            release_entry_idempotency,
        )

        c1 = self._canonical("coid-1", "intent-1")
        _enforce_entry_idempotency(c1)
        mark_entry_idempotency_submitted("KXBTC15M-TEST", "yes", "coid-1", "ord-1")

        # Venue-authoritative terminal (expired/canceled, no fills) releases.
        assert release_entry_idempotency("KXBTC15M-TEST", "yes") is True

        # One bounded re-quote is admitted (full gates re-run upstream).
        _enforce_entry_idempotency(self._canonical("coid-2", "intent-2"))

    def test_requote_budget_exhausted_after_max(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            _enforce_entry_idempotency,
            mark_entry_idempotency_submitted,
            release_entry_idempotency,
        )

        # Original entry + one re-quote admitted; second release exhausts.
        c1 = self._canonical("coid-1", "intent-1")
        _enforce_entry_idempotency(c1)
        mark_entry_idempotency_submitted("KXBTC15M-TEST", "yes", "coid-1", "ord-1")
        release_entry_idempotency("KXBTC15M-TEST", "yes")

        c2 = self._canonical("coid-2", "intent-2")
        _enforce_entry_idempotency(c2)
        mark_entry_idempotency_submitted("KXBTC15M-TEST", "yes", "coid-2", "ord-2")
        release_entry_idempotency("KXBTC15M-TEST", "yes")

        with pytest.raises(OrderIntentValidationError, match="requote_budget_exhausted"):
            _enforce_entry_idempotency(self._canonical("coid-3", "intent-3"))

    def test_executed_record_never_releases(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            _enforce_entry_idempotency,
            mark_entry_idempotency_executed,
            mark_entry_idempotency_submitted,
            release_entry_idempotency,
        )

        c1 = self._canonical("coid-1", "intent-1")
        _enforce_entry_idempotency(c1)
        mark_entry_idempotency_submitted("KXBTC15M-TEST", "yes", "coid-1", "ord-1")
        mark_entry_idempotency_executed("KXBTC15M-TEST", "yes")

        # A filled order keeps protecting the window even if a release is
        # requested by a stale venue-terminal event.
        assert release_entry_idempotency("KXBTC15M-TEST", "yes") is False
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _enforce_entry_idempotency(self._canonical("coid-2", "intent-2"))

    def test_unsubmitted_release_does_not_consume_budget(self):
        from merid.event_venues.kalshi.order_intent_contract import (
            _enforce_entry_idempotency,
            release_entry_idempotency,
        )

        c1 = self._canonical("coid-1", "intent-1")
        _enforce_entry_idempotency(c1)
        # Pre-submit release (router rejection) frees the slot but does not
        # consume the re-quote budget - no venue slot was ever used.
        assert release_entry_idempotency("KXBTC15M-TEST", "yes") is True

        # Three sequential pre-submit rejects remain admissible.
        for n in (2, 3, 4):
            _enforce_entry_idempotency(self._canonical(f"coid-{n}", f"intent-{n}"))
            release_entry_idempotency("KXBTC15M-TEST", "yes")
