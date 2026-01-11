def blind_vote(responses_with_agents, threshold=0.75):
    weighted_total = 0.0
    weight_total = 0.0
    summaries = []

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

    return {
        "consensus": consensus,
        "approved": approved,
        "summaries": summaries
    }
