# Duplicate Configuration Files Archive

**Archived Date:** 2026-05-13
**Reason:** These are duplicate/backup versions of kalshi_agent_grid.yaml that are not referenced in the codebase

## Archived Files

### kalshi_agent_grid_clean.yaml
- **Purpose:** Clean version of agent grid (duplicate of main)
- **References:** Only in analysis/documentation files
- **Action:** Archived to reduce config file confusion

### kalshi_agent_grid_crypto_backup.yaml
- **Purpose:** Backup of crypto agent grid configuration
- **References:** Only in analysis/documentation files
- **Action:** Archived as backup no longer needed (git provides version control)

### kalshi_agent_grid_sports.yaml
- **Purpose:** Sports-specific agent grid configuration
- **References:** Only in analysis/documentation files
- **Action:** Archived as sports agents are not currently active

## Restoration

If any of these files need to be restored:
```bash
# Move back to config directory
mv archive/duplicate_configs/kalshi_agent_grid_clean.yaml config/
mv archive/duplicate_configs/kalshi_agent_grid_crypto_backup.yaml config/
mv archive/duplicate_configs/kalshi_agent_grid_sports.yaml config/
```

## Notes

- The canonical agent grid configuration is `config/kalshi_agent_grid.yaml`
- Git history provides proper version control for configuration changes
- Sports agents can be re-enabled by restoring the sports config if needed
