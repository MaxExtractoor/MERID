# 📊 **MERID SEASON 1 ANALYTICS IMPLEMENTATION SPEC**
**Last Updated:** 2026-01-26  
**Target:** Implementation-Ready Analytics for D0-D30 Retention Analysis

---

## 🎯 **EVENT NAMES AND PROPERTIES FOR D0-D30 COHORTS**

### **Core Events Definition**
```python
# Event schema for MERID analytics
EVENT_DEFINITIONS = {
    "user_first_active": {
        "description": "User's first meaningful use (defines D0)",
        "triggers": [
            "dashboard_load_complete",
            "session_duration > 60s",
            "user_authenticated"
        ],
        "defines_cohort": True,
        "frequency": "once_per_user"
    },
    "session_active": {
        "description": "User reaches active state in session",
        "triggers": [
            "main_dashboard_fully_loaded",
            "key_screen_viewed",
            "meaningful_interaction"
        ],
        "used_for_retention": True,
        "frequency": "once_per_session"
    },
    "core_value_experienced": {
        "description": "User experiences core value sequence",
        "triggers": [
            "dashboard_with_real_data_loaded",
            "mode_and_risk_banners_viewed",
            "positions_or_shadow_pnl_inspected"
        ],
        "used_for_segmentation": True,
        "frequency": "once_per_user_per_session"
    }
}
```

### **Common Properties Schema**
```sql
-- Events table with consistent properties
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL,           -- Canonical user ID (post-merge)
    device_id VARCHAR,                   -- Raw device ID for diagnostics
    event_time TIMESTAMP WITH TIME ZONE NOT NULL,  -- UTC timestamp
    event_name VARCHAR NOT NULL,          -- Event name
    properties JSONB,                    -- Additional event properties
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Indexes for performance
    INDEX idx_events_user_time (user_id, event_time),
    INDEX idx_events_name_time (event_name, event_time),
    INDEX idx_events_device_time (device_id, event_time)
);

-- Materialized view for user first activity
CREATE MATERIALIZED VIEW user_first_active AS
SELECT 
    user_id,
    MIN(event_time::date) AS cohort_date,
    MIN(CASE WHEN event_name = 'core_value_experienced' 
         THEN event_time::date END) AS first_core_value_date,
    MIN(device_id) AS first_device_id,
    MIN(properties->>'platform') AS first_platform
FROM events 
WHERE event_name = 'user_first_active'
GROUP BY user_id;

-- Refresh function for materialized view
CREATE OR REPLACE FUNCTION refresh_user_first_active()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW user_first_active;
END;
$$ LANGUAGE plpgsql;
```

### **Event Capture Implementation**
```python
def capture_analytics_event(user_id, event_name, properties=None, device_id=None):
    """Capture analytics event with proper validation"""
    
    # Validate required fields
    if not user_id:
        raise ValueError("user_id is required")
    
    if not event_name:
        raise ValueError("event_name is required")
    
    # Validate event name
    if event_name not in EVENT_DEFINITIONS:
        raise ValueError(f"Unknown event: {event_name}")
    
    # Build event data
    event_data = {
        "user_id": user_id,
        "event_name": event_name,
        "event_time": datetime.utcnow().isoformat() + "Z",  # UTC timestamp
        "properties": properties or {},
        "device_id": device_id
    }
    
    # Insert into events table
    insert_event_into_database(event_data)
    
    # Handle special events
    if event_name == "user_first_active":
        update_user_first_active(user_id, datetime.utcnow())
    elif event_name == "core_value_experienced":
        update_user_core_value(user_id, datetime.utcnow())

def update_user_first_active(user_id, event_time):
    """Update user_first_active materialized view data"""
    # This would trigger a refresh of the materialized view
    schedule_materialized_view_refresh()

def update_user_core_value(user_id, event_time):
    """Update user core value experience"""
    sql = """
    UPDATE user_first_active 
    SET first_core_value_date = %s
    WHERE user_id = %s
    """
    execute_sql(sql, (event_time.date(), user_id))

def schedule_materialized_view_refresh():
    """Schedule materialized view refresh"""
    # This would be called periodically (e.g., every hour)
    execute_sql("SELECT refresh_user_first_active()")
```

---

## 📈 **EXACT SQL COHORT WINDOWING FOR D7 AND D14**

### **Complete SQL Implementation**
```sql
-- D7 and D14 cohort analysis with precise windowing
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
    (e.event_time::date - uf.cohort_date) AS day_offset,
    e.event_time,
    e.properties
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
),

retention_summary AS (
  SELECT
    cohort_date,
    COUNT(DISTINCT user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_users,
    COUNT(DISTINCT CASE WHEN day_offset = 14 THEN user_id END) AS d14_users,
    COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_users
  FROM activity
  GROUP BY cohort_date
)

SELECT
  cohort_date,
  cohort_size,
  d7_users,
  d14_users,
  d30_users,
  ROUND(d7_users::decimal / cohort_size * 100, 2) AS d7_retention_percent,
  ROUND(d14_users::decimal / cohort_size * 100, 2) AS d14_retention_percent,
  ROUND(d30_users::decimal / cohort_size * 100, 2) AS d30_retention_percent,
  ROUND(
    CASE WHEN d7_users > 0
         THEN d30_users::decimal / d7_users * 100
         ELSE NULL
    END, 2
  ) AS d7_to_d14_conversion_percent
FROM retention_summary
ORDER BY cohort_date DESC;
```

### **Core Value Segmentation**
```sql
-- D7/D14/D30 retention for users who experienced core value
WITH user_first AS (
  SELECT
    user_id,
    MIN(event_time::date) AS cohort_date
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
      AND e.event_time::date = uf.cohort_date
  )
),

activity AS (
  SELECT
    cvu.user_id,
    cvu.cohort_date,
    (e.event_time::date - cvu.cohort_date) AS day_offset
  FROM core_value_users cvu
  JOIN events e
    ON e.user_id = cvu.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN cvu.cohort_date
                               AND cvu.cohort_date + INTERVAL '30 days'
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
  ROUND(d7_core_users::decimal / core_value_cohort_size * 100, 2) AS d7_core_retention_percent,
  ROUND(d14_core_users::decimal / core_value_cohort_size * 100, 2) AS d14_core_retention_percent,
  ROUND(d30_core_users::decimal / core_value_cohort_size * 100, 2) AS d30_core_retention_percent,
  ROUND(
    CASE WHEN d7_core_users > 0
         THEN d30_core_users::decimal / d7_core_users * 100
         ELSE NULL
    END, 2
  ) AS d7_core_to_d30_conversion_percent
FROM core_value_retention
ORDER BY cohort_date DESC;
```

---

## 📊 **SQL TO COMPUTE D7 → D30 RETENTION CONVERSION**

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
    (e.event_time::date - uf.cohort_date) AS day_offset,
    e.event_time,
    e.properties
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
),

retention AS (
  SELECT
    cohort_date,
    COUNT(DISTINCT user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN day_offset = 7  THEN user_id END) AS d7_users,
    COUNT(DISTINCT CASE WHEN day_offset = 30 THEN user_id END) AS d30_users
  FROM activity
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
    CASE 
      WHEN d7_users > 0 
      THEN d30_users::decimal / d7_users * 100
      ELSE NULL 
    END, 2
  ) AS d7_to_d30_conversion_percent,
  -- Additional metrics for analysis
  ROUND(
    (d30_users::decimal / cohort_size) - (d7_users::decimal / cohort_size), 2
  ) AS retention_change_d7_to_d30,
  CASE 
    WHEN d7_users::decimal / cohort_size > 0.4 THEN 'Above Target'
    WHEN d7_users::decimal / cohort_size > 0.3 THEN 'Near Target'
    ELSE 'Below Target'
    END AS d7_retention_status,
  CASE 
    WHEN d30_users::decimal / cohort_size > 0.25 THEN 'Above Target'
    WHEN d30_users::decimal / cohort_size > 0.15 THEN 'Near Target'
    ELSE 'Below Target'
    END AS d30_retention_status
FROM retention
ORDER BY cohort_date DESC;
```

### **Conversion Analysis with Confidence Intervals**
```sql
-- D7→D30 conversion with Wilson confidence intervals
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

retention_counts AS (
  SELECT
    uf.cohort_date,
    COUNT(DISTINCT uf.user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN day_offset = 7  THEN uf.user_id END) AS d7_users,
    COUNT(DISTINCT CASE WHEN day_offset = 30 THEN uf.user_id END) AS d30_users
  FROM user_first uf
  JOIN activity a
    ON a.user_id = uf.user_id
   AND a.day_offset IN (7, 30)
  GROUP BY uf.cohort_date
),

-- Wilson score interval calculation
conversion_stats AS (
  SELECT
    cohort_date,
    cohort_size,
    d7_users,
    d30_users,
    d7_users::decimal / cohort_size AS d7_retention,
    d30_users::decimal / cohort_size AS d30_retention,
    d30_users::decimal / NULLIF(d7_users, 1) AS d7_to_d30_conversion,
    -- Wilson interval for conversion rate
    CASE 
      WHEN d7_users > 0 AND d30_users > 0
      THEN (
        (d30_users::decimal / d7_users) + 
        1.96 * 1.96 * SQRT(
          (d30_users::decimal / d7_users) * (1 - (d30_users::decimal / d7_users)) / d7_users +
          1.96**2 / (4 * d7_users**2)
        ) / (
          1 + 1.96**2 / d7_users
        )
      ELSE NULL
    END AS conversion_wilson_lower,
    CASE 
      WHEN d7_users > 0 AND d30_users > 0
      THEN (
        (d30_users::decimal / d7_users) + 
        1.96 * 1.96 * SQRT(
          (d30_users::decimal / d7_users) * (1 - (d30_users::decimal / d7_users)) / d7_users +
          1.96**2 / (4 * d7_users**2)
        ) / (
          1 + 1.96**2 / d7_users
        )
      ELSE NULL
    END AS conversion_wilson_upper
  FROM retention_counts
)

SELECT
  cohort_date,
  cohort_size,
  d7_users,
  d30_users,
  ROUND(d7_retention * 100, 2) AS d7_retention_percent,
  ROUND(d30_retention * 100, 2) AS d30_retention_percent,
  ROUND(d7_to_d30_conversion * 100, 2) AS d7_to_d30_conversion_percent,
  ROUND(conversion_wilson_lower * 100, 2) AS conversion_ci_lower,
  ROUND(conversion_wilson_upper * 100, 2) AS conversion_ci_upper,
  ROUND(conversion_wilson_upper - conversion_wilson_lower, 2) AS conversion_ci_width
FROM conversion_stats
WHERE cohort_size >= 10  -- Minimum cohort size for reliable statistics
ORDER BY cohort_date DESC;
```

---

## 👥 **HANDLING MULTIPLE DEVICES AND MERGED USER IDS**

### **Identity Resolution Strategy**
```python
# Identity resolution for device-to-user mapping
class IdentityResolver:
    def __init__(self):
        self.identity_map = {}  # device_id -> user_id mapping
        self.user_devices = {}  # user_id -> set of device_ids
    
    def resolve_user_id(self, device_id, user_id=None):
        """Resolve or create canonical user_id"""
        
        if user_id:
            # Logged in user - update mapping
            if device_id in self.identity_map:
                old_user_id = self.identity_map[device_id]
                if old_user_id != user_id:
                    self._merge_user_data(old_user_id, user_id)
            
            self.identity_map[device_id] = user_id
            self.user_devices.setdefault(user_id, set()).add(device_id)
            return user_id
        
        else:
            # Anonymous user - return existing or create temporary
            return self.identity_map.get(device_id, f"temp_{device_id}")
    
    def _merge_user_data(self, old_user_id, new_user_id):
        """Merge data from old user_id to new user_id"""
        # Reattribute past events
        update_events_user_id(old_user_id, new_user_id)
        
        # Update device mappings
        for device_id, mapped_user_id in self.identity_map.items():
            if mapped_user_id == old_user_id:
                self.identity_map[id] = new_user_id
        
        # Update user devices mapping
        if old_user_id in self.user_devices:
            self.user_devices[new_user_id] = self.user_devices[old_user_id]
            del self.user_devices[old_user_id]
    
    def get_canonical_user_id(self, device_id):
        """Get canonical user_id for device"""
        return self.identity_map.get(device_id)

# Global identity resolver instance
identity_resolver = IdentityResolver()
```

### **Event Processing with Identity Resolution**
```python
def process_incoming_event(raw_event):
    """Process incoming event with identity resolution"""
    
    # Extract device_id and user_id from raw event
    device_id = raw_event.get('device_id')
    user_id = raw_event.get('user_id')
    
    # Resolve canonical user_id
    canonical_user_id = identity_resolver.resolve_user_id(device_id, user_id)
    
    # Build canonical event
    canonical_event = {
        'user_id': canonical_user_id,
        'device_id': device_id,
        'event_time': raw_event['event_time'],
        'event_name': raw_event['event_name'],
        'properties': raw_event.get('properties', {})
    }
    
    # Add identity metadata
    canonical_event['properties']['identity_resolution'] = {
        'original_user_id': user_id,
        'canonical_user_id': canonical_user_id,
        'device_id': device_id
    }
    
    # Capture the canonical event
    capture_analytics_event(
        user_id=canonical_user_id,
        event_name=canonical_event['event_name'],
        properties=canonical_event['properties'],
        device_id=device_id
    )
    
    return canonical_event

def update_events_user_id(old_user_id, new_user_id):
    """Update existing events to use new canonical user_id"""
    sql = """
    UPDATE events 
    SET user_id = %s
    WHERE user_id = %s
    """
    execute_sql(sql, (new_user_id, old_user_id))

# Example usage in event processing pipeline
def handle_user_login(device_id, user_id):
    """Handle user login with identity resolution"""
    canonical_user_id = identity_resolver.resolve_user_id(device_id, user_id)
    
    # Fire first_active event if this is the first meaningful use
    if not has_user_had_first_active(canonical_user_id):
        capture_analytics_event(
            user_id=canonical_user_id,
            event_name='user_first_active',
            properties={'login_method': 'authenticated'},
            device_id=device_id
        )
```

### **SQL with Identity Resolution**
```sql
-- Ensure events table has canonical user_id
-- All queries should use canonical user_id, not device_id

-- Identity map table for device-to-user resolution
CREATE TABLE identity_map (
    device_id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME Zone DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    
    INDEX idx_identity_map_user (user_id),
    INDEX idx_identity_map_expires (expires_at)
);

-- Function to get canonical user_id
CREATE OR REPLACE FUNCTION get_canonical_user_id(device_id VARCHAR)
RETURNS VARCHAR AS $$
BEGIN
    RETURN (
        SELECT user_id 
        FROM identity_map 
        WHERE device_id = %s
          AND (expires_at IS NULL OR expires_at > NOW())
    );
END;
$$ LANGUAGE plpgsql;

-- Updated cohort query with identity resolution
WITH user_first AS (
  SELECT
    get_canonical_user_id(e.device_id) AS user_id,
    MIN(e.event_time::date) AS cohort_date
  FROM events e
  WHERE e.event_name = 'user_first_active'
    AND get_canonical_user_id(e.device_id) IS NOT NULL
  GROUP BY get_canonical_user_id(e.device_id)
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

---

## 🕐 **EVENT TIMESTAMP AND TIMEZONE BEST PRACTICES**

### **UTC Storage Strategy**
```sql
-- Events table with UTC timestamp storage
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL,
    device_id VARCHAR,
    event_time TIMESTAMP WITH TIME ZONE NOT NULL,  -- Always UTC
    event_name VARCHAR NOT NULL,
    properties JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Indexes for performance
    INDEX idx_events_user_time (user_id, event_time),
    INDEX idx_events_name_time (event_name, event_time),
    INDEX idx_events_device_time (device_id, event_time)
);

-- Function to normalize timestamp to UTC
CREATE OR REPLACE FUNCTION normalize_to_utc(timestamp_with_tz TIMESTAMP WITH TIME ZONE)
RETURNS TIMESTAMP WITH TIME ZONE AS $$
BEGIN
    RETURN timestamp_with_tz AT TIME ZONE 'UTC';
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically normalize timestamps
CREATE OR REPLACE FUNCTION normalize_event_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.event_time = normalize_to_utc(NEW.event_time);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to events table
CREATE TRIGGER normalize_event_timestamp
BEFORE INSERT OR UPDATE ON events
FOR EACH ROW EXECUTE FUNCTION normalize_event_timestamp();
```

### **Consistent Cohort Date Calculation**
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
    EXTRACT(EPOCH FROM (e.event_time AT TIME ZONE 'UTC')) - 
    EXTRACT(EPOCH FROM (uf.cohort_date AT TIME ZONE 'UTC')) AS day_offset_seconds,
    -- Convert to days for readability
    FLOOR(
      EXTRACT(EPOCH FROM (e.event_time AT TIME ZONE 'UTC')) / 86400
    ) AS day_offset
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
        # Convert UTC date to local timezone for display
        import pytz
        utc = pytz.UTC
        target_tz = pytz.timezone(timezone)
        local_date = utc.localize(cohort_date).cast(target_tz)
        return local_date.strftime('%Y-%m-%d (%Z)')

def generate_retention_report(start_date, end_date, timezone='UTC'):
    """Generate retention report with timezone-aware dates"""
    
    # Get cohort data
    cohorts = get_cohort_analysis(start_date, end_date)
    
    report = f"""
# MERID Season 1 Retention Report
# Timezone: {timezone}
# Period: {start_date} to {end_date}

{'='*80}
{'='*80}
## Cohort Analysis

| Cohort Date | Size | D7 Retention | D30 Retention | D7→D30 Conversion |
|------------|------|---------------|---------------|-------------------|
"""
    
    for cohort in cohorts:
        cohort_date_display = format_cohort_date_for_display(cohort['cohort_date'], timezone)
        report += f"| {cohort_date_display} | {cohort['cohort_size']} | {cohort['d7_retention']:.1f}% | {cohort['d30_retention']:.1f}% | {cohort['d7_to_d30_conversion']:.1f}% |\n"
    
    report += f"""
{'='*80}
{'='*80}
## Summary

- Total Cohorts Analyzed: {len(cohorts)}
- Average D7 Retention: {np.mean([c['d7_retention'] for c in cohorts]):.1f}%
- Average D30 Retention: {np.mean([c['d30_retention'] for c in cohorts]):.1f}%
- Average D7→D30 Conversion: {np.mean([c['d7_to_d30_conversion'] for c in cohorts]):.1f}%
"""
    
    return report
```

---

## 🔄 **IMPLEMENTATION ROADMAP**

### **Week 1: Event Schema Setup**
- [ ] Create events table with proper UTC timestamps
- [ ] Implement canonical event definitions
- [ ] Build user_first_active materialized view
- [ ] Set up identity resolution system
- [ ] Create event capture functions

### **Week 2: Cohort Analysis Pipeline**
- [ ] Implement D7/D14/D30 SQL queries
- [ ] Build confidence interval calculations
- [ ] Create conversion analysis functions
- [ ] Set up automated materialized view refresh
- [ ] Test with sample data

### **Week 3: Identity Resolution**
- [ ] Implement device-to-user mapping
- [ ] Create identity resolution functions
- [ ] Update event processing pipeline
- [ ] Handle user login/logout flows
- [ ] Test with multiple device scenarios

### **Week 4: Timezone and Reporting**
- [ ] Implement UTC timestamp normalization
- [ ] Create timezone-aware reporting functions
- [ ] Build automated retention reports
- [ ] Set up dashboard integration
- [ ] Validate timezone handling

---

## 📋 **SUCCESS METRICS**

### **Technical Success**
- [ ] Event schema implemented with UTC timestamps
- [ ] Identity resolution system functional
- [ ] Cohort analysis SQL working correctly
- [ ] Confidence intervals calculated accurately

### **Analytics Success**
- [ ] D7 core activation retention > 40%
- [ ] D7-D30 correlation > 0.7
- [ ] Conversion analysis with confidence intervals
- [ ] Timezone handling consistent

### **Business Success**
- [ ] Early predictor validated statistically
- [ ] Actionable insights generated
- [ ] Investor pack enhanced with rigorous metrics
- [ ] Product optimization recommendations provided

---

**🚀 This specification provides MERID Season 1 with implementation-ready analytics: precise event definitions for D0-D30 lifecycle, exact SQL for D7/D14/D30 cohort windowing, complete D7→D30 conversion analysis, robust identity resolution for multiple devices, and UTC timestamp handling with timezone awareness - all ready for direct implementation into the analytics pipeline.**
