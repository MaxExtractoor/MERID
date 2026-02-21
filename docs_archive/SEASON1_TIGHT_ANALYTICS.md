# 🎯 **MERID SEASON 1 TIGHT ANALYTICS IMPLEMENTATION**
**Last Updated:** 2026-01-26  
**Target:** One Event Schema + One Cohorting Pattern + Clear Identity/Time Rules

---

## 📊 **EVENT PAYLOAD SCHEMA EXAMPLES**

### **Canonical Event Payload**
```json
{
  "user_id": "u_12345",
  "device_id": "dev_abc", 
  "event_name": "user_first_active",
  "event_time": "2026-01-26T14:03:22Z",
  "properties": {
    "platform": "web",
    "role": "operator",
    "env": "prod",
    "session_id": "sess_789",
    "version": "v1.2.3"
  }
}
```

### **Minimal Events Table**
```sql
CREATE TABLE events (
  user_id      TEXT NOT NULL,
  device_id    TEXT,
  event_name   TEXT NOT NULL,
  event_time   TIMESTAMPTZ NOT NULL,  -- always UTC
  properties   JSONB,
  
  -- Indexes for performance
  INDEX idx_events_user_time (user_id, event_time),
  INDEX idx_events_name_time (event_name, event_time),
  INDEX idx_events_device_time (device_id, event_time)
);
```

### **Recommended Events**
- **`user_first_active`** - First meaningful use (defines D0)
- **`session_active`** - Once per session when dashboard fully loaded
- **`core_value_experienced`** - When user sees positions/risk/shadow PnL (optional)

### **Event Capture Implementation**
```python
def capture_event(user_id, device_id, event_name, properties=None):
    """Capture event with UTC timestamp"""
    event_data = {
        "user_id": user_id,
        "device_id": device_id,
        "event_name": event_name,
        "event_time": datetime.utcnow().isoformat() + "Z",  # UTC
        "properties": properties or {}
    }
    
    # Insert into events table
    insert_event_sql = """
    INSERT INTO events (user_id, device_id, event_name, event_time, properties)
    VALUES (%s, %s, %s, %s, %s)
    """
    execute_sql(insert_event_sql, (
        event_data["user_id"],
        event_data["device_id"], 
        event_data["event_name"],
        event_data["event_time"],
        json.dumps(event_data["properties"])
    ))

# Example usage
capture_event(
    user_id="u_12345",
    device_id="dev_abc",
    event_name="user_first_active",
    properties={
        "platform": "web",
        "role": "operator",
        "env": "prod",
        "session_id": "sess_789",
        "version": "v1.2.3"
    }
)
```

---

## 📈 **SQL TO ASSIGN USERS TO D7 AND D14**

### **Complete Cohorting Pattern with Edge Cases**
```sql
WITH user_first AS (
  SELECT
    user_id,
    MIN(event_time::date) AS cohort_date
  FROM events
  WHERE event_name = 'user_first_active'
  GROUP BY user_id
),

activity AS (
  SELECT
    uf.user_id,
    uf.cohort_date,
    (e.event_time::date - uf.cohort_date) AS day_offset
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
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
    COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END)::decimal / 
    COUNT(DISTINCT user_id) * 100, 2
  ) AS d7_retention_percent,
  ROUND(
    COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END)::decimal / 
    COUNT(DISTINCT user_id) * 100, 2
  ) AS d14_retention_percent
FROM users_by_day
GROUP BY cohort_date
ORDER BY cohort_date DESC;
```

### **Edge Cases Handled**
- **Multiple sessions on D7/D14** → `DISTINCT user_id` ensures each user counted once
- **No events on D7/D14** → User isn't counted as retained for that day
- **Events after D30** → Excluded by `BETWEEN 0 AND 30` filter
- **Multiple first_active events** → `MIN(event_time::date)` picks earliest

---

## 📊 **QUERY: CONVERSION FROM D7 RETAINED TO D30 RETAINED**

### **Complete Conversion Analysis**
```sql
WITH user_first AS (
  SELECT
    user_id,
    MIN(event_time::date) AS cohort_date
  FROM events
  WHERE event_name = 'user_first_active'
  GROUP BY user_id
),

activity AS (
  SELECT
    uf.user_id,
    uf.cohort_date,
    (e.event_time::date - uf.cohort_date) AS day_offset
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
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
  ROUND(d7_users::decimal / cohort_size * 100, 2) AS d7_retention_percent,
  ROUND(d30_users::decimal / cohort_size * 100, 2) AS d30_retention_percent,
  ROUND(
    CASE WHEN d7_users > 0
         THEN d30_users::decimal / d7_users * 100
         ELSE NULL
    END, 2
  ) AS d7_to_d30_conversion_percent,
  -- Additional analysis columns
  ROUND(
    (d30_users::decimal / cohort_size) - (d7_users::decimal / cohort_size), 2
  ) AS retention_change_d7_to_d30,
  CASE 
    WHEN d7_users::decimal / cohort_size > 0.4 THEN 'Above Target'
    WHEN d7_users::decimal / cohort_size > 0.3 THEN 'Near Target'
    ELSE 'Below Target'
  END AS d7_retention_status
FROM retention
WHERE cohort_size >= 5  -- Minimum cohort size for reliability
ORDER BY cohort_date DESC;
```

### **Conversion Interpretation**
- **d7_retention_percent**: % of cohort that returned on day 7
- **d30_retention_percent**: % of cohort that returned on day 30
- **d7_to_d30_conversion_percent**: "Of users who came back on D7, what % also came back on D30"
- **retention_change_d7_to_d30**: Net change in retention from D7 to D30

---

## 👥 **BEST PRACTICES FOR CROSS-DEVICE IDENTITY MERGING**

### **Identities Table for Cross-Device Resolution**
```sql
CREATE TABLE identities (
  raw_id     TEXT PRIMARY KEY,   -- device_id or temp ID
  user_id    TEXT NOT NULL,      -- canonical ID
  linked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,       -- Optional expiration for temp IDs
  
  INDEX idx_identities_user (user_id),
  INDEX idx_identities_expires (expires_at)
);
```

### **Identity Resolution Service**
```python
class IdentityService:
    def __init__(self):
        self.temp_id_prefix = "temp_"
    
    def get_canonical_user_id(self, raw_id, user_id=None):
        """Get canonical user_id for raw_id, creating mapping if needed"""
        
        if user_id:
            # Logged in user - create or update mapping
            self._link_identity(raw_id, user_id)
            return user_id
        else:
            # Anonymous user - get existing or create temp
            return self._get_or_create_temp_user(raw_id)
    
    def _link_identity(self, raw_id, canonical_user_id):
        """Link raw_id to canonical user_id"""
        sql = """
        INSERT INTO identities (raw_id, user_id, linked_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (raw_id) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          linked_at = EXCLUDED.linked_at
        """
        execute_sql(sql, (raw_id, canonical_user_id, datetime.utcnow()))
        
        # Log merge for audit
        self._log_identity_merge(raw_id, canonical_user_id)
    
    def _get_or_create_temp_user(self, raw_id):
        """Get existing temp user_id or create new one"""
        sql = "SELECT user_id FROM identities WHERE raw_id = %s"
        result = execute_sql(sql, (raw_id,))
        
        if result:
            return result[0]['user_id']
        else:
            temp_user_id = f"{self.temp_id_prefix}{raw_id}"
            self._link_identity(raw_id, temp_user_id)
            return temp_user_id
    
    def _log_identity_merge(self, raw_id, canonical_user_id):
        """Log identity merge for audit trail"""
        log_data = {
            "raw_id": raw_id,
            "canonical_user_id": canonical_user_id,
            "merge_time": datetime.utcnow().isoformat(),
            "merge_type": "login_link"
        }
        # Store in audit log table
        insert_audit_log("identity_merge", log_data)

# Global identity service instance
identity_service = IdentityService()
```

### **Event Processing with Identity Resolution**
```python
def process_incoming_event(raw_event):
    """Process event with identity resolution"""
    
    # Extract identifiers
    raw_id = raw_event.get('device_id') or raw_event.get('temp_id')
    user_id = raw_event.get('user_id')
    
    # Resolve canonical user_id
    canonical_user_id = identity_service.get_canonical_user_id(raw_id, user_id)
    
    # Build canonical event
    canonical_event = {
        "user_id": canonical_user_id,
        "device_id": raw_event.get('device_id'),
        "event_name": raw_event['event_name'],
        "event_time": raw_event['event_time'],
        "properties": raw_event.get('properties', {})
    }
    
    # Add identity metadata
    canonical_event['properties']['identity_resolution'] = {
        "raw_id": raw_id,
        "canonical_user_id": canonical_user_id,
        "resolved_at": datetime.utcnow().isoformat()
    }
    
    # Capture the event
    capture_event(
        user_id=canonical_event['user_id'],
        device_id=canonical_event['device_id'],
        event_name=canonical_event['event_name'],
        properties=canonical_event['properties']
    )
    
    return canonical_event

# Example usage
def handle_user_login(device_id, user_id):
    """Handle user login with identity resolution"""
    canonical_user_id = identity_service.get_canonical_user_id(device_id, user_id)
    
    # Fire first_active event if this is first meaningful use
    if not has_user_had_first_active(canonical_user_id):
        process_incoming_event({
            'device_id': device_id,
            'user_id': canonical_user_id,
            'event_name': 'user_first_active',
            'event_time': datetime.utcnow().isoformat() + "Z",
            'properties': {
                'login_method': 'authenticated',
                'platform': 'web'
            }
        })
```

### **Security Considerations**
```python
# Security rules for identity handling
SECURITY_RULES = {
    "no_pii_in_ids": True,  # Use internal stable IDs, not email/phone
    "backend_only_resolution": True,  # Keep resolution logic in backend
    "audit_all_merges": True,  # Log all identity merges
    "temp_id_expiration": "30 days",  # Expire temp IDs after 30 days
    "rate_limit_merges": "10 per minute per IP"  # Prevent abuse
}

def validate_identity_operation(raw_id, user_id, ip_address):
    """Validate identity operation for security"""
    
    # Check rate limiting
    if is_rate_limited(ip_address, "identity_merge"):
        raise SecurityError("Rate limit exceeded for identity operations")
    
    # Validate ID formats
    if not is_valid_id_format(raw_id) or not is_valid_id_format(user_id):
        raise SecurityError("Invalid ID format")
    
    # Check for PII in IDs
    if contains_pii(raw_id) or contains_pii(user_id):
        raise SecurityError("PII detected in ID")
    
    return True
```

---

## 🕐 **TIMEZONES AND EVENT_TIMESTAMP IN RETENTION QUERIES**

### **UTC Storage Strategy**
```sql
-- Always store timestamps in UTC
CREATE TABLE events (
  event_time TIMESTAMPTZ NOT NULL,  -- Always UTC
  -- Other fields...
);

-- Function to normalize timestamp to UTC
CREATE OR REPLACE FUNCTION normalize_to_utc(timestamp_str TEXT)
RETURNS TIMESTAMPTZ AS $$
BEGIN
    RETURN timestamp_str::TIMESTAMPTZ AT TIME ZONE 'UTC';
END;
$$ LANGUAGE plpgsql;

-- Trigger to ensure UTC normalization
CREATE OR REPLACE FUNCTION ensure_utc_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.event_time = NEW.event_time AT TIME ZONE 'UTC';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ensure_utc_timestamp
BEFORE INSERT OR UPDATE ON events
FOR EACH ROW EXECUTE FUNCTION ensure_utc_timestamp();
```

### **Consistent Cohort Day Calculation**
```sql
-- Always use UTC-based date truncation for cohorts
WITH user_first AS (
  SELECT
    user_id,
    MIN(event_time::date) AS cohort_date  -- UTC date
  FROM events
  WHERE event_name = 'user_first_active'
  GROUP BY user_id
),

activity AS (
  SELECT
    uf.user_id,
    uf.cohort_date,
    -- Calculate day offset in UTC
    (e.event_time::date - uf.cohort_date) AS day_offset,
    -- Alternative using date_trunc for precision
    EXTRACT(DAY FROM (e.event_time - uf.cohort_date)) AS day_offset_precise
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
)

SELECT
  cohort_date,
  COUNT(DISTINCT user_id) AS cohort_size,
  COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_users,
  COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_users
FROM activity
GROUP BY cohort_date
ORDER BY cohort_date DESC;
```

### **Timezone-Aware Reporting**
```python
def format_cohort_date_for_display(cohort_date, timezone='UTC'):
    """Format cohort date for display with timezone awareness"""
    
    if timezone == 'UTC':
        return cohort_date.strftime('%Y-%m-%d')
    else:
        # Convert UTC date to local timezone for display only
        import pytz
        utc = pytz.UTC
        target_tz = pytz.timezone(timezone)
        
        # Convert to local timezone
        utc_datetime = utc.localize(
            datetime.combine(cohort_date, datetime.min.time())
        )
        local_datetime = utc_datetime.astimezone(target_tz)
        
        return local_datetime.strftime('%Y-%m-%d (%Z)')

def generate_retention_report(start_date, end_date, timezone='UTC'):
    """Generate retention report with timezone-aware dates"""
    
    # Get cohort data (always in UTC)
    cohorts = get_cohort_analysis(start_date, end_date)
    
    report = f"""
# MERID Season 1 Retention Report
# Timezone: {timezone}
# Period: {start_date} to {end_date}

{'='*80}
## Cohort Analysis

| Cohort Date | Size | D7 Retention | D30 Retention | D7→D30 Conversion |
|------------|------|---------------|---------------|-------------------|
"""
    
    for cohort in cohorts:
        cohort_date_display = format_cohort_date_for_display(cohort['cohort_date'], timezone)
        report += f"| {cohort_date_display} | {cohort['cohort_size']} | {cohort['d7_retention']:.1f}% | {cohort['d30_retention']:.1f}% | {cohort['d7_to_d30_conversion']:.1f}% |\n"
    
    # Summary statistics
    avg_d7 = np.mean([c['d7_retention'] for c in cohorts])
    avg_d30 = np.mean([c['d30_retention'] for c in cohorts])
    avg_conversion = np.mean([c['d7_to_d30_conversion'] for c in cohorts])
    
    report += f"""
{'='*80}
## Summary

- Total Cohorts Analyzed: {len(cohorts)}
- Average D7 Retention: {avg_d7:.1f}%
- Average D30 Retention: {avg_d30:.1f}%
- Average D7→D30 Conversion: {avg_conversion:.1f}%
- All timestamps stored in UTC
- Display timezone: {timezone}
"""
    
    return report
```

### **Timezone Best Practices**
```python
# Timezone handling rules
TIMEZONE_RULES = {
    "storage_timezone": "UTC",  # Always store in UTC
    "calculation_timezone": "UTC",  # Always calculate in UTC
    "display_timezone": "user_local",  # Convert only for display
    "no_local_storage": True,  # Never store local timezone strings
    "utc_validation": True  # Validate all timestamps are UTC
}

def validate_utc_timestamp(timestamp_str):
    """Validate timestamp is in UTC format"""
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return timestamp.tzinfo == timezone.utc or timestamp_str.endswith('Z')
    except:
        return False

def normalize_event_timestamp(event_time):
    """Normalize any timestamp to UTC"""
    if isinstance(event_time, str):
        timestamp = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
    else:
        timestamp = event_time
    
    # Convert to UTC
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    
    return timestamp
```

---

## 🔄 **IMPLEMENTATION ROADMAP**

### **Week 1: Core Schema Setup**
- [ ] Create events table with UTC timestamps
- [ ] Implement canonical event definitions
- [ ] Set up identity resolution table
- [ ] Create event capture functions
- [ ] Test UTC timestamp normalization

### **Week 2: Cohort Analysis**
- [ ] Implement D7/D14/D30 SQL queries
- [ ] Build conversion analysis functions
- [ ] Create identity resolution service
- [ ] Test edge cases (multiple sessions, missing events)
- [ ] Validate timezone handling

### **Week 3: Identity Resolution**
- [ ] Implement cross-device identity merging
- [ ] Create security validation functions
- [ ] Set up audit logging for merges
- [ ] Test login/logout flows
- [ ] Validate rate limiting

### **Week 4: Production Integration**
- [ ] Integrate with governance engine
- [ ] Create automated retention reports
- [ ] Set up dashboard integration
- [ ] Test with real user data
- [ ] Document all processes

---

## 📋 **SUCCESS METRICS**

### **Technical Success**
- [ ] Single event schema implemented
- [ ] UTC timestamp handling consistent
- [ ] Identity resolution working correctly
- [ ] Cohort analysis SQL functional

### **Analytics Success**
- [ ] D7 core activation retention > 40%
- [ ] D7-D30 conversion analysis working
- [ ] Cross-device identity resolution functional
- [ ] Timezone handling consistent

### **Business Success**
- [ ] Early predictor validated
- [ ] Actionable insights generated
- [ ] Investor pack enhanced
- [ ] Product optimization recommendations provided

---

**🚀 This tight analytics implementation provides MERID Season 1 with: one simple event schema, one consistent cohorting pattern, and clear identity/time rules - all ready for direct implementation into the governance engine with minimal complexity and maximum reliability.**
