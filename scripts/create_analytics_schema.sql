-- MERID Analytics Database Schema
-- Created: 2026-01-26
-- Purpose: Core analytics infrastructure for D0-D30 retention analysis

-- Events table for all user activity
CREATE TABLE IF NOT EXISTS events (
    user_id      TEXT NOT NULL,
    device_id    TEXT,
    event_name   TEXT NOT NULL,
    event_time   TIMESTAMPTZ NOT NULL,  -- always UTC
    properties   JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes for performance
    INDEX IF NOT EXISTS idx_events_user_time (user_id, event_time),
    INDEX IF NOT EXISTS idx_events_name_time (event_name, event_time),
    INDEX IF NOT EXISTS idx_events_device_time (device_id, event_time)
);

-- Identities table for cross-device resolution
CREATE TABLE IF NOT EXISTS identities (
    raw_id      TEXT PRIMARY KEY,   -- device_id or temp ID
    user_id     TEXT NOT NULL,      -- canonical ID
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,       -- Optional expiration for temp IDs
    
    INDEX IF NOT EXISTS idx_identities_user (user_id),
    INDEX IF NOT EXISTS idx_identities_expires (expires_at)
);

-- Audit log for identity merges (security sensitive)
CREATE TABLE IF NOT EXISTS identity_audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_id       TEXT NOT NULL,
    canonical_user_id TEXT NOT NULL,
    merge_time   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    merge_type   TEXT NOT NULL,  -- 'login_link', 'manual_merge', 'auto_merge'
    metadata     JSONB,
    
    INDEX IF NOT EXISTS idx_identity_audit_time (merge_time),
    INDEX IF NOT EXISTS idx_identity_audit_user (canonical_user_id)
);

-- UTC normalization trigger
CREATE OR REPLACE FUNCTION ensure_utc_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.event_time = NEW.event_time AT TIME ZONE 'UTC';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply UTC normalization trigger
DROP TRIGGER IF EXISTS ensure_utc_timestamp ON events;
CREATE TRIGGER ensure_utc_timestamp
BEFORE INSERT OR UPDATE ON events
FOR EACH ROW EXECUTE FUNCTION ensure_utc_timestamp();

-- Sample data for testing
INSERT INTO events (user_id, device_id, event_name, event_time, properties) VALUES
('u_12345', 'dev_abc', 'user_first_active', '2026-01-26T14:03:22Z', '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_789", "version": "v1.2.3"}'),
('u_12345', 'dev_abc', 'session_active', '2026-01-26T14:05:15Z', '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_789"}'),
('u_67890', 'dev_def', 'user_first_active', '2026-01-26T15:30:10Z', '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_790", "version": "v1.2.3"}'),
('u_67890', 'dev_def', 'session_active', '2026-01-26T15:32:45Z', '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_790"}'),
('u_12345', 'dev_abc', 'session_active', '2026-02-02T14:03:22Z', '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_791", "version": "v1.2.3"}'),
('u_12345', 'dev_abc', 'session_active', '2026-02-09T14:03:22Z', '{"platform": "web", "role": "operator", "env": "prod", "session_id": "sess_792", "version": "v1.2.3"}'),
('u_67890', 'dev_def', 'session_active', '2026-02-02T15:30:10Z', '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_793", "version": "v1.2.3"}'),
('u_67890', 'dev_def', 'session_active', '2026-02-09T15:30:10Z', '{"platform": "web", "role": "developer", "env": "prod", "session_id": "sess_794", "version": "v1.2.3"}');

-- Sample identity mappings
INSERT INTO identities (raw_id, user_id, linked_at) VALUES
('dev_abc', 'u_12345', '2026-01-26T14:03:22Z'),
('dev_def', 'u_67890', '2026-01-26T15:30:10Z'),
('temp_ghi', 'temp_user_ghi', '2026-01-26T16:00:00Z');

-- Sample audit log entries
INSERT INTO identity_audit_log (raw_id, canonical_user_id, merge_type, metadata) VALUES
('dev_abc', 'u_12345', 'login_link', '{"ip_address": "192.168.1.100", "user_agent": "Mozilla/5.0"}'),
('dev_def', 'u_67890', 'login_link', '{"ip_address": "192.168.1.101", "user_agent": "Mozilla/5.0"}');

COMMIT;
