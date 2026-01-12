"""
Neo4j Graph Database Service for MERID

Provides graph database integration for:
- Trade proposal lineage tracking
- Execution and position management
- Risk exposure queries
- Incident and circuit breaker tracking
- Agent decision provenance

Follows Neo4j driver best practices for production:
- Single driver instance
- Explicit session management
- Parameterized queries
- Secure connections (neo4j+s://)
"""

from neo4j import GraphDatabase
from typing import Dict, List, Optional, Any
import logging
from dataclasses import asdict
import time

logger = logging.getLogger(__name__)


# Initialization Cypher for setting default properties on existing nodes
INIT_CYPHER = """
// Wallets
MATCH (w:Wallet)
SET w.tier = coalesce(w.tier, 'HOT'),
    w.time_lock_hours = coalesce(w.time_lock_hours, 0);

// Positions
MATCH (pos:Position)
SET pos.net_size_usd    = coalesce(pos.net_size_usd, 0.0),
    pos.avg_entry_price = coalesce(pos.avg_entry_price, 0.0),
    pos.pnl_percent     = coalesce(pos.pnl_percent, 0.0),
    pos.updated_at      = coalesce(pos.updated_at, datetime());

// Incidents
MATCH (inc:Incident)
SET inc.status     = coalesce(inc.status, 'OPEN'),
    inc.severity   = coalesce(inc.severity, 'MEDIUM'),
    inc.created_at = coalesce(inc.created_at, datetime()),
    inc.category   = coalesce(inc.category, 'GENERAL');

// Threats
MATCH (t:Threat)
SET t.severity = coalesce(t.severity, 'MEDIUM'),
    t.category = coalesce(t.category, 'GENERAL');

// Proposals
MATCH (p:TradeProposal)
SET p.state      = coalesce(p.state, 'CREATED'),
    p.created_at = coalesce(p.created_at, datetime());

// Orders
MATCH (o:Order)
SET o.status     = coalesce(o.status, 'PENDING'),
    o.created_at = coalesce(o.created_at, datetime());

// Agents
MATCH (ag:Agent)
SET ag.created_at = coalesce(ag.created_at, datetime());

// Venues
MATCH (v:Venue)
SET v.created_at = coalesce(v.created_at, datetime());

// Assets
MATCH (a:Asset)
SET a.created_at = coalesce(a.created_at, datetime());
"""


class GraphService:
    """
    Neo4j graph database service for MERID.
    
    CRITICAL: This service provides the graph backbone for:
    - Complete trade lineage (proposal → order → execution → position)
    - Risk exposure tracking across wallets/venues/assets
    - Incident and circuit breaker relationships
    - Agent decision provenance
    
    All writes are ACID-compliant and immediately queryable.
    """
    
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j"
    ):
        """
        Initialize Neo4j driver with secure connection.
        
        Args:
            uri: Neo4j connection URI (use neo4j+s:// for secure)
            user: Database username
            password: Database password
            database: Database name (default: neo4j)
        """
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        
        # Verify connection
        self._verify_connection()
        
        # Initialize schema
        self._initialize_schema()
        
        logger.info(f"GraphService initialized: {uri}, database: {database}")
    
    def close(self):
        """Close driver connection."""
        if self.driver:
            self.driver.close()
            logger.info("GraphService connection closed")
    
    def _verify_connection(self) -> None:
        """Verify Neo4j connection is working."""
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run("RETURN 1 AS num")
                record = result.single()
                if record["num"] != 1:
                    raise ConnectionError("Neo4j connection test failed")
            logger.info("Neo4j connection verified")
        except Exception as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise
    
    def _initialize_schema(self) -> None:
        """
        Initialize Neo4j schema with indexes and constraints.
        
        Creates indexes on frequently queried properties for performance.
        """
        schema_queries = [
            # Unique constraints
            "CREATE CONSTRAINT proposal_id_unique IF NOT EXISTS FOR (p:TradeProposal) REQUIRE p.proposal_id IS UNIQUE",
            "CREATE CONSTRAINT order_id_unique IF NOT EXISTS FOR (o:Order) REQUIRE o.order_id IS UNIQUE",
            "CREATE CONSTRAINT execution_id_unique IF NOT EXISTS FOR (e:Execution) REQUIRE e.execution_id IS UNIQUE",
            "CREATE CONSTRAINT position_id_unique IF NOT EXISTS FOR (pos:Position) REQUIRE pos.position_id IS UNIQUE",
            "CREATE CONSTRAINT wallet_id_unique IF NOT EXISTS FOR (w:Wallet) REQUIRE w.wallet_id IS UNIQUE",
            "CREATE CONSTRAINT venue_id_unique IF NOT EXISTS FOR (v:Venue) REQUIRE v.venue_id IS UNIQUE",
            "CREATE CONSTRAINT asset_id_unique IF NOT EXISTS FOR (a:Asset) REQUIRE a.asset_id IS UNIQUE",
            "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (ag:Agent) REQUIRE ag.agent_id IS UNIQUE",
            "CREATE CONSTRAINT assertion_id_unique IF NOT EXISTS FOR (as:Assertion) REQUIRE as.assertion_id IS UNIQUE",
            "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (inc:Incident) REQUIRE inc.incident_id IS UNIQUE",
            
            # Indexes for performance
            "CREATE INDEX proposal_state_idx IF NOT EXISTS FOR (p:TradeProposal) ON (p.state)",
            "CREATE INDEX proposal_created_idx IF NOT EXISTS FOR (p:TradeProposal) ON (p.created_at)",
            "CREATE INDEX order_status_idx IF NOT EXISTS FOR (o:Order) ON (o.status)",
            "CREATE INDEX position_updated_idx IF NOT EXISTS FOR (pos:Position) ON (pos.updated_at)",
            "CREATE INDEX incident_status_idx IF NOT EXISTS FOR (inc:Incident) ON (inc.status)",
            "CREATE INDEX assertion_status_idx IF NOT EXISTS FOR (as:Assertion) ON (as.status)",
        ]
        
        for query in schema_queries:
            try:
                self._run(query)
            except Exception as e:
                # Constraint/index may already exist
                logger.debug(f"Schema query skipped (may exist): {e}")
    
    def _run(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute Cypher query with parameters.
        
        Args:
            query: Cypher query string
            params: Query parameters (prevents injection)
        
        Returns:
            List of result records as dictionaries
        """
        with self.driver.session(database=self.database) as session:
            try:
                result = session.execute_write(
                    lambda tx: list(tx.run(query, params or {}))
                )
                return [dict(record) for record in result]
            except Exception as e:
                logger.error(f"Query failed: {query[:100]}... Error: {e}")
                raise
    
    def run_init(self) -> None:
        """
        Run initialization Cypher to set default properties on existing nodes.
        
        This ensures all nodes have required properties with sensible defaults.
        Safe to run multiple times (uses coalesce to only set if null).
        
        Call this after connecting to an existing database or after schema changes.
        """
        try:
            with self.driver.session(database=self.database) as session:
                session.execute_write(lambda tx: tx.run(INIT_CYPHER))
            logger.info("Graph initialization complete: default properties set on all nodes")
        except Exception as e:
            logger.error(f"Graph initialization failed: {e}")
            raise
    
    # =========================================================================
    # WRITE METHODS - Trade Proposal Lifecycle
    # =========================================================================
    
    def record_proposal(
        self,
        proposal: Dict[str, Any],
        assertions: List[Dict[str, Any]],
        agent_id: str
    ) -> None:
        """
        Record trade proposal with assertions and agent linkage.
        
        Creates:
        - TradeProposal node
        - Assertion nodes
        - Agent → CREATED → TradeProposal
        - TradeProposal → ASSERTED_BY → Assertion
        
        Args:
            proposal: Proposal data (proposal_id, state, side, asset_id, etc.)
            assertions: List of assertion data (assertion_id, domain, status, etc.)
            agent_id: ID of agent that created proposal
        """
        query = """
        MERGE (p:TradeProposal {proposal_id: $proposal_id})
          ON CREATE SET p.created_at = datetime()
        SET p.state            = $state,
            p.side             = $side,
            p.asset_id         = $asset_id,
            p.venue_id         = $venue_id,
            p.size_usd         = $size_usd,
            p.leverage         = $leverage,
            p.stop_loss_pct    = $stop_loss_pct,
            p.take_profit_pct  = $take_profit_pct,
            p.strategy         = $strategy,
            p.confidence       = $confidence,
            p.updated_at       = datetime()
        
        WITH p
        MERGE (ag:Agent {agent_id: $agent_id})
          ON CREATE SET ag.created_at = datetime()
        MERGE (ag)-[:CREATED]->(p)
        
        WITH p
        UNWIND $assertions AS a_map
        MERGE (as:Assertion {assertion_id: a_map.assertion_id})
          ON CREATE SET as.created_at = datetime()
        SET as.domain       = a_map.domain,
            as.status       = a_map.status,
            as.confidence   = a_map.confidence,
            as.decay_factor = a_map.decay_factor,
            as.expires_at   = datetime(a_map.expires_at),
            as.updated_at   = datetime()
        MERGE (p)-[:ASSERTED_BY]->(as)
        """
        
        params = {
            "proposal_id": proposal["proposal_id"],
            "state": proposal["state"],
            "side": proposal["side"],
            "asset_id": proposal["asset_id"],
            "venue_id": proposal["venue_id"],
            "size_usd": proposal["size_usd"],
            "leverage": proposal.get("leverage", 1.0),
            "stop_loss_pct": proposal.get("stop_loss_pct"),
            "take_profit_pct": proposal.get("take_profit_pct"),
            "strategy": proposal.get("strategy", "unknown"),
            "confidence": proposal.get("confidence", 0.0),
            "agent_id": agent_id,
            "assertions": assertions,
        }
        
        self._run(query, params)
        logger.info(f"Recorded proposal {proposal['proposal_id']} with {len(assertions)} assertions")
    
    def record_proposal_state_change(
        self,
        proposal_id: str,
        from_state: str,
        to_state: str,
        event_id: str,
        reason: str,
        updated_by: str
    ) -> None:
        """
        Record proposal state transition with event.
        
        Creates:
        - Event node
        - Event → TARGET → TradeProposal
        - Updates TradeProposal.state
        
        Args:
            proposal_id: Proposal ID
            from_state: Previous state
            to_state: New state
            event_id: Unique event ID
            reason: Reason for transition
            updated_by: Who/what triggered transition
        """
        query = """
        MATCH (p:TradeProposal {proposal_id: $proposal_id})
        SET p.state = $to_state,
            p.updated_at = datetime()
        
        MERGE (ev:Event {event_id: $event_id})
        SET ev.type       = 'PROPOSAL_STATE_CHANGE',
            ev.from_state = $from_state,
            ev.to_state   = $to_state,
            ev.reason     = $reason,
            ev.updated_by = $updated_by,
            ev.at         = datetime()
        
        MERGE (ev)-[:TARGET]->(p)
        """
        
        params = {
            "proposal_id": proposal_id,
            "from_state": from_state,
            "to_state": to_state,
            "event_id": event_id,
            "reason": reason,
            "updated_by": updated_by,
        }
        
        self._run(query, params)
        logger.info(f"Recorded state change for {proposal_id}: {from_state} → {to_state}")
    
    def record_execution(
        self,
        proposal_id: str,
        wallet_id: str,
        venue_id: str,
        asset_id: str,
        order: Dict[str, Any],
        execution: Dict[str, Any],
        position_id: str
    ) -> None:
        """
        Record order execution and update position.
        
        Creates/Updates:
        - Order node
        - Execution node
        - Position node
        - Relationships: Proposal → Order → Execution
        - Relationships: Wallet → Order, Wallet → Position
        - Relationships: Order/Position → Venue/Asset
        
        Args:
            proposal_id: Source proposal ID
            wallet_id: Wallet that placed order
            venue_id: Venue where order executed
            asset_id: Asset traded
            order: Order data (order_id, side, size_usd, status)
            execution: Execution data (execution_id, size_usd, price, fees)
            position_id: Position ID to update
        """
        query = """
        MATCH (p:TradeProposal {proposal_id: $proposal_id})
        MERGE (w:Wallet {wallet_id: $wallet_id})
          ON CREATE SET w.created_at = datetime()
        MERGE (v:Venue {venue_id: $venue_id})
          ON CREATE SET v.created_at = datetime()
        MERGE (a:Asset {asset_id: $asset_id})
          ON CREATE SET a.created_at = datetime()
        
        MERGE (o:Order {order_id: $order_id})
          ON CREATE SET o.created_at = datetime()
        SET o.side      = $side,
            o.size_usd  = $order_size_usd,
            o.status    = $order_status,
            o.updated_at = datetime()
        
        MERGE (p)-[:EXECUTED_AS]->(o)
        MERGE (w)-[:PLACED_ORDER]->(o)
        MERGE (o)-[:ON_VENUE]->(v)
        MERGE (o)-[:ON_ASSET]->(a)
        
        MERGE (e:Execution {execution_id: $execution_id})
          ON CREATE SET e.timestamp = datetime()
        SET e.size_usd = $exec_size_usd,
            e.price    = $exec_price,
            e.fees_usd = $exec_fees_usd,
            e.slippage_bps = $exec_slippage_bps
        
        MERGE (o)-[:FILLED_AS]->(e)
        
        MERGE (pos:Position {position_id: $position_id})
          ON CREATE SET pos.created_at = datetime(),
                        pos.net_size_usd = 0
        SET pos.net_size_usd   = pos.net_size_usd + $exec_size_usd_signed,
            pos.avg_entry_price = $exec_price,
            pos.updated_at      = datetime()
        MERGE (w)-[:OWNS_POSITION]->(pos)
        MERGE (pos)-[:ON_ASSET]->(a)
        MERGE (pos)-[:ON_VENUE]->(v)
        """
        
        # Calculate signed size for position update
        exec_size_signed = execution["size_usd"]
        if order["side"] == "SELL":
            exec_size_signed = -exec_size_signed
        
        params = {
            "proposal_id": proposal_id,
            "wallet_id": wallet_id,
            "venue_id": venue_id,
            "asset_id": asset_id,
            "order_id": order["order_id"],
            "side": order["side"],
            "order_size_usd": order["size_usd"],
            "order_status": order.get("status", "FILLED"),
            "execution_id": execution["execution_id"],
            "exec_size_usd": execution["size_usd"],
            "exec_size_usd_signed": exec_size_signed,
            "exec_price": execution["price"],
            "exec_fees_usd": execution.get("fees_usd", 0.0),
            "exec_slippage_bps": execution.get("slippage_bps", 0.0),
            "position_id": position_id,
        }
        
        self._run(query, params)
        logger.info(f"Recorded execution {execution['execution_id']} for order {order['order_id']}")
    
    def record_risk_violation(
        self,
        proposal_id: str,
        violation_id: str,
        violation_type: str,
        severity: str,
        limit: float,
        actual: float,
        message: str
    ) -> None:
        """
        Record risk limit violation.
        
        Creates:
        - RiskViolation node
        - RiskViolation → BLOCKED → TradeProposal
        
        Args:
            proposal_id: Proposal that violated limits
            violation_id: Unique violation ID
            violation_type: Type of violation (e.g., "POSITION_SIZE")
            severity: Severity level
            limit: Limit that was exceeded
            actual: Actual value
            message: Human-readable message
        """
        query = """
        MATCH (p:TradeProposal {proposal_id: $proposal_id})
        
        MERGE (rv:RiskViolation {violation_id: $violation_id})
        SET rv.type     = $violation_type,
            rv.severity = $severity,
            rv.limit    = $limit,
            rv.actual   = $actual,
            rv.message  = $message,
            rv.at       = datetime()
        
        MERGE (rv)-[:BLOCKED]->(p)
        """
        
        params = {
            "proposal_id": proposal_id,
            "violation_id": violation_id,
            "violation_type": violation_type,
            "severity": severity,
            "limit": limit,
            "actual": actual,
            "message": message,
        }
        
        self._run(query, params)
        logger.info(f"Recorded risk violation {violation_id} for proposal {proposal_id}")
    
    def record_incident(
        self,
        incident_id: str,
        incident_type: str,
        severity: str,
        description: str,
        wallet_id: Optional[str] = None,
        venue_id: Optional[str] = None,
        threat_id: Optional[str] = None
    ) -> None:
        """
        Record security/operational incident.
        
        Creates:
        - Incident node
        - Relationships to involved entities
        
        Args:
            incident_id: Unique incident ID
            incident_type: Type of incident
            severity: Severity level
            description: Description
            wallet_id: Optional wallet involved
            venue_id: Optional venue involved
            threat_id: Optional threat ID
        """
        query = """
        MERGE (inc:Incident {incident_id: $incident_id})
        SET inc.type        = $incident_type,
            inc.severity    = $severity,
            inc.description = $description,
            inc.status      = 'OPEN',
            inc.created_at  = datetime()
        
        WITH inc
        OPTIONAL MATCH (w:Wallet {wallet_id: $wallet_id})
        FOREACH (_ IN CASE WHEN w IS NOT NULL THEN [1] ELSE [] END |
            MERGE (inc)-[:INVOLVES]->(w)
        )
        
        WITH inc
        OPTIONAL MATCH (v:Venue {venue_id: $venue_id})
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (inc)-[:INVOLVES]->(v)
        )
        
        WITH inc
        OPTIONAL MATCH (t:Threat {threat_id: $threat_id})
        FOREACH (_ IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
            MERGE (inc)-[:RELATED_TO]->(t)
        )
        """
        
        params = {
            "incident_id": incident_id,
            "incident_type": incident_type,
            "severity": severity,
            "description": description,
            "wallet_id": wallet_id,
            "venue_id": venue_id,
            "threat_id": threat_id,
        }
        
        self._run(query, params)
        logger.info(f"Recorded incident {incident_id}: {incident_type}")
    
    def record_circuit_breaker(
        self,
        breaker_id: str,
        breaker_type: str,
        threshold: float,
        actual_value: float,
        action: str,
        incident_id: Optional[str] = None
    ) -> None:
        """
        Record circuit breaker trigger.
        
        Creates:
        - CircuitBreakerEvent node
        - Optional link to incident
        
        Args:
            breaker_id: Unique breaker event ID
            breaker_type: Type of breaker
            threshold: Threshold that was exceeded
            actual_value: Actual value
            action: Action taken
            incident_id: Optional related incident
        """
        query = """
        MERGE (cb:CircuitBreakerEvent {breaker_id: $breaker_id})
        SET cb.type         = $breaker_type,
            cb.threshold    = $threshold,
            cb.actual_value = $actual_value,
            cb.action       = $action,
            cb.triggered_at = datetime()
        
        WITH cb
        OPTIONAL MATCH (inc:Incident {incident_id: $incident_id})
        FOREACH (_ IN CASE WHEN inc IS NOT NULL THEN [1] ELSE [] END |
            MERGE (cb)-[:TRIGGERED_BY]->(inc)
        )
        """
        
        params = {
            "breaker_id": breaker_id,
            "breaker_type": breaker_type,
            "threshold": threshold,
            "actual_value": actual_value,
            "action": action,
            "incident_id": incident_id,
        }
        
        self._run(query, params)
        logger.info(f"Recorded circuit breaker {breaker_id}: {breaker_type}")
    
    # =========================================================================
    # READ METHODS - Lineage and Provenance
    # =========================================================================
    
    def get_execution_lineage(
        self,
        execution_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get complete lineage for an execution.
        
        Returns:
        - Proposal details
        - Order details
        - Execution details
        - All assertions
        - Creating agent
        - State change events
        
        Args:
            execution_id: Execution ID to trace
        
        Returns:
            Dictionary with lineage data or None if not found
        """
        query = """
        MATCH (e:Execution {execution_id: $execution_id})
        MATCH (e)<-[:FILLED_AS]-(o:Order)<-[:EXECUTED_AS]-(p:TradeProposal)
        OPTIONAL MATCH (p)-[:ASSERTED_BY]->(as:Assertion)
        OPTIONAL MATCH (ag:Agent)-[:CREATED]->(p)
        OPTIONAL MATCH (ev:Event)-[:TARGET]->(p)
        RETURN p AS proposal,
               o AS order,
               e AS execution,
               collect(DISTINCT as) AS assertions,
               collect(DISTINCT ag) AS agents,
               collect(DISTINCT ev) AS events
        ORDER BY ev.at DESC
        """
        
        result = self._run(query, {"execution_id": execution_id})
        
        if result:
            return result[0]
        return None
    
    def get_proposal_lineage(
        self,
        proposal_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get complete lineage for a proposal.
        
        Returns all related nodes and relationships.
        
        Args:
            proposal_id: Proposal ID to trace
        
        Returns:
            Dictionary with lineage data or None if not found
        """
        query = """
        MATCH (p:TradeProposal {proposal_id: $proposal_id})
        OPTIONAL MATCH (p)-[:ASSERTED_BY]->(as:Assertion)
        OPTIONAL MATCH (ag:Agent)-[:CREATED]->(p)
        OPTIONAL MATCH (ev:Event)-[:TARGET]->(p)
        OPTIONAL MATCH (p)-[:EXECUTED_AS]->(o:Order)
        OPTIONAL MATCH (o)-[:FILLED_AS]->(e:Execution)
        OPTIONAL MATCH (rv:RiskViolation)-[:BLOCKED]->(p)
        RETURN p AS proposal,
               collect(DISTINCT as) AS assertions,
               collect(DISTINCT ag) AS agents,
               collect(DISTINCT ev) AS events,
               collect(DISTINCT o) AS orders,
               collect(DISTINCT e) AS executions,
               collect(DISTINCT rv) AS violations
        """
        
        result = self._run(query, {"proposal_id": proposal_id})
        
        if result:
            return result[0]
        return None
    
    # =========================================================================
    # READ METHODS - Risk and Exposure
    # =========================================================================
    
    def get_wallet_exposure(
        self,
        wallet_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get current exposure for a wallet across all assets and venues.
        
        Returns:
        - Asset ID
        - Venue ID
        - Net exposure in USD
        
        Args:
            wallet_id: Wallet ID
        
        Returns:
            List of exposure records
        """
        query = """
        MATCH (w:Wallet {wallet_id: $wallet_id})-[:OWNS_POSITION]->(pos:Position)-[:ON_ASSET]->(a:Asset)
        OPTIONAL MATCH (pos)-[:ON_VENUE]->(v:Venue)
        RETURN a.asset_id AS asset,
               v.venue_id AS venue,
               sum(pos.net_size_usd) AS exposure_usd,
               count(pos) AS position_count
        """
        
        return self._run(query, {"wallet_id": wallet_id})
    
    def get_asset_exposure_across_wallets(
        self,
        asset_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get total exposure to an asset across all wallets.
        
        Args:
            asset_id: Asset ID
        
        Returns:
            List of wallet exposures
        """
        query = """
        MATCH (w:Wallet)-[:OWNS_POSITION]->(pos:Position)-[:ON_ASSET]->(a:Asset {asset_id: $asset_id})
        RETURN w.wallet_id AS wallet,
               sum(pos.net_size_usd) AS exposure_usd
        """
        
        return self._run(query, {"asset_id": asset_id})
    
    def get_venue_exposure(
        self,
        venue_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get total exposure on a venue across all wallets and assets.
        
        Args:
            venue_id: Venue ID
        
        Returns:
            List of exposure records
        """
        query = """
        MATCH (w:Wallet)-[:OWNS_POSITION]->(pos:Position)-[:ON_VENUE]->(v:Venue {venue_id: $venue_id})
        MATCH (pos)-[:ON_ASSET]->(a:Asset)
        RETURN w.wallet_id AS wallet,
               a.asset_id AS asset,
               sum(pos.net_size_usd) AS exposure_usd
        """
        
        return self._run(query, {"venue_id": venue_id})
    
    # =========================================================================
    # READ METHODS - Incidents and Circuit Breakers
    # =========================================================================
    
    def get_active_incidents_for_wallet(
        self,
        wallet_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get active incidents involving a wallet.
        
        Args:
            wallet_id: Wallet ID
        
        Returns:
            List of incidents with circuit breakers
        """
        query = """
        MATCH (w:Wallet {wallet_id: $wallet_id})
        MATCH (inc:Incident {status: 'OPEN'})-[:INVOLVES]->(w)
        OPTIONAL MATCH (cb:CircuitBreakerEvent)-[:TRIGGERED_BY]->(inc)
        RETURN inc AS incident,
               collect(cb) AS circuit_breakers
        ORDER BY inc.created_at DESC
        """
        
        return self._run(query, {"wallet_id": wallet_id})
    
    def get_active_incidents_for_venue(
        self,
        venue_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get active incidents involving a venue.
        
        Args:
            venue_id: Venue ID
        
        Returns:
            List of incidents with circuit breakers
        """
        query = """
        MATCH (v:Venue {venue_id: $venue_id})
        MATCH (inc:Incident {status: 'OPEN'})-[:INVOLVES]->(v)
        OPTIONAL MATCH (cb:CircuitBreakerEvent)-[:TRIGGERED_BY]->(inc)
        RETURN inc AS incident,
               collect(cb) AS circuit_breakers
        ORDER BY inc.created_at DESC
        """
        
        return self._run(query, {"venue_id": venue_id})
    
    def get_recent_circuit_breakers(
        self,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get circuit breaker events in the last N hours.
        
        Args:
            hours: Number of hours to look back
        
        Returns:
            List of circuit breaker events
        """
        query = """
        MATCH (cb:CircuitBreakerEvent)
        WHERE cb.triggered_at > datetime() - duration({hours: $hours})
        OPTIONAL MATCH (cb)-[:TRIGGERED_BY]->(inc:Incident)
        RETURN cb AS circuit_breaker,
               inc AS incident
        ORDER BY cb.triggered_at DESC
        """
        
        return self._run(query, {"hours": hours})
    
    # =========================================================================
    # READ METHODS - Analytics and Reporting
    # =========================================================================
    
    def get_agent_performance(
        self,
        agent_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get agent performance metrics.
        
        Args:
            agent_id: Agent ID
            days: Number of days to analyze
        
        Returns:
            Performance metrics
        """
        query = """
        MATCH (ag:Agent {agent_id: $agent_id})-[:CREATED]->(p:TradeProposal)
        WHERE p.created_at > datetime() - duration({days: $days})
        OPTIONAL MATCH (p)-[:EXECUTED_AS]->(o:Order)-[:FILLED_AS]->(e:Execution)
        OPTIONAL MATCH (rv:RiskViolation)-[:BLOCKED]->(p)
        RETURN count(DISTINCT p) AS proposals_created,
               count(DISTINCT o) AS orders_executed,
               count(DISTINCT rv) AS proposals_blocked,
               avg(p.confidence) AS avg_confidence,
               sum(e.size_usd) AS total_volume_usd
        """
        
        result = self._run(query, {"agent_id": agent_id, "days": days})
        
        if result:
            return result[0]
        return {}
    
    def get_system_health_summary(self) -> Dict[str, Any]:
        """
        Get system-wide health summary.
        
        Returns:
            Summary statistics
        """
        query = """
        MATCH (p:TradeProposal)
        OPTIONAL MATCH (o:Order)
        OPTIONAL MATCH (e:Execution)
        OPTIONAL MATCH (inc:Incident {status: 'OPEN'})
        OPTIONAL MATCH (cb:CircuitBreakerEvent)
        WHERE cb.triggered_at > datetime() - duration({hours: 24})
        RETURN count(DISTINCT p) AS total_proposals,
               count(DISTINCT o) AS total_orders,
               count(DISTINCT e) AS total_executions,
               count(DISTINCT inc) AS open_incidents,
               count(DISTINCT cb) AS circuit_breakers_24h
        """
        
        result = self._run(query)
        
        if result:
            return result[0]
        return {}


# Singleton instance
_graph_service: Optional[GraphService] = None


def initialize_graph_service(
    uri: str,
    user: str,
    password: str,
    database: str = "neo4j"
) -> GraphService:
    """
    Initialize global GraphService instance.
    
    Call this once at application startup.
    
    Args:
        uri: Neo4j connection URI (neo4j+s:// for secure)
        user: Database username
        password: Database password
        database: Database name
    
    Returns:
        GraphService instance
    """
    global _graph_service
    
    if _graph_service is not None:
        logger.warning("GraphService already initialized, returning existing instance")
        return _graph_service
    
    _graph_service = GraphService(uri, user, password, database)
    return _graph_service


def get_graph_service() -> GraphService:
    """
    Get global GraphService instance.
    
    Returns:
        GraphService instance
    
    Raises:
        RuntimeError: If GraphService not initialized
    """
    if _graph_service is None:
        raise RuntimeError(
            "GraphService not initialized. "
            "Call initialize_graph_service() at application startup."
        )
    
    return _graph_service


def close_graph_service() -> None:
    """
    Close global GraphService instance.
    
    Call this at application shutdown.
    """
    global _graph_service
    
    if _graph_service is not None:
        _graph_service.close()
        _graph_service = None
