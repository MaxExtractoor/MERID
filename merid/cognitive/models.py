"""Cognitive Layer data models — structured hypotheses, evidence, and snapshots.

Core objects:
  Hypothesis        — a tagged belief about a market/domain regime
  EvidenceLink      — reference to signal, opinion, debate, or external data
  RegimeTag         — structured label for narrative classification
  CognitiveSnapshot — point-in-time set of hypotheses for a market/domain
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────

class HypothesisStatus(str, Enum):
    """Lifecycle status of a hypothesis."""
    ACTIVE = "active"
    BROKEN = "broken"        # reality contradicted it
    RETIRED = "retired"      # superseded or no longer relevant
    CONFIRMED = "confirmed"  # outcome validated it


class HypothesisAction(str, Enum):
    """Actions that can be taken on a hypothesis."""
    CREATED = "created"
    UPDATED = "updated"
    BROKEN = "broken"
    RETIRED = "retired"
    CONFIRMED = "confirmed"
    CONFIDENCE_ADJUSTED = "confidence_adjusted"
    EVIDENCE_ADDED = "evidence_added"
    REGIME_TAG_CHANGED = "regime_tag_changed"


class EvidenceType(str, Enum):
    """Type of evidence supporting or contradicting a hypothesis."""
    SIGNAL = "signal"            # from signal layer metrics
    OPINION = "opinion"          # from prediction opinion
    DEBATE_ARGUMENT = "debate_argument"  # from debate session
    MARKET_OUTCOME = "market_outcome"    # resolved market
    EXTERNAL_DATA = "external_data"      # article, memo, domain knowledge
    PRICE_ACTION = "price_action"        # observed price movement
    SYSTEM_METRIC = "system_metric"      # SLO, latency, error rate


class SnapshotDomain(str, Enum):
    """Domain a cognitive snapshot applies to."""
    MARKET = "market"        # prediction/betting market
    MACRO = "macro"          # macro regime (Fed, inflation, etc.)
    CRYPTO = "crypto"        # crypto-specific narrative
    INFRA = "infra"          # system/infrastructure hypothesis
    DEV = "dev"              # dev swarm hypothesis


# ── RegimeTag ─────────────────────────────────────────────────────────

@dataclass
class RegimeTag:
    """A structured label classifying the narrative/regime.

    Examples:
      RegimeTag("macro/regime", "soft_landing", "Fed achieves soft landing")
      RegimeTag("policy", "fed_tightening", "Fed continues rate hikes")
      RegimeTag("micro/idiosyncratic", "earnings_miss", "Company missed Q4")
    """
    category: str = ""       # macro/regime, policy, micro/idiosyncratic, crypto/narrative, infra/incident
    label: str = ""          # machine-readable tag (e.g. "soft_landing", "liquidity_crunch")
    description: str = ""    # human-readable explanation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RegimeTag:
        return cls(
            category=d.get("category", ""),
            label=d.get("label", ""),
            description=d.get("description", ""),
        )


# ── EvidenceLink ──────────────────────────────────────────────────────

@dataclass
class EvidenceLink:
    """A reference to data that supports or contradicts a hypothesis."""
    id: str = field(default_factory=lambda: f"ev-{uuid.uuid4().hex[:12]}")
    evidence_type: str = EvidenceType.EXTERNAL_DATA.value
    reference_id: str = ""       # ID of the referenced object (opinion_id, debate_id, etc.)
    title: str = ""              # human-readable title
    url: str = ""                # optional URL for external evidence
    supports: bool = True        # True = supports hypothesis, False = contradicts
    strength: float = 0.5        # 0–1 how strongly this evidence affects confidence
    added_by: str = ""           # agent_id or user_id who added this
    added_at: float = field(default_factory=time.time)
    notes: str = ""              # free-text annotation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "evidence_type": self.evidence_type,
            "reference_id": self.reference_id,
            "title": self.title,
            "url": self.url,
            "supports": self.supports,
            "strength": round(self.strength, 3),
            "added_by": self.added_by,
            "added_at": self.added_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> EvidenceLink:
        return cls(
            id=d.get("id", f"ev-{uuid.uuid4().hex[:12]}"),
            evidence_type=d.get("evidence_type", EvidenceType.EXTERNAL_DATA.value),
            reference_id=d.get("reference_id", ""),
            title=d.get("title", ""),
            url=d.get("url", ""),
            supports=d.get("supports", True),
            strength=d.get("strength", 0.5),
            added_by=d.get("added_by", ""),
            added_at=d.get("added_at", time.time()),
            notes=d.get("notes", ""),
        )


# ── Hypothesis ────────────────────────────────────────────────────────

@dataclass
class Hypothesis:
    """A tagged belief about a market, regime, or domain.

    Hypotheses are the core cognitive objects — they represent the "story"
    an agent or human is implicitly assuming.  They have:
      - A regime tag (what kind of narrative)
      - Confidence (0–1)
      - Evidence links (what supports/contradicts)
      - Status lifecycle (active → broken/retired/confirmed)
    """
    id: str = field(default_factory=lambda: f"hyp-{uuid.uuid4().hex[:12]}")
    text: str = ""                   # human-readable hypothesis statement
    regime_tag: RegimeTag = field(default_factory=RegimeTag)
    confidence: float = 0.5          # 0–1
    status: str = HypothesisStatus.ACTIVE.value
    owner: str = ""                  # agent_id or user_id
    evidence_links: List[EvidenceLink] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    broken_at: Optional[float] = None
    broken_reason: str = ""          # why it was marked broken
    prior_confidence: Optional[float] = None  # confidence before last update

    @property
    def is_active(self) -> bool:
        return self.status == HypothesisStatus.ACTIVE.value

    @property
    def supporting_evidence_count(self) -> int:
        return sum(1 for e in self.evidence_links if e.supports)

    @property
    def contradicting_evidence_count(self) -> int:
        return sum(1 for e in self.evidence_links if not e.supports)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "regime_tag": self.regime_tag.to_dict(),
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "owner": self.owner,
            "evidence_links": [e.to_dict() for e in self.evidence_links],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "broken_at": self.broken_at,
            "broken_reason": self.broken_reason,
            "prior_confidence": self.prior_confidence,
            "supporting_evidence": self.supporting_evidence_count,
            "contradicting_evidence": self.contradicting_evidence_count,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Hypothesis:
        tag_data = d.get("regime_tag", {})
        evidence_data = d.get("evidence_links", [])
        return cls(
            id=d.get("id", f"hyp-{uuid.uuid4().hex[:12]}"),
            text=d.get("text", ""),
            regime_tag=RegimeTag.from_dict(tag_data) if isinstance(tag_data, dict) else RegimeTag(),
            confidence=d.get("confidence", 0.5),
            status=d.get("status", HypothesisStatus.ACTIVE.value),
            owner=d.get("owner", ""),
            evidence_links=[EvidenceLink.from_dict(e) for e in evidence_data],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            broken_at=d.get("broken_at"),
            broken_reason=d.get("broken_reason", ""),
            prior_confidence=d.get("prior_confidence"),
        )


# ── CognitiveSnapshot ────────────────────────────────────────────────

@dataclass
class CognitiveSnapshot:
    """Point-in-time set of hypotheses about a market or domain.

    This is the core cognitive object that gets attached to:
      - Instruments (what story are we assuming for this market?)
      - Opinions (this forecast assumes hypotheses H1, H2)
      - Debate sessions (proposer and challenger have different hypotheses)

    Snapshots form a history per market, so you can see how hypotheses
    evolve as data arrives.
    """
    id: str = field(default_factory=lambda: f"snap-{uuid.uuid4().hex[:12]}")
    market_id: str = ""              # instrument symbol or domain identifier
    domain: str = SnapshotDomain.MARKET.value
    hypotheses: List[Hypothesis] = field(default_factory=list)
    overall_regime_confidence: float = 0.5  # aggregate confidence in current regime
    owner: str = ""                  # agent_id or user_id who created this snapshot
    opinion_id: str = ""             # linked opinion (if attached to a forecast)
    debate_id: str = ""              # linked debate session (if attached to a debate)
    notes: str = ""                  # free-text context
    created_at: float = field(default_factory=time.time)

    @property
    def active_hypotheses(self) -> List[Hypothesis]:
        return [h for h in self.hypotheses if h.is_active]

    @property
    def broken_hypotheses(self) -> List[Hypothesis]:
        return [h for h in self.hypotheses if h.status == HypothesisStatus.BROKEN.value]

    @property
    def hypothesis_count(self) -> int:
        return len(self.hypotheses)

    @property
    def active_count(self) -> int:
        return len(self.active_hypotheses)

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        for h in self.hypotheses:
            if h.id == hypothesis_id:
                return h
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "market_id": self.market_id,
            "domain": self.domain,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "overall_regime_confidence": round(self.overall_regime_confidence, 4),
            "owner": self.owner,
            "opinion_id": self.opinion_id,
            "debate_id": self.debate_id,
            "notes": self.notes,
            "created_at": self.created_at,
            "hypothesis_count": self.hypothesis_count,
            "active_count": self.active_count,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CognitiveSnapshot:
        hyp_data = d.get("hypotheses", [])
        return cls(
            id=d.get("id", f"snap-{uuid.uuid4().hex[:12]}"),
            market_id=d.get("market_id", ""),
            domain=d.get("domain", SnapshotDomain.MARKET.value),
            hypotheses=[Hypothesis.from_dict(h) for h in hyp_data],
            overall_regime_confidence=d.get("overall_regime_confidence", 0.5),
            owner=d.get("owner", ""),
            opinion_id=d.get("opinion_id", ""),
            debate_id=d.get("debate_id", ""),
            notes=d.get("notes", ""),
            created_at=d.get("created_at", time.time()),
        )
