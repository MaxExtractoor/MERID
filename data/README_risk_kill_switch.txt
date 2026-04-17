risk_kill_switch.json — operational state (not configuration)

This file is written by merid.risk.kill_switches.RiskController when the global
kill switch changes. On process startup it is reloaded so an operator-triggered
halt survives restarts (fail-safe).

The copy committed in git must keep "active": false. Do not commit "active": true;
CI enforces this. Production servers may flip active at runtime; use dashboard
reset or risk_controller.reset() to clear before trading.

Override path: MERID_RISK_KS_FILE (default: data/risk_kill_switch.json).
