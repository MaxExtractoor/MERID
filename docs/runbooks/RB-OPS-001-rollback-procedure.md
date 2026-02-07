# RB-OPS-001: Rollback Procedure

**Last updated:** 2026-02-07
**Owner:** Operations
**Severity:** P1 — use when a deploy causes trading errors, data corruption, or service degradation

---

## Pre-requisites

- SSH access to production host (or local access for single-server deployment)
- `git` CLI available
- Ability to restart `merid-dev-swarm.service` via `systemctl`

---

## 1. Immediate Halt (< 30 seconds)

```bash
# Stop all trading immediately
curl -X POST http://localhost:8000/api/v1/pipeline/domain/halt -d '{"domain":"all"}'

# Or via kill switch in Operator Dashboard → DomainControlPanel
```

## 2. Identify the Bad Commit

```bash
cd /opt/merid  # or wherever MERID is deployed
git log --oneline -10
# Note the last known-good commit hash
```

## 3. Rollback Code

### Option A: Git revert (preferred — preserves history)

```bash
git revert HEAD --no-edit
# Or revert multiple commits:
git revert HEAD~3..HEAD --no-edit
```

### Option B: Git reset (fast — destructive)

```bash
git reset --hard <known-good-commit>
git push --force-with-lease origin develop
```

## 4. Restart Services

```bash
# Restart the main service
sudo systemctl restart merid-dev-swarm.service

# Verify it's running
sudo systemctl status merid-dev-swarm.service

# Check health
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

## 5. Verify Recovery

```bash
# Check trading is halted (should still be halted from step 1)
curl http://localhost:8000/api/v1/pipeline/summary | jq '.domains'

# Verify positions are intact
curl http://localhost:8000/api/v1/trading/portfolio/summary | jq '.positions'

# Check for errors in logs
journalctl -u merid-dev-swarm.service --since "5 minutes ago" | grep -i error
```

## 6. Resume Trading

Only after verifying all checks pass:

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/domain/resume -d '{"domain":"all"}'
```

## 7. Post-Rollback

- [ ] File a post-incident review (see `RB-OPS-002-post-incident-review.md`)
- [ ] Notify team via Telegram
- [ ] Update `CHANGELOG.md` with rollback details
- [ ] Create a fix branch from the reverted commit

---

## Backup Restore (if data is corrupted)

```bash
# List available snapshots
python -m ops.backup_restore list

# Restore from a snapshot
python -m ops.backup_restore restore --snapshot backups/merid-snapshot-<timestamp>

# Restart services after restore
sudo systemctl restart merid-dev-swarm.service
```

---

## Decision Matrix

| Symptom | Action |
|---------|--------|
| API errors after deploy | Rollback code (Option A) |
| Position data wrong | Restore from backup + rollback |
| Service won't start | `git reset --hard` to last tag + restart |
| Partial degradation | Halt affected domain only, investigate |
