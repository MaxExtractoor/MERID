"""
Neo4j Schema Initialization for MERID System
Fixes missing relationships and properties for Energy-Reality graph
"""

def create_neo4j_schema():
    """
    Create required Neo4j schema for MERID system
    """
    from core.graph_service import get_graph_service
    
    try:
        graph_service = get_graph_service()
        
        # Create constraints for better performance
        constraints = [
            "CREATE CONSTRAINT energy_id_unique IF NOT EXISTS FOR (e:Energy) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT reality_id_unique IF NOT EXISTS FOR (r:Reality) REQUIRE r.id IS UNIQUE", 
            "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE"
        ]
        
        # Create indexes for frequently queried properties
        indexes = [
            "CREATE INDEX energy_timestamp IF NOT EXISTS FOR (e:Energy) ON (e.timestamp)",
            "CREATE INDEX reality_timestamp IF NOT EXISTS FOR (r:Reality) ON (r.timestamp)",
            "CREATE INDEX reality_mode IF NOT EXISTS FOR (r:Reality) ON (r.mode)"
        ]
        
        # Create sample data if needed
        sample_queries = [
            # Create a sample Energy node
            """
            MERGE (e:Energy {id: 'sample-energy-001', timestamp: datetime(), payload: 'sample payload'})
            RETURN e
            """,
            
            # Create a sample Reality node with required properties
            """
            MERGE (r:Reality {id: 'sample-reality-001', timestamp: datetime(), mode: 'operational', 
                         consensus: 0.85, approved: true, valid_assertions_pct: 0.92, 
                         regime_entropy: 0.12, active_conflicts: 0, blind_spots: []})
            RETURN r
            """,
            
            # Create the BECAME relationship
            """
            MATCH (e:Energy {id: 'sample-energy-001'})
            MATCH (r:Reality {id: 'sample-reality-001'})
            MERGE (e)-[:BECAME]->(r)
            RETURN e, r
            """,
            
            # Create sample Agent and VOTED relationships
            """
            MERGE (a:Agent {id: 'sample-agent-001'})
            MERGE (e:Energy {id: 'sample-energy-001'})
            MERGE (a)-[v:VOTED {vote: 'YES', confidence: 0.85}]->(e)
            RETURN a, e, v
            """
        ]
        
        print("Creating Neo4j schema...")
        
        # Execute constraints
        for constraint in constraints:
            try:
                result = graph_service.run_query(constraint)
                print(f"✅ Constraint created: {constraint}")
            except Exception as e:
                print(f"❌ Constraint failed: {constraint} - {e}")
        
        # Execute indexes  
        for index in indexes:
            try:
                result = graph_service.run_query(index)
                print(f"✅ Index created: {index}")
            except Exception as e:
                print(f"❌ Index failed: {index} - {e}")
        
        # Execute sample data
        for query in sample_queries:
            try:
                result = graph_service.run_query(query)
                print(f"✅ Sample data created")
            except Exception as e:
                print(f"❌ Sample data failed: {query} - {e}")
        
        print("✅ Neo4j schema initialization completed!")
        return True
        
    except Exception as e:
        print(f"❌ Schema initialization failed: {e}")
        return False

if __name__ == "__main__":
    create_neo4j_schema()
