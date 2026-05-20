# Legacy Agent Specification Files

**Archived Date:** 2026-05-13
**Reason:** These files contain implementation logic that duplicates configuration already available in the profile system and agent grid

## Status: NOT YET ARCHIVED

These files are **still in use** and cannot be archived until the agent implementations are refactored to use profile-based configuration instead.

### Files to Archive (Future)

- `config/kalshi_btc_15m_agent_spec.py` - Used by merid/agents/btc_15m_agent.py
- `config/eth_15m_agent_spec.py` - Used by merid/agents/eth_15m_agent.py
- `config/sol_15m_agent_spec.py` - Used by merid/agents/sol_15m_agent.py
- `config/xrp_15m_agent_spec.py` - Used by merid/agents/xrp_15m_agent.py
- `config/doge_15m_agent_spec.py` - Used by merid/agents/doge_15m_agent.py

### Migration Path

These agent spec files contain:
1. **Configuration data** (risk limits, edge thresholds) - Should come from profile
2. **Implementation logic** (signal generation, risk rules) - Should be in agent implementation

The migration requires:
1. Move all configuration data to `config/profiles/kalshi_crypto_15m.yaml`
2. Move implementation logic into the agent implementation files
3. Update agent imports to use profile for config, internal classes for logic

### Dependencies

- Agent implementations must be refactored first
- Profile system must be fully adopted
- Tests must be updated to use profile-based configuration

## Restoration

If archived in the future, restore with:
```bash
mv archive/legacy_agent_specs/*.py config/
```
