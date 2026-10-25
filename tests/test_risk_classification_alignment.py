"""Branch-level tests for the no-edge risk classification used by LOSS_CAP.

Covers the 2026-10-25 SOL-2215 incident: a bounded negative-net-EV probe
(pinned_fav admission, authorized net claim -4.997c) was classified
"model-edge" because

  * ``position_cache`` stamps ``entry_edge_pct = tp_targets.get("edge_pct") or
    0.03`` -- a missing stamp (and a legitimately-zero stamp) becomes a
    fabricated +3% net claim, and
  * ``entry_edge = +0.0101`` (gross model-vs-market delta) was positive,

so the union discriminator ``_position_no_edge_claim`` returned False and the
no-edge salvage floor (DROP_NO_EDGE=14c) never armed.  With LOSS_EXITS_ENABLED=0
and HARD_STOP shadow-frozen, the position rode to settlement at -90c.

These tests are characterization/regression tests: they pin the OBSERVED
behavior, the documented-intent behavior, and the boundary between them.
The policy question -- whether a positive gross edge should exempt a probe
whose *authorized net claim* is negative from the salvage floor -- is decided
separately; nothing here asserts a live-behavior change.

Imports are lazy: merid.position_management.position_monitor performs a live
Kalshi balance fetch at module load (~30s); tests skip cleanly if the import
is unavailable.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _claim(position):
    from merid.position_management.position_monitor import _position_no_edge_claim
    return _position_no_edge_claim(position)


def _pos(**kw):
    return SimpleNamespace(**kw)


class TestUnionDiscriminatorBranches:
    """_position_no_edge_claim returns True iff EITHER stamp is present and <=0."""

    def test_both_positive_is_model_edge(self):
        assert _claim(_pos(entry_edge_pct=0.03, entry_edge=0.0101)) is False

    def test_net_negative_gross_positive_is_no_edge(self):
        assert _claim(_pos(entry_edge_pct=-4.997, entry_edge=0.0101)) is True

    def test_net_positive_gross_negative_is_no_edge(self):
        assert _claim(_pos(entry_edge_pct=0.03, entry_edge=-0.0163)) is True

    def test_both_negative_is_no_edge(self):
        assert _claim(_pos(entry_edge_pct=-1.0, entry_edge=-0.02)) is True

    def test_zero_stamps_count_as_no_edge(self):
        assert _claim(_pos(entry_edge_pct=0.0, entry_edge=0.01)) is True
        assert _claim(_pos(entry_edge_pct=0.03, entry_edge=0.0)) is True

    def test_missing_stamps_fall_back_to_model_edge(self):
        """Both fields absent -> False -> classified MODEL_EDGE.

        This is the missing-provenance fallback: absent claims are treated as
        a positive edge rather than 'unknown'.  Pinned pending the explicit
        risk contract; if the contract is approved this test must change.
        """
        assert _claim(_pos()) is False
        assert _claim(_pos(entry_edge_pct=None, entry_edge=None)) is False


class TestSOL2215Reproduction:
    """Exact stamp reproduction for KXSOL15M-26OCT242215-15 (fill 02:11:40)."""

    def test_observed_stamps_classify_model_edge(self):
        # Persisted stamps: entry_edge=+0.0101 (gross), entry_edge_pct=0.03
        # (the `or 0.03` default -- the intent's edge_pct was falsy).
        assert _claim(_pos(entry_edge=0.0101, entry_edge_pct=0.03)) is False

    def test_authorized_net_claim_would_classify_no_edge(self):
        # The eval's advertised net claim (raw_edge_cents=-4.997c) would have
        # armed the no-edge salvage floor had it been stamped.
        assert _claim(_pos(entry_edge=0.0101, entry_edge_pct=-4.997)) is True

    def test_positive_gross_alone_does_not_exempt(self):
        # Union semantics: a positive entry_edge cannot veto a non-positive
        # entry_edge_pct.  Only the fabricated +3% default did.
        assert _claim(_pos(entry_edge=0.0101, entry_edge_pct=-0.073)) is True


class TestXRPPrecedent:
    """stop_candidate.py documents XRP NO@89 as the intended no-edge case."""

    def test_gross_positive_net_negative_is_no_edge(self):
        assert _claim(_pos(entry_edge=0.0062, entry_edge_pct=-2.89)) is True


class TestDefaultStampingSemantics:
    """position_cache.py:3264 `tp_targets.get("edge_pct") or 0.03` masks both
    missing AND legitimately-zero stamps.  Characterizes the defect without
    importing position_cache (heavy init); mirrors the exact expression."""

    @staticmethod
    def _stamped(tp_targets):
        return tp_targets.get("edge_pct") or 0.03

    def test_missing_edge_pct_becomes_positive_default(self):
        assert self._stamped({}) == 0.03

    def test_zero_edge_pct_is_masked(self):
        # `or` treats an explicit 0.0 as absent -- a flat claim becomes +3%.
        assert self._stamped({"edge_pct": 0.0}) == 0.03

    def test_negative_net_claim_survives(self):
        assert self._stamped({"edge_pct": -4.997}) == -4.997

    def test_none_is_masked(self):
        assert self._stamped({"edge_pct": None}) == 0.03


# ── Position risk contract (2026-10-26 alignment patch) ──────────────────

from merid.position_management.position_risk_contract import (
    NET_CLAIM_CONFLICT,
    NET_CLAIM_KNOWN_NONPOSITIVE,
    NET_CLAIM_KNOWN_POSITIVE,
    NET_CLAIM_UNKNOWN,
    RISK_POLICY_ID,
    RISK_POLICY_VERSION,
    classify_net_claim,
    legacy_union_no_edge_claim,
    no_edge_salvage_eligible,
    resolve_net_claim_state,
    risk_contract_fields,
)

ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
SIDES = ["yes", "no"]


def _contract_pos(**kw):
    """Simulate the position a correctly-stamped probe fill produces."""
    base = dict(
        entry_edge_pct=None,
        entry_edge_pct_claim_source="missing",
        entry_edge=None,
        entry_authorized_net_edge_c=None,
        no_edge_salvage_eligible=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestNetClaimStates:
    def test_explicit_zero_is_nonpositive(self):
        assert classify_net_claim(0.0) == NET_CLAIM_KNOWN_NONPOSITIVE

    def test_positive_and_negative(self):
        assert classify_net_claim(-4.997) == NET_CLAIM_KNOWN_NONPOSITIVE
        assert classify_net_claim(1.5) == NET_CLAIM_KNOWN_POSITIVE

    def test_missing_is_unknown_not_fabricated(self):
        assert classify_net_claim(None) == NET_CLAIM_UNKNOWN
        p = _contract_pos()
        state, _v, src = resolve_net_claim_state(p)
        assert state == NET_CLAIM_UNKNOWN
        assert src == "no_persisted_claim"

    def test_conflict_is_explicit(self):
        p = _contract_pos(
            entry_authorized_net_edge_c=5.0,
            entry_edge_pct=-2.0,
            entry_edge_pct_claim_source="intent",
        )
        state, _v, src = resolve_net_claim_state(p)
        assert state == NET_CLAIM_CONFLICT
        assert "entry_edge_pct" in src

    def test_compat_default_cannot_conflict(self):
        # A fabricated 0.03 must not veto the authorized net claim.
        p = _contract_pos(
            entry_authorized_net_edge_c=-1.18,
            entry_edge_pct=0.03,
            entry_edge_pct_claim_source="post_init_compat_default",
        )
        state, _v, _src = resolve_net_claim_state(p)
        assert state == NET_CLAIM_KNOWN_NONPOSITIVE


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
class TestSalvageEligibilityMatrix:
    """Approved policy: authorized net claim <= 0 -> eligible under the
    existing no-edge policy, regardless of gross-edge sign."""

    def test_positive_gross_negative_net_eligible(self, asset, side):
        p = _contract_pos(entry_edge=0.0101, entry_authorized_net_edge_c=-1.18)
        assert no_edge_salvage_eligible(p) == (True, "net_claim_nonpositive:contract")

    def test_negative_gross_negative_net_eligible(self, asset, side):
        p = _contract_pos(entry_edge=-0.0163, entry_authorized_net_edge_c=-2.89)
        assert no_edge_salvage_eligible(p)[0] is True

    def test_zero_net_eligible(self, asset, side):
        p = _contract_pos(entry_authorized_net_edge_c=0.0)
        assert no_edge_salvage_eligible(p)[0] is True

    def test_positive_net_not_eligible(self, asset, side):
        p = _contract_pos(entry_authorized_net_edge_c=2.0)
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False and reason.startswith("net_claim_positive")

    def test_missing_net_is_unknown_never_eligible(self, asset, side):
        p = _contract_pos()
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False
        assert reason.startswith("unknown_claim")
        # never manufactured: no 0.03 and no implicit-zero anywhere
        assert p.entry_authorized_net_edge_c is None

    def test_conflict_not_eligible(self, asset, side):
        p = _contract_pos(
            entry_authorized_net_edge_c=3.0,
            entry_edge_pct=-1.0,
            entry_edge_pct_claim_source="intent",
        )
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False and reason.startswith("claim_conflict")


class TestSOL2215EndToEnd:
    """Regression: correctly persisted admission semantics make the position
    eligible for the existing loss-cap path.  (No exit/P&L assertions.)"""

    def test_authorized_claim_makes_probe_eligible(self):
        fields = risk_contract_fields(
            gross_edge_c=1.01,
            authorized_net_edge_c=-1.18,
            net_edge_source="intent.ev_net_cents",
            admission_type="bounded_research_probe",
            admission_lane="pinned_fav",
            effective_threshold_c=-7.0,
            decision_id="cand_d6ed759f:maker_bid",
            selected_route="maker_bid",
        )
        assert fields["no_edge_salvage_eligible"] is True
        assert fields["net_claim_state"] == NET_CLAIM_KNOWN_NONPOSITIVE
        assert fields["risk_policy_id"] == RISK_POLICY_ID
        assert fields["risk_policy_version"] == RISK_POLICY_VERSION
        # the monitor's discriminator agrees
        assert _claim(_contract_pos(**fields)) is True
        # the historical fabricated-stamp position does NOT self-eligible-fix:
        # contract field absent + positive-only legacy stamps -> suppressed
        assert _claim(_contract_pos(
            entry_edge=0.0101, entry_edge_pct=0.03,
            entry_edge_pct_claim_source="post_init_compat_default",
        )) is False


class TestRoundTripSurvival:
    def test_contract_survives_snapshot_restore(self):
        from merid.position_management.position import Position
        fields = risk_contract_fields(
            gross_edge_c=1.01, authorized_net_edge_c=-1.18,
            net_edge_source="intent.ev_net_cents",
            admission_type="probe", admission_lane="pinned_fav",
            effective_threshold_c=-7.0,
        )
        pos = Position(
            position_id="T", market_id="M", series_ticker="KXSOL15M",
            side=None, size=__import__("decimal").Decimal("0.98"),
            avg_entry_price_cents=90, opened_at=None,
            outcome_side="yes",
            entry_edge_pct=None,  # missing intent claim
            **fields,
        )
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.entry_authorized_net_edge_c == -1.18
        assert restored.no_edge_salvage_eligible is True
        ok, _r = no_edge_salvage_eligible(restored)
        assert ok is True

    def test_zero_edge_pct_survives_deserialize(self):
        from merid.position_management.position import Position
        d = {"position_id": "T", "market_id": "M", "outcome_side": "yes", "entry_edge_pct": 0.0}
        pos = Position.from_dict(d)
        assert pos.entry_edge_pct == 0.0
        assert pos.entry_edge_pct_claim_source == "persisted"

    def test_compat_source_survives_deserialize(self):
        # A compat-fabricated 0.03 keeps its label across restore — it can
        # never be mistaken for an authentic intent claim.
        from merid.position_management.position import Position
        d = {"position_id": "T", "market_id": "M", "outcome_side": "yes"}
        pos = Position.from_dict(d)
        assert pos.entry_edge_pct == 0.03
        assert pos.entry_edge_pct_claim_source == "deserialize_compat_default"


class TestPersistedVerdictSemantics:
    """Truth table: persisted verdict + policy-version/disagreement handling."""

    def _pos_with_verdict(self, eligible, version=RISK_POLICY_VERSION, **kw):
        return _contract_pos(
            no_edge_salvage_eligible=eligible,
            risk_policy_version=version,
            entry_authorized_net_edge_c=kw.pop("net", None),
            **kw,
        )

    def test_same_version_persisted_honored(self):
        p = self._pos_with_verdict(True, net=-1.18)
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is True and reason.startswith("persisted_contract")

    def test_prior_policy_version_preserved_not_recomputed(self):
        # A verdict stamped under an older policy is preserved, never
        # silently recomputed under the new version.
        p = self._pos_with_verdict(False, version="2026-10-01.0", net=-1.18)
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False and reason.startswith("persisted_prior_policy")

    def test_restore_disagreement_flagged_persisted_wins(self):
        p = self._pos_with_verdict(True, net=2.0)  # fields say positive
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is True and reason.startswith("restore_disagreement")

    def test_conflict_state_overrides_persisted(self):
        p = self._pos_with_verdict(
            True, net=2.0,
            entry_edge_pct=-1.0, entry_edge_pct_claim_source="intent",
        )
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False and reason.startswith("claim_conflict")

    def test_conflict_never_falls_through_to_legacy_union(self):
        # CONFLICT is explicit — it must not degrade to ordinary-UNKNOWN
        # legacy-union handling where a gross-negative stamp would win.
        p = _contract_pos(
            entry_authorized_net_edge_c=3.0,
            entry_edge=-0.02,  # legacy union would say no-edge
            entry_edge_pct=-1.0, entry_edge_pct_claim_source="intent",
        )
        ok, reason = no_edge_salvage_eligible(p)
        assert ok is False and reason.startswith("claim_conflict")


class TestGateOperandLineage:
    """The persisted position claim must be the exact quantity the admission
    gate compared — intent.gate_ev_cents (breakdown.net_edge for lane-admitted
    sides), not the downstream calibrated ev_net_cents."""

    def _contract(self, **kw):
        from merid.event_venues.kalshi.order_router import _position_risk_contract
        return _position_risk_contract(SimpleNamespace(**kw))

    def test_sol2215_gate_pair_persisted(self):
        # SOL-2215 joined record: gate_ev_cents=-4.997 vs enforced bound -12.0
        # (pinned_fav floor); ev_net_cents=-1.18 is the calibrated EV — a
        # different number that must NOT displace the gate operand.
        c = self._contract(
            gate_ev_cents=-4.997290340656976,
            ev_net_cents=-1.181665340656977,
            effective_required_edge_cents=-12.0,
            entry_edge=0.010133346593430237,
            decision_id="cand_d6ed759f57461d2d37b50dd5:maker_bid",
            decision_lane="pinned_fav",
            admission_owner="pinned_fav",
            execution_mode="maker",
        )
        assert c is not None
        assert c["entry_authorized_net_edge_c"] == pytest.approx(
            -4.997290340656976
        )
        assert c["entry_authorized_net_edge_source"] == "intent.gate_ev_cents"
        assert c["entry_effective_threshold_c"] == -12.0
        assert c["entry_gross_edge_c"] == pytest.approx(1.0133346593430237)
        assert c["entry_admission_lane"] == "pinned_fav"
        assert c["net_claim_state"] == NET_CLAIM_KNOWN_NONPOSITIVE
        assert c["no_edge_salvage_eligible"] is True

    def test_ev_net_cents_fallback_when_gate_absent(self):
        c = self._contract(
            ev_net_cents=-1.181665340656977,
            entry_edge=0.0101,
            min_required_edge=0.02,  # fraction -> 2.0 cents
        )
        assert c["entry_authorized_net_edge_c"] == pytest.approx(
            -1.181665340656977
        )
        assert c["entry_authorized_net_edge_source"] == "intent.ev_net_cents"
        assert c["entry_effective_threshold_c"] == pytest.approx(2.0)

    def test_no_claim_is_unknown_not_fabricated(self):
        c = self._contract(entry_edge=0.03)
        assert c["entry_authorized_net_edge_c"] is None
        assert c["entry_authorized_net_edge_source"] == "absent"
        assert c["net_claim_state"] == NET_CLAIM_UNKNOWN
        assert c["no_edge_salvage_eligible"] is False


class TestQuantitySerializationBoundary:
    """Exact wire-quantity assertion: 98 centi-contracts must serialize as
    "0.98" contracts (Kalshi fixed-point decimal), never "98"."""

    def test_98cc_serializes_as_098_contracts(self):
        from decimal import Decimal
        from merid.event_venues.kalshi.client import _format_count_fp
        # internal position qty_cc=98 -> intent.count_fp=Decimal("0.98")
        assert _format_count_fp(Decimal("0.98")) == "0.98"
        # whole contracts still serialize as integers
        assert _format_count_fp(Decimal("13")) == "13"
        # a centi-contract value passed unconverted would serialize "98"
        # contracts — the assertion below pins that count_fp, not count,
        # is the wire authority.
        assert Decimal("98") != Decimal("0.98")

    def test_request_size_uses_count_fp_not_count(self):
        # _build_create_order_request: canonical_count = intent.count_fp
        # (contracts); intent.count is cc-scale display on exit intents.
        from decimal import Decimal
        from merid.event_venues.kalshi.order_router import (
            OrderIntent,
            _build_create_order_request,
        )
        intent = OrderIntent(
            ticker="KXSOL15M-T",
            side="yes",
            action="sell",
            price_cents=61,
            count=98,                    # cc-scale display
            count_fp=Decimal("0.98"),    # contracts authority
            order_type="limit",
            execution_mode="ioc",
        )
        intent.client_order_id = "qtytest" + "0" * 24  # finalized identity
        req = _build_create_order_request(
            intent, ticker="KXSOL15M-T", exchange_index=None,
            final_price_cents=61, effective_order_type="limit",
            effective_tif="ioc", expiration_ts=None, post_only=False,
        )
        assert Decimal(str(req.size)) == Decimal("0.98")


class TestShadowedStopTerminalPath:
    """HARD_STOP candidates are recorded but never submitted while the
    entry-relative executor is shadow-frozen (2026-10-19 freeze)."""

    def test_hard_stop_is_in_shadowed_set(self):
        from merid.event_venues.kalshi.stop_candidate import (
            SHADOWED_PRICE_STOP_TRIGGERS,
        )
        assert "HARD_STOP" in SHADOWED_PRICE_STOP_TRIGGERS
        # LOSS_CAP is deliberately NOT shadowed -- it is the designed
        # replacement class and the only live loss path while
        # LOSS_EXITS_ENABLED=0.
        assert "LOSS_CAP" not in SHADOWED_PRICE_STOP_TRIGGERS

    def test_shadow_flag_defaults_on(self, monkeypatch):
        monkeypatch.delenv("MERID_PRICE_STOP_SHADOW", raising=False)
        from merid.event_venues.kalshi.stop_candidate import (
            price_stop_shadow_enabled,
        )
        assert price_stop_shadow_enabled() is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-x", "-q"]))
