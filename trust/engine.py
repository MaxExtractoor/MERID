from db.neo4j import update_trust  # Assume helper

def evolve_trust(agent_id, accuracy, expected=0.8):
    old_trust = 1.0  # Fetch from Neo4j
    new_trust = min(max(old_trust * (accuracy / expected), 0.5), 2.0)
    update_trust(agent_id, new_trust)
    return new_trust
