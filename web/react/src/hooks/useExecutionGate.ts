import { useKalshiStore, selectRisk, selectSystem, selectConnected } from '../store';

export interface BlockReason {
  source: string;
  severity: 'critical' | 'warning';
  message: string;
  details: string | null;
  hint: string | null;
}

export type GateState = 'clear' | 'limited' | 'blocked';

/**
 * Execution gate derived from shared store state — no endpoint of its own
 * (the old /api/v1/system/execution-gate never existed on the lean app).
 *
 * blocked  = a critical reason is active (live entries halted, kill switch)
 * limited  = warning only (backend unreachable — controls may still render
 *            but submissions will fail server-side)
 * clear    = nothing blocking
 */
export function useExecutionGate() {
  const risk = useKalshiStore(selectRisk);
  const system = useKalshiStore(selectSystem);
  const connected = useKalshiStore(selectConnected);

  const reasons: BlockReason[] = [];
  if (system.live?.entry_halted) {
    reasons.push({
      source: 'runtime',
      severity: 'critical',
      message: 'Live entries halted',
      details: system.live.reason ?? null,
      hint: 'Release via the Risk view after investigating the cause',
    });
  }
  if (risk.kill_switch_active) {
    reasons.push({
      source: 'kill_switch',
      severity: 'critical',
      message: 'Kill switch active',
      details: risk.kill_switch_reason || null,
      hint: 'Reset via the Risk view kill switch control',
    });
  }
  if (!connected) {
    reasons.push({
      source: 'connection',
      severity: 'warning',
      message: 'Backend unreachable — data may be stale',
      details: null,
      hint: null,
    });
  }

  const blocked = reasons.some((r) => r.severity === 'critical');
  const gateState: GateState = blocked ? 'blocked' : reasons.length ? 'limited' : 'clear';
  const topHint = reasons.find((r) => r.hint)?.hint ?? null;

  return {
    blocked,
    safeToTrade: gateState === 'clear',
    gateState,
    reasons,
    blockSummary: reasons.map((r) => r.message).join('; ') || 'No blocks',
    topHint,
  };
}
