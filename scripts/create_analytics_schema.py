#!/usr/bin/env python3
"""
MERID Analytics Schema Creation Script
Creates the database schema for analytics infrastructure
"""

import psycopg2
import os
from datetime import datetime
import json

def create_analytics_schema():
    """Create the analytics database schema"""
    
    # Database connection parameters
    db_params = {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432'),
        'database': os.environ.get('DB_NAME', 'merid'),
        'user': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', '')
    }
    
    try:
        # Connect to database
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        print("Creating analytics schema...")
        
        # Read and execute SQL file
        sql_file_path = os.path.join(os.path.dirname(__file__), 'create_analytics_schema.sql')
        
        with open(sql_file_path, 'r') as f:
            sql_content = f.read()
        
        # Execute SQL commands
        cursor.execute(sql_content)
        
        # Commit changes
        conn.commit()
        
        print("✅ Analytics schema created successfully!")
        
        # Verify tables exist
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('events', 'identities', 'identity_audit_log')
        """)
        
        tables = cursor.fetchall()
        print(f"✅ Tables created: {[table[0] for table in tables]}")
        
        # Insert sample data if tables are empty
        cursor.execute("SELECT COUNT(*) FROM events")
        event_count = cursor.fetchone()[0]
        
        if event_count == 0:
            print("📊 Inserting sample data...")
            
            # Sample events
            sample_events = [
                ('u_12345', 'dev_abc', 'user_first_active', '2026-01-26T14:03:22Z', 
                 '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_789", "version": "v1.2.3"}'),
                ('u_12345', 'dev_abc', 'session_active', '2026-01-26T14:05:15Z', 
                 '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_789"}'),
                ('u_67890', 'dev_def', 'user_first_active', '2026-01-26T15:30:10Z', 
                 '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_790", "version": "v1.2.3"}'),
                ('u_67890', 'dev_def', 'session_active', '2026-01-26T15:32:45Z', 
                 '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_790"}'),
                ('u_12345', 'dev_abc', 'session_active', '2026-02-02T14:03:22Z', 
                 '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_791", "version": "v1.2.3"}'),
                ('u_12345', 'dev_abc', 'session_active', '2026-02-09T14:03:22Z', 
                 '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_792", "version": "v1.2.3"}'),
                ('u_67890', 'dev_def', 'session_active', '2026-02-02T15:30:10Z', 
                 '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_793", "version": "v1.2.3"}'),
                ('u_67890', 'dev_def', 'session_active', '2026-02-09T15:30:10Z', 
                 '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_794", "version": "v1.2.3"}')
            ]
            
            for event in sample_events:
                cursor.execute("""
                    INSERT INTO events (user_id, device_id, event_name, event_time, properties)
                    VALUES (%s, %s, %s, %s, %s)
                """, event)
            
            # Sample identities
            sample_identities = [
                ('dev_abc', 'u_12345', '2026-01-26T14:03:22Z'),
                ('dev_def', 'u_67890', '2026-01-26T15:30:10Z'),
                ('temp_ghi', 'temp_user_ghi', '2026-01-26T16:00:00Z')
            ]
            
            for identity in sample_identities:
                cursor.execute("""
                    INSERT INTO identities (raw_id, user_id, linked_at)
                    VALUES (%s, %s, %s)
                """, identity)
            
            # Sample audit log
            sample_audit_logs = [
                ('dev_abc', 'u_12345', 'login_link', 
                 '{"ip_address": "192.168.1.100", "user_agent": "Mozilla/5.0"}'),
                ('dev_def', 'u_67890', 'login_link', 
                 '{"ip_address": "192.168.1.101", "user_agent": "Mozilla/5.0"}')
            ]
            
            for log in sample_audit_logs:
                cursor.execute("""
                    INSERT INTO identity_audit_log (raw_id, canonical_user_id, merge_type, metadata)
                    VALUES (%s, %s, %s, %s)
                """, log)
            
            conn.commit()
            print("📊 Sample data inserted successfully!")
        else:
            print(f"📊 Events table already has {event_count} records")
        
        # Test basic queries
        print("\n🔍 Testing basic queries...")
        
        # Test cohort analysis
        cursor.execute("""
            WITH user_first AS (
              SELECT user_id, MIN(event_time::date) AS cohort_date
              FROM events WHERE event_name = 'user_first_active'
              GROUP BY user_id
            ),
            activity AS (
              SELECT uf.user_id, uf.cohort_date,
                     (e.event_time::date - uf.cohort_date) AS day_offset
              FROM user_first uf
              JOIN events e ON e.user_id = uf.user_id
               AND e.event_name = 'session_active'
               AND e.event_time::date BETWEEN uf.cohortort
                                           AND uf.cohort_date + INTERVAL '30 days'
            ),
            users_by_day AS (
              SELECT DISTINCT user_id, cohort_date, day_offset
              FROM activity WHERE day_offset BETWEEN 0 AND 30
            )
            SELECT 
                cohort_date,
                COUNT(DISTINCT user_id) AS cohort_size,
                COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_users,
                COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END) AS d14_users,
                COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_users
            FROM users_by_day
            GROUP BY cohort_date
            ORDER BY cohort_date DESC
        """)
        
        results = cursor.fetchall()
        
        print("\n📊 Cohort Analysis Results:")
        print("Cohort Date | Size | D7 Users | D14 Users | D30 Users")
        print("-" * 50)
        for row in results:
            print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")
        
        # Calculate retention rates
        for row in results:
            if row[1] > 0:
                d7_retention = (row[2] / row[1]) * 100
                d14_retention = (row[3] / row[1]) * 100
                d30_retention = (row[4] / row[1]) * 100
                d7_to_d30 = (row[4] / row[2]) * 100 if row[2] > 0 else 0
                
                print(f"📈 {row[0]}: D7={d7_retention:.1f}%, D14={d14_retention:.1f}%, D30={d30_retention:.1f}%, D7→D30={d7_to_d30:.1f}%")
        
        print("\n✅ Analytics schema validation complete!")
        
    except Exception as e:
        print(f"❌ Error creating analytics schema: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()
    
    return True

if __name__ == "__main__":
    create_analytics_schema()
