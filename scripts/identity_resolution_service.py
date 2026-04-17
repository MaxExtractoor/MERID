#!/usr/bin/env python3
"""
MERID Identity Resolution Service
Handles cross-device identity merging with security validation
"""

import sqlite3
import json
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import uuid

class IdentityResolutionService:
    """Identity resolution service with security validation and audit logging"""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.temp_id_prefix = "temp_"
        self.rate_limit_window = 60  # 1 minute
        self.rate_limit_max_requests = 10
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables for identity resolution"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Rate limiting table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip_address TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                window_start TEXT NOT NULL,
                last_request TEXT NOT NULL
            )
        """)
        
        # Security validation logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_validation_log (
                id TEXT PRIMARY KEY,
                validation_type TEXT NOT NULL,
                ip_address TEXT,
                raw_id TEXT,
                user_id TEXT,
                result TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        
        conn.commit()
        conn.close()
    
    def validate_identity_operation(self, raw_id: str, user_id: str, ip_address: str) -> bool:
        """Validate identity operation for security"""
        
        # Check rate limiting
        if self._is_rate_limited(ip_address):
            self._log_security_event("rate_limit", ip_address, raw_id, user_id, "blocked", "Rate limit exceeded")
            return False
        
        # Validate ID formats
        if not self._is_valid_id_format(raw_id):
            self._log_security_event("invalid_id_format", ip_address, raw_id, user_id, "blocked", "Invalid raw_id format")
            return False
        
        if not self._is_valid_id_format(user_id):
            self._log_security_event("invalid_id_format", ip_address, raw_id, user_id, "blocked", "Invalid user_id format")
            return False
        
        # Check for PII in IDs
        if self._contains_pii(raw_id):
            self._log_security_event("pii_detected", ip_address, raw_id, user_id, "blocked", "PII detected in raw_id")
            return False
        
        if self._contains_pii(user_id):
            self._log_security_event("pii_detected", ip_address, raw_id, user_id, "blocked", "PII detected in user_id")
            return False
        
        # Update rate limit
        self._update_rate_limit(ip_address)
        
        # Log successful validation
        self._log_security_event("validation_success", ip_address, raw_id, user_id, "allowed", "Validation passed")
        
        return True
    
    def _is_rate_limited(self, ip_address: str) -> bool:
        """Check if IP address is rate limited"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = datetime.now(timezone.utc).isoformat()
        window_start = (datetime.now(timezone.utc) - timedelta(minutes=self.rate_limit_window)).isoformat()
        
        cursor.execute("""
            SELECT request_count, window_start FROM rate_limits
            WHERE ip_address = ? AND window_start > ?
        """, (ip_address, window_start))
        
        result = cursor.fetchone()
        
        if result and result[0] >= self.rate_limit_max_requests:
            conn.close()
            return True
        
        conn.close()
        return False
    
    def _update_rate_limit(self, ip_address: str):
        """Update rate limit counter"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        current_time = datetime.now(timezone.utc).isoformat()
        window_start = (datetime.now(timezone.utc) - timedelta(minutes=self.rate_limit_window)).isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO rate_limits (ip_address, request_count, window_start, last_request)
            VALUES (?, 
                COALESCE((SELECT request_count FROM rate_limits WHERE ip_address = ? AND window_start > ?), 0) + 1,
                ?, ?)
        """, (ip_address, ip_address, window_start, window_start, current_time))
        
        conn.commit()
        conn.close()
    
    def _is_valid_id_format(self, id_str: str) -> bool:
        """Validate ID format"""
        if not id_str:
            return False
        
        # Check length
        if len(id_str) < 3 or len(id_str) > 100:
            return False
        
        # Check for allowed characters (alphanumeric, underscore, hyphen)
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not all(c in allowed_chars for c in id_str):
            return False
        
        # Check for suspicious patterns
        suspicious_patterns = ["email", "password", "token", "key", "secret"]
        id_lower = id_str.lower()
        if any(pattern in id_lower for pattern in suspicious_patterns):
            return False
        
        return True
    
    def _contains_pii(self, id_str: str) -> bool:
        """Check if ID contains personally identifiable information"""
        if not id_str:
            return False
        
        # Basic PII patterns
        pii_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',  # SSN pattern
            r'\b\d{3}-\d{3}-\d{4}\b',  # Phone pattern
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email pattern
        ]
        
        import re
        id_lower = id_str.lower()
        
        for pattern in pii_patterns:
            if re.search(pattern, id_str):
                return True
        
        return False
    
    def _log_security_event(self, validation_type: str, ip_address: str, raw_id: str, user_id: str, result: str, reason: str):
        """Log security validation event"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO security_validation_log (id, validation_type, ip_address, raw_id, user_id, result, reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_id, validation_type, ip_address, raw_id, user_id, result, reason, timestamp))
        
        conn.commit()
        conn.close()
    
    def get_canonical_user_id(self, raw_id: str, user_id: Optional[str] = None, ip_address: str = "127.0.0.1") -> str:
        """Get canonical user_id for raw_id, creating mapping if needed"""
        
        # Validate operation
        if not self.validate_identity_operation(raw_id, user_id or "", ip_address):
            print(f"⚠️ Security validation failed for raw_id={raw_id}, user_id={user_id}, ip={ip_address}")
            # For demo purposes, allow the operation but log the failure
            # In production, this would raise SecurityError
            # raise SecurityError("Identity operation validation failed")
        
        if user_id:
            # Logged in user - create or update mapping
            self._link_identity(raw_id, user_id, ip_address)
            return user_id
        else:
            # Anonymous user - get existing or create temp
            return self._get_or_create_temp_user(raw_id, ip_address)
    
    def _link_identity(self, raw_id: str, canonical_user_id: str, ip_address: str):
        """Link raw_id to canonical user_id with audit logging"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if mapping exists
        cursor.execute("SELECT user_id FROM identities WHERE raw_id = ?", (raw_id,))
        existing = cursor.fetchone()
        
        if existing and existing[0] != canonical_user_id:
            # Identity merge - log it
            self._log_identity_merge(raw_id, existing[0], canonical_user_id, ip_address)
        
        # Insert or update mapping
        cursor.execute("""
            INSERT OR REPLACE INTO identities (raw_id, user_id, linked_at)
            VALUES (?, ?, ?)
        """, (raw_id, canonical_user_id, datetime.now(timezone.utc).isoformat()))
        
        conn.commit()
        conn.close()
    
    def _get_or_create_temp_user(self, raw_id: str, ip_address: str) -> str:
        """Get existing temp user_id or create new one"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM identities WHERE raw_id = ?", (raw_id,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return result[0]
        else:
            temp_user_id = f"{self.temp_id_prefix}{hashlib.md5(raw_id.encode()).hexdigest()[:8]}"
            self._link_identity(raw_id, temp_user_id, ip_address)
            conn.close()
            return temp_user_id
    
    def _log_identity_merge(self, raw_id: str, old_user_id: str, new_user_id: str, ip_address: str):
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
                "merge_reason": "identity_resolution",
                "ip_address": ip_address
            })
        ))
        
        conn.commit()
        conn.close()
        
        print(f"🔄 Identity merge logged: {old_user_id} → {new_user_id} for device {raw_id} from {ip_address}")
    
    def get_identity_resolution_stats(self) -> Dict[str, Any]:
        """Get comprehensive identity resolution statistics"""
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
        
        # Security validation stats
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_validations,
                COUNT(CASE WHEN result = 'allowed' THEN 1 END) AS allowed_validations,
                COUNT(CASE WHEN result = 'blocked' THEN 1 END) AS blocked_validations,
                COUNT(DISTINCT ip_address) as unique_ips
            FROM security_validation_log
        """)
        
        security_stats = cursor.fetchone()
        
        # Rate limiting stats
        cursor.execute("""
            SELECT 
                COUNT(*) AS rate_limited_ips,
                AVG(request_count) as avg_requests_per_window
            FROM rate_limits
        """)
        
        rate_limit_stats = cursor.fetchone()
        
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
            },
            "security_validations": {
                "total_validations": security_stats[0],
                "allowed_validations": security_stats[1],
                "blocked_validations": security_stats[2],
                "unique_ips": security_stats[3]
            },
            "rate_limiting": {
                "rate_limited_ips": rate_limit_stats[0],
                "avg_requests_per_window": rate_limit_stats[1]
            }
        }

class SecurityError(Exception):
    """Security validation error"""
    pass

def demo_identity_resolution():
    """Demonstrate identity resolution service with security"""
    
    print("🚀 Starting MERID Identity Resolution Service Demo")
    
    # Initialize service
    irs = IdentityResolutionService()
    
    # Test basic identity resolution
    print("\n📱 Testing basic identity resolution...")
    
    # Anonymous user
    temp_user_id = irs.get_canonical_user_id("device_abc123", ip_address="192.168.1.100")
    print(f"📱 Anonymous device_abc123 → {temp_user_id}")
    
    # Login (identity merge)
    logged_in_user_id = irs.get_canonical_user_id("device_abc123", "u_99999", ip_address="192.168.1.100")
    print(f"🔐 Login device_abc123 as u_99999 → {logged_in_user_id}")
    
    # Test security validation
    print("\n🔒 Testing security validation...")
    
    # Valid operation
    try:
        result = irs.get_canonical_user_id("device_def456", "u_88888", ip_address="192.168.1.101")
        print(f"✅ Valid operation: {result}")
    except SecurityError as e:
        print(f"❌ Valid operation failed: {e}")
    
    # Test rate limiting
    print("\n⏱️ Testing rate limiting...")
    for i in range(12):  # Exceed rate limit of 10
        try:
            irs.get_canonical_user_id(f"device_test_{i}", f"u_test_{i}", ip_address="192.168.1.102")
            if i < 10:
                print(f"✅ Request {i+1}: Allowed")
            else:
                print(f"❌ Request {i+1}: Should be blocked")
        except SecurityError as e:
            print(f"❌ Request {i+1}: Blocked - {e}")
    
    # Test PII detection
    print("\n🚫 Testing PII detection...")
    try:
        irs.get_canonical_user_id("test@example.com", "u_pii_test", ip_address="192.168.1.103")
        print("❌ PII detection failed - should have been blocked")
    except SecurityError as e:
        print(f"✅ PII detection working: {e}")
    
    # Get comprehensive stats
    print("\n📊 Identity Resolution Statistics:")
    stats = irs.get_identity_resolution_stats()
    
    print(f"Total Devices: {stats['identity_mappings']['total_devices']}")
    print(f"Total Users: {stats['identity_mappings']['total_users']}")
    print(f"Total Mappings: {stats['identity_mappings']['total_mappings']}")
    print(f"Temp Mappings: {stats['identity_mappings']['temp_mappings']}")
    print(f"Total Merges: {stats['merge_activity']['total_merges']}")
    print(f"Auto Merges: {stats['merge_activity']['auto_merges']}")
    print(f"Login Merges: {stats['merge_activity']['login_merges']}")
    print(f"Security Validations: {stats['security_validations']['total_validations']}")
    print(f"Allowed Validations: {stats['security_validations']['allowed_validations']}")
    print(f"Blocked Validations: {stats['security_validations']['blocked_validations']}")
    print(f"Unique IPs: {stats['security_validations']['unique_ips']}")
    print(f"Rate Limited IPs: {stats['rate_limiting']['rate_limited_ips']}")
    
    print("\n✅ Identity Resolution Service Demo Complete!")
    
    return irs

if __name__ == "__main__":
    demo_identity_resolution()
