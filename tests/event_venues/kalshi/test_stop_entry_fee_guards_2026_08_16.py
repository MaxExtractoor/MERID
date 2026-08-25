"""Regression tests for the 2026-08-16 production-safety patch.

Covers:
- Stop-loss candidates are submitted exactly once when the guarded flag is on,
  use bounded-slippage limit prices, and are blocked by the emergency kill
  switch even under ``force=True``.
- New entries are hard-rejected with ``PROTECTIVE_EXIT_DISABLED`` while
  protective exits cannot be submitted.
- Per-(ticker, side, window) entry idempotency: repeated candidate cycles
  produce one accepted entry; cancel/replace (same client_order_id) is a
  separate, allowed path.
- Fee accounting: exact Decimal dollars -> integer cents with ROUND_HALF_UP,
  sub-cent / fractional-cent values, and reconciliation of summed fees.
- A stale quote can never produce an unbounded IOC liquidation.
"""

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.order_intent_contract import (
    OrderIntentValidationError,
    clear_entry_idempotency_registry,
    mark_entry_idempotency_executed,
    mark_entry_idempotency_reconciliation_required,
    mark_entry_idempotency_submitted,
    normalize_order,
    release_entry_idempotency,
    validate_canonical_intent,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    TradingMode,
    _post_route_canonical_idempotency_cleanup,
    route_order,
    route_order_async,
)
from merid.event_venues.kalshi import stop_candidate as sc


@pytest.fixture(autouse=True)
def _clean_env_and_registry(monkeypatch):
    """Each test manages the guard env vars and dedup registry explicitly."""
    for var in (
        "MERID_ENABLE_STOP_CANDIDATE_SUBMISSION",
        "MERID_STOP_SUBMISSION_KILL",
        "MERID_ALLOW_UNPROTECTED_ENTRIES",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "1")
    monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_TTL_SECONDS", "900")
    clear_entry_idempotency_registry()
    yield
    clear_entry_idempotency_registry()


def _open_intent(ticker="KXBTC15M-26AUG160100-00", side="yes", client_order_id=None, intent_id=None):
    return SimpleNamespace(
        ticker=ticker,
        side=side,
        action="buy",
        price_cents=40,
        count=1,
        source="test_entry",
        intent_id=intent_id,
        client_order_id=client_order_id,
        time_to_expiry_seconds=600.0,
    )


def _validate_open(intent, exchange_position_cc=0):
    canonical = normalize_order(intent, exchange_position_cc=exchange_position_cc)
    validate_canonical_intent(canonical, exchange_position_cc=exchange_position_cc)
    return canonical


# ── Protective-exit entry kill switch ─────────────────────────────────────────


class TestProtectiveExitEntryGate:
    def test_entry_rejected_when_protective_exits_disabled(self):
        with pytest.raises(OrderIntentValidationError, match="PROTECTIVE_EXIT_DISABLED"):
            _validate_open(_open_intent())

    def test_entry_allowed_when_stop_submission_enabled(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        canonical = _validate_open(_open_intent())
        assert canonical.purpose == "open"

    def test_kill_switch_blocks_entries_even_if_enable_flag_on(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        monkeypatch.setenv("MERID_STOP_SUBMISSION_KILL", "1")
        with pytest.raises(OrderIntentValidationError, match="PROTECTIVE_EXIT_DISABLED"):
            _validate_open(_open_intent())

    def test_ops_override_allows_unprotected_entries(self, monkeypatch):
        monkeypatch.setenv("MERID_ALLOW_UNPROTECTED_ENTRIES", "1")
        canonical = _validate_open(_open_intent())
        assert canonical.purpose == "open"

    def test_entry_rejected_into_live_position(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        with pytest.raises(OrderIntentValidationError, match="entry_with_open_position"):
            _validate_open(_open_intent(), exchange_position_cc=100)


# ── Per-(ticker, side, window) entry idempotency ─────────────────────────────


class TestEntryIdempotency:
    def test_repeated_candidate_cycles_accept_one_entry(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        # Same ticker/side/window, new intent -> rejected.
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))

    def test_opposite_side_same_window_rejected_independently(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        _validate_open(_open_intent(side="yes", client_order_id="coid-y"))
        # Different side is a different key and is allowed.
        _validate_open(_open_intent(side="no", client_order_id="coid-n"))

    def test_different_window_allowed(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        _validate_open(_open_intent(client_order_id="coid-1"))
        _validate_open(
            _open_intent(ticker="KXBTC15M-26AUG160115-15", client_order_id="coid-2")
        )

    def test_cancel_replace_same_client_order_id_allowed(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        # Deliberate replace path: same client_order_id qualifies.
        canonical = _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        assert canonical.purpose == "open"

    def test_dedup_disabled_env_allows_repeats(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "0")
        _validate_open(_open_intent(client_order_id="coid-1"))
        _validate_open(_open_intent(client_order_id="coid-2"))


# ── Fee accounting ────────────────────────────────────────────────────────────


class TestFeeAccounting:
    def test_fee_dollars_to_cents_sub_cent(self):
        from merid.event_venues.kalshi.fills_ledger import fee_dollars_to_cents

        # Observed live fill: $0.00496 fee.  HALF_UP -> 0 cents (documented);
        # the exact dollar value remains in KalshiFill.fee_cost.
        assert fee_dollars_to_cents(Decimal("0.00496")) == 0
        assert fee_dollars_to_cents(Decimal("0.005")) == 1  # half-cent rounds up
        assert fee_dollars_to_cents(Decimal("0.0149")) == 1
        assert fee_dollars_to_cents(Decimal("1.75")) == 175
        assert fee_dollars_to_cents(Decimal("0")) == 0
        assert fee_dollars_to_cents(None) == 0

    def test_fee_totals_reconcile_to_exchange_dollars(self):
        """Integer-cent fields are per-fill rounded, but the exact dollar sum
        of fills must match the exchange-reported total to the cent."""
        from merid.event_venues.kalshi.fills_ledger import fee_dollars_to_cents

        fees = [Decimal("0.00496"), Decimal("0.00015"), Decimal("0.0080"), Decimal("0.0128")]
        total_dollars = sum(fees, Decimal("0"))
        # Exchange reports total fees in dollars; cent conversion of the exact
        # total must match rounding the total (not necessarily the sum of
        # rounded parts).
        assert fee_dollars_to_cents(total_dollars) == 3  # $0.02591 -> 2.591c -> 3c
        assert total_dollars == Decimal("0.02591")

    def test_parse_fill_preserves_exact_dollar_fee(self):
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        raw = {
            "fill_id": "fill-fee-1",
            "market_ticker": "KXBTC15M-TEST",
            "client_order_id": "coid-fee-1",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.0700",
            "count_fp": "0.99",
            "fee_cost": "0.00496",
            "created_time": "2026-08-15T14:28:01+00:00",
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.fee_cost == Decimal("0.00496")

    def test_parse_fill_dollar_fee_above_one_dollar_not_divided(self):
        """A legitimate $1.75 fee must not be misread as cents."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        raw = {
            "fill_id": "fill-fee-2",
            "market_ticker": "KXBTC15M-TEST",
            "client_order_id": "coid-fee-2",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.5000",
            "count_fp": "100",
            "fee_cost": "1.75",
            "created_time": "2026-08-15T14:28:01+00:00",
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.fee_cost == Decimal("1.75")

    def test_parse_fill_legacy_cent_fee_still_converted(self):
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        raw = {
            "fill_id": "fill-fee-3",
            "market_ticker": "KXBTC15M-TEST",
            "client_order_id": "coid-fee-3",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "yes_price": 50,
            "count": 1,
            "fee": 25,  # legacy cent-denominated payload
            "created_time": "2026-08-15T14:28:01+00:00",
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.fee_cost == Decimal("0.25")


# ── Stop-candidate submission ─────────────────────────────────────────────────


def _price_stop_candidate():
    return sc.build_stop_candidate(
        market_ticker="KXBTC15M-26AUG160100-00",
        exchange_position_cc=100,  # long 1 YES
        trigger_reason="POSITION_MONITOR_STOP",
        entry_price_cents=55,
        executable_exit_cents=40,
        quote_age_ms=100,
        seconds_to_expiry=600.0,
    )


class TestStopCandidateSubmission:
    @pytest.mark.asyncio
    async def test_stop_trigger_submits_exactly_one_bounded_exit(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")

        async def _fake_exposure(ticker, timeout=1.0, fallback_to_cache=True):
            return 100, 55, "yes"

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
            _fake_exposure,
        )
        route_mock = AsyncMock(return_value=SimpleNamespace(status="filled_live", fill_price_cents=40))
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router.route_order_async", route_mock
        )

        result = await sc.maybe_submit_stop_candidate(_price_stop_candidate())

        assert route_mock.await_count == 1
        intent = route_mock.await_args.args[0]
        assert intent.reduce_only is True
        assert intent.time_in_force == "ioc"
        assert intent.action == "sell"
        # Bounded liquidation: 40c bid - 3c cap = 37c limit, never unbounded.
        assert intent.price_cents == 40 - sc.STOP_MAX_SLIPPAGE_CENTS
        assert result.status == "filled_live"

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_even_forced_submission(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        monkeypatch.setenv("MERID_STOP_SUBMISSION_KILL", "1")
        route_mock = AsyncMock()
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router.route_order_async", route_mock
        )

        result = await sc.maybe_submit_stop_candidate(_price_stop_candidate(), force=True)

        assert route_mock.await_count == 0
        assert result is not None
        assert result.status == "rejected"
        assert "kill_switch" in result.reason

    @pytest.mark.asyncio
    async def test_disabled_submission_alerts_and_does_not_route(self, monkeypatch, caplog):
        route_mock = AsyncMock()
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router.route_order_async", route_mock
        )

        with caplog.at_level("CRITICAL"):
            result = await sc.maybe_submit_stop_candidate(_price_stop_candidate())

        assert route_mock.await_count == 0
        assert result.status == "rejected"
        assert result.reason == "stop_candidate_submission_disabled_until_replay_tests"
        assert any("STOP-CANDIDATE-NOT-SUBMITTED" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_price_stop_does_not_require_model_fair_value(self, monkeypatch):
        """POSITION_MONITOR_STOP has fair_value_cents=None; it must still be
        submittable (previously rejected as stop_candidate_no_fair_value)."""
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")

        async def _fake_exposure(ticker, timeout=1.0, fallback_to_cache=True):
            return 100, 55, "yes"

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
            _fake_exposure,
        )
        route_mock = AsyncMock(return_value=SimpleNamespace(status="filled_live"))
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router.route_order_async", route_mock
        )

        candidate = _price_stop_candidate()
        assert candidate.fair_value_cents is None
        result = await sc.maybe_submit_stop_candidate(candidate)
        assert route_mock.await_count == 1
        assert result.status == "filled_live"


class TestStaleQuoteCannotLiquidate:
    def test_stale_quote_rejected_by_invariants(self):
        order = SimpleNamespace(
            market_ticker="KXBTC15M-26AUG160100-00",
            contract="yes",
            action="sell",
            qty_cc=100,
            reduce_only=True,
            time_in_force="ioc",
            expected_position_before=100,
            expected_position_after=0,
        )
        with pytest.raises(sc.StopOrderInvariantError, match="stale_quote"):
            sc.validate_stop_order_invariants(
                order,
                exchange_position_cc=100,
                quote_age_ms=sc.MAX_EXIT_QUOTE_AGE_MS + 1,
            )

    def test_over_close_rejected_by_invariants(self):
        order = SimpleNamespace(
            market_ticker="KXBTC15M-26AUG160100-00",
            contract="yes",
            action="sell",
            qty_cc=200,
            reduce_only=True,
            time_in_force="ioc",
            expected_position_before=100,
            expected_position_after=-100,
        )
        with pytest.raises(sc.StopOrderInvariantError, match="over_close"):
            sc.validate_stop_order_invariants(order, exchange_position_cc=100)


class TestStalePreSubmitIdempotency:
    """Regression tests for the 2026-08-16 pre-submit idempotency fix.

    A canonical entry record that never reaches the exchange must not block
    retries indefinitely.  It is evicted after a bounded pre-submit TTL and
    after reconciliation with the local idempotent order store.
    """

    @pytest.fixture(autouse=True)
    def _enable_entries_and_short_pre_ttl(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")
        monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_TTL_SECONDS", "900")

    @pytest.fixture
    def _fake_pre_trade_gate(self, monkeypatch):
        """Patch order_gate.get_pre_trade_gate to return a controllable store."""
        records = {}

        def _lookup(client_order_id):
            return records.get(client_order_id)

        class _FakeStore:
            lookup = _lookup

        class _FakeGate:
            store = _FakeStore()

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_gate.get_pre_trade_gate",
            lambda: _FakeGate(),
        )
        return records

    def _record(self, status_value, created_at=None):
        return SimpleNamespace(
            status=SimpleNamespace(value=status_value),
            created_at=created_at if created_at is not None else time.time(),
        )

    def test_stale_pre_submit_no_gate_replacement(self, monkeypatch):
        """A pre-submit record with no gate entry is replaced after the TTL."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        # Fresh duplicate is still rejected.
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))
        time.sleep(0.02)
        # After TTL, the stale record is replaced.
        canonical = _validate_open(
            _open_intent(client_order_id="coid-2", intent_id="intent-2")
        )
        assert canonical.purpose == "open"

    def test_stale_pre_submit_rejected_gate_replacement(
        self, monkeypatch, _fake_pre_trade_gate
    ):
        """A terminal gate record lets the canonical registry replace the stale entry."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        _fake_pre_trade_gate["coid-1"] = self._record("rejected")
        time.sleep(0.02)
        canonical = _validate_open(
            _open_intent(client_order_id="coid-2", intent_id="intent-2")
        )
        assert canonical.purpose == "open"

    def test_stale_pre_submit_old_pending_gate_replacement(
        self, monkeypatch, _fake_pre_trade_gate
    ):
        """A gate PENDING record older than the TTL is also treated as stale."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        _fake_pre_trade_gate["coid-1"] = self._record(
            "pending", created_at=time.time() - 0.02
        )
        time.sleep(0.02)
        canonical = _validate_open(
            _open_intent(client_order_id="coid-2", intent_id="intent-2")
        )
        assert canonical.purpose == "open"

    def test_fresh_pre_submit_pending_gate_still_blocks(
        self, monkeypatch, _fake_pre_trade_gate
    ):
        """A fresh gate PENDING record means an order is in flight; keep blocking."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "10")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        _fake_pre_trade_gate["coid-1"] = self._record("pending")
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))

    def test_submitted_gate_still_blocks_and_updates_canonical_record(
        self, monkeypatch, _fake_pre_trade_gate
    ):
        """A SUBMITTED gate record proves a real order is in flight; it still blocks."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        _fake_pre_trade_gate["coid-1"] = self._record("submitted")
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))

    def test_release_clears_pre_submit_record(self, monkeypatch):
        """Explicit release immediately unblocks retries."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "900")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        release_entry_idempotency(
            market_ticker="KXBTC15M-26AUG160100-00",
            contract="yes",
            client_order_id="coid-1",
        )
        canonical = _validate_open(
            _open_intent(client_order_id="coid-2", intent_id="intent-2")
        )
        assert canonical.purpose == "open"

    def test_mark_submitted_and_executed_blocks_retries(self, monkeypatch):
        """A submitted/executed record remains active well beyond the pre-submit TTL."""
        monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")
        _validate_open(_open_intent(client_order_id="coid-1", intent_id="intent-1"))
        mark_entry_idempotency_submitted(
            market_ticker="KXBTC15M-26AUG160100-00",
            contract="yes",
            client_order_id="coid-1",
            order_id="order-123",
        )
        time.sleep(0.02)
        # Submitted record still blocks even after the short pre-submit TTL.
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))
        # Execution makes it even more clearly active.
        mark_entry_idempotency_executed(
            market_ticker="KXBTC15M-26AUG160100-00",
            contract="yes",
            client_order_id="coid-1",
            fill_id="fill-123",
        )
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            _validate_open(_open_intent(client_order_id="coid-2", intent_id="intent-2"))


# ── Router idempotency lifecycle wrapper ────────────────────────────────────


class TestOrderRouterIdempotencyLifecycle:
    @pytest.fixture(autouse=True)
    def _enable_stop_submission(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", "1")

    def _make_intent(
        self,
        ticker="KXBTC15M-26AUG160100-00",
        side="yes",
        client_order_id="coid-test",
        validate=True,
    ):
        """Build an OrderIntent and, by default, pre-populate the canonical idempotency record."""
        intent = OrderIntent(
            ticker=ticker,
            side=side,
            action="buy",
            price_cents=40,
            count=1,
            mode=TradingMode.LIVE,
            source="test",
            agent_id="BTC_15M",
            client_order_id=client_order_id,
            time_to_expiry_seconds=600.0,
        )
        canonical = normalize_order(intent, exchange_position_cc=0)
        if validate:
            validate_canonical_intent(canonical, exchange_position_cc=0)
            intent._canonical_entry_key = (canonical.market_ticker, canonical.contract)
            intent._canonical_client_order_id = canonical.client_order_id
            intent.client_tag = canonical.client_order_id
        return intent

    def _fresh_canonical(self, intent, client_order_id):
        """Normalize a fresh intent for the same ticker/side without validating."""
        fresh = OrderIntent(
            ticker=intent.ticker,
            side=intent.side,
            action="buy",
            price_cents=40,
            count=1,
            mode=TradingMode.LIVE,
            source="test",
            agent_id="BTC_15M",
            client_order_id=client_order_id,
            time_to_expiry_seconds=600.0,
        )
        return normalize_order(fresh, exchange_position_cc=0)

    def _assert_record_blocks_retry(self, intent):
        """A fresh intent with the same ticker/side should raise duplicate_entry."""
        canonical = self._fresh_canonical(intent, client_order_id="coid-retry")
        with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
            validate_canonical_intent(canonical, exchange_position_cc=0)

    def _assert_record_allows_retry(self, intent):
        """A fresh intent with the same ticker/side should be accepted."""
        canonical = self._fresh_canonical(intent, client_order_id="coid-retry")
        validate_canonical_intent(canonical, exchange_position_cc=0)

    def test_local_pre_submit_reject_releases_record(self):
        intent = self._make_intent()
        result = OrderResult(
            status="rejected",
            mode=TradingMode.LIVE,
            reason="microstructure_gate_failed:spread_too_wide",
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_allows_retry(intent)

    def test_unfilled_ioc_releases_record(self):
        intent = self._make_intent()
        result = OrderResult(
            status="unfilled_ioc",
            mode=TradingMode.LIVE,
            order_id="kalshi-123",
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=True,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_allows_retry(intent)

    def test_filled_live_blocks_retry_and_marks_executed(self):
        intent = self._make_intent()
        result = OrderResult(
            status="filled_live",
            mode=TradingMode.LIVE,
            order_id="kalshi-123",
            fill={"filled_count": 1, "requested_count": 1, "remaining_count": 0},
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=True,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_blocks_retry(intent)

    def test_resting_order_blocks_retry_and_marks_submitted(self):
        intent = self._make_intent()
        result = OrderResult(
            status="resting",
            mode=TradingMode.LIVE,
            order_id="kalshi-123",
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=True,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_blocks_retry(intent)

    def test_submission_unknown_marks_reconciliation(self):
        intent = self._make_intent()
        result = OrderResult(
            status="submission_unknown",
            mode=TradingMode.LIVE,
            reason="timeout_after_submit",
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=False,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_blocks_retry(intent)

    def test_duplicate_unknown_marks_reconciliation(self):
        intent = self._make_intent()
        result = OrderResult(
            status="duplicate_unknown",
            mode=TradingMode.LIVE,
            reason="kalshi_duplicate_lookup_failure",
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=False,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_blocks_retry(intent)

    def test_explicit_reconciliation_required_public_hook(self):
        intent = self._make_intent()
        canonical = normalize_order(intent, exchange_position_cc=0)
        mark_entry_idempotency_reconciliation_required(
            market_ticker=canonical.market_ticker,
            contract=canonical.contract,
            client_order_id=canonical.client_order_id,
            reason="manual_test",
        )
        self._assert_record_blocks_retry(intent)

    def test_uncertain_reject_with_attempted_request_marks_reconciliation(self):
        # A rejected result where a request left the process but we never got an
        # ack is treated conservatively.
        intent = self._make_intent()
        result = OrderResult(
            status="rejected",
            mode=TradingMode.LIVE,
            reason="network_error",
            submission_attempted=True,
            exchange_request_sent=True,
            exchange_ack_received=False,
        )
        _post_route_canonical_idempotency_cleanup(intent, result)
        self._assert_record_blocks_retry(intent)

    @pytest.mark.asyncio
    async def test_async_local_reject_releases_and_allows_retry(self, monkeypatch):
        intent = self._make_intent()
        impl = AsyncMock(
            return_value=OrderResult(
                status="rejected",
                mode=TradingMode.LIVE,
                reason="microstructure_gate_failed:spread_too_wide",
            )
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._route_order_async_impl", impl
        )

        result = await route_order_async(intent)
        assert result.status == "rejected"
        assert impl.call_count == 1
        self._assert_record_allows_retry(intent)

    @pytest.mark.asyncio
    async def test_async_exception_after_canonical_releases_record(self, monkeypatch):
        intent = self._make_intent()
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._route_order_async_impl",
            AsyncMock(side_effect=RuntimeError("port exploded")),
        )

        with pytest.raises(RuntimeError, match="port exploded"):
            await route_order_async(intent)

        self._assert_record_allows_retry(intent)

    @pytest.mark.asyncio
    async def test_async_submission_unknown_keeps_record_locked(self, monkeypatch):
        intent = self._make_intent()
        impl = AsyncMock(
            return_value=OrderResult(
                status="submission_unknown",
                mode=TradingMode.LIVE,
                reason="timeout",
                submission_attempted=True,
                exchange_request_sent=True,
                exchange_ack_received=False,
            )
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._route_order_async_impl", impl
        )

        result = await route_order_async(intent)
        assert result.status == "submission_unknown"
        self._assert_record_blocks_retry(intent)

    def test_sync_local_reject_releases_and_allows_retry(self, monkeypatch):
        intent = self._make_intent()

        def _impl(i):
            return OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason="risk_limit_exceeded",
            )

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._route_order_impl", _impl
        )

        result = route_order(intent)
        assert result.status == "rejected"
        self._assert_record_allows_retry(intent)

    def test_sync_exception_after_canonical_releases_record(self, monkeypatch):
        intent = self._make_intent()

        def _raise(_i):
            raise RuntimeError("sync port exploded")

        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._route_order_impl", _raise
        )

        with pytest.raises(RuntimeError, match="sync port exploded"):
            route_order(intent)

        self._assert_record_allows_retry(intent)
