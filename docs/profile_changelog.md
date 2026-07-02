# Kalshi Crypto 15m Profile Changelog

This document tracks all changes to `config/profiles/kalshi_crypto_15m.yaml` for reproducibility and change tracking.

## Version Format

Profile versions follow semantic versioning: `MAJOR.MINOR.PATCH`
- **MAJOR**: Breaking changes (e.g., risk model restructuring, parameter removal)
- **MINOR**: Feature additions or parameter tuning (e.g., Kelly fraction adjustment, edge threshold changes)
- **PATCH**: Bug fixes or documentation updates (no behavioral changes)

---

## v2.0.0 (2026-05-23)

### Summary
Baseline version for profile versioning enforcement. Added explicit `profile_version` field and startup validation.

### Changes
- **Added**: `profile_version: "2.0.0"` field to profile YAML
- **Added**: `validate_profile_version()` function in `merid/startup_validations.py`
- **Added**: Profile version logging to session snapshots
- **Added**: `GET /api/v1/config/profile_version` API endpoint
- **Added**: `docs/profile_changelog.md` for change tracking

### Rationale
- Enable reproducibility of trading runs by tagging each run with exact config version
- Prevent accidental config drift by validating profile version at startup
- Provide audit trail for parameter tuning decisions

### Breaking Changes
None (this is the baseline versioning change)

### Migration Notes
- No migration required for existing deployments
- Startup validation will log current profile version without blocking (expected_version is optional)

---

## v1.0.0 (2026-05-XX)

### Summary
Initial profile version (retroactively assigned). Original kalshi_crypto_15m_v2 profile configuration.

### Configuration
- Kelly fraction: 0.30
- Min edge mid: 2.0%
- Max cycle risk: 2.0%
- Drawdown halt: 10%
- Drawdown unwind: 5%
- Per-asset caps: BTC/ETH 25%, SOL/XRP/DOGE 10%

### Notes
- This version was used during initial live trading deployment
- Profile version field was not explicitly tracked in this version
- Assigned retroactively for changelog continuity

---

## Change Guidelines

When modifying `kalshi_crypto_15m.yaml`:

1. **Bump version** according to semantic versioning rules
2. **Add entry** to this changelog with:
   - Version number and date
   - Summary of changes
   - Specific parameter changes (before/after values)
   - Rationale for the change
   - Breaking changes (if any)
   - Migration notes (if applicable)
3. **Update expected version** in startup validation if enforcing strict versioning
4. **Commit snapshot** of the YAML to snapshots/ directory for rollback capability

### Example Entry Template

```markdown
## vX.Y.Z (YYYY-MM-DD)

### Summary
Brief description of the change.

### Changes
- **Modified**: `kelly_fraction` from 0.30 to 0.32
- **Added**: New parameter `deep_otm_threshold_cents: 40`
- **Removed**: Deprecated parameter `legacy_max_notional`

### Rationale
Explain why this change was made (e.g., based on fill-rate analysis, edge-rejection data, etc.)

### Breaking Changes
List any breaking changes that require migration.

### Migration Notes
Steps required to migrate from previous version.
```
