"""Promotion-gate evidence for discretionary exits (audit Phases 4-6).

The discretionary EV exit gate (``MERID_ENABLE_EV_EXIT_GATE`` /
``MERID_DISCRETIONARY_EXIT_MODE``) stays observe-only until three evidence
classes exist:

* **Deterministic replay** — the same recorded evaluation inputs, replayed
  through fresh evaluator instances (in-process and cross-process), produce
  byte-identical decision sequences and economics.  Any wall-clock, RNG, or
  ambient-state leakage into the decision is a promotion blocker.

* **Independent shadow recomputation** — a from-scratch reimplementation of
  the sell-vs-hold policy in this file recomputes blockers, economics, and
  the final decision for every corpus record and must agree with the
  production evaluator on every field that authorizes an order.

* **Lifecycle parity** — a replayed exit-attempt lifecycle (durable
  ExitOrderAttemptStore + PositionMonitor reconciliation) produces identical
  durable state trajectories on independent runs, and reaches the correct
  terminal state for each staged exchange-evidence class.

Nothing here enables the gate; it produces the evidence the promotion review
consumes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from merid.event_venues.kalshi.settlement_aligned_exit import (
    EvDecision,
    EvGatePolicy,
    ExitEvaluationRegistry,
    SettlementAlignedExitEvaluator,
)


# ── corpus construction ──────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

# A fixed policy so the corpus never depends on ambient env vars.
_POLICY = EvGatePolicy(
    switch_margin_cents=2,
    uncertainty_reserve_cents=2,
    hold_risk_reserve_cents=1,
    near_expiry_reserve_cents=4,
    near_expiry_reserve_below_seconds=300.0,
    min_consecutive=3,
    no_discretionary_below_seconds=60.0,
    max_quote_age_ms=10_000,
    max_rti_age_ms=2_000,
    slippage_cents=2,
    require_sequence_confirmed=True,
    require_rti=True,
    require_calibrated_model=True,
    require_sufficient_bid_depth=True,
    discretionary_mode="observe_only",
)

_CANARY_POLICY = EvGatePolicy(
    **{**_POLICY.__dict__, "discretionary_mode": "ev_gated_canary",
       "canary_assets": frozenset({"ETH"})}
)


def _position(
    *,
    market_id: str = "KXBTC15M-26SEP90000-00",
    position_id: str = "pos-ev-1",
    side: str = "yes",
    size: str = "100",
    provenance: bool = True,
) -> SimpleNamespace:
    pos = SimpleNamespace(
        market_id=market_id,
        position_id=position_id,
        size=Decimal(size),
        outcome_side=side,
    )
    if provenance:
        pos.entry_fill_id = "fill-entry-1"
        pos.avg_entry_price_cents = 50
        pos.entry_model = "bachelier-v2"
        pos.risk_params_state = "original_persisted"
    return pos


def _state(
    *,
    yes_bid: Optional[int] = None,
    yes_ask: Optional[int] = None,
    no_bid: Optional[int] = None,
    no_ask: Optional[int] = None,
    depth: int = 500,
    seq: bool = True,
    s2e: float = 400.0,
    vol_source: str = "live_estimate",
    calibration_version: str = "v2",
    calibrated_prob: Optional[float] = None,
    transition: str = "VALID",
) -> SimpleNamespace:
    """Market-state stand-in carrying everything evaluate() reads."""
    return SimpleNamespace(
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        best_no_bid_cents=no_bid,
        best_no_ask_cents=no_ask,
        book=SimpleNamespace(
            yes_bids=(
                [SimpleNamespace(price_cents=yes_bid, size=depth)]
                if yes_bid is not None
                else []
            ),
            no_bids=(
                [SimpleNamespace(price_cents=no_bid, size=depth)]
                if no_bid is not None
                else []
            ),
        ),
        live_sequence_confirmed=seq,
        snapshot_complete=False,
        transition=transition,
        book_health="",
        data_quality="",
        book_source="ws",
        seconds_to_expiry=s2e,
        annualized_vol_source=vol_source,
        calibration_version=calibration_version,
        calibrated_prob=calibrated_prob,
    )


def _rti(eligible: bool = True) -> Optional[SimpleNamespace]:
    """RTI observation with no timestamp fields: age is unknowable (None),
    which exercises the eligibility branch without touching any clock."""
    if not eligible:
        return SimpleNamespace(execution_eligible=False)
    return SimpleNamespace(execution_eligible=True)


def _spec(
    name: str,
    *,
    position: Optional[SimpleNamespace] = None,
    held_side: str = "yes",
    canonical_reason: str = "stop_loss",
    quantity: str = "100",
    state: Optional[SimpleNamespace] = None,
    fair_value_cents: Optional[int] = 40,
    executable_bid_cents: Optional[int] = None,
    book_age_ms: Optional[int] = 500,
    seconds_to_expiry: Optional[float] = 400.0,
    rti: Any = "__default__",
    gate_enabled: bool = True,
    repeat: int = 1,
) -> Dict[str, Any]:
    if rti == "__default__":
        rti = _rti(True)
    return {
        "name": name,
        "position": position if position is not None else _position(),
        "held_side": held_side,
        "canonical_reason": canonical_reason,
        "quantity": quantity,
        "state": state if state is not None else _state(yes_bid=40, yes_ask=45),
        "fair_value_cents": fair_value_cents,
        "executable_bid_cents": executable_bid_cents,
        "book_age_ms": book_age_ms,
        "seconds_to_expiry": seconds_to_expiry,
        "rti": rti,
        "gate_enabled": gate_enabled,
        "repeat": repeat,
    }


def _corpus() -> List[Dict[str, Any]]:
    """The recorded input set replayed identically in every evidence run."""
    return [
        # Economics: net_sell ~37.3 < cons_hold 57 → hold.
        _spec("clean_hold", fair_value_cents=40,
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        # breach (net_sell ~85.3 > cons_hold 27 + margin 2) → persistence, then
        # SELL_SIGNALLED on the 3rd consecutive qualifying observation.
        _spec("breach_then_sell", fair_value_cents=30,
              state=_state(yes_bid=88, yes_ask=92, calibrated_prob=0.30),
              repeat=3),
        # NO-held sell path: YES calibrated_prob 0.70 → held-NO p_cal 30.
        _spec("no_held_breach_then_sell", held_side="no", fair_value_cents=30,
              position=_position(side="no"),
              state=_state(no_bid=88, no_ask=92, calibrated_prob=0.70),
              repeat=3),
        _spec("stale_book", book_age_ms=20_000,
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("no_same_side_bid", state=_state(yes_ask=45)),
        _spec("book_not_sequence_confirmed",
              state=_state(yes_bid=40, yes_ask=45, seq=False,
                           calibrated_prob=0.60)),
        _spec("crossed_book_incoherent",
              state=_state(yes_bid=60, yes_ask=55, calibrated_prob=0.60)),
        _spec("missing_entry_provenance",
              position=_position(provenance=False),
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("rti_unavailable", rti=None,
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("rti_ineligible", rti=_rti(False),
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("no_model_valuation", fair_value_cents=None,
              state=_state(yes_bid=40, yes_ask=45)),
        _spec("untrusted_vol_source",
              state=_state(yes_bid=40, yes_ask=45, vol_source="default",
                           calibrated_prob=0.60)),
        _spec("near_expiry_defers", seconds_to_expiry=30.0,
              state=_state(yes_bid=88, yes_ask=92, s2e=30.0,
                           calibrated_prob=0.30)),
        _spec("insufficient_bid_depth", quantity="100",
              state=_state(yes_bid=88, yes_ask=92, depth=50,
                           calibrated_prob=0.30)),
        _spec("zero_quantity", quantity="0",
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("operational_reason", canonical_reason="reconciliation",
              state=_state(yes_bid=40, yes_ask=45)),
        _spec("emergency_reason", canonical_reason="expiry_liquidation",
              state=_state(yes_bid=40, yes_ask=45)),
        _spec("unknown_reason_fails_closed", canonical_reason="bogus_reason",
              state=_state(yes_bid=40, yes_ask=45)),
        _spec("noncanonical_market_key",
              position=_position(market_id="KXBTC15M"),
              state=_state(yes_bid=40, yes_ask=45, calibrated_prob=0.60)),
        _spec("gate_off_still_signals_but_never_submits", gate_enabled=False,
              fair_value_cents=30,
              state=_state(yes_bid=88, yes_ask=92, calibrated_prob=0.30),
              repeat=3),
    ]


def _new_evaluator(policy: EvGatePolicy = _POLICY) -> SettlementAlignedExitEvaluator:
    return SettlementAlignedExitEvaluator(
        policy=policy,
        registry=ExitEvaluationRegistry(persist_dir=None),
        rti_provider=lambda _asset: None,
        tail_calibrator=None,
    )


def _run_corpus(policy: EvGatePolicy = _POLICY) -> List[Dict[str, Any]]:
    """Replay the corpus on a fresh evaluator; return one record per eval."""
    evaluator = _new_evaluator(policy)
    out: List[Dict[str, Any]] = []
    for spec in _corpus():
        for i in range(spec["repeat"]):
            ev = evaluator.evaluate(
                spec["position"],
                market_key=spec["position"].market_id,
                held_side=spec["held_side"],
                canonical_reason=spec["canonical_reason"],
                quantity_contracts=Decimal(spec["quantity"]),
                kalshi_state=spec["state"],
                unified_state=None,
                fair_value_cents=spec["fair_value_cents"],
                executable_bid_cents=spec["executable_bid_cents"],
                book_age_ms=spec["book_age_ms"],
                seconds_to_expiry=spec["seconds_to_expiry"],
                rti_observation=spec["rti"],
                gate_enabled=spec["gate_enabled"],
                record=False,
            )
            out.append(_fingerprint(spec["name"], i, ev))
    return out


def _fingerprint(name: str, iteration: int, ev: Any) -> Dict[str, Any]:
    """Deterministic projection of an evaluation — excludes the uuid
    evaluation_id and wall-clock ts, which are record metadata, not decision
    outputs."""
    d = ev.to_dict()
    d.pop("evaluation_id", None)
    d.pop("ts", None)
    d["corpus_name"] = name
    d["corpus_iteration"] = iteration
    return d


def _run_corpus_json(policy_mode: str = "base") -> str:
    """Whole-corpus fingerprint as canonical JSON — the replay artifact."""
    policy = _CANARY_POLICY if policy_mode == "canary" else _POLICY
    records = _run_corpus(policy)
    return json.dumps(records, sort_keys=True, default=str)


# ── Phase 5: independent shadow recomputation ────────────────────────────────

_UNTRUSTED_VOL = frozenset({"", "default", "requested", "fallback", "unknown",
                            "n/a", "none"})
_DISCRETIONARY_REASONS = frozenset({
    "stop_loss", "loss_cut", "value_switch_exit",
})
_OPERATIONAL_REASONS = frozenset({
    "reconciliation", "manual", "market_expired", "market_closed",
    "mechanical_time_exit", "scheduled_closeout",
    "trailing_stop", "take_profit", "signal_reversal",
    "model_invalidation", "time_exit", "edge_decay",
    "scale_out", "ratchet_trim",
})
_EMERGENCY_REASONS = frozenset({"expiry_liquidation", "emergency", "hard_risk"})
_TRUSTED_RISK_STATES = frozenset({"original_persisted", "fallback"})
_TRUSTED_BOOK_QUALITIES = frozenset({"AT_FILL", "AT_FILL_OR_NEAREST_PRE_FILL"})


def _shadow_fee_cents(price_cents: int) -> Decimal:
    """Independent Kalshi taker fee: rate*C*P*(1-P) rounded up to $0.0001."""
    p = Decimal(price_cents) / Decimal(100)
    fee_usd = Decimal("0.07") * Decimal(1) * p * (1 - p)
    return fee_usd.quantize(Decimal("0.0001"), rounding=ROUND_CEILING) * 100


def _shadow_provenance(position: Any) -> List[str]:
    missing: List[str] = []
    linkage = any(
        getattr(position, a, None)
        for a in ("entry_fill_id", "entry_order_id", "client_order_id",
                  "entry_intent_id")
    )
    if not linkage:
        missing.append("entry_linkage")
    basis = (getattr(position, "entry_fill_price_cents", None)
             or getattr(position, "all_in_entry_basis_cents", None)
             or getattr(position, "avg_entry_price_cents", None))
    if not basis:
        missing.append("entry_price")
    if not (getattr(position, "entry_model", None)
            or getattr(position, "entry_model_version", None)
            or getattr(position, "entry_model_probability", None) is not None
            or getattr(position, "entry_signal_id", None)):
        missing.append("entry_model")
    quality = str(getattr(position, "entry_book_capture_quality", "") or "")
    risk_state = str(getattr(position, "risk_params_state", "") or "").lower()
    if (quality not in _TRUSTED_BOOK_QUALITIES
            and not getattr(position, "entry_book_snapshot_id", None)
            and risk_state not in _TRUSTED_RISK_STATES):
        missing.append("entry_book")
    return missing


def _shadow_evaluate(
    spec: Dict[str, Any],
    policy: EvGatePolicy,
    streaks: Dict[str, int],
) -> Dict[str, Any]:
    """Independent reimplementation of the production decision rules.

    Deliberately shares NO code with settlement_aligned_exit: constants and
    the fee formula are restated from the documented contract, so agreement is
    evidence rather than tautology.
    """
    position = spec["position"]
    state = spec["state"]
    held = spec["held_side"].lower()
    canonical = spec["canonical_reason"].lower()
    qty = Decimal(spec["quantity"])
    s2e = spec["seconds_to_expiry"]
    mkey = str(position.market_id).upper().replace("_", "-")

    if canonical in _OPERATIONAL_REASONS:
        return {"decision": EvDecision.BYPASS_OPERATIONAL,
                "consecutive_breach": 0}
    if canonical in _EMERGENCY_REASONS:
        return {"decision": EvDecision.BYPASS_EMERGENCY,
                "consecutive_breach": 0}
    if canonical not in _DISCRETIONARY_REASONS:
        return {"decision": EvDecision.BLOCK_UNKNOWN_REASON,
                "consecutive_breach": 0}

    missing_prov = _shadow_provenance(position)

    bid = spec["executable_bid_cents"]
    if bid is None:
        bid = getattr(state, "best_bid_cents" if held == "yes"
                      else "best_no_bid_cents", None)
    ask = getattr(state, "best_ask_cents" if held == "yes"
                  else "best_no_ask_cents", None)
    book = getattr(state, "book", None)
    depth = None
    if book is not None:
        levels = getattr(book, "yes_bids" if held == "yes" else "no_bids", None)
        if levels:
            depth = getattr(levels[0], "size", None)
    crossed = bid is not None and ask is not None and bid >= ask
    coherent = not crossed and str(getattr(state, "transition", "VALID")).upper() not in {
        "RESYNC_REQUIRED", "CIRCUIT_BREAKER", "INVALID_INVERTED",
        "INVALID_SEQUENCE_GAP", "INVALID_UNKNOWN_MARKET",
    }

    rti = spec["rti"]
    rti_ok = rti is not None and bool(getattr(rti, "execution_eligible", False))
    fair = spec["fair_value_cents"]

    vol_source = str(getattr(state, "annualized_vol_source", "") or "").lower()
    calib_version = str(getattr(state, "calibration_version", "") or "")
    calib_prob = getattr(state, "calibrated_prob", None)
    p_cal: Optional[int] = None
    if calib_prob is not None and held in ("yes", "no"):
        yes_cents = int(round(calib_prob * 100)) if calib_prob <= 1.0 else int(round(calib_prob))
        if 0 <= yes_cents <= 100:
            p_cal = yes_cents if held == "yes" else 100 - yes_cents
    if p_cal is None and calib_version:
        p_cal = fair
    model_ok = vol_source not in _UNTRUSTED_VOL and bool(calib_version)

    blockers: List[str] = []
    if missing_prov:
        blockers.append("missing_entry_provenance")
    if "-" not in mkey:
        blockers.append("noncanonical_market_key")
    if held not in ("yes", "no"):
        blockers.append("unknown_held_side")
    if bid is None:
        blockers.append("no_same_side_bid")
    elif spec["book_age_ms"] is None or spec["book_age_ms"] > policy.max_quote_age_ms:
        blockers.append("stale_book")
    elif policy.require_sequence_confirmed and not (
        getattr(state, "live_sequence_confirmed", False)
        or getattr(state, "snapshot_complete", False)
    ):
        blockers.append("book_not_sequence_confirmed")
    elif not coherent:
        blockers.append("book_incoherent")
    if policy.require_rti and not rti_ok:
        blockers.append("rti_unavailable_or_ineligible")
    if fair is None:
        blockers.append("no_model_valuation")
    if policy.require_calibrated_model and not model_ok:
        blockers.append("uncalibrated_model_inputs")
    if qty <= 0:
        blockers.append("zero_quantity")
    if (policy.require_sufficient_bid_depth and bid is not None
            and depth is not None and qty > 0 and Decimal(depth) < qty):
        blockers.append("insufficient_bid_depth")

    near_expiry = s2e is not None and s2e <= policy.no_discretionary_below_seconds

    net_sell = cons_hold = None
    breach = False
    if bid is not None and fair is not None:
        fee = _shadow_fee_cents(bid)
        net_sell = Decimal(bid) - fee - Decimal(policy.slippage_cents)
        hold_risk = Decimal(policy.hold_risk_reserve_cents)
        if s2e is not None and s2e <= policy.near_expiry_reserve_below_seconds:
            hold_risk += Decimal(policy.near_expiry_reserve_cents)
        cons_prob = Decimal(p_cal) if p_cal is not None else Decimal(fair)
        cons_hold = cons_prob - Decimal(policy.uncertainty_reserve_cents) - hold_risk
        breach = net_sell > cons_hold + Decimal(policy.switch_margin_cents)

    sig = (mkey, str(position.position_id), held, canonical, vol_source,
           calib_version)
    counts = breach and not blockers and not near_expiry and qty > 0
    if counts:
        streaks[sig] = streaks.get(sig, 0) + 1
    else:
        for k in [k for k in streaks if k[0] == mkey and k[1] == str(position.position_id)]:
            streaks.pop(k, None)
    consecutive = streaks.get(sig, 0)

    if near_expiry:
        decision = EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED
    elif blockers:
        decision = EvDecision.HOLD_DATA_INSUFFICIENT
    elif breach and consecutive >= policy.min_consecutive:
        decision = EvDecision.SELL_SIGNALLED
    elif breach:
        decision = EvDecision.HOLD_PERSISTENCE_NOT_MET
    else:
        decision = EvDecision.HOLD_SELL_VALUE_INFERIOR

    out: Dict[str, Any] = {"decision": decision, "consecutive_breach": consecutive}
    if net_sell is not None:
        out["net_sell_value_cents"] = str(net_sell)
        out["conservative_hold_cents"] = str(cons_hold)
        out["exit_fee_cents"] = str(fee)
    return out


# ── Phase 4: deterministic replay ────────────────────────────────────────────

class TestDeterministicReplay:
    """Identical inputs on independent evaluator instances must produce
    identical decisions — the replay evidence the promotion gate requires."""

    def test_fresh_evaluator_replay_identical(self):
        run_a = _run_corpus()
        run_b = _run_corpus()
        assert run_a == run_b
        assert len(run_a) >= 20, "corpus must exercise enough evaluations"

    def test_persistence_state_replays_identically(self):
        """Breach-streak state is keyed deterministically: two fresh evaluators
        accumulate identical consecutive_breach trajectories."""
        run_a = _run_corpus()
        run_b = _run_corpus()
        seq_a = [(r["corpus_name"], r["consecutive_breach"]) for r in run_a]
        seq_b = [(r["corpus_name"], r["consecutive_breach"]) for r in run_b]
        assert seq_a == seq_b
        # And the corpus actually exercises a streak reaching SELL_SIGNALLED.
        assert any(
            r["decision"] == EvDecision.SELL_SIGNALLED.value for r in run_a
        ), "corpus must reach SELL_SIGNALLED to prove the sell path replays"

    def test_cross_process_replay_identical(self, tmp_path):
        """Two independent subprocesses replaying the corpus must emit
        byte-identical fingerprints — catches ambient env / hash-order /
        platform-state leakage."""
        driver = (
            "import sys, json;"
            # Repo root must precede tests/ on sys.path so `monitoring`
            # resolves to the repo package, not tests/monitoring/.
            f"sys.path.insert(0, {str(REPO_ROOT / 'tests')!r});"
            f"sys.path.insert(0, {str(REPO_ROOT)!r});"
            "from kalshi.test_discretionary_exit_evidence import _run_corpus_json;"
            "sys.stdout.write(_run_corpus_json())"
        )
        env = dict(
            os.environ,
            MERID_ENV="testing",
            MERID_TRADE_MODE="paper",
            # The driver runs outside pytest, so conftest's durable-path pins
            # do not apply — pin them here so an import-time writer can never
            # touch repo data/.
            MERID_TRADE_ATTRIBUTION_DB_PATH=str(tmp_path / "attr.db"),
            MERID_FILLS_DB_PATH=str(tmp_path / "fills.db"),
            MERID_KALSHI_ORDER_ATTEMPT_DB=str(tmp_path / "attempts.db"),
        )
        outs = []
        for _ in range(2):
            res = subprocess.run(
                [sys.executable, "-c", driver],
                capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
                timeout=120,
            )
            assert res.returncode == 0, f"driver failed: {res.stderr[-2000:]}"
            outs.append(res.stdout)
        assert outs[0] == outs[1]
        assert json.loads(outs[0]), "empty corpus output"

    def test_decision_coverage(self):
        """The corpus must cover every decision branch the gate can take, so
        replay evidence isn't vacuous."""
        run = _run_corpus()
        seen = {r["decision"] for r in run}
        for expected in (
            EvDecision.SELL_SIGNALLED,
            EvDecision.HOLD_PERSISTENCE_NOT_MET,
            EvDecision.HOLD_SELL_VALUE_INFERIOR,
            EvDecision.HOLD_DATA_INSUFFICIENT,
            EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED,
            EvDecision.BLOCK_UNKNOWN_REASON,
            EvDecision.BYPASS_OPERATIONAL,
            EvDecision.BYPASS_EMERGENCY,
        ):
            assert expected.value in seen, f"corpus missing {expected.value}"

    def test_gate_off_never_would_submit(self):
        """With the gate off, even a SELL_SIGNALLED evaluation can never
        authorize an order — the observe-only veto is part of the contract."""
        run = _run_corpus()
        for r in run:
            if r["corpus_name"] == "gate_off_still_signals_but_never_submits":
                assert r["would_submit"] is False
                assert r["gate_enabled"] is False


# ── Phase 5: shadow recomputation parity ─────────────────────────────────────

class TestShadowRecomputation:
    """The independent reimplementation in this file must agree with the
    production evaluator on every decision and every economic field."""

    def test_shadow_parity_all_corpus(self):
        evaluator = _new_evaluator()
        streaks: Dict[str, int] = {}
        for spec in _corpus():
            for _ in range(spec["repeat"]):
                ev = evaluator.evaluate(
                    spec["position"],
                    market_key=spec["position"].market_id,
                    held_side=spec["held_side"],
                    canonical_reason=spec["canonical_reason"],
                    quantity_contracts=Decimal(spec["quantity"]),
                    kalshi_state=spec["state"],
                    unified_state=None,
                    fair_value_cents=spec["fair_value_cents"],
                    executable_bid_cents=spec["executable_bid_cents"],
                    book_age_ms=spec["book_age_ms"],
                    seconds_to_expiry=spec["seconds_to_expiry"],
                    rti_observation=spec["rti"],
                    gate_enabled=spec["gate_enabled"],
                    record=False,
                )
                shadow = _shadow_evaluate(spec, _POLICY, streaks)
                assert ev.decision == shadow["decision"], (
                    f"{spec['name']}: evaluator={ev.decision} "
                    f"shadow={shadow['decision']} detail={ev.detail}"
                )
                assert ev.consecutive_breach == shadow["consecutive_breach"], (
                    f"{spec['name']}: streak mismatch "
                    f"{ev.consecutive_breach} != {shadow['consecutive_breach']}"
                )
                if "net_sell_value_cents" in shadow:
                    assert ev.net_sell_value_cents == shadow["net_sell_value_cents"], (
                        f"{spec['name']}: net_sell {ev.net_sell_value_cents} "
                        f"!= shadow {shadow['net_sell_value_cents']}"
                    )
                    assert ev.conservative_hold_cents == shadow["conservative_hold_cents"]
                    assert ev.exit_fee_cents == shadow["exit_fee_cents"]

    def test_shadow_fee_matches_documented_schedule(self):
        """The shadow fee must reproduce the documented parabolic schedule on
        boundary prices (1c and 99c are the fee maxima/asymmetry edge)."""
        # 1 contract @ 47c -> $0.017437 -> $0.0175 -> 1.75c (verified live fill)
        assert _shadow_fee_cents(47) == Decimal("1.75")
        assert _shadow_fee_cents(1) == Decimal("0.07")
        assert _shadow_fee_cents(99) == Decimal("0.07")
        assert _shadow_fee_cents(50) == Decimal("1.75")


# ── Phase 6: lifecycle parity ────────────────────────────────────────────────

def _lifecycle_scenario_json(
    tmp_path: Path, evidence: List[Dict[str, Any]], size: int = 1
) -> Path:
    scenario = {
        "id": "lifecycle-parity",
        "description": "exit attempt replay parity",
        "time_range": {"start": "2026-09-03T14:00:00Z",
                       "end": "2026-09-03T14:30:00Z"},
        "positions": [{
            "market_id": "KXBTC15M-27JAN010000-00",
            "series_ticker": "KXBTC15M",
            "side": "yes",
            "size": size,
            "avg_entry_price_cents": 50,
            "entry_fill_price_cents": 50,
            "risk_params_state": "original_persisted",
            "risk_params_schema_version": 2,
            "client_order_id": "entry-abc123",
            "entry_fill_id": "fill-abc123",
            "entry_intent_id": "intent-entry-abc123",
        }],
        "exit_attempts": [{
            "exit_intent_id": "intent-exit-parity",
            "position_key": "KXBTC15M-27JAN010000-00",
            "ticker": "KXBTC15M-27JAN010000-00",
            "reason": "take_profit",
            "client_order_id": "exit_parity_001",
            "requested_quantity": 100,
            "requested_limit_cents": 80,
            "initial_state": "SUBMISSION_UNKNOWN",
        }],
        "exchange_evidence": evidence,
    }
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return path


@pytest.mark.asyncio
class TestLifecycleParity:
    """Replayed exit-attempt lifecycles must reach identical durable terminal
    states on independent runs — the durable FSM is the live code path, so
    identical replay trajectories are the parity evidence."""

    async def _run_lifecycle(
        self, tmp_path: Path, monkeypatch, evidence: List[Dict[str, Any]],
        size: int = 1,
    ) -> List[str]:
        from merid.event_venues.kalshi.incidents.replayer import (
            ExitOrderIncidentReplay, IncidentExchangeEvidence, load_scenario,
        )
        from merid.event_venues.kalshi.order_attempt_store import (
            OrderAttemptStore,
        )
        from merid.event_venues.kalshi import order_attempt_store as _oas

        tmp_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            "merid.position_management.position_monitor._is_expired_ticker",
            lambda _: False,
        )
        db = tmp_path / "attempts.db"
        monkeypatch.setenv("MERID_KALSHI_ORDER_ATTEMPT_DB", str(db))
        monkeypatch.setattr(_oas, "DEFAULT_DB_PATH", str(db))
        OrderAttemptStore._instances.clear()

        scenario = load_scenario(_lifecycle_scenario_json(tmp_path, evidence, size))
        replay = ExitOrderIncidentReplay(scenario)
        states = [replay.seed_exit_attempt().state]
        replay.build_position()
        for ev in evidence:
            states.append(
                (await replay.reconcile(IncidentExchangeEvidence(**ev))).state
            )
        OrderAttemptStore._instances.clear()
        return states

    async def test_lifecycle_trajectory_parity_canceled(self, tmp_path, monkeypatch):
        evidence = [
            {"client_order_id": "exit_parity_001", "order_status": "resting",
             "order_id": "ord-1", "order_price": 0.80,
             "exchange_position_size": 1},
            {"client_order_id": "exit_parity_001", "order_status": "canceled",
             "order_id": "ord-1", "order_price": 0.80,
             "exchange_position_size": 1},
        ]
        run_a = await self._run_lifecycle(tmp_path / "a", monkeypatch, evidence)
        run_b = await self._run_lifecycle(tmp_path / "b", monkeypatch, evidence)
        assert run_a == run_b
        assert run_a[0] == "SUBMISSION_UNKNOWN"
        assert run_a[1] == "RESOLVING_ON_EXCHANGE"
        assert run_a[-1] == "CANCELED"

    async def test_lifecycle_trajectory_parity_filled(self, tmp_path, monkeypatch):
        evidence = [
            {"client_order_id": "exit_parity_001", "order_status": "filled",
             "order_id": "ord-1", "order_price": 0.80,
             "exchange_position_size": 0},
        ]
        run_a = await self._run_lifecycle(tmp_path / "a", monkeypatch, evidence)
        run_b = await self._run_lifecycle(tmp_path / "b", monkeypatch, evidence)
        assert run_a == run_b
        assert run_a[-1] == "FILLED"

    async def test_lifecycle_still_resting_stays_nonterminal(
        self, tmp_path, monkeypatch
    ):
        evidence = [
            {"client_order_id": "exit_parity_001", "order_status": "resting",
             "order_id": "ord-1", "order_price": 0.80,
             "exchange_position_size": 1},
        ]
        run_a = await self._run_lifecycle(tmp_path / "a", monkeypatch, evidence)
        run_b = await self._run_lifecycle(tmp_path / "b", monkeypatch, evidence)
        assert run_a == run_b
        # A resting order must never terminalize — reservation is retained.
        assert run_a[-1] == "RESOLVING_ON_EXCHANGE"

    async def test_lifecycle_flat_position_terminalizes(
        self, tmp_path, monkeypatch
    ):
        """Zero canonical exposure terminalizes the attempt without touching
        the exchange — replay must reproduce the same terminal state."""
        evidence = [
            {"client_order_id": "exit_parity_001", "order_status": "not_found",
             "exchange_position_size": 0},
        ]
        run_a = await self._run_lifecycle(
            tmp_path / "a", monkeypatch, evidence, size=0
        )
        run_b = await self._run_lifecycle(
            tmp_path / "b", monkeypatch, evidence, size=0
        )
        assert run_a == run_b
        assert run_a[-1] in ("NOT_ACCEPTED_CONFIRMED", "EXCHANGE_CONFIRMED_FLAT")
