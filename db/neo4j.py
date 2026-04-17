import logging as _stdlib_logging

try:
    from neo4j import GraphDatabase
    # Silence neo4j driver's internal retry/connection noise — MERID handles
    # unavailability gracefully and logs it through its own logger.
    _stdlib_logging.getLogger("neo4j").setLevel(_stdlib_logging.CRITICAL)
    _stdlib_logging.getLogger("neo4j.io").setLevel(_stdlib_logging.CRITICAL)
except ImportError:
    GraphDatabase = None  # type: ignore[assignment,misc]

from core.env import capabilities
from utils.logger import get_logger as _get_logger
import uuid
from datetime import datetime

_log = _get_logger(__name__)


class Neo4jMemory:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            capabilities.neo4j_uri,
            auth=(capabilities.neo4j_user, capabilities.neo4j_password),
            connection_timeout=2,
            max_transaction_retry_time=0,
            max_connection_pool_size=5,
            connection_acquisition_timeout=2,
        )
        self._create_constraints()

    def close(self):
        self.driver.close()

    # -------------------------
    # Schema / Constraints
    # -------------------------
    def _create_constraints(self):
        with self.driver.session() as session:
            session.execute_write(self._constraints_tx)

    @staticmethod
    def _constraints_tx(tx):
        tx.run(
            "CREATE CONSTRAINT energy_id IF NOT EXISTS "
            "FOR (e:Energy) REQUIRE e.id IS UNIQUE"
        )
        tx.run(
            "CREATE CONSTRAINT reality_id IF NOT EXISTS "
            "FOR (r:Reality) REQUIRE r.id IS UNIQUE"
        )
        tx.run(
            "CREATE CONSTRAINT agent_id IF NOT EXISTS "
            "FOR (a:Agent) REQUIRE a.id IS UNIQUE"
        )

    # -------------------------
    # Energy Logging
    # -------------------------
    def log_energy(self, energy: dict):
        with self.driver.session() as session:
            session.execute_write(self._log_energy_tx, energy)

    @staticmethod
    def _log_energy_tx(tx, energy):
        tx.run(
            """
            CREATE (e:Energy {
                id: $id,
                source: $source,
                payload: $payload,
                timestamp: $timestamp,
                status: 'pending'
            })
            """,
            {
                "id": energy["energy_id"],
                "source": energy["source"],
                "payload": energy["payload"],
                "timestamp": energy["timestamp"]["utc_iso"],
            },
        )

    # -------------------------
    # Voting
    # -------------------------
    def log_votes(self, energy_id: str, votes: list):
        with self.driver.session() as session:
            for vote in votes:
                session.execute_write(self._log_vote_tx, energy_id, vote)

    @staticmethod
    def _log_vote_tx(tx, energy_id, vote):
        tx.run(
            """
            MATCH (e:Energy {id: $energy_id})
            MERGE (a:Agent {id: $agent_id})
            CREATE (a)-[:VOTED {
                vote: $vote,
                confidence: $confidence,
                reasoning: $reasoning
            }]->(e)
            """,
            {
                "energy_id": energy_id,
                "agent_id": vote["agent_id"],
                "vote": vote["vote"],
                "confidence": vote["confidence"],
                "reasoning": vote.get("reasoning", ""),
            },
        )

    # -------------------------
    # Reality Resolution
    # -------------------------
    def log_reality(self, energy_id: str, result: dict, votes: list):
        reality_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        with self.driver.session() as session:
            session.execute_write(
                self._log_reality_tx,
                energy_id,
                reality_id,
                result,
                timestamp,
            )

        self.evolve_trust(votes, result["approved"])

    @staticmethod
    def _log_reality_tx(tx, energy_id, reality_id, result, timestamp):
        tx.run(
            """
            MATCH (e:Energy {id: $energy_id})
            SET e.status = 'reality'
            CREATE (r:Reality {
                id: $reality_id,
                consensus: $consensus,
                approved: $approved,
                timestamp: $timestamp
            })
            CREATE (e)-[:BECAME]->(r)
            """,
            {
                "energy_id": energy_id,
                "reality_id": reality_id,
                "consensus": result["consensus"],
                "approved": result["approved"],
                "timestamp": timestamp,
            },
        )

    # -------------------------
    # Trust Evolution
    # -------------------------
    def evolve_trust(self, votes: list, approved: bool):
        with self.driver.session() as session:
            for vote in votes:
                correct = (
                    (vote["vote"] == "accept" and approved)
                    or (vote["vote"] == "reject" and not approved)
                )
                adjustment = 1.1 if correct else 0.9
                session.execute_write(
                    self._trust_update_tx,
                    vote["agent_id"],
                    adjustment,
                )

    @staticmethod
    def _trust_update_tx(tx, agent_id, adjustment):
        tx.run(
            """
            MERGE (a:Agent {id: $agent_id})
            SET a.trust = COALESCE(a.trust, 1.0) * $adjustment
            SET a.trust =
                CASE
                    WHEN a.trust > 2.0 THEN 2.0
                    WHEN a.trust < 0.5 THEN 0.5
                    ELSE a.trust
                END
            """,
            {
                "agent_id": agent_id,
                "adjustment": adjustment,
            },
        )

    # -------------------------
    # History Query
    # -------------------------
    def get_history(self, limit: int = 20):
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Energy)-[:BECAME]->(r:Reality)
                OPTIONAL MATCH (a:Agent)-[v:VOTED]->(e)
                WITH e, r, collect({
                    agent: a.id,
                    vote: v.vote,
                    confidence: v.confidence
                }) AS votes
                RETURN
                    e.id AS energy_id,
                    e.payload AS payload,
                    e.timestamp AS timestamp,
                    r.consensus AS consensus,
                    r.approved AS approved,
                    votes
                ORDER BY r.timestamp DESC
                LIMIT $limit
                """,
                {"limit": limit},
            )
            return [record.data() for record in result]


# Instantiate once at startup — graceful fallback if Neo4j is unavailable
try:
    memory = Neo4jMemory()
except Exception as _neo4j_err:
    _log.warning("Neo4j unavailable — running without graph memory: %s", _neo4j_err)
    memory = None
