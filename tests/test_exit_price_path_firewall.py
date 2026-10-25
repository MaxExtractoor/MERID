"""Regression: the BTC LOSS_CAP 61c -> 93c price transformation (2026-10-26).

Venue record for order ``01a170d1-f778-7278-a8d7-9dd1af7d1066`` showed a 93c
limit sell where the local stop candidate had recorded 61c.  The transform was
the firewall's fee-adjusted min-proceeds floor: the LOSS_CAP's structured
emergency authorization (exit_class=operational, emergency_type=
POSITION_LOSS_BUDGET, source=position_monitor, generation=entry fill id) was
denied solely because the reduce-only fills-ledger PositionSnapshot dropped
``parent_entry_fill_id``, failing the generation-binding leg.

Fixed:
  - fills-ledger replay now returns the exposure-episode opener fill id and
    ``_fetch_local_position`` propagates it as the snapshot generation.
  - FirewallDecision now carries the explicit execution contract:
    requested/policy/final limit, execution_mode, marketable_at_snapshot,
    nonmarketable_reason, and a per-stage price_transforms attribution chain.

These tests pin the exact BTC historical inputs and the corrected behavior.
"""

import asyncio
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.binary_price_space import (
    fill_to_signed_yes_exposure,
    legacy_to_v2,
    yes_delta,
)
from merid.event_venues.kalshi.execution_risk_firewall import (
    BookDepth,
    ExecutionRiskFirewall,
    PositionSnapshot,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent


BTC_TICKER = "KXBTC15M-26OCT242215-15"
BTC_ENTRY_FILL = "0724b393-5e91-bb8f-1563-f7b2e85f71e1"
BTC_CLIENT_ORDER_ID = "stopcand_sc-d137c5e063f9"
BTC_INTENT_ID = "stop_candidate:sc-d137c5e063f9"


def _btc_book() -> BookDepth:
    """Book snapshot the BTC firewall evaluated: bids ~69-77c, vwap 77."""
    return BookDepth(
        vwap_cents=77,
        available_qty_cc=98,
        levels=[(77, 50), (73, 30), (69, 18)],
        best_bid_cents=77,
        best_ask_cents=None,
        book_age_ms=120,
        book_sequence=4242,
        marginal_price_cents=69,
    )


def _pos(*, position_cc=98, side="yes", avg_cents=90, parent=BTC_ENTRY_FILL):
    return PositionSnapshot(
        position_cc=position_cc,
        side=side,
        avg_price_cents=avg_cents,
        version="fills_ledger:test",
        snapshot_age_ms=0,
        parent_entry_fill_id=parent,
    )


def _loss_cap_canonical(*, ticker=BTC_TICKER, contract="yes", qty_cc=98,
                        limit_cents=61, pos_cc=98, generation=BTC_ENTRY_FILL,
                        authorized=True):
    """The BTC LOSS_CAP canonical: sell YES 98cc @61c, structured emergency."""
    delta = yes_delta("sell", contract, qty_cc)
    return CanonicalOrderIntent(
        market_ticker=ticker,
        contract=contract,
        action="sell",
        purpose="close",
        qty_cc=qty_cc,
        limit_cents=limit_cents,
        strategy_signal="down",
        expected_position_before=pos_cc,
        expected_position_after=pos_cc + delta,
        expected_realized_pnl_cents=None,
        reason="LOSS_CAP:no_edge_salvage",
        reduce_only=True,
        intent_id=BTC_INTENT_ID,
        client_order_id=BTC_CLIENT_ORDER_ID,
        time_in_force="ioc",
        exit_class="operational",
        emergency_type="POSITION_LOSS_BUDGET",
        authorization_source="position_monitor",
        position_generation_id=generation,
        parent_entry_fill_id=generation,
    ) if authorized else CanonicalOrderIntent(
        market_ticker=ticker,
        contract=contract,
        action="sell",
        purpose="close",
        qty_cc=qty_cc,
        limit_cents=limit_cents,
        strategy_signal="down",
        expected_position_before=pos_cc,
        expected_position_after=pos_cc + delta,
        expected_realized_pnl_cents=None,
        reason="LOSS_CAP:no_edge_salvage",
        reduce_only=True,
        intent_id=BTC_INTENT_ID,
        client_order_id=BTC_CLIENT_ORDER_ID,
        time_in_force="ioc",
        # Positive edge claims but NO structured emergency tuple — the
        # compatibility edge fields must not manufacture below-floor authority.
        ev_net_cents=5.0,
        gross_edge=0.05,
    )


def _firewall(monkeypatch, *, pos, book):
    """Firewall with every external dependency replaced by the BTC fixtures."""
    ExecutionRiskFirewall.reset_for_test()
    fw = ExecutionRiskFirewall.get_instance()
    captured = []

    async def _no_position(_ticker):
        return None  # force the reduce-only local-position fallback

    monkeypatch.setattr(
        fw, "_market_active_and_before_deadline", lambda _t: True
    )
    monkeypatch.setattr(fw, "_has_in_flight_exit", lambda _c: None)
    monkeypatch.setattr(fw, "_fetch_position", _no_position)
    monkeypatch.setattr(fw, "_fetch_local_position", lambda _t: pos)
    monkeypatch.setattr(fw, "_fetch_book", lambda _c: book)
    monkeypatch.setattr(
        fw, "_persisted_trail_lock_cents", lambda *a, **k: None
    )
    monkeypatch.setattr(fw, "_persist_decision", lambda d: captured.append(d))
    return fw, captured


def _run(fw, canonical, intent=None):
    return asyncio.run(fw.validate_exit(canonical, intent))


# ── 1. BTC replay: the exact historical transformation ──────────────────────


def test_btc_denied_generation_reproduces_93c_transformation(monkeypatch):
    """Exact BTC inputs: pos_gen dropped -> floor raises 61 -> 93 -> nonmarketable."""
    pos = _pos(parent=None)  # the pre-fix fills-ledger snapshot: generationless
    book = _btc_book()
    canonical = _loss_cap_canonical()
    fw, captured = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    assert decision.status == "approved"
    assert decision.requested_limit_cents == 61
    assert decision.approved_limit_cents == 93  # ceil(90 + 0.63 + 1.67)
    assert decision.emergency is False
    assert decision.execution_mode == "price_constrained_exit"
    assert decision.policy_floor_cents == 93
    assert decision.marketable_at_snapshot is False  # 93 > best_bid 77
    assert decision.nonmarketable_reason == "PRICE_CONSTRAINT_PREVENTS_IMMEDIATE_EXIT"
    assert decision.price_transforms == [
        {
            "stage": "min_proceeds_floor",
            "input_cents": 61,
            "output_cents": 93,
            "reason": "fee_adjusted_breakeven_floor",
            "policy_id": "MERID_MIN_PROCEEDS_FEE_ADJUST",
            "source_claim": {
                "entry_cents": 90,
                "trail_lock_cents": None,
                "emergency_authorized": False,
            },
        }
    ]


def test_btc_authorized_loss_cap_keeps_requested_limit(monkeypatch):
    """Corrected path: ledger-sourced generation binds -> exempt -> stays 61c."""
    pos = _pos(parent=BTC_ENTRY_FILL)  # ledger now supplies the generation
    book = _btc_book()
    canonical = _loss_cap_canonical()
    fw, captured = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    assert decision.status == "approved"
    assert decision.emergency is True
    assert decision.execution_mode == "immediate_risk_reduction"
    assert decision.requested_limit_cents == 61
    assert decision.approved_limit_cents == 61  # the explicitly authorized price
    assert decision.policy_floor_cents is None
    assert decision.marketable_at_snapshot is True  # 61 <= 77 bids -> IOC fills
    assert decision.nonmarketable_reason is None
    assert decision.price_transforms == []


def test_mismatched_generation_denies_and_keeps_floor(monkeypatch):
    """A wrong-generation LOSS_CAP must NOT gain below-floor authority."""
    pos = _pos(parent=BTC_ENTRY_FILL)
    book = _btc_book()
    canonical = _loss_cap_canonical(generation="some-other-fill-id")
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    assert decision.status == "approved"
    assert decision.emergency is False
    assert decision.approved_limit_cents == 93
    assert decision.nonmarketable_reason == "PRICE_CONSTRAINT_PREVENTS_IMMEDIATE_EXIT"


# ── 2. Fills-ledger generation propagation ──────────────────────────────────


def _fill(fill_id, ticker, action, side, qty_cc, price_dollars, fee="0.001"):
    from merid.event_venues.kalshi.fills_ledger import KalshiFill

    return KalshiFill(
        fill_id=fill_id,
        market_ticker=ticker,
        canonical_position_action=action,
        canonical_position_side=side,
        quantity_cc=qty_cc,
        yes_price_dollars=Decimal(price_dollars),
        fee_cost=Decimal(fee),
        canonicalization_state="TRUSTED_LIVE_V1",
    )


def _bare_ledger():
    """KalshiFillsLedger object without __init__ (no DB) — only _fills is needed."""
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._fills = {}
    return ledger


def test_ledger_episode_opener_is_entry_generation():
    """Single-fill episode: the opening fill IS the position generation."""
    ledger = _bare_ledger()
    f = _fill("f_entry", BTC_TICKER, "buy", "yes", 98, "0.90")
    ledger._fills[f.fill_id] = f

    pos = ledger._compute_position_from_fill_ids(BTC_TICKER, [f.fill_id])

    assert pos["signed_yes_exposure"] == 98
    assert pos["entry_fill_id"] == "f_entry"


def test_ledger_episode_opener_survives_partial_fills():
    """Averaging in and partial exits do not change the generation."""
    ledger = _bare_ledger()
    f1 = _fill("f1", BTC_TICKER, "buy", "yes", 50, "0.90")
    f2 = _fill("f2", BTC_TICKER, "buy", "yes", 48, "0.91")
    f3 = _fill("f3", BTC_TICKER, "sell", "yes", 20, "0.70")
    for f in (f1, f2, f3):
        ledger._fills[f.fill_id] = f

    pos = ledger._compute_position_from_fill_ids(
        BTC_TICKER, [f1.fill_id, f2.fill_id, f3.fill_id]
    )

    assert pos["signed_yes_exposure"] == 78
    assert pos["entry_fill_id"] == "f1"  # still the episode opener


def test_ledger_episode_opener_resets_after_zero_crossing():
    """Full close then reopen: the reopening fill is the new generation."""
    ledger = _bare_ledger()
    f1 = _fill("f1", BTC_TICKER, "buy", "yes", 100, "0.90")
    f2 = _fill("f2", BTC_TICKER, "sell", "yes", 100, "0.70")
    f3 = _fill("f3", BTC_TICKER, "buy", "yes", 50, "0.80")
    for f in (f1, f2, f3):
        ledger._fills[f.fill_id] = f

    pos = ledger._compute_position_from_fill_ids(
        BTC_TICKER, [f1.fill_id, f2.fill_id, f3.fill_id]
    )

    assert pos["signed_yes_exposure"] == 50
    assert pos["entry_fill_id"] == "f3"  # generation of the CURRENT episode


def test_ledger_episode_opener_tracks_sign_flip_fill():
    """One oversized fill flipping the sign opens a new episode itself."""
    ledger = _bare_ledger()
    f1 = _fill("f1", BTC_TICKER, "buy", "yes", 50, "0.90")
    f2 = _fill("f2", BTC_TICKER, "sell", "yes", 98, "0.70")
    for f in (f1, f2):
        ledger._fills[f.fill_id] = f

    pos = ledger._compute_position_from_fill_ids(
        BTC_TICKER, [f1.fill_id, f2.fill_id]
    )

    assert pos["signed_yes_exposure"] == -48  # long NO now
    assert pos["entry_fill_id"] == "f2"  # the flip fill opened this episode


def test_fetch_local_position_propagates_generation(monkeypatch):
    """The firewall's fills-ledger fallback must not drop the generation id."""
    from merid.event_venues.kalshi import execution_risk_firewall as erf

    ExecutionRiskFirewall.reset_for_test()
    fw = ExecutionRiskFirewall.get_instance()

    class _StubLedger:
        def compute_position_from_fills(self, ticker):
            return {
                "signed_yes_exposure": 98,
                "side": "yes",
                "avg_price_cents": 90,
                "entry_fill_id": BTC_ENTRY_FILL,
            }

    monkeypatch.setattr(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
        lambda: _StubLedger(),
    )
    # position_cache is only reached when the ledger path fails — leave it.

    snap = fw._fetch_local_position(BTC_TICKER)

    assert snap is not None
    assert snap.position_cc == 98
    assert snap.avg_price_cents == 90
    assert snap.parent_entry_fill_id == BTC_ENTRY_FILL


# ── 3. Five assets x both held outcomes ──────────────────────────────────────


_TICKERS = {
    "BTC": "KXBTC15M-26OCT242215-15",
    "ETH": "KXETH15M-26OCT242215-15",
    "SOL": "KXSOL15M-26OCT242215-15",
    "XRP": "KXXRP15M-26OCT242215-15",
    "DOGE": "KXDOGE15M-26OCT242215-15",
}


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
@pytest.mark.parametrize("held", ["yes", "no"])
def test_authorized_loss_cap_preserves_limit_all_assets_both_sides(
    monkeypatch, asset, held
):
    """An authorized LOSS_CAP keeps its requested limit on every asset and
    both held outcomes — the floor only applies to non-exempt exits."""
    ticker = _TICKERS[asset]
    pos_cc = 98 if held == "yes" else -98
    pos = _pos(
        position_cc=pos_cc,
        side=held,
        avg_cents=90 if held == "yes" else 10,
        parent="gen-fill-1",
    )
    # Sell-side exit at a deep loss limit; book executable above it.
    book = BookDepth(
        vwap_cents=50,
        available_qty_cc=98,
        levels=[(50, 98)],
        best_bid_cents=50,
        best_ask_cents=None,
        book_age_ms=100,
        book_sequence=1,
        marginal_price_cents=50,
    )
    delta = yes_delta("sell", held, 98)
    canonical = CanonicalOrderIntent(
        market_ticker=ticker,
        contract=held,
        action="sell",
        purpose="close",
        qty_cc=98,
        limit_cents=30,
        strategy_signal="down",
        expected_position_before=pos_cc,
        expected_position_after=pos_cc + delta,
        expected_realized_pnl_cents=None,
        reason="LOSS_CAP:no_edge_salvage",
        reduce_only=True,
        intent_id=f"stop_candidate:sc-{asset}",
        client_order_id=f"stopcand_sc-{asset}",
        time_in_force="ioc",
        exit_class="operational",
        emergency_type="POSITION_LOSS_BUDGET",
        authorization_source="position_monitor",
        position_generation_id="gen-fill-1",
        parent_entry_fill_id="gen-fill-1",
    )
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    assert decision.status == "approved", decision.reason
    assert decision.emergency is True
    assert decision.execution_mode == "immediate_risk_reduction"
    assert decision.approved_limit_cents == 30
    assert decision.price_transforms == []


# ── 4. Ordinary exits keep the floor (denied/never-claimed authorization) ────


@pytest.mark.parametrize("held", ["yes", "no"])
def test_ordinary_exit_floor_applies_without_authorization(monkeypatch, held):
    """No emergency tuple at all -> ordinary price-constrained exit, floor
    applies and nonmarketability is attributed."""
    pos_cc = 98 if held == "yes" else -98
    entry = 90 if held == "yes" else 10
    pos = _pos(position_cc=pos_cc, side=held, avg_cents=entry, parent="g1")
    book = BookDepth(
        vwap_cents=50,
        available_qty_cc=98,
        levels=[(50, 98)],
        best_bid_cents=50,
        best_ask_cents=None,
        book_age_ms=100,
        book_sequence=1,
        marginal_price_cents=50,
    )
    delta = yes_delta("sell", held, 98)
    canonical = CanonicalOrderIntent(
        market_ticker=BTC_TICKER,
        contract=held,
        action="sell",
        purpose="close",
        qty_cc=98,
        limit_cents=30 if held == "yes" else 4,
        strategy_signal="down",
        expected_position_before=pos_cc,
        expected_position_after=pos_cc + delta,
        expected_realized_pnl_cents=None,
        reason="take_profit",
        reduce_only=True,
        intent_id="intent_tp_1",
        client_order_id="tp_coid_1",
        time_in_force="ioc",
    )
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    assert decision.status == "approved", decision.reason
    assert decision.emergency is False
    assert decision.execution_mode == "price_constrained_exit"
    # floor = ceil(entry + entry_fee + exit_fee)
    # yes: ceil(90 + 0.63 + 1.47) = 93; no: ceil(10 + 0.63 + 0.27) = 11
    expected_floor = 93 if held == "yes" else 11
    requested = 30 if held == "yes" else 4
    assert decision.approved_limit_cents == max(requested, expected_floor)
    assert decision.policy_floor_cents == expected_floor
    stage_names = [t["stage"] for t in decision.price_transforms]
    assert "min_proceeds_floor" in stage_names


def test_compat_edge_claim_cannot_inject_profit_floor_semantics(monkeypatch):
    """A positive compatibility edge claim does not manufacture below-floor
    authority — the floor is bound to AUTHORIZATION, not to edge fields."""
    pos = _pos(parent=BTC_ENTRY_FILL)
    book = _btc_book()
    canonical = _loss_cap_canonical(authorized=False)
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    # ev_net_cents=+5.0 / gross_edge=+0.05 compat claims cannot exempt the exit.
    assert decision.emergency is False
    assert decision.execution_mode == "price_constrained_exit"
    assert decision.approved_limit_cents == 93
    assert decision.price_transforms[0]["source_claim"][
        "emergency_authorized"
    ] is False


# ── 5. YES/NO wire normalization + quantity boundary ─────────────────────────


def test_legacy_to_v2_direction_matrix():
    """The single permitted YES/NO conversion — a YES sell at 61c is ask@61."""
    assert legacy_to_v2("sell", "yes", 61) == ("ask", 61)
    assert legacy_to_v2("buy", "yes", 61) == ("bid", 61)
    assert legacy_to_v2("sell", "no", 39) == ("bid", 61)   # 100-39 complement
    assert legacy_to_v2("buy", "no", 39) == ("ask", 61)
    # BTC wire truth: sell yes @93 -> ask@93 (a YES-side ask, NOT 'sell no@7').
    assert legacy_to_v2("sell", "yes", 93) == ("ask", 93)


def test_quantity_boundary_98cc_serializes_098_contracts():
    """98 centi-contracts -> '0.98' contracts on the wire, never '98'."""
    from merid.event_venues.kalshi.client import _format_count_fp

    assert _format_count_fp(Decimal("0.98")) == "0.98"
    assert _format_count_fp(Decimal("1")) == "1"
    assert _format_count_fp(Decimal("0.5")) == "0.50"


def test_decision_dict_carries_execution_contract(monkeypatch):
    """The persisted decision (order_decisions.jsonl) exposes every contract
    field the closeout requires."""
    pos = _pos(parent=None)
    book = _btc_book()
    canonical = _loss_cap_canonical()
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)
    d = decision.to_dict()

    for key in (
        "requested_limit_cents",
        "policy_floor_cents",
        "execution_mode",
        "marketable_at_snapshot",
        "nonmarketable_reason",
        "price_transforms",
    ):
        assert key in d, f"missing contract field: {key}"
    assert d["requested_limit_cents"] == 61
    assert d["approved_limit_cents"] == 93
    assert d["nonmarketable_reason"] == "PRICE_CONSTRAINT_PREVENTS_IMMEDIATE_EXIT"


def test_over_close_rejected_before_any_transform(monkeypatch):
    """No retry/competing exit may exceed the remaining position."""
    pos = _pos(position_cc=98)
    book = _btc_book()
    canonical = _loss_cap_canonical(qty_cc=99)  # 99cc > 98cc held
    fw, _ = _firewall(monkeypatch, pos=pos, book=book)

    decision = _run(fw, canonical)

    # Enforced mode returns "rejected"; test observe-only mode records the
    # same denial reason with status "observe_only".  An exit larger than the
    # held position is denied at whichever bound it hits first (local-position
    # support on the fallback path, or the explicit over_close check).
    assert decision.status in ("rejected", "observe_only")
    assert any(
        k in decision.reason for k in ("over_close", "no_local_position")
    ), decision.reason
