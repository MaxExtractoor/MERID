#!/usr/bin/env python3
"""
MERID Cohort Analysis Queries
Implements D7/D14/D30 cohort analysis with edge case handling
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List

class CohortAnalysisQueries:
    """Cohort analysis with complete SQL implementations"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
    
    def get_d7_d14_cohort_analysis(self) -> List[Dict[str, Any]]:
        """Complete SQL for D7 and D14 cohort analysis with edge cases"""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Complete SQL with edge case handling
        query = """
            WITH user_first AS (
              SELECT
                user_id,
                MIN(date(event_time)) AS cohort_date
              FROM events
              WHERE event_name = 'user_first_active'
              GROUP BY user_id
            ),

            activity AS (
              SELECT
                uf.user_id,
                uf.cohort_date,
                (date(e.event_time) - uf.cohort_date) AS day_offset
              FROM user_first uf
              JOIN events e
                ON e.user_id = uf.user_id
               AND e.event_name = 'session_active'
               AND date(e.event_time) BETWEEN uf.cohort_date
                                           AND date(uf.cohort_date, '+30 days')
            ),

            users_by_day AS (
              SELECT DISTINCT
                user_id,
                cohort_date,
                day_offset
              FROM activity
              WHERE day_offset BETWEEN 0 AND 30
            )

            SELECT
              cohort_date,
              COUNT(DISTINCT user_id)                                             AS cohort_size,
              COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END)          AS d7_users,
              COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END)          AS d14_users,
              ROUND(
                COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) * 100.0 / 
                COUNT(DISTINCT user_id), 2
              ) AS d7_retention_percent,
              ROUND(
                COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END) * 100.0 / 
                COUNT(DISTINCT user_id), 2
              ) AS d14_retention_percent
            FROM users_by_day
            GROUP BY cohort_date
            ORDER BY cohort_date DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        cohorts = []
        for row in results:
            cohorts.append({
                "cohort_date": row[0],
                "cohort_size": row[1],
                "d7_users": row[2],
                "d14_users": row[3],
                "d7_retention_percent": row[4],
                "d14_retention_percent": row[5]
            })
        
        return cohorts
    
    def get_d7_to_d30_conversion_analysis(self) -> List[Dict[str, Any]]:
        """Complete conversion analysis from D7 retained to D30 retained"""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = """
            WITH user_first AS (
              SELECT
                user_id,
                MIN(date(event_time)) AS cohort_date
              FROM events
              WHERE event_name = 'user_first_active'
              GROUP BY user_id
            ),

            activity AS (
              SELECT
                uf.user_id,
                uf.cohort_date,
                (date(e.event_time) - uf.cohort_date) AS day_offset
              FROM user_first uf
              JOIN events e
                ON e.user_id = uf.user_id
               AND e.event_name = 'session_active'
               AND date(e.event_time) BETWEEN uf.cohort_date
                                           AND date(uf.cohort_date, '+30 days')
            ),

            users_by_day AS (
              SELECT DISTINCT
                user_id,
                cohort_date,
                day_offset
              FROM activity
              WHERE day_offset BETWEEN 0 AND 30
            ),

            retention AS (
              SELECT
                cohort_date,
                COUNT(DISTINCT user_id) AS cohort_size,
                COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_users,
                COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_users
              FROM users_by_day
              GROUP BY cohort_date
            )

            SELECT
              cohort_date,
              cohort_size,
              d7_users,
              d30_users,
              ROUND(d7_users * 100.0 / cohort_size, 2) AS d7_retention_percent,
              ROUND(d30_users * 100.0 / cohort_size, 2) AS d30_retention_percent,
              ROUND(
                CASE WHEN d7_users > 0
                     THEN d30_users * 100.0 / d7_users
                     ELSE 0
                END, 2
              ) AS d7_to_d30_conversion_percent,
              ROUND(
                (d30_users * 1.0 / cohort_size) - (d7_users * 1.0 / cohort_size), 2
              ) AS retention_change_d7_to_d30,
              CASE 
                WHEN d7_users * 1.0 / cohort_size > 0.4 THEN 'Above Target'
                WHEN d7_users * 1.0 / cohort_size > 0.3 THEN 'Near Target'
                ELSE 'Below Target'
              END AS d7_retention_status,
              CASE 
                WHEN d30_users * 1.0 / cohort_size > 0.25 THEN 'Above Target'
                WHEN d30_users * 1.0 / cohort_size > 0.15 THEN 'Near Target'
                ELSE 'Below Target'
              END AS d30_retention_status
            FROM retention
            WHERE cohort_size >= 5  -- Minimum cohort size for reliability
            ORDER BY cohort_date DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        cohorts = []
        for row in results:
            cohorts.append({
                "cohort_date": row[0],
                "cohort_size": row[1],
                "d7_users": row[2],
                "d30_users": row[3],
                "d7_retention_percent": row[4],
                "d30_retention_percent": row[5],
                "d7_to_d30_conversion_percent": row[6],
                "retention_change_d7_to_d30": row[7],
                "d7_retention_status": row[8],
                "d30_retention_status": row[9]
            })
        
        return cohorts
    
    def get_core_value_segmentation(self) -> List[Dict[str, Any]]:
        """Core value segmentation analysis"""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = """
            WITH user_first AS (
              SELECT
                user_id,
                MIN(date(event_time)) AS cohort_date
              FROM events
              WHERE event_name = 'user_first_active'
              GROUP BY user_id
            ),

            core_value_users AS (
              SELECT
                uf.user_id,
                uf.cohort_date
              FROM user_first uf
              WHERE EXISTS (
                SELECT 1 FROM events e
                WHERE e.user_id = uf.user_id
                  AND e.event_name = 'core_value_experienced'
                  AND date(e.event_time) = uf.cohort_date
              )
            ),

            activity AS (
              SELECT
                cvu.user_id,
                cvu.cohort_date,
                (date(e.event_time) - cvu.cohort_date) AS day_offset
              FROM core_value_users cvu
              JOIN events e
                ON e.user_id = cvu.user_id
               AND e.event_name = 'session_active'
               AND date(e.event_time) BETWEEN cvu.cohort_date
                                           AND date(cvu.cohort_date, '+30 days')
            ),

            core_value_retention AS (
              SELECT
                cohort_date,
                COUNT(DISTINCT user_id) AS core_value_cohort_size,
                COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_core_users,
                COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END) AS d14_core_users,
                COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_core_users
              FROM activity
              GROUP BY cohort_date
            )

            SELECT
              cohort_date,
              core_value_cohort_size,
              d7_core_users,
              d14_core_users,
              d30_core_users,
              ROUND(d7_core_users * 100.0 / core_value_cohort_size, 2) AS d7_core_retention_percent,
              ROUND(d14_core_users * 100.0 / core_value_cohort_size, 2) AS d14_core_retention_percent,
              ROUND(d30_core_users * 100.0 / core_value_cohort_size, 2) AS d30_core_retention_percent,
              ROUND(
                CASE WHEN d7_core_users > 0
                     THEN d30_core_users * 100.0 / d7_core_users
                     ELSE 0
                END, 2
              ) AS d7_core_to_d30_conversion_percent
            FROM core_value_retention
            ORDER BY cohort_date DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        cohorts = []
        for row in results:
            cohorts.append({
                "cohort_date": row[0],
                "core_value_cohort_size": row[1],
                "d7_core_users": row[2],
                "d14_core_users": row[3],
                "d30_core_users": row[4],
                "d7_core_retention_percent": row[5],
                "d14_core_retention_percent": row[6],
                "d30_core_retention_percent": row[7],
                "d7_core_to_d30_conversion_percent": row[8]
            })
        
        return cohorts
    
    def get_identity_resolution_stats(self) -> Dict[str, Any]:
        """Get identity resolution statistics"""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Identity mapping stats
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT raw_id) AS total_devices,
                COUNT(DISTINCT user_id) AS total_users,
                COUNT(*) AS total_mappings,
                COUNT(CASE WHEN user_id LIKE 'temp_%' THEN 1 END) AS temp_mappings
            FROM identities
        """)
        
        identity_stats = cursor.fetchone()
        
        # Audit log stats
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_merges,
                COUNT(CASE WHEN merge_type = 'identity_merge' THEN 1 END) AS auto_merges,
                COUNT(CASE WHEN merge_type = 'login_link' THEN 1 END) AS login_merges,
                DATE(MAX(merge_time)) as last_merge_date
            FROM identity_audit_log
        """)
        
        audit_stats = cursor.fetchone()
        
        conn.close()
        
        return {
            "identity_mappings": {
                "total_devices": identity_stats[0],
                "total_users": identity_stats[1],
                "total_mappings": identity_stats[2],
                "temp_mappings": identity_stats[3]
            },
            "merge_activity": {
                "total_merges": audit_stats[0],
                "auto_merges": audit_stats[1],
                "login_merges": audit_stats[2],
                "last_merge_date": audit_stats[3]
            }
        }

def demo_cohort_analysis():
    """Demonstrate cohort analysis queries"""
    
    print("🚀 Starting MERID Cohort Analysis Demo")
    
    # Initialize queries
    queries = CohortAnalysisQueries()
    
    # D7/D14 analysis
    print("\n📊 D7/D14 Cohort Analysis:")
    d7_d14_cohorts = queries.get_d7_d14_cohort_analysis()
    
    print("Cohort Date | Size | D7 Users | D14 Users | D7% | D14%")
    print("-" * 60)
    for cohort in d7_d14_cohorts:
        print(f"{cohort['cohort_date']} | {cohort['cohort_size']} | {cohort['d7_users']} | {cohort['d14_users']} | {cohort['d7_retention_percent']:.1f}% | {cohort['d14_retention_percent']:.1f}%")
    
    # D7→D30 conversion analysis
    print("\n📈 D7→D30 Conversion Analysis:")
    conversion_cohorts = queries.get_d7_to_d30_conversion_analysis()
    
    print("Cohort Date | Size | D7 | D30 | D7% | D30% | D7→D30% | Status")
    print("-" * 75)
    for cohort in conversion_cohorts:
        print(f"{cohort['cohort_date']} | {cohort['cohort_size']} | {cohort['d7_users']} | {cohort['d30_users']} | {cohort['d7_retention_percent']:.1f}% | {cohort['d30_retention_percent']:.1f}% | {cohort['d7_to_d30_conversion_percent']:.1f}% | {cohort['d7_retention_status']}")
    
    # Core value segmentation
    print("\n🎯 Core Value Segmentation:")
    core_value_cohorts = queries.get_core_value_segmentation()
    
    print("Cohort Date | Core Size | D7 Core | D30 Core | D7% | D30% | D7→D30%")
    print("-" * 70)
    for cohort in core_value_cohorts:
        print(f"{cohort['cohort_date']} | {cohort['core_value_cohort_size']} | {cohort['d7_core_users']} | {cohort['d30_core_users']} | {cohort['d7_core_retention_percent']:.1f}% | {cohort['d30_core_retention_percent']:.1f}% | {cohort['d7_core_to_d30_conversion_percent']:.1f}%")
    
    # Identity resolution stats
    print("\n🔄 Identity Resolution Statistics:")
    identity_stats = queries.get_identity_resolution_stats()
    
    print(f"Total Devices: {identity_stats['identity_mappings']['total_devices']}")
    print(f"Total Users: {identity_stats['identity_mappings']['total_users']}")
    print(f"Total Mappings: {identity_stats['identity_mappings']['total_mappings']}")
    print(f"Temp Mappings: {identity_stats['identity_mappings']['temp_mappings']}")
    print(f"Total Merges: {identity_stats['merge_activity']['total_merges']}")
    print(f"Auto Merges: {identity_stats['merge_activity']['auto_merges']}")
    print(f"Login Merges: {identity_stats['merge_activity']['login_merges']}")
    print(f"Last Merge: {identity_stats['merge_activity']['last_merge_date']}")
    
    print("\n✅ Cohort Analysis Demo Complete!")
    
    return queries

if __name__ == "__main__":
    demo_cohort_analysis()
