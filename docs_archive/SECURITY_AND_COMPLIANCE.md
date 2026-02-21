# MERID Security & Compliance

> **Primary Module**: `security/secrets_manager.py`  
> **Test File**: `tests/test_sections_8_14.py`

---

## Overview

MERID's security model enforces a strict boundary: **LLM agents can USE secrets but never SEE them**. All credential access flows through the `SecretsManager`, which provides:

- Vault/HSM integration abstraction
- Per-service RBAC (agents have no direct access)
- Key rotation tracking and alerting
- Comprehensive audit logging
- Automatic telemetry redaction

---

## Core Principle: Agents Never Access Secrets

```
┌─────────────┐     ┌───────────────────┐     ┌─────────────┐
│  LLM Agent  │────▶│  Governed Service │────▶│   Secrets   │
│             │     │  (Venue Adapter)  │     │   Manager   │
└─────────────┘     └───────────────────┘     └─────────────┘
       │                     │                       │
       │   Cannot access     │   Can request         │
       │   secrets directly  │   via service_id      │
       └─────────────────────┴───────────────────────┘
```

---

## Secret Types

| Type | Description | Example |
|------|-------------|---------|
| `API_KEY` | Exchange/service API keys | `KRAKEN_API_KEY` |
| `SIGNING_KEY` | HMAC/signing secrets | `KRAKEN_SECRET` |
| `DATABASE_CREDENTIAL` | Database connection strings | `DATABASE_URL` |
| `ENCRYPTION_KEY` | Data encryption keys | `AES_KEY` |
| `OAUTH_TOKEN` | OAuth refresh tokens | `TWITTER_OAUTH` |
| `WEBHOOK_SECRET` | Webhook validation secrets | `TELEGRAM_WEBHOOK_SECRET` |

---

## Usage

### Registering Secrets

```python
from security.secrets_manager import SecretsManager, SecretType

manager = SecretsManager.get_instance()

# Register a secret (typically done at startup from env vars)
secret_id = await manager.register_secret(
    name="KRAKEN_API_KEY",
    value="your-api-key-here",
    secret_type=SecretType.API_KEY,
    allowed_services=["venue_adapter", "kraken_service"],
    rotation_days=90,
)
```

### Accessing Secrets (Services Only)

```python
# Only services can access secrets - agents cannot call this
value = await manager.get_secret(
    secret_id=secret_id,
    service_id="venue_adapter",
    purpose="order_signing",
)

if value is None:
    # Access denied or secret not found
    logger.error("Secret access denied")
```

### Using Secrets for Signing

```python
# Preferred method: use secret without exposing value
signature = await manager.use_secret_for_signing(
    secret_id=secret_id,
    service_id="venue_adapter",
    data_to_sign=order_payload.encode(),
)
```

---

## RBAC Tiers

### Access Levels

| Level | Can See Value | Can Use | Description |
|-------|---------------|---------|-------------|
| `NONE` | ❌ | ❌ | No access |
| `READ` | ✅ | ❌ | Read-only (debugging) |
| `USE` | ❌ | ✅ | Use through governed APIs |
| `FULL` | ✅ | ✅ | Full access (services only) |

### Service vs Agent Access

```python
# Services get full access to allowed secrets
manager.register_secret(
    name="KRAKEN_API_KEY",
    allowed_services=["venue_adapter"],  # Services listed here
    allowed_agents=[],  # Agents should NOT be listed
)

# Check if agent can use (not see) a secret
can_use = manager.agent_can_access("bull_primary", secret_id)
# Returns True only if explicitly granted USE permission

# Grant agent USE permission (rare, requires justification)
manager.grant_agent_access(
    agent_id="execution_agent",
    secret_id=secret_id,
    granted_by="admin",
)
```

---

## Key Rotation

### Tracking Rotation

```python
# Check which secrets need rotation
needing_rotation = manager.get_secrets_needing_rotation()
for meta in needing_rotation:
    print(f"Secret {meta['name']} needs rotation (last: {meta['last_rotated']})")
```

### Performing Rotation

```python
# Rotate a secret
success = await manager.rotate_secret(
    secret_id=secret_id,
    new_value="new-api-key-value",
    rotated_by="admin@merid.io",
)

if success:
    # Metadata updated, audit logged
    logger.info("Secret rotated successfully")
```

### Rotation Policy

| Secret Type | Default Rotation | Recommended |
|-------------|------------------|-------------|
| API keys | 90 days | 30-60 days |
| Signing keys | 90 days | 30 days |
| Database credentials | 90 days | 60 days |
| OAuth tokens | Varies | Per provider policy |

---

## Telemetry Redaction

**Critical**: Before sending any data to external logging or LLM training, redact sensitive content.

### Redacting Text

```python
text = 'api_key="sk_live_1234567890" password="hunter2"'
safe_text = manager.redact_sensitive_data(text)
# Output: 'api_key=REDACTED password=REDACTED'
```

### Redacting Dictionaries

```python
from security.secrets_manager import sanitize_for_logging

data = {
    "user": "admin",
    "api_key": "secret123",
    "config": {"password": "hunter2", "host": "localhost"},
}

safe_data = sanitize_for_logging(data)
# Output: {
#   "user": "admin",
#   "api_key": "REDACTED",
#   "config": {"password": "REDACTED", "host": "localhost"},
# }
```

### Redaction Patterns

The manager automatically redacts:
- `api_key`, `apikey`, `api-key`
- `secret`, `secret_key`
- `password`, `passwd`
- `token`, `bearer`
- `authorization`
- `credential`
- `private_key`, `signing_key`

---

## Audit Logging

Every secret access attempt is logged with full context.

### Viewing Audit Log

```python
# Get all audit entries
audit = manager.get_audit_log(limit=100)

# Filter by secret
audit = manager.get_audit_log(secret_id=secret_id)

# Filter by accessor
audit = manager.get_audit_log(accessor_id="venue_adapter")
```

### Audit Entry Fields

```json
{
  "audit_id": "audit_abc123",
  "secret_name": "KRAKEN_API_KEY",
  "accessor_type": "service",
  "accessor_id": "venue_adapter",
  "granted": true,
  "denial_reason": "",
  "timestamp": 1738750800.0
}
```

---

## Compliance Report

```python
report = manager.get_compliance_report()

# Output:
# {
#   "total_secrets": 10,
#   "secrets_needing_rotation": 2,
#   "rotation_compliance_rate": 0.8,
#   "total_access_attempts": 1500,
#   "access_denials": 12,
#   "denial_rate": 0.008,
#   "agents_with_access": 1,
# }
```

---

## Environment Variable Loading

At startup, load secrets from environment variables:

```python
from security.secrets_manager import load_secrets_from_env

await load_secrets_from_env()
# Loads: KRAKEN_API_KEY, COINBASE_API_KEY, OPENAI_API_KEY, etc.
# Each mapped to appropriate services
```

### Expected Environment Variables

| Variable | Type | Allowed Services |
|----------|------|------------------|
| `KRAKEN_API_KEY` | API_KEY | venue_adapter, kraken_service |
| `KRAKEN_SECRET` | SIGNING_KEY | venue_adapter, kraken_service |
| `COINBASE_API_KEY` | API_KEY | venue_adapter, coinbase_service |
| `KALSHI_API_KEY` | API_KEY | venue_adapter, kalshi_service |
| `OPENAI_API_KEY` | API_KEY | llm_service |
| `ANTHROPIC_API_KEY` | API_KEY | llm_service |
| `TELEGRAM_BOT_TOKEN` | API_KEY | telegram_bot |
| `TWITTER_API_KEY` | API_KEY | twitter_bot |

---

## Security Checklist

- [ ] All secrets loaded via `SecretsManager`, never hardcoded
- [ ] No agents listed in `allowed_services`
- [ ] Telemetry redacted before external logging
- [ ] Rotation alerts configured
- [ ] Audit log reviewed weekly
- [ ] Access denials investigated

---

*See also*: `docs/PROGRESS_CHECKPOINT_2026-02-05.md` for full module context.
