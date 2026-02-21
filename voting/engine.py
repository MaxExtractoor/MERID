def blind_vote(responses_with_agents, threshold=0.75):
    from utils.logger import get_logger
    logger = get_logger("voting.engine")
    
    weighted_total = 0.0
    weight_total = 0.0
    summaries = []
    
    # Diagnostic counters
    vote_counts = {"accept": 0, "reject": 0, "abstain": 0, "invalid": 0}
    low_confidence_count = 0

    for resp, agent in responses_with_agents:
        vote_val = 0
        confidence = 0.0
        trust = getattr(agent, "trust", 1.0)

        if isinstance(resp, dict):
            vote_str = str(resp.get("vote", "")).strip().lower()
            if vote_str in ["accept", "+1", "1"]:
                vote_val = 1
            elif vote_str in ["reject", "-1"]:
                vote_val = -1
            else:
                vote_val = 0
                
            try:
                confidence = float(resp.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

        weighted = vote_val * confidence * trust
        weighted_total += weighted
        weight_total += confidence * trust

        # SAFE STRING CONVERSION FOR EVERY FIELD
        reasoning_raw = resp.get("reasoning") if isinstance(resp, dict) else ""
        reasoning = str(reasoning_raw) if reasoning_raw is not None else ""

        simulation_raw = resp.get("simulation") if isinstance(resp, dict) else ""
        simulation = str(simulation_raw) if simulation_raw is not None else ""

        # Track vote distribution
        vote_str_normalized = str(resp.get("vote", "")).strip().lower()
        if vote_str_normalized in ["accept", "+1", "1"]:
            vote_counts["accept"] += 1
        elif vote_str_normalized in ["reject", "-1"]:
            vote_counts["reject"] += 1
        elif vote_str_normalized in ["abstain", "0", "hold"]:
            vote_counts["abstain"] += 1
        else:
            vote_counts["invalid"] += 1
        
        if confidence < 0.3:
            low_confidence_count += 1
        
        summaries.append({
            "agent": agent.agent_id,
            "vote": vote_val,
            "confidence": confidence,
            "trust": trust,
            "weighted": weighted,
            "reasoning": reasoning[:200] + ("..." if len(reasoning) > 200 else ""),
            "simulation": simulation[:150] + ("..." if len(simulation) > 150 else "")
        })

    consensus = weighted_total / weight_total if weight_total > 0 else 0
    approved = consensus >= 0.75
    
    # DIAGNOSTIC LOGGING
    logger.info(
        "Consensus calculated: %.3f (threshold=%.2f) | Votes: %d accept, %d reject, %d abstain, %d invalid | "
        "Low confidence: %d/%d agents | weighted_total=%.3f, weight_total=%.3f",
        consensus, threshold,
        vote_counts["accept"], vote_counts["reject"], vote_counts["abstain"], vote_counts["invalid"],
        low_confidence_count, len(summaries),
        weighted_total, weight_total
    )
    
    # Log individual agent decisions for debugging
    if consensus == 0.0 or vote_counts["abstain"] == len(summaries):
        logger.warning(
            "🚨 ALL AGENTS ABSTAINING - Likely Ollama connection issue or stub mode active"
        )
        for s in summaries:
            logger.debug(
                "  Agent %s: vote=%s, confidence=%.2f, simulation=%s",
                s["agent"], s["vote"], s["confidence"], s["simulation"][:80]
            )

    return {
        "consensus": consensus,
        "approved": approved,
        "summaries": summaries
    }
