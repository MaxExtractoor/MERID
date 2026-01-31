#!/usr/bin/env python3
"""
MERID Event Capture System
Handles event capture, identity resolution, and UTC timestamp normalization
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import hashlib
import sqlite3
import os

class EventCaptureSystem:
    """Event capture system with identity resolution and UTC handling"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.temp_id_prefix = "temp_"
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database for demo purposes"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                device_id TEXT,
                event_name TEXT NOT NULL,
                event_time TEXT NOT NULL,
                properties TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Identities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS identities (
                raw_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)
        
        # Audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS identity_audit_log (
                id TEXT PRIMARY KEY,
                raw_id TEXT NOT NULL,
                canonical_user_id TEXT NOT NULL,
                merge_time TEXT NOT NULL,
                merge_type TEXT NOT NULL,
                metadata TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def normalize_utc_timestamp(self, timestamp_str: str) -> str:
        """Normalize any timestamp to UTC format"""
        try:
            if timestamp_str.endswith('Z'):
                # Already UTC
                return timestamp_str
            
            # Parse and convert to UTC
            if '+' in timestamp_str:
                # Has timezone info
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                # Assume UTC if no timezone
                dt = datetime.fromisoformat(timestamp_str)
                dt = dt.replace(tzinfo=timezone.utc)
            
            # Convert to UTC and format
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        except Exception as e:
            print(f"Error normalizing timestamp {timestamp_str}: {e}")
            # Fallback to current UTC time
            return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    def capture_event(self, user_id: str, device_id: str, event_name: str, 
                    properties: Optional[Dict[str, Any]] = None) -> str:
        """Capture an event with UTC timestamp normalization"""
        
        # Validate required fields
        if not user_id:
            raise ValueError("user_id is required")
        
        if not event_name:
            raise ValueError("event_name is required")
        
        # Validate event name
        valid_events = ['user_first_active', 'session_active', 'core_value_experienced']
        if event_name not in valid_events:
            raise ValueError(f"Unknown event: {event_name}")
        
        # Build event data
        event_id = str(uuid.uuid4())
        event_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        event_data = {
            "id": event_id,
            "user_id": user_id,
            "device_id": device_id,
            "event_name": event_name,
            "event_time": event_time,
            "properties": properties or {}
        }
        
        # Store in database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO events (id, user_id, device_id, event_name, event_time, properties)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event_data["id"],
            event_data["user_id"],
            event_data["device_id"],
            event_data["event_name"],
            event_data["event_time"],
            json.dumps(event_data["properties"])
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Event captured: {event_name} for user {user_id}")
        return event_id
    
    def get_canonical_user_id(self, raw_id: str, user_id: Optional[str] = None) -> str:
        """Get canonical user_id for raw_id, creating mapping if needed"""
        
        if user_id:
            # Logged in user - create or update mapping
            self._link_identity(raw_id, user_id)
            return user_id
        else:
            # Anonymous user - get existing or create temp
            return self._get_or_create_temp_user(raw_id)
    
    def _link_identity(self, raw_id: str, canonical_user_id: str):
        """Link raw_id to canonical user_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if mapping exists
        cursor.execute("SELECT user_id FROM identities WHERE raw_id = ?", (raw_id,))
        existing = cursor.fetchone()
        
        if existing and existing[0] != canonical_user_id:
            # Identity merge - log it
            self._log_identity_merge(raw_id, existing[0], canonical_user_id)
        
        # Insert or update mapping
        cursor.execute("""
            INSERT OR REPLACE INTO identities (raw_id, user_id, linked_at)
            VALUES (?, ?, ?)
        """, (raw_id, canonical_user_id, datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
        conn.close()
    
    def _get_or_create_temp_user(self, raw_id: str) -> str:
        """Get existing temp user_id or create new one"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM identities WHERE raw_id = ?", (raw_id,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return result[0]
        else:
            temp_user_id = f"{self.temp_id_prefix}{raw_id}"
            self._link_identity(raw_id, temp_user_id)
            conn.close()
            return temp_user_id
    
    def _log_identity_merge(self, raw_id: str, old_user_id: str, new_user_id: str):
        """Log identity merge for audit trail"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        log_id = str(uuid.uuid4())
        merge_time = datetime.now(timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO identity_audit_log (id, raw_id, canonical_user_id, merge_time, merge_type, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            raw_id,
            new_user_id,
            merge_time,
            "identity_merge",
            json.dumps({
                "old_user_id": old_user_id,
                "new_user_id": new_user_id,
                "merge_reason": "identity_resolution"
            })
        ))
        
        conn.commit()
        conn.close()
        
        print(f"🔄 Identity merge logged: {old_user_id} → {new_user_id} for device {raw_id}")
    
    def process_incoming_event(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming event with identity resolution"""
        
        # Extract identifiers
        raw_id = raw_event.get('device_id') or raw_event.get('temp_id')
        user_id = raw_event.get('user_id')
        
        # Resolve canonical user_id
        canonical_user_id = self.get_canonical_user_id(raw_id, user_id)
        
        # Build canonical event
        canonical_event = {
            "user_id": canonical_user_id,
            "device_id": raw_event.get('device_id'),
            "event_name": raw_event['event_name'],
            "event_time": self.normalize_utc_timestamp(raw_event.get('event_time', datetime.now(timezone.utc).isoformat())),
            "properties": raw_event.get('properties', {})
        }
        
        # Add identity metadata
        canonical_event['properties']['identity_resolution'] = {
            "raw_id": raw_id,
            "canonical_user_id": canonical_user_id,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Capture the event
        self.capture_event(
            user_id=canonical_event['user_id'],
            device_id=canonical_event['device_id'],
            event_name=canonical_event['event_name'],
            properties=canonical_event['properties']
        )
        
        return canonical_event
    
    def get_cohort_analysis(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Get cohort analysis for date range"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # SQLite version of cohort analysis
        cursor.execute("""
            WITH user_first AS (
              SELECT user_id, MIN(date(event_time)) AS cohort_date
              FROM events WHERE event_name = 'user_first_active'
              GROUP BY user_id
            ),
            activity AS (
              SELECT uf.user_id, uf.cohort_date,
                     (date(e.event_time) - uf.cohort_date) AS day_offset
              FROM user_first uf
              JOIN events e ON e.user_id = uf.user_id
               AND e.event_name = 'session_active'
               AND date(e.event_time) BETWEEN uf.cohort_date
                                           AND date(uf.cohort_date, '+30 days')
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
        
        cohorts = []
        for row in results:
            cohort_data = {
                "cohort_date": row[0],
                "cohort_size": row[1],
                "d7_users": row[2],
                "d14_users": row[3],
                "d30_users": row[4]
            }
            
            # Calculate retention rates
            if cohort_data["cohort_size"] > 0:
                cohort_data["d7_retention"] = (cohort_data["d7_users"] / cohort_data["cohort_size"]) * 100
                cohort_data["d14_retention"] = (cohort_data["d14_users"] / cohort_data["cohort_size"]) * 100
                cohort_data["d30_retention"] = (cohort_data["d30_users"] / cohort_data["cohort_size"]) * 100
                
                if cohort_data["d7_users"] > 0:
                    cohort_data["d7_to_d30_conversion"] = (cohort_data["d30_users"] / cohort_data["d7_users"]) * 100
                else:
                    cohort_data["d7_to_d30_conversion"] = 0
            else:
                cohort_data["d7_retention"] = 0
                cohort_data["d14_retention"] = 0
                cohort_data["d30_retention"] = 0
                cohort_data["d7_to_d30_conversion"] = 0
            
            cohorts.append(cohort_data)
        
        conn.close()
        
        return {
            "cohorts": cohorts,
            "total_cohorts": len(cohorts),
            "analysis_period": f"{start_date} to {end_date}"
        }

# Demo usage
def demo_event_capture():
    """Demonstrate event capture system"""
    
    print("🚀 Starting MERID Event Capture System Demo")
    
    # Initialize system
    ecs = EventCaptureSystem()
    
    # Sample events
    sample_events = [
        {
            "device_id": "dev_abc",
            "user_id": "u_12345",
            "event_name": "user_first_active",
            "event_time": "2026-01-26T14:03:22Z",
            "properties": {
                "platform": "web",
                "role": "operator",
                "env": "prod",
                "session_id": "sess_789",
                "version": "v1.2.3"
            }
        },
        {
            "device_id": "dev_abc",
            "user_id": "u_12345",
            "event_name": "session_active",
            "event_time": "2026-01-26T14:05:15Z",
            "properties": {
                "platform": "web",
                "role": "operator",
                "env": "prod",
                "session_id": "sess_789"
            }
        },
        {
            "device_id": "dev_abc",
            "user_id": "u_12345",
            "event_name": "session_active",
            "event_time": "2026-02-02T14:03:22Z",
            "properties": {
                "platform": "web",
                "role": "operator",
                "env": "prod",
                "session_id": "sess_791",
                "version": "v1.2.3"
            }
        },
        {
            "device_id": "dev_abc",
            "user_id": "u_12345",
            "event_name": "session_active",
            "event_time": "2026-02-09T14:03:22Z",
            "properties": {
                "platform": "web",
                "role": "operator",
                "env": "prod",
                "session_id": "sess_792",
                "version": "v1.2.3"
            }
        },
        {
            "device_id": "dev_def",
            "user_id": "u_67890",
            "event_name": "user_first_active",
            "event_time": "2026-01-26T15:30:10Z",
            "properties": {
                "platform": "web",
                "role": "developer",
                "env": "prod",
                "session_id": "sess_790",
                "version": "v1.2.3"
            }
        },
        {
            "device_id": "dev_def",
            "user_id": "u_67890",
            "event_name": "session_active",
            "event_time": "2026-02-02T15:30:10Z",
            "properties": {
                "platform": "web",
                "role": "developer",
                "env": "prod",
                "session_id": "sess_793",
                "version": "v1.2.3"
            }
        },
        {
            "device_id": "dev_def",
            "user_id": "u_67890",
            "event_name": "session_active",
            "event_time": "2026-02-09T15:30:10Z",
            "properties": {
                "platform": "web",
                "role": "developer",
                "env": "prod",
                "session_id": "sess_794",
                "version": "v1.2.3"
            }
        }
    ]
    
    # Process events
    print("\n📊 Processing sample events...")
    for event in sample_events:
        processed_event = ecs.process_incoming_event(event)
        print(f"✅ Processed: {processed_event['event_name']} for user {processed_event['user_id']}")
    
    # Get cohort analysis
    print("\n📈 Generating cohort analysis...")
    analysis = ecs.get_cohort_analysis("2026-01-01", "2026-02-29")
    
    print(f"\n📊 Cohort Analysis Results ({analysis['total_cohorts']} cohorts):")
    print("Cohort Date | Size | D7 | D14 | D30 | D7% | D14% | D30% | D7→D30%")
    print("-" * 80)
    
    for cohort in analysis["cohorts"]:
        print(f"{cohort['cohort_date']} | {cohort['cohort_size']} | {cohort['d7_users']} | {cohort['d14_users']} | {cohort['d30_users']} | {cohort['d7_retention']:.1f}% | {cohort['d14_retention']:.1f}% | {cohort['d30_retention']:.1f}% | {cohort['d7_to_d30_conversion']:.1f}%")
    
    # Test identity resolution
    print("\n🔄 Testing identity resolution...")
    
    # Test anonymous user
    temp_user_id = ecs.get_canonical_user_id("temp_device_123")
    print(f"📱 Anonymous device temp_device_123 → {temp_user_id}")
    
    # Test login (identity merge)
    logged_in_user_id = ecs.get_canonical_user_id("temp_device_123", "u_99999")
    print(f"🔐 Login temp_device_123 as u_99999 → {logged_in_user_id}")
    
    print("\n✅ Event Capture System Demo Complete!")
    return ecs

if __name__ == "__main__":
    demo_event_capture()
