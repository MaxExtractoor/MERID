# Neo4j Setup Guide for MERID

## Overview

MERID now integrates Neo4j graph database for advanced memory storage and querying. The system uses **dual-write** architecture:
- **JSON files** (primary, always available)
- **Neo4j graph** (optional, for advanced queries)

This ensures the system works even if Neo4j is unavailable, while providing powerful graph capabilities when connected.

---

## Installation

### 1. Install Neo4j

**Option A: Neo4j Desktop (Recommended for Development)**
1. Download from https://neo4j.com/download/
2. Install and launch Neo4j Desktop
3. Create a new project
4. Create a new database (default credentials: neo4j/password)
5. Start the database

**Option B: Docker**
```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

**Option C: System Installation**
- Windows: Download installer from neo4j.com
- Mac: `brew install neo4j`
- Linux: Follow official docs

### 2. Install Python Driver

```bash
pip install neo4j
```

### 3. Configure MERID

Update `.env` file with your Neo4j credentials:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_DATABASE=neo4j
```

---

## Architecture

### Dual-Write System

```
Reality Memory Record
        ↓
    ┌───────────────┐
    │ RealityMemory │
    └───────┬───────┘
            │
        ┌───┴────┐
        ↓        ↓
   ┌────────┐  ┌──────────┐
   │  JSON  │  │  Neo4j   │
   │  File  │  │  Graph   │
   └────────┘  └──────────┘
   (Primary)   (Optional)
```

**Benefits:**
- System works without Neo4j (JSON fallback)
- Advanced queries when Neo4j available
- No data loss if Neo4j goes down
- Easy migration path

### Graph Schema

```cypher
// Nodes
(:Agent {id, name, total_votes, created_at, last_vote_at})
(:Energy {id, payload, source, timestamp, metadata})
(:Decision {id, consensus, validated, timestamp})

// Relationships
(:Agent)-[:VOTED_ON {vote, confidence, timestamp}]->(:Energy)
(:Energy)-[:RESULTED_IN]->(:Decision)
```

---

## API Endpoints

### Status Check
```bash
GET /api/v1/memory/graph/status
```

Returns Neo4j connection status.

### Agent Network
```bash
GET /api/v1/memory/graph/agent/{agent_id}/network?depth=2
```

Get agent's collaboration network showing which agents voted on the same energies.

**Response:**
```json
{
  "agent_id": "analyst_gemma",
  "network": [
    {
      "agent_id": "analyst_llama",
      "total_votes": 45,
      "distance": 1
    }
  ]
}
```

### Agent Statistics
```bash
GET /api/v1/memory/graph/agent/{agent_id}/stats
```

Get comprehensive agent stats from graph.

**Response:**
```json
{
  "agent_id": "analyst_gemma",
  "stats": {
    "total_votes": 150,
    "energies_voted_on": 120,
    "correct_predictions": 108,
    "avg_confidence": 0.85,
    "avg_consensus": 0.78
  }
}
```

### Pattern Detection
```bash
GET /api/v1/memory/graph/patterns?limit=10
```

Find common patterns in validated decisions.

**Response:**
```json
{
  "patterns": [
    {
      "source": "twitter",
      "frequency": 45,
      "avg_consensus": 0.82
    }
  ],
  "count": 10
}
```

### Recent Decisions
```bash
GET /api/v1/memory/graph/decisions/recent?limit=20
```

Get recent decisions with full graph context.

### Top Agents
```bash
GET /api/v1/memory/graph/agents/top?limit=10
```

Get top agents ranked by participation and accuracy.

---

## Cypher Query Examples

### Find Agent Collaborations
```cypher
MATCH (a:Agent {id: 'analyst_gemma'})-[:VOTED_ON]->(e:Energy)<-[:VOTED_ON]-(other:Agent)
WHERE a <> other
RETURN other.id, count(e) as shared_votes
ORDER BY shared_votes DESC
LIMIT 10
```

### Find High-Consensus Decisions
```cypher
MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
WHERE d.consensus > 0.8 AND d.validated = true
RETURN e.payload, d.consensus, e.source
ORDER BY d.consensus DESC
LIMIT 20
```

### Agent Trust Network
```cypher
MATCH (a:Agent)-[:VOTED_ON]->(e:Energy)<-[:VOTED_ON]-(b:Agent)
WHERE a <> b
WITH a, b, count(e) as collaborations
WHERE collaborations > 5
RETURN a.id, b.id, collaborations
ORDER BY collaborations DESC
```

### Pattern Analysis by Source
```cypher
MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
WHERE d.validated = true
WITH e.source as source, 
     count(*) as total,
     avg(d.consensus) as avg_consensus,
     sum(CASE WHEN d.consensus > 0.8 THEN 1 ELSE 0 END) as high_consensus
RETURN source, total, avg_consensus, high_consensus
ORDER BY total DESC
```

---

## Startup Behavior

### Automatic Initialization

On startup, MERID will:
1. Attempt to connect to Neo4j using `.env` credentials
2. Create schema (indexes and constraints)
3. Log connection status
4. Continue with JSON-only if Neo4j unavailable

**Startup Logs:**
```
Phase 1: Initializing core systems...
✅ Consensus engine: 3 min votes, 0.67 quorum
✅ Paper trading engine: 1 portfolios loaded
✅ Reflection layer: 49 reflections, 2 agents
✅ Brier metrics: 0 predictions tracked
✅ Neo4j graph database connected: bolt://localhost:7687
```

### Graceful Degradation

If Neo4j is unavailable:
- System continues with JSON-only storage
- All core functionality works
- Graph API endpoints return 503 errors
- Logs show: `⚠️ Neo4j not available - using JSON-only memory storage`

---

## Data Migration

### Export from JSON to Neo4j

```python
from memory.store import reality_memory
from memory.neo4j_graph import get_neo4j_graph

# Get all JSON entries
entries = reality_memory.all_entries()

# Get Neo4j graph
graph = get_neo4j_graph()

# Migrate each entry
for entry in entries:
    graph.record_reality(
        energy_id=entry["energy_id"],
        payload=entry["payload"],
        source=entry["source"],
        consensus=entry["consensus"],
        validated=entry["validation"]["status"] == "validated",
        contributions=entry["contributions"],
        metadata=entry.get("metadata", {})
    )

print(f"Migrated {len(entries)} entries to Neo4j")
```

### Verify Migration

```cypher
// Count nodes
MATCH (n) RETURN labels(n) as type, count(*) as count

// Check recent data
MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
RETURN e.id, e.timestamp, d.consensus
ORDER BY e.timestamp DESC
LIMIT 10
```

---

## Monitoring

### Check Connection Status

```bash
curl http://localhost:8000/api/v1/memory/graph/status
```

### View Startup Health

```bash
curl http://localhost:8000/api/v1/health/startup
```

Look for `neo4j` service status:
```json
{
  "services": {
    "neo4j": {
      "status": "running",
      "started_at": 1234567890
    }
  }
}
```

### Neo4j Browser

Access Neo4j Browser at http://localhost:7474

Run queries directly:
```cypher
// Overview
CALL db.schema.visualization()

// Count everything
MATCH (n) RETURN count(n)

// Recent activity
MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
RETURN e, d
ORDER BY d.timestamp DESC
LIMIT 25
```

---

## Troubleshooting

### Connection Failed

**Error:** `Neo4j connection failed: Failed to establish connection`

**Solutions:**
1. Check Neo4j is running: `neo4j status`
2. Verify credentials in `.env`
3. Check port 7687 is not blocked
4. Try connecting with Neo4j Browser first

### Authentication Failed

**Error:** `Neo4j connection failed: Authentication failed`

**Solutions:**
1. Verify username/password in `.env`
2. Reset Neo4j password if needed
3. Check NEO4J_AUTH environment variable in Docker

### Package Not Installed

**Error:** `neo4j package not installed`

**Solution:**
```bash
pip install neo4j
```

### Schema Errors

**Error:** `Constraint already exists`

**Solution:** This is normal - constraints are idempotent. The system will continue.

### Dual-Write Failures

If Neo4j write fails, the system:
- Logs warning: `Failed to write to Neo4j: <error>`
- Continues with JSON write (no data loss)
- Retries on next record

---

## Performance Tuning

### Indexes

The system automatically creates indexes on:
- `Agent.id` (unique constraint)
- `Agent.name`
- `Energy.id` (unique constraint)
- `Energy.timestamp`
- `Decision.id` (unique constraint)
- `Decision.consensus`

### Query Optimization

For large datasets:
```cypher
// Use LIMIT
MATCH (a:Agent)-[:VOTED_ON]->(e:Energy)
RETURN a, e
LIMIT 100

// Use indexes
MATCH (a:Agent {id: 'specific_id'})
RETURN a

// Avoid full scans
MATCH (a:Agent)
WHERE a.total_votes > 100  // Uses index
RETURN a
```

### Memory Configuration

For production, increase Neo4j memory in `neo4j.conf`:
```
dbms.memory.heap.initial_size=2G
dbms.memory.heap.max_size=4G
dbms.memory.pagecache.size=2G
```

---

## Production Deployment

### Docker Compose

```yaml
version: '3.8'
services:
  neo4j:
    image: neo4j:latest
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/your_secure_password
      - NEO4J_dbms_memory_heap_max__size=4G
      - NEO4J_dbms_memory_pagecache_size=2G
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs

volumes:
  neo4j_data:
  neo4j_logs:
```

### Backup Strategy

```bash
# Backup Neo4j
neo4j-admin dump --database=neo4j --to=/backups/neo4j-backup.dump

# Backup JSON (always maintained)
cp logs/reality_memory.json backups/reality_memory_$(date +%Y%m%d).json
```

### High Availability

For production HA:
1. Use Neo4j Enterprise with clustering
2. Configure read replicas
3. Set up monitoring with Prometheus
4. Implement automatic failover

---

## Development Tips

### Clear Test Data

```bash
# Via API
curl -X POST http://localhost:8000/api/v1/memory/graph/clear

# Via Cypher
MATCH (n) DETACH DELETE n
```

### Seed Test Data

```python
from memory.store import reality_memory

# Record test entries
for i in range(10):
    reality_memory.record(
        energy={"energy_id": f"test_{i}", "payload": f"Test {i}", "source": "test"},
        vote_result={"consensus": 0.8},
        validation={"status": "validated"},
        contributions=[
            {"agent_id": "test_agent", "vote": "accept", "confidence": 0.9}
        ]
    )
```

### Inspect Graph

```cypher
// See everything
MATCH (n) RETURN n LIMIT 100

// Agent relationships
MATCH (a:Agent)-[r]->(e:Energy)
RETURN a, r, e
LIMIT 50

// Decision patterns
MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
WHERE d.validated = true
RETURN e.source, count(*) as validated_count
```

---

## Summary

**Neo4j Integration Status:** ✅ Complete

**Features:**
- ✅ Dual-write (JSON + Neo4j)
- ✅ Automatic initialization
- ✅ Graceful degradation
- ✅ REST API endpoints
- ✅ Agent network queries
- ✅ Pattern detection
- ✅ Performance optimized

**Next Steps:**
1. Install Neo4j
2. Configure `.env`
3. Start MERID
4. Verify connection at `/api/v1/memory/graph/status`
5. Explore graph with Neo4j Browser
6. Use API endpoints for advanced queries

**Support:**
- Neo4j Docs: https://neo4j.com/docs/
- Cypher Guide: https://neo4j.com/developer/cypher/
- MERID Issues: Check logs in `logs/full.log`
