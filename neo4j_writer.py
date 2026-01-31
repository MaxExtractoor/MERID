from neo4j import GraphDatabase

NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "F@tc0ck42069"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def write_decision_to_neo4j(decision: dict) -> None:
    with driver.session() as session:
        session.run(
            """
            MERGE (t:Trial {id: $trial_id})
              ON CREATE SET t.phase = $phase,
                            t.start_date = $start_date,
                            t.end_date = $end_date

            MERGE (m:Model {id: $model_id})

            MERGE (d:Decision {id: $decision_id})
              ON CREATE SET d.timestamp = $timestamp
            SET d.week             = $week,
                d.phase            = $phase,
                d.human_decision   = $human_decision,
                d.metrics_state    = $metrics_state,
                d.alignment_score  = $alignment_score,
                d.compliance_score = $compliance_score

            MERGE (m)-[:MADE_DECISION]->(d)
            MERGE (d)-[:IN_TRIAL]->(t)
            """,
            **decision,
        )


def main() -> None:
    decision = {
        "trial_id": "phase0b-2026-03-07",
        "phase": "0b",
        "start_date": "2026-03-07T00:00:00Z",
        "end_date": "2026-04-04T00:00:00Z",
        "model_id": "crypto_prediction_agent_v1",
        "decision_id": "phase0b-week1-cpa",
        "timestamp": "2026-03-14T12:00:00Z",
        "week": 1,
        "human_decision": "hold",
        "metrics_state": "MISSING",
        "alignment_score": 0.7,
        "compliance_score": 0.95,
    }
    write_decision_to_neo4j(decision)


if __name__ == "__main__":
    main()
