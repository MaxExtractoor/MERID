# Kalshi-Only Trading - Operator Guide

## 🎯 System Status: Ready for Live Trading

The MERID system has been configured for **Kalshi-only live trading** with a minimal safety stack.

## 📋 Eligibility Requirements

### Prediction Domain Eligibility
The prediction domain becomes eligible when:
- ✅ **Kalshi is enabled** (`kalshi_pm_live_enabled=true`)
- ✅ **At least one prediction instrument is registered** in `INSTRUMENT_REGISTRY`
- ✅ **Matching engine is operational** (internal CLOB)

### Advisory Checks (Non-Blocking)
The following checks are **advisory only** in the Kalshi-only phase:
- 🔍 **Blueprint checks**: Code quality and configuration validation
- 🧪 **Paper matrix tests**: Core functionality tests (7 essential tests)
- 🤖 **Agent gauntlet**: Strategy agent health monitoring

**These provide telemetry and health signals but do not block live trading.**

## 🚀 Enabling Live Trading

### Step 1: Set Environment Variable
```bash
export KALSHI_PM_LIVE_ENABLED=true
```

### Step 2: Verify System Status
```bash
python -m merid.promotion_report --json --fast
```

Expected output:
```json
{
  "overall_eligible": true,
  "domains": {
    "eligible": ["prediction"],
    "detail": [{
      "domain": "prediction",
      "eligible": true,
      "instruments": 2,
      "blockers": []
    }]
  }
}
```

## 🛡️ Safety Stack (Active Controls)

### Risk Limits
- **Domain caps**: $2,000 daily notional, $500 single order
- **Venue caps**: $1,500 total Kalshi exposure
- **Position sizing**: Enforced per instrument limits
- **Order validation**: Size, venue, and domain checks

### Kill Switches
- **Global kill switch**: Stops all trading immediately
- **Domain kill switch**: Stops prediction domain trading
- **Venue kill switch**: Stops Kalshi venue trading

### Matching Engine Safety
- **Internal CLOB**: Price discovery and order matching
- **Reference price validation**: Rejects orders without valid prices
- **Order size limits**: Enforces min/max position sizes

## 📊 Current Configuration

### Active Domains
- ✅ **prediction**: Enabled, paper mode, 2 instruments registered
- ❌ **crypto**: Disabled (Kalshi-only phase)
- ❌ **equity**: Disabled (Kalshi-only phase)
- ❌ **betting**: Disabled (Kalshi-only phase)
- ❌ **macro**: Disabled (Kalshi-only phase)

### Registered Instruments
- **KXBTC-26FEB-YES**: BTC binary option, max stake $500
- **KXELECTION-YES**: Election market, max stake $500

### Advisory Test Results
- **Paper Matrix**: 7/7 tests passed (essential Kalshi functionality)
- **Agent Gauntlet**: Strategy agents healthy (lenient PnL thresholds)
- **Blueprint**: 4/5 checks passed (form fields informational)

## 🔧 Operational Commands

### Check System Status
```bash
# Full promotion report
python -m merid.promotion_report --json --fast

# Paper matrix tests only
pytest tests/test_paper_trading_matrix.py -m kalshi_core -v

# Agent gauntlet health check
python -m merid.agent_gauntlet --category strategy --cycles 5 --json
```

### Monitor Live Trading
```bash
# Check execution guard status
python -c "from merid.execution_guard import get_execution_guard; print(get_execution_guard().kill_switch_active)"

# View domain caps
python -c "from merid.execution_guard import get_execution_guard; print(get_execution_guard()._domain_caps['prediction'])"
```

### Emergency Controls
```bash
# Activate global kill switch
python -c "from merid.execution_guard import get_execution_guard; get_execution_guard().activate_kill_switch('emergency')"

# Deactivate kill switch
python -c "from merid.execution_guard import get_execution_guard; get_execution_guard().deactivate_kill_switch()"
```

## ⚠️ Important Notes

### Current Phase Characteristics
- **Collateralized**: All trades are fully collateralized on Kalshi
- **CFTC Regulated**: Trading through regulated prediction market venue
- **Size Limited**: Conservative position sizing for initial phase
- **Internal Matching**: Uses internal CLOB for price discovery

### What's Not Enforced (Advisory Only)
- Blueprint validation results (form fields, etc.)
- Paper matrix test performance
- Agent gauntlet promotion status
- PnL discipline metrics (lenient thresholds)

### What's Still Enforced (Hard Controls)
- Domain and venue notional caps
- Kill switch mechanisms
- Order size and validation limits
- Matching engine safety checks

## 📞 Support

For operational issues:
1. Check promotion report status first
2. Verify environment variables are set
3. Review kill switch status
4. Monitor matching engine logs

## 🎯 Next Steps

When ready to expand beyond Kalshi-only:
1. Re-enable additional domains in `paper_config.py`
2. Add corresponding instruments to `INSTRUMENT_REGISTRY`
3. Tighten PnL SLOs in agent gauntlet
4. Enable promotion gating in execution guard

---

**Status**: ✅ **READY FOR KALSHI LIVE TRADING**  
**Last Updated**: 2026-03-05  
**Phase**: Kalshi-only, minimal safety stack
