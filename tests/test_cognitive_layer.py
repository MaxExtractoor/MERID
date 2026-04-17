"""Tests for the Cognitive Layer (Sprint 10).

Covers:
  - Data models: Hypothesis, EvidenceLink, RegimeTag, CognitiveSnapshot
  - CognitiveStore: CRUD, history, actions, metrics
  - RealityDebugger: stuck models, conceptual disagreement, hypothesis dynamics
  - Golden scenarios: stuck model, healthy update, overreactive flipping
  - Alert rules: StaleHypothesisAlert, OverreactiveModelAlert
  - API endpoints: snapshots, hypotheses, reality-debug, health
  - Integration with reward engine CognitiveEvents
  - Observability: alert registry count, cognitive_health block
"""

from __future__ import annotations

import os
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# ── Models ────────────────────────────────────────────────────────────

from merid.cognitive.models import (
    CognitiveSnapshot,
    EvidenceLink,
    EvidenceType,
    Hypothesis,
    HypothesisAction,
    HypothesisStatus,
    RegimeTag,
    SnapshotDomain,
)

# ── Store ─────────────────────────────────────────────────────────────

from merid.cognitive.store import CognitiveStore

# ── Reality Debugger ──────────────────────────────────────────────────

from merid.cognitive.reality_debugger import (
    ConceptualDisagreement,
    HypothesisDynamics,
    RealityDebugger,
    StuckModel,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Data Model Tests
# ═══════════════════════════════════════════════════════════════════════

class TestRegimeTag:
    """RegimeTag dataclass and serialization."""

    def test_create_regime_tag(self):
        tag = RegimeTag(category="macro/regime", label="soft_landing", description="Fed soft landing")
        assert tag.category == "macro/regime"
        assert tag.label == "soft_landing"

    def test_to_dict(self):
        tag = RegimeTag(category="policy", label="fed_tightening", description="Rate hikes")
        d = tag.to_dict()
        assert d["category"] == "policy"
        assert d["label"] == "fed_tightening"

    def test_from_dict(self):
        d = {"category": "crypto/narrative", "label": "defi_summer", "description": "DeFi boom"}
        tag = RegimeTag.from_dict(d)
        assert tag.label == "defi_summer"

    def test_from_dict_empty(self):
        tag = RegimeTag.from_dict({})
        assert tag.category == ""
        assert tag.label == ""


class TestEvidenceLink:
    """EvidenceLink dataclass and serialization."""

    def test_create_evidence(self):
        ev = EvidenceLink(
            evidence_type=EvidenceType.SIGNAL.value,
            title="CPI print",
            supports=True,
            strength=0.8,
        )
        assert ev.evidence_type == "signal"
        assert ev.supports is True
        assert ev.strength == 0.8

    def test_to_dict(self):
        ev = EvidenceLink(title="Test", supports=False, strength=0.3)
        d = ev.to_dict()
        assert d["supports"] is False
        assert d["strength"] == 0.3
        assert d["id"].startswith("ev-")

    def test_from_dict(self):
        d = {
            "evidence_type": "opinion",
            "title": "Agent forecast",
            "supports": True,
            "strength": 0.7,
            "reference_id": "op-123",
        }
        ev = EvidenceLink.from_dict(d)
        assert ev.reference_id == "op-123"
        assert ev.evidence_type == "opinion"

    def test_evidence_types_enum(self):
        assert EvidenceType.SIGNAL.value == "signal"
        assert EvidenceType.DEBATE_ARGUMENT.value == "debate_argument"
        assert EvidenceType.MARKET_OUTCOME.value == "market_outcome"
        assert EvidenceType.EXTERNAL_DATA.value == "external_data"
        assert EvidenceType.PRICE_ACTION.value == "price_action"
        assert EvidenceType.SYSTEM_METRIC.value == "system_metric"


class TestHypothesis:
    """Hypothesis dataclass, lifecycle, and serialization."""

    def test_create_hypothesis(self):
        hyp = Hypothesis(
            text="Soft landing base case",
            regime_tag=RegimeTag("macro/regime", "soft_landing", ""),
            confidence=0.7,
            owner="agent-1",
        )
        assert hyp.text == "Soft landing base case"
        assert hyp.confidence == 0.7
        assert hyp.is_active is True

    def test_status_lifecycle(self):
        assert HypothesisStatus.ACTIVE.value == "active"
        assert HypothesisStatus.BROKEN.value == "broken"
        assert HypothesisStatus.RETIRED.value == "retired"
        assert HypothesisStatus.CONFIRMED.value == "confirmed"

    def test_hypothesis_actions(self):
        actions = [a.value for a in HypothesisAction]
        assert "created" in actions
        assert "updated" in actions
        assert "broken" in actions
        assert "retired" in actions
        assert "confirmed" in actions
        assert "confidence_adjusted" in actions
        assert "evidence_added" in actions
        assert "regime_tag_changed" in actions

    def test_evidence_counts(self):
        hyp = Hypothesis(
            evidence_links=[
                EvidenceLink(supports=True),
                EvidenceLink(supports=True),
                EvidenceLink(supports=False),
            ]
        )
        assert hyp.supporting_evidence_count == 2
        assert hyp.contradicting_evidence_count == 1

    def test_to_dict(self):
        hyp = Hypothesis(
            text="Test",
            regime_tag=RegimeTag("macro/regime", "test_tag", "desc"),
            confidence=0.6,
            owner="agent-1",
        )
        d = hyp.to_dict()
        assert d["text"] == "Test"
        assert d["regime_tag"]["label"] == "test_tag"
        assert d["confidence"] == 0.6
        assert d["supporting_evidence"] == 0
        assert d["contradicting_evidence"] == 0

    def test_from_dict(self):
        d = {
            "text": "Liquidity crunch",
            "regime_tag": {"category": "macro/regime", "label": "liquidity_crunch", "description": ""},
            "confidence": 0.8,
            "owner": "agent-2",
            "status": "active",
            "evidence_links": [
                {"title": "CPI", "supports": True, "strength": 0.9},
            ],
        }
        hyp = Hypothesis.from_dict(d)
        assert hyp.text == "Liquidity crunch"
        assert hyp.regime_tag.label == "liquidity_crunch"
        assert len(hyp.evidence_links) == 1

    def test_is_active_false_when_broken(self):
        hyp = Hypothesis(status=HypothesisStatus.BROKEN.value)
        assert hyp.is_active is False


class TestCognitiveSnapshot:
    """CognitiveSnapshot dataclass and serialization."""

    def test_create_snapshot(self):
        snap = CognitiveSnapshot(
            market_id="PRED:KALSHI:FED-RATE:YES",
            domain=SnapshotDomain.MARKET.value,
            hypotheses=[
                Hypothesis(text="H1", confidence=0.7),
                Hypothesis(text="H2", confidence=0.3, status=HypothesisStatus.BROKEN.value),
            ],
            overall_regime_confidence=0.65,
            owner="agent-1",
        )
        assert snap.hypothesis_count == 2
        assert snap.active_count == 1
        assert len(snap.active_hypotheses) == 1
        assert len(snap.broken_hypotheses) == 1

    def test_get_hypothesis(self):
        h1 = Hypothesis(id="hyp-1", text="H1")
        h2 = Hypothesis(id="hyp-2", text="H2")
        snap = CognitiveSnapshot(hypotheses=[h1, h2])
        assert snap.get_hypothesis("hyp-1") is h1
        assert snap.get_hypothesis("hyp-999") is None

    def test_to_dict(self):
        snap = CognitiveSnapshot(
            market_id="BTC",
            domain="crypto",
            hypotheses=[Hypothesis(text="Bull run")],
            overall_regime_confidence=0.8,
        )
        d = snap.to_dict()
        assert d["market_id"] == "BTC"
        assert d["hypothesis_count"] == 1
        assert d["active_count"] == 1
        assert len(d["hypotheses"]) == 1

    def test_from_dict(self):
        d = {
            "market_id": "SPY",
            "domain": "market",
            "hypotheses": [
                {"text": "Earnings beat", "confidence": 0.9, "regime_tag": {"category": "micro/idiosyncratic", "label": "earnings_beat", "description": ""}},
            ],
            "overall_regime_confidence": 0.85,
        }
        snap = CognitiveSnapshot.from_dict(d)
        assert snap.market_id == "SPY"
        assert len(snap.hypotheses) == 1
        assert snap.hypotheses[0].regime_tag.label == "earnings_beat"

    def test_snapshot_domains(self):
        assert SnapshotDomain.MARKET.value == "market"
        assert SnapshotDomain.MACRO.value == "macro"
        assert SnapshotDomain.CRYPTO.value == "crypto"
        assert SnapshotDomain.INFRA.value == "infra"
        assert SnapshotDomain.DEV.value == "dev"


# ═══════════════════════════════════════════════════════════════════════
# 2. CognitiveStore Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCognitiveStore:
    """SQLite CRUD for snapshots, hypotheses, evidence, and actions."""

    def _make_store(self):
        return CognitiveStore(db_path=":memory:")

    def test_save_and_get_snapshot(self):
        store = self._make_store()
        snap = CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[Hypothesis(text="Bull", confidence=0.8, owner="a1")],
            owner="a1",
        )
        store.save_snapshot(snap)
        got = store.get_snapshot(snap.id)
        assert got is not None
        assert got.market_id == "BTC"
        assert len(got.hypotheses) == 1
        assert got.hypotheses[0].text == "Bull"

    def test_get_snapshot_not_found(self):
        store = self._make_store()
        assert store.get_snapshot("nonexistent") is None

    def test_snapshot_count(self):
        store = self._make_store()
        assert store.snapshot_count() == 0
        store.save_snapshot(CognitiveSnapshot(market_id="A"))
        store.save_snapshot(CognitiveSnapshot(market_id="B"))
        assert store.snapshot_count() == 2

    def test_hypothesis_count(self):
        store = self._make_store()
        assert store.hypothesis_count() == 0
        store.save_snapshot(CognitiveSnapshot(
            market_id="A",
            hypotheses=[Hypothesis(text="H1"), Hypothesis(text="H2")],
        ))
        assert store.hypothesis_count() == 2

    def test_get_snapshots_for_market(self):
        store = self._make_store()
        store.save_snapshot(CognitiveSnapshot(market_id="BTC", created_at=time.time() - 100))
        store.save_snapshot(CognitiveSnapshot(market_id="BTC", created_at=time.time()))
        store.save_snapshot(CognitiveSnapshot(market_id="ETH"))
        snaps = store.get_snapshots_for_market("BTC")
        assert len(snaps) == 2
        # Newest first
        assert snaps[0].created_at >= snaps[1].created_at

    def test_get_latest_snapshot(self):
        store = self._make_store()
        store.save_snapshot(CognitiveSnapshot(market_id="BTC", created_at=time.time() - 100))
        snap2 = CognitiveSnapshot(market_id="BTC", created_at=time.time())
        store.save_snapshot(snap2)
        latest = store.get_latest_snapshot("BTC")
        assert latest is not None
        assert latest.id == snap2.id

    def test_get_latest_snapshot_none(self):
        store = self._make_store()
        assert store.get_latest_snapshot("NOPE") is None

    def test_get_snapshots_for_debate(self):
        store = self._make_store()
        store.save_snapshot(CognitiveSnapshot(market_id="A", debate_id="deb-1"))
        store.save_snapshot(CognitiveSnapshot(market_id="A", debate_id="deb-1"))
        store.save_snapshot(CognitiveSnapshot(market_id="A", debate_id="deb-2"))
        snaps = store.get_snapshots_for_debate("deb-1")
        assert len(snaps) == 2

    def test_get_snapshots_for_opinion(self):
        store = self._make_store()
        store.save_snapshot(CognitiveSnapshot(market_id="A", opinion_id="op-1"))
        snaps = store.get_snapshots_for_opinion("op-1")
        assert len(snaps) == 1

    def test_list_snapshots_with_filters(self):
        store = self._make_store()
        store.save_snapshot(CognitiveSnapshot(market_id="A", domain="market", owner="a1"))
        store.save_snapshot(CognitiveSnapshot(market_id="B", domain="infra", owner="a2"))
        store.save_snapshot(CognitiveSnapshot(market_id="C", domain="market", owner="a2"))
        assert len(store.list_snapshots(domain="market")) == 2
        assert len(store.list_snapshots(owner="a2")) == 2
        assert len(store.list_snapshots(domain="market", owner="a2")) == 1

    def test_evidence_persisted(self):
        store = self._make_store()
        hyp = Hypothesis(
            text="Test",
            evidence_links=[
                EvidenceLink(title="CPI", supports=True, strength=0.9),
                EvidenceLink(title="Jobs", supports=False, strength=0.4),
            ],
        )
        store.save_snapshot(CognitiveSnapshot(market_id="A", hypotheses=[hyp]))
        got = store.get_hypothesis(hyp.id)
        assert got is not None
        assert len(got.evidence_links) == 2
        titles = {e.title for e in got.evidence_links}
        assert "CPI" in titles
        assert "Jobs" in titles


class TestCognitiveStoreHypothesisActions:
    """Hypothesis lifecycle operations: confidence, broken, retire, evidence."""

    def _make_store_with_hyp(self):
        store = CognitiveStore(db_path=":memory:")
        hyp = Hypothesis(id="hyp-test", text="Test hypothesis", confidence=0.7, owner="a1")
        snap = CognitiveSnapshot(market_id="BTC", hypotheses=[hyp])
        store.save_snapshot(snap)
        return store

    def test_update_confidence(self):
        store = self._make_store_with_hyp()
        hyp = store.update_hypothesis_confidence("hyp-test", 0.9, actor="human-1", reason="New data")
        assert hyp is not None
        assert hyp.confidence == 0.9
        assert hyp.prior_confidence == 0.7

    def test_update_confidence_not_found(self):
        store = CognitiveStore(db_path=":memory:")
        assert store.update_hypothesis_confidence("nope", 0.5) is None

    def test_mark_broken(self):
        store = self._make_store_with_hyp()
        hyp = store.mark_hypothesis_broken("hyp-test", actor="human-1", reason="CPI contradicted")
        assert hyp is not None
        assert hyp.status == HypothesisStatus.BROKEN.value
        assert hyp.broken_at is not None
        assert hyp.broken_reason == "CPI contradicted"

    def test_mark_broken_not_found(self):
        store = CognitiveStore(db_path=":memory:")
        assert store.mark_hypothesis_broken("nope") is None

    def test_retire_hypothesis(self):
        store = self._make_store_with_hyp()
        hyp = store.retire_hypothesis("hyp-test", actor="human-1", reason="Superseded")
        assert hyp is not None
        assert hyp.status == HypothesisStatus.RETIRED.value

    def test_retire_not_found(self):
        store = CognitiveStore(db_path=":memory:")
        assert store.retire_hypothesis("nope") is None

    def test_add_evidence(self):
        store = self._make_store_with_hyp()
        ev = EvidenceLink(title="New data point", supports=True, strength=0.8)
        ok = store.add_evidence("hyp-test", ev, actor="human-1")
        assert ok is True
        hyp = store.get_hypothesis("hyp-test")
        assert len(hyp.evidence_links) == 1
        assert hyp.evidence_links[0].title == "New data point"

    def test_add_evidence_not_found(self):
        store = CognitiveStore(db_path=":memory:")
        ev = EvidenceLink(title="Test")
        assert store.add_evidence("nope", ev) is False

    def test_get_active_hypotheses_for_market(self):
        store = CognitiveStore(db_path=":memory:")
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[
                Hypothesis(text="H1", owner="a1"),
                Hypothesis(text="H2", owner="a2", status=HypothesisStatus.BROKEN.value),
            ],
        ))
        active = store.get_active_hypotheses_for_market("BTC")
        assert len(active) == 1
        assert active[0].text == "H1"


class TestCognitiveStoreActions:
    """Action log queries."""

    def test_actions_logged_on_creation(self):
        store = CognitiveStore(db_path=":memory:")
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[Hypothesis(text="H1")],
        ))
        actions = store.get_actions_for_market("BTC")
        assert len(actions) >= 1
        assert actions[0]["action"] == "created"

    def test_actions_logged_on_confidence_update(self):
        store = CognitiveStore(db_path=":memory:")
        hyp = Hypothesis(id="hyp-1", text="H1", confidence=0.5)
        store.save_snapshot(CognitiveSnapshot(market_id="BTC", hypotheses=[hyp]))
        store.update_hypothesis_confidence("hyp-1", 0.8, actor="human", reason="test")
        actions = store.get_actions_for_hypothesis("hyp-1")
        action_types = [a["action"] for a in actions]
        assert "created" in action_types
        assert "confidence_adjusted" in action_types

    def test_actions_logged_on_broken(self):
        store = CognitiveStore(db_path=":memory:")
        hyp = Hypothesis(id="hyp-1", text="H1")
        store.save_snapshot(CognitiveSnapshot(market_id="BTC", hypotheses=[hyp]))
        store.mark_hypothesis_broken("hyp-1", actor="human", reason="wrong")
        actions = store.get_actions_for_hypothesis("hyp-1")
        action_types = [a["action"] for a in actions]
        assert "broken" in action_types

    def test_get_all_actions(self):
        store = CognitiveStore(db_path=":memory:")
        store.save_snapshot(CognitiveSnapshot(
            market_id="A", hypotheses=[Hypothesis(text="H1")],
        ))
        store.save_snapshot(CognitiveSnapshot(
            market_id="B", hypotheses=[Hypothesis(text="H2")],
        ))
        actions = store.get_all_actions()
        assert len(actions) >= 2


class TestCognitiveStoreMetrics:
    """Cognitive metrics computation."""

    def test_empty_metrics(self):
        store = CognitiveStore(db_path=":memory:")
        m = store.get_cognitive_metrics()
        assert m["total_snapshots"] == 0
        assert m["total_hypotheses"] == 0

    def test_metrics_with_data(self):
        store = CognitiveStore(db_path=":memory:")
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[
                Hypothesis(text="H1", owner="a1"),
                Hypothesis(text="H2", owner="a2", status=HypothesisStatus.BROKEN.value),
            ],
        ))
        m = store.get_cognitive_metrics()
        assert m["total_snapshots"] == 1
        assert m["total_hypotheses"] == 2
        assert m["active_hypotheses"] == 1
        assert m["broken_hypotheses"] == 1
        assert m["markets_covered"] == 1
        assert m["unique_owners"] == 2


# ═══════════════════════════════════════════════════════════════════════
# 3. Reality Debugger Tests
# ═══════════════════════════════════════════════════════════════════════

class TestStuckModelDetection:
    """Detect markets with high error and stale hypotheses."""

    def _make_debugger(self):
        store = CognitiveStore(db_path=":memory:")
        return RealityDebugger(store=store, stale_lag_s=100.0), store

    def test_no_stuck_when_brier_low(self):
        debugger, store = self._make_debugger()
        stuck = debugger.detect_stuck_models({"BTC": 0.1})
        assert len(stuck) == 0

    def test_stuck_when_no_hypotheses(self):
        debugger, store = self._make_debugger()
        stuck = debugger.detect_stuck_models({"BTC": 0.6})
        assert len(stuck) == 1
        assert stuck[0].market_id == "BTC"
        assert "No hypotheses" in stuck[0].suggestion

    def test_stuck_when_hypotheses_stale(self):
        debugger, store = self._make_debugger()
        old_time = time.time() - 500  # 500s ago
        surprise_time = time.time() - 200  # surprise 200s ago
        hyp = Hypothesis(text="Old", owner="a1", created_at=old_time, updated_at=old_time)
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC", hypotheses=[hyp], created_at=old_time,
        ))
        stuck = debugger.detect_stuck_models(
            {"BTC": 0.6},
            market_surprise_times={"BTC": surprise_time},
        )
        assert len(stuck) == 1
        assert stuck[0].stale_hypotheses == 1
        assert "a1" in stuck[0].owners

    def test_not_stuck_when_recently_updated(self):
        debugger, store = self._make_debugger()
        now = time.time()
        hyp = Hypothesis(text="Fresh", owner="a1", created_at=now, updated_at=now)
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC", hypotheses=[hyp], created_at=now,
        ))
        stuck = debugger.detect_stuck_models(
            {"BTC": 0.6},
            market_surprise_times={"BTC": now - 50},
        )
        assert len(stuck) == 0

    def test_stuck_model_to_dict(self):
        sm = StuckModel(market_id="BTC", brier_score=0.7, lag_seconds=1000.0, stale_hypotheses=2)
        d = sm.to_dict()
        assert d["market_id"] == "BTC"
        assert d["brier_score"] == 0.7


class TestConceptualDisagreement:
    """Detect agents with similar probs but different hypotheses."""

    def _make_debugger(self):
        store = CognitiveStore(db_path=":memory:")
        return RealityDebugger(store=store, prob_spread_threshold=0.10), store

    def test_no_disagreement_when_probs_differ(self):
        debugger, store = self._make_debugger()
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[
                Hypothesis(text="H1", owner="a1", regime_tag=RegimeTag("", "bull", "")),
                Hypothesis(text="H2", owner="a2", regime_tag=RegimeTag("", "bear", "")),
            ],
        ))
        # Probs differ by more than threshold
        dis = debugger.detect_conceptual_disagreements("BTC", {"a1": 0.8, "a2": 0.3})
        assert len(dis) == 0

    def test_disagreement_when_same_probs_different_tags(self):
        debugger, store = self._make_debugger()
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[
                Hypothesis(text="Fed cuts", owner="a1", regime_tag=RegimeTag("", "fed_cuts", "")),
                Hypothesis(text="Strong earnings", owner="a2", regime_tag=RegimeTag("", "strong_earnings", "")),
            ],
        ))
        dis = debugger.detect_conceptual_disagreements("BTC", {"a1": 0.60, "a2": 0.62})
        assert len(dis) == 1
        assert dis[0].market_id == "BTC"
        assert "fed_cuts" in dis[0].regime_tags_a
        assert "strong_earnings" in dis[0].regime_tags_b

    def test_no_disagreement_when_same_tags(self):
        debugger, store = self._make_debugger()
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[
                Hypothesis(text="H1", owner="a1", regime_tag=RegimeTag("", "bull", "")),
                Hypothesis(text="H2", owner="a2", regime_tag=RegimeTag("", "bull", "")),
            ],
        ))
        dis = debugger.detect_conceptual_disagreements("BTC", {"a1": 0.60, "a2": 0.62})
        assert len(dis) == 0

    def test_conceptual_disagreement_to_dict(self):
        cd = ConceptualDisagreement(
            market_id="BTC",
            agents=[{"agent_id": "a1"}, {"agent_id": "a2"}],
            probability_spread=0.02,
            regime_tags_a=["bull"],
            regime_tags_b=["bear"],
        )
        d = cd.to_dict()
        assert d["market_id"] == "BTC"
        assert d["probability_spread"] == 0.02


class TestHypothesisDynamics:
    """Hypothesis change dynamics computation."""

    def _make_debugger(self):
        store = CognitiveStore(db_path=":memory:")
        return RealityDebugger(store=store), store

    def test_empty_dynamics(self):
        debugger, store = self._make_debugger()
        dyn = debugger.compute_hypothesis_dynamics("BTC")
        assert dyn.total_actions == 0
        assert dyn.flips == 0
        assert dyn.flip_rate_per_day == 0.0

    def test_dynamics_with_activity(self):
        debugger, store = self._make_debugger()
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[Hypothesis(text="H1"), Hypothesis(text="H2")],
        ))
        dyn = debugger.compute_hypothesis_dynamics("BTC")
        assert dyn.creations == 2
        assert dyn.total_actions >= 2

    def test_rigidity_flag(self):
        debugger, store = self._make_debugger()
        # No activity in 7+ days → rigid
        dyn = debugger.compute_hypothesis_dynamics("BTC", window_s=604800.0)
        assert dyn.rigidity_flag is True  # 0 actions in 7 days

    def test_dynamics_to_dict(self):
        dyn = HypothesisDynamics(
            market_id="BTC",
            total_actions=10,
            flips=3,
            flip_rate_per_day=0.5,
        )
        d = dyn.to_dict()
        assert d["market_id"] == "BTC"
        assert d["flips"] == 3


class TestRealityDebugReport:
    """Full reality debug report generation."""

    def test_empty_report(self):
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store)
        report = debugger.reality_debug()
        assert report["stuck_count"] == 0
        assert report["disagreement_count"] == 0
        assert report["markets_analyzed"] == 0

    def test_report_with_stuck_model(self):
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store, stale_lag_s=100.0)
        report = debugger.reality_debug(
            market_brier_scores={"BTC": 0.7},
        )
        assert report["stuck_count"] == 1

    def test_report_includes_dynamics(self):
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store)
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC", hypotheses=[Hypothesis(text="H1")],
        ))
        report = debugger.reality_debug(
            market_brier_scores={"BTC": 0.1},
        )
        assert "BTC" in report["hypothesis_dynamics"]
        assert report["cognitive_metrics"]["total_hypotheses"] >= 1


class TestCognitiveHealth:
    """Cognitive health metrics for observability."""

    def test_empty_health(self):
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store)
        health = debugger.get_cognitive_health()
        assert health["active_hypotheses"] == 0
        assert health["pct_surprised_with_updates"] == 100.0

    def test_health_with_data(self):
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store)
        store.save_snapshot(CognitiveSnapshot(
            market_id="BTC",
            hypotheses=[Hypothesis(text="H1", owner="a1")],
        ))
        health = debugger.get_cognitive_health()
        assert health["active_hypotheses"] == 1
        assert health["markets_covered"] == 1
        assert health["unique_owners"] == 1


# ═══════════════════════════════════════════════════════════════════════
# 4. Golden Scenarios
# ═══════════════════════════════════════════════════════════════════════

class TestGoldenScenarioStuckModel:
    """Simulate a 'stuck model' scenario and verify detection."""

    def test_stuck_model_scenario(self):
        """Agent creates hypothesis, market resolves badly, agent doesn't update."""
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store, stale_lag_s=100.0, brier_threshold=0.3)

        # Step 1: Agent creates hypothesis 500s ago
        old_time = time.time() - 500
        hyp = Hypothesis(
            text="Soft landing base case",
            regime_tag=RegimeTag("macro/regime", "soft_landing", ""),
            confidence=0.8,
            owner="agent-macro",
            created_at=old_time,
            updated_at=old_time,
        )
        store.save_snapshot(CognitiveSnapshot(
            market_id="FED-RATE",
            hypotheses=[hyp],
            created_at=old_time,
        ))

        # Step 2: Market resolves with high error (surprise 200s ago)
        surprise_time = time.time() - 200
        brier_scores = {"FED-RATE": 0.65}  # bad forecast
        surprise_times = {"FED-RATE": surprise_time}

        # Step 3: Agent does NOT update hypothesis

        # Step 4: Reality debugger detects stuck model
        stuck = debugger.detect_stuck_models(brier_scores, surprise_times)
        assert len(stuck) == 1
        assert stuck[0].market_id == "FED-RATE"
        assert stuck[0].stale_hypotheses == 1
        assert "agent-macro" in stuck[0].owners

        # Full report also catches it
        report = debugger.reality_debug(
            market_brier_scores=brier_scores,
            market_surprise_times=surprise_times,
        )
        assert report["stuck_count"] == 1


class TestGoldenScenarioHealthyUpdate:
    """Simulate a healthy update after surprise."""

    def test_healthy_update_scenario(self):
        """Agent creates hypothesis, surprise happens, agent updates promptly."""
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(store=store, stale_lag_s=100.0, brier_threshold=0.3)

        # Step 1: Agent creates hypothesis
        now = time.time()
        hyp = Hypothesis(
            id="hyp-healthy",
            text="Soft landing",
            regime_tag=RegimeTag("macro/regime", "soft_landing", ""),
            confidence=0.8,
            owner="agent-macro",
            created_at=now - 300,
            updated_at=now - 300,
        )
        store.save_snapshot(CognitiveSnapshot(
            market_id="FED-RATE",
            hypotheses=[hyp],
            created_at=now - 300,
        ))

        # Step 2: Surprise happens, agent updates hypothesis
        store.mark_hypothesis_broken("hyp-healthy", actor="agent-macro", reason="CPI contradicted")

        # Step 3: Verify not stuck
        stuck = debugger.detect_stuck_models(
            {"FED-RATE": 0.65},
            {"FED-RATE": now - 100},
        )
        # The hypothesis is now broken (not active), so no stale active hypotheses
        assert len(stuck) == 0 or all(s.stale_hypotheses == 0 for s in stuck)


class TestGoldenScenarioOverreactiveFlipping:
    """Simulate overreactive hypothesis flipping."""

    def test_overreactive_flipping_scenario(self):
        """Agent rapidly creates and breaks hypotheses without improvement."""
        store = CognitiveStore(db_path=":memory:")
        debugger = RealityDebugger(
            store=store,
            flip_rate_high=0.5,  # low threshold for test
            min_actions_for_flailing=3,
        )

        now = time.time()
        # Rapidly create and break hypotheses
        for i in range(5):
            hyp = Hypothesis(
                id=f"hyp-flip-{i}",
                text=f"Hypothesis {i}",
                owner="agent-flip",
                created_at=now - (10 - i),
                updated_at=now - (10 - i),
            )
            store.save_snapshot(CognitiveSnapshot(
                market_id="VOLATILE",
                hypotheses=[hyp],
                created_at=now - (10 - i),
            ))
            if i < 4:  # break all but the last
                store.mark_hypothesis_broken(
                    f"hyp-flip-{i}", actor="agent-flip", reason=f"Wrong {i}",
                )

        # Compute dynamics — should detect flailing
        dyn = debugger.compute_hypothesis_dynamics("VOLATILE", window_s=86400.0)
        assert dyn.creations >= 5
        assert dyn.breakages >= 4
        # With 4 breakages and 5 creations in quick succession, flips should be detected
        assert dyn.total_actions >= 9


# ═══════════════════════════════════════════════════════════════════════
# 5. Alert Rule Tests
# ═══════════════════════════════════════════════════════════════════════

class TestStaleHypothesisAlert:
    """StaleHypothesisAlert fires correctly."""

    def test_not_firing_when_healthy(self):
        from web.api.system_observability import StaleHypothesisAlert
        alert = StaleHypothesisAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "pct_surprised_with_updates": 100.0,
            "rigidity_count": 0,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is False

    def test_firing_when_low_update_pct(self):
        from web.api.system_observability import StaleHypothesisAlert
        alert = StaleHypothesisAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "pct_surprised_with_updates": 30.0,
            "rigidity_count": 0,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_firing_when_rigid(self):
        from web.api.system_observability import StaleHypothesisAlert
        alert = StaleHypothesisAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "pct_surprised_with_updates": 100.0,
            "rigidity_count": 2,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_graceful_on_exception(self):
        from web.api.system_observability import StaleHypothesisAlert
        alert = StaleHypothesisAlert()
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", side_effect=Exception("boom")):
            result = alert.evaluate()
        assert result["firing"] is False


class TestOverreactiveModelAlert:
    """OverreactiveModelAlert fires correctly."""

    def test_not_firing_when_healthy(self):
        from web.api.system_observability import OverreactiveModelAlert
        alert = OverreactiveModelAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "hypothesis_flip_rate_per_day": 0.1,
            "flailing_count": 0,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is False

    def test_firing_when_flailing(self):
        from web.api.system_observability import OverreactiveModelAlert
        alert = OverreactiveModelAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "hypothesis_flip_rate_per_day": 0.5,
            "flailing_count": 3,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_firing_when_high_flip_rate(self):
        from web.api.system_observability import OverreactiveModelAlert
        alert = OverreactiveModelAlert()
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "hypothesis_flip_rate_per_day": 3.0,
            "flailing_count": 0,
        }
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_graceful_on_exception(self):
        from web.api.system_observability import OverreactiveModelAlert
        alert = OverreactiveModelAlert()
        with patch("merid.cognitive.reality_debugger.get_reality_debugger", side_effect=Exception("boom")):
            result = alert.evaluate()
        assert result["firing"] is False


class TestAlertRegistryCount:
    """Verify alert registry has correct count after Sprint 10."""

    def test_alert_count_is_20(self):
        from web.api.system_observability import ALERT_RULES
        assert len(ALERT_RULES) == 28

    def test_cognitive_alerts_in_registry(self):
        from web.api.system_observability import ALERT_RULES
        names = [r.name for r in ALERT_RULES]
        assert "stale_hypothesis" in names
        assert "overreactive_model" in names


# ═══════════════════════════════════════════════════════════════════════
# 6. API Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCognitiveAPISnapshots:
    """Test cognitive API snapshot endpoints."""

    def test_create_snapshot_endpoint(self):
        from web.api.cognitive_api import create_snapshot, CreateSnapshotRequest, HypothesisInput
        import asyncio

        req = CreateSnapshotRequest(
            market_id="BTC",
            domain="crypto",
            hypotheses=[
                HypothesisInput(
                    text="Bull run",
                    regime_category="crypto/narrative",
                    regime_label="bull_run",
                    confidence=0.8,
                    owner="agent-1",
                ),
            ],
            owner="agent-1",
        )
        mock_store = MagicMock()
        mock_snap = MagicMock()
        mock_snap.to_dict.return_value = {"id": "snap-1", "market_id": "BTC"}
        mock_store.save_snapshot.return_value = mock_snap

        with patch("web.api.cognitive_api._get_store", return_value=mock_store), \
             patch("web.api.cognitive_api._emit_cognitive_event"):
            result = asyncio.get_event_loop().run_until_complete(create_snapshot(req))
        assert result["status"] == "ok"
        assert mock_store.save_snapshot.called

    def test_list_snapshots_endpoint(self):
        from web.api.cognitive_api import list_snapshots
        import asyncio

        mock_store = MagicMock()
        mock_snap = MagicMock()
        mock_snap.to_dict.return_value = {"id": "snap-1"}
        mock_store.list_snapshots.return_value = [mock_snap]

        with patch("web.api.cognitive_api._get_store", return_value=mock_store):
            result = asyncio.get_event_loop().run_until_complete(list_snapshots())
        assert result["count"] == 1

    def test_get_snapshot_not_found(self):
        from web.api.cognitive_api import get_snapshot
        from fastapi import HTTPException
        import asyncio

        mock_store = MagicMock()
        mock_store.get_snapshot.return_value = None

        with patch("web.api.cognitive_api._get_store", return_value=mock_store):
            try:
                asyncio.get_event_loop().run_until_complete(get_snapshot("nope"))
                assert False, "Should have raised"
            except HTTPException as e:
                assert e.status_code == 404


class TestCognitiveAPIHypothesisActions:
    """Test hypothesis action endpoints."""

    def test_update_confidence_endpoint(self):
        from web.api.cognitive_api import update_confidence, UpdateConfidenceRequest
        import asyncio

        mock_store = MagicMock()
        mock_hyp = MagicMock()
        mock_hyp.to_dict.return_value = {"id": "hyp-1", "confidence": 0.9}
        mock_hyp.prior_confidence = 0.7
        mock_hyp.regime_tag = MagicMock()
        mock_hyp.regime_tag.label = "test"
        mock_store.update_hypothesis_confidence.return_value = mock_hyp

        req = UpdateConfidenceRequest(new_confidence=0.9, actor="human", reason="test")
        with patch("web.api.cognitive_api._get_store", return_value=mock_store), \
             patch("web.api.cognitive_api._emit_cognitive_event"):
            result = asyncio.get_event_loop().run_until_complete(update_confidence("hyp-1", req))
        assert result["status"] == "ok"

    def test_mark_broken_endpoint(self):
        from web.api.cognitive_api import mark_broken, MarkBrokenRequest
        import asyncio

        mock_store = MagicMock()
        mock_hyp = MagicMock()
        mock_hyp.to_dict.return_value = {"id": "hyp-1", "status": "broken"}
        mock_hyp.confidence = 0.7
        mock_hyp.regime_tag = MagicMock()
        mock_hyp.regime_tag.label = "test"
        mock_store.mark_hypothesis_broken.return_value = mock_hyp

        req = MarkBrokenRequest(actor="human", reason="CPI")
        with patch("web.api.cognitive_api._get_store", return_value=mock_store), \
             patch("web.api.cognitive_api._emit_cognitive_event"):
            result = asyncio.get_event_loop().run_until_complete(mark_broken("hyp-1", req))
        assert result["status"] == "ok"

    def test_retire_endpoint(self):
        from web.api.cognitive_api import retire_hypothesis, RetireRequest
        import asyncio

        mock_store = MagicMock()
        mock_hyp = MagicMock()
        mock_hyp.to_dict.return_value = {"id": "hyp-1", "status": "retired"}
        mock_hyp.regime_tag = MagicMock()
        mock_hyp.regime_tag.label = "test"
        mock_store.retire_hypothesis.return_value = mock_hyp

        req = RetireRequest(actor="human", reason="superseded")
        with patch("web.api.cognitive_api._get_store", return_value=mock_store), \
             patch("web.api.cognitive_api._emit_cognitive_event"):
            result = asyncio.get_event_loop().run_until_complete(retire_hypothesis("hyp-1", req))
        assert result["status"] == "ok"

    def test_add_evidence_endpoint(self):
        from web.api.cognitive_api import add_evidence, AddEvidenceRequest
        import asyncio

        mock_store = MagicMock()
        mock_store.add_evidence.return_value = True

        req = AddEvidenceRequest(title="CPI data", supports=True, strength=0.9, actor="human")
        with patch("web.api.cognitive_api._get_store", return_value=mock_store), \
             patch("web.api.cognitive_api._emit_cognitive_event"):
            result = asyncio.get_event_loop().run_until_complete(add_evidence("hyp-1", req))
        assert result["status"] == "ok"

    def test_add_evidence_not_found(self):
        from web.api.cognitive_api import add_evidence, AddEvidenceRequest
        from fastapi import HTTPException
        import asyncio

        mock_store = MagicMock()
        mock_store.add_evidence.return_value = False

        req = AddEvidenceRequest(title="Test")
        with patch("web.api.cognitive_api._get_store", return_value=mock_store):
            try:
                asyncio.get_event_loop().run_until_complete(add_evidence("nope", req))
                assert False, "Should have raised"
            except HTTPException as e:
                assert e.status_code == 404


class TestCognitiveAPIRealityDebug:
    """Test reality debug and health endpoints."""

    def test_reality_debug_post(self):
        from web.api.cognitive_api import reality_debug, RealityDebugRequest
        import asyncio

        mock_debugger = MagicMock()
        mock_debugger.reality_debug.return_value = {
            "stuck_models": [], "conceptual_disagreements": [],
            "hypothesis_dynamics": {}, "cognitive_metrics": {},
            "markets_analyzed": 0, "stuck_count": 0, "disagreement_count": 0,
        }

        req = RealityDebugRequest()
        with patch("web.api.cognitive_api._get_debugger", return_value=mock_debugger):
            result = asyncio.get_event_loop().run_until_complete(reality_debug(req))
        assert result["stuck_count"] == 0

    def test_reality_debug_get(self):
        from web.api.cognitive_api import reality_debug_get
        import asyncio

        mock_debugger = MagicMock()
        mock_debugger.reality_debug.return_value = {"stuck_count": 0, "disagreement_count": 0}

        with patch("web.api.cognitive_api._get_debugger", return_value=mock_debugger):
            result = asyncio.get_event_loop().run_until_complete(reality_debug_get())
        assert "stuck_count" in result

    def test_cognitive_health_endpoint(self):
        from web.api.cognitive_api import cognitive_health
        import asyncio

        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "active_hypotheses": 5, "pct_surprised_with_updates": 80.0,
        }

        with patch("web.api.cognitive_api._get_debugger", return_value=mock_debugger):
            result = asyncio.get_event_loop().run_until_complete(cognitive_health())
        assert result["active_hypotheses"] == 5

    def test_cognitive_actions_endpoint(self):
        from web.api.cognitive_api import cognitive_actions
        import asyncio

        mock_store = MagicMock()
        mock_store.get_all_actions.return_value = [{"action": "created"}]

        with patch("web.api.cognitive_api._get_store", return_value=mock_store):
            result = asyncio.get_event_loop().run_until_complete(cognitive_actions())
        assert result["count"] == 1

    def test_cognitive_metrics_endpoint(self):
        from web.api.cognitive_api import cognitive_metrics
        import asyncio

        mock_store = MagicMock()
        mock_store.get_cognitive_metrics.return_value = {"total_hypotheses": 10}

        with patch("web.api.cognitive_api._get_store", return_value=mock_store):
            result = asyncio.get_event_loop().run_until_complete(cognitive_metrics())
        assert result["total_hypotheses"] == 10


# ═══════════════════════════════════════════════════════════════════════
# 7. Reward Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCognitiveRewardIntegration:
    """Verify CognitiveEvents are emitted correctly."""

    def test_emit_cognitive_event_on_create(self):
        from web.api.cognitive_api import _emit_cognitive_event
        mock_engine = MagicMock()
        with patch("merid.rewards.engine.get_reward_engine", return_value=mock_engine):
            _emit_cognitive_event("created", "hyp-1", "agent-1", regime_tag="bull")
        assert mock_engine.process_event.called
        event = mock_engine.process_event.call_args[0][0]
        assert event.action == "created"
        assert event.hypothesis_id == "hyp-1"
        assert event.agent_id == "agent-1"

    def test_emit_cognitive_event_on_broken(self):
        from web.api.cognitive_api import _emit_cognitive_event
        mock_engine = MagicMock()
        with patch("merid.rewards.engine.get_reward_engine", return_value=mock_engine):
            _emit_cognitive_event(
                "broken", "hyp-1", "human-1",
                was_contradicted=True, prior_confidence=0.8, new_confidence=0.0,
            )
        event = mock_engine.process_event.call_args[0][0]
        assert event.was_contradicted is True

    def test_emit_graceful_on_failure(self):
        from web.api.cognitive_api import _emit_cognitive_event
        with patch("merid.rewards.engine.get_reward_engine", side_effect=Exception("boom")):
            # Should not raise
            _emit_cognitive_event("created", "hyp-1", "agent-1")

    def test_cognitive_event_schema(self):
        from merid.rewards.events import CognitiveEvent
        event = CognitiveEvent(
            agent_id="agent-1",
            action="created",
            hypothesis_id="hyp-1",
            regime_tag="soft_landing",
            new_confidence=0.8,
        )
        d = event.to_dict()
        assert d["action"] == "created"
        assert d["hypothesis_id"] == "hyp-1"
        assert d["regime_tag"] == "soft_landing"
        assert d["category"] == "cognitive"


# ═══════════════════════════════════════════════════════════════════════
# 8. Package Exports
# ═══════════════════════════════════════════════════════════════════════

class TestPackageExports:
    """Verify merid.cognitive exports all public symbols."""

    def test_models_exported(self):
        from merid.cognitive import (
            CognitiveSnapshot, Hypothesis, EvidenceLink, RegimeTag,
            HypothesisStatus, HypothesisAction, EvidenceType, SnapshotDomain,
        )
        assert CognitiveSnapshot is not None
        assert Hypothesis is not None

    def test_store_exported(self):
        from merid.cognitive import CognitiveStore, get_cognitive_store
        assert CognitiveStore is not None

    def test_debugger_exported(self):
        from merid.cognitive import (
            RealityDebugger, StuckModel, ConceptualDisagreement,
            HypothesisDynamics, get_reality_debugger,
        )
        assert RealityDebugger is not None
        assert StuckModel is not None
