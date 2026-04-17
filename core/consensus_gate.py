"""Stage 6.5: Non-bypassable consensus gate with adversarial hardening authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.adversarial_hardening import get_hardening_layer
from core.agent_trust import get_trust_registry
from core.consensus_math import Vote, compute_consensus
from core.source_health import get_source_registry
from utils.logger import get_logger

logger = get_logger("core.consensus_gate")


@dataclass
class ConsensusResolution:
    """Final consensus resolution with hardening context."""

    consensus_score: float
    confidence: float
    approved: bool
    poisoning_detected: bool
    trust_updates_allowed: bool
    degraded_mode: bool
    temporal_violations: int
    collusion_detected: bool
    shadow_divergence: bool
    metadata: Dict[str, any]


def resolve_consensus(
    votes: List[Vote],
    claims: List[Dict[str, float]],
    threshold: float = 0.6,
) -> ConsensusResolution:
    """
    Stage 6.5: Non-bypassable consensus gate.
    
    All truth flows through this function. No alternate paths.
    
    Flow:
    1. Run temporal consistency checks
    2. Run collusion detection
    3. Run shadow consensus divergence check
    4. Determine poisoning state
    5. If poisoning: freeze trust, fork agents, degrade confidence
    6. Compute final consensus
    7. Record event
    """
    hardening = get_hardening_layer()
    
    # 1. Temporal consistency checks
    temporal_violations = 0
    for claim in claims:
        source = claim.get("source", "unknown")
        metric = claim.get("metric", "value")
        value = claim.get("value", 0.0)
        if hardening.check_temporal_consistency(source, metric, value):
            temporal_violations += 1
    
    # 2. Collusion detection
    for vote in votes:
        # Record delta from mean for collusion analysis
        mean_confidence = sum(v.confidence for v in votes) / len(votes) if votes else 0
        delta = vote.confidence - mean_confidence
        hardening.record_source_delta(vote.source, delta)
    
    collusion_clusters = hardening.detect_collusion_clusters()
    collusion_detected = len(collusion_clusters) > 0
    
    # 3. Shadow consensus divergence check
    primary, shadow, shadow_divergence = hardening.run_shadow_consensus_check(claims)
    
    # 4. Determine poisoning state
    poisoning_detected = (
        temporal_violations >= 2
        or collusion_detected
        or shadow_divergence
    )
    
    # 5. Apply poisoning response
    if poisoning_detected:
        logger.error(
            "POISONING DETECTED: temporal=%d, collusion=%s, shadow_div=%s",
            temporal_violations,
            collusion_detected,
            shadow_divergence,
        )
        # Freeze trust updates
        hardening.trust_updates_frozen = True
        
        # Degrade confidence
        confidence_multiplier = 0.5
        degraded_mode = True
        
        # Use safe consensus (median-based)
        consensus_result = compute_consensus(votes, threshold=threshold)
        consensus_score = shadow  # Use shadow consensus value
        confidence = consensus_result.consensus_score * confidence_multiplier
        approved = consensus_score >= (threshold * 1.2)  # Higher bar during poisoning
        
    else:
        # Normal weighted consensus
        consensus_result = compute_consensus(votes, threshold=threshold)
        consensus_score = consensus_result.consensus_score
        
        # Apply consensus floor check
        source_weights = [v.trust * v.confidence for v in votes]
        floor_multiplier = hardening.check_consensus_floor(source_weights)
        
        confidence = consensus_result.consensus_score * floor_multiplier
        approved = consensus_result.approved
        degraded_mode = floor_multiplier < 1.0
    
    # 6. Record consensus event
    resolution = ConsensusResolution(
        consensus_score=consensus_score,
        confidence=confidence,
        approved=approved,
        poisoning_detected=poisoning_detected,
        trust_updates_allowed=not hardening.trust_updates_frozen,
        degraded_mode=degraded_mode,
        temporal_violations=temporal_violations,
        collusion_detected=collusion_detected,
        shadow_divergence=shadow_divergence,
        metadata={
            "vote_count": len(votes),
            "avg_source_srw": sum(v.source_srw for v in votes) / len(votes) if votes else 0,
            "collusion_clusters": collusion_clusters,
            "primary_consensus": primary,
            "shadow_consensus": shadow,
        },
    )
    
    logger.info(
        "Consensus resolved: score=%.3f, conf=%.3f, approved=%s, poisoning=%s, trust_frozen=%s",
        consensus_score,
        confidence,
        approved,
        poisoning_detected,
        hardening.trust_updates_frozen,
    )
    
    return resolution


def update_agent_trust_gated(
    agent_id: str,
    vote_correct: bool,
    source_srw: float,
) -> bool:
    """
    Stage 6.5: Gated agent trust update with poisoning lock.
    
    Returns True if update was applied, False if blocked.
    """
    hardening = get_hardening_layer()
    
    # HARD STOP: No trust updates during poisoning
    if hardening.trust_updates_frozen:
        logger.debug(
            "Trust update BLOCKED for agent %s (poisoning state active)",
            agent_id,
        )
        return False
    
    # Normal trust update
    trust_registry = get_trust_registry()
    trust_registry.update_trust(agent_id, vote_correct, source_srw)
    return True


def get_source_weight_gated(source: str, base_weight: float = 1.0) -> float:
    """
    Stage 6.5: Gated source weight with quarantine enforcement.
    
    No override. No exception. No temporary use.
    """
    source_health = get_source_registry().get_health(source)
    
    if source_health is None:
        return base_weight
    
    # Check quarantine status (if implemented in future)
    status = getattr(source_health, "status", "active")
    
    if status == "quarantined":
        logger.warning("Source %s is QUARANTINED, weight=0.0", source)
        return 0.0
    
    if status == "degraded":
        logger.debug("Source %s is DEGRADED, weight reduced to 30%%", source)
        return base_weight * 0.3
    
    # Apply SRW-based weight
    return base_weight * source_health.srw


def fork_agents_on_poisoning(reason: str) -> List[str]:
    """
    Stage 6.5: Fork all active agents in response to poisoning detection.
    
    Returns list of new agent IDs created.
    """
    from swarm.agents.instances import AgentInstance
    from swarm.agents.charters import CHARTER_REGISTRY
    import uuid
    
    trust_registry = get_trust_registry()
    forked_ids = []
    
    # Get all active agent profiles
    for agent_id, profile in trust_registry.all_profiles().items():
        # Create forked agent with reset trust
        forked_id = f"{agent_id}_fork_{uuid.uuid4().hex[:8]}"
        
        # Create new trust profile with inherited accuracy but reset trust
        forked_profile = trust_registry._agents.get(forked_id)
        if forked_profile is None:
            from core.agent_trust import AgentTrustProfile
            forked_profile = AgentTrustProfile(
                agent_id=forked_id,
                trust=1.0,  # Reset to default
                total_votes=0,
                correct_votes=0,
                avg_srw_used=profile.avg_srw_used,  # Inherit source quality awareness
            )
            trust_registry._agents[forked_id] = forked_profile
        
        forked_ids.append(forked_id)
        
        logger.info(
            "Forked agent %s → %s (reason=%s, inherited_avg_srw=%.3f)",
            agent_id,
            forked_id,
            reason,
            profile.avg_srw_used,
        )
    
    return forked_ids


def check_rehab_eligibility(source: str, required_clean_cycles: int = 10) -> bool:
    """
    Stage 6.5: Check if a degraded/quarantined source is eligible for rehabilitation.
    
    Trust never snaps back. It regrows.
    """
    from core.adversarial_hardening import get_hardening_layer
    
    hardening = get_hardening_layer()
    source_health = get_source_registry().get_health(source)
    
    if source_health is None:
        return False
    
    # Check if source has status attribute (may not exist in base implementation)
    status = getattr(source_health, "status", "active")
    
    if status == "active":
        return False  # Already active
    
    # Check temporal profile for recent violations
    temporal_key = (source, "default")
    if temporal_key in hardening.temporal_profiles:
        profile = hardening.temporal_profiles[temporal_key]
        if profile.suspicion_counter > 0:
            # Decay suspicion over time
            profile.suspicion_counter = max(0, profile.suspicion_counter - 1)
            if profile.suspicion_counter == 0:
                logger.info("Source %s suspicion counter cleared", source)
    
    # Check if source is in any suspect clusters
    if any(source in cluster for cluster in hardening.agreement_graph.suspect_clusters):
        logger.debug("Source %s still in suspect cluster, rehab denied", source)
        return False
    
    # Check source reliability
    if source_health.srw < 0.6:
        logger.debug("Source %s SRW too low for rehab: %.3f", source, source_health.srw)
        return False
    
    # Gradual restoration: quarantined -> degraded -> active
    if status == "quarantined" and source_health.srw >= 0.7:
        setattr(source_health, "status", "degraded")
        logger.info("Source %s rehabilitated: quarantined → degraded", source)
        return True
    
    if status == "degraded" and source_health.srw >= 0.8:
        setattr(source_health, "status", "active")
        logger.info("Source %s rehabilitated: degraded → active", source)
        return True
    
    return False
