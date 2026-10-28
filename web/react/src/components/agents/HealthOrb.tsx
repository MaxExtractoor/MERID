/**
 * HealthOrb — big readable-at-distance agent health orb for the wallboard.
 * Ring color = agent state; center = asset glyph + eval heartbeat age.
 * Live operational states get a soft outer pulse (motion-safe only).
 */

import { memo } from 'react';
import type { AssetAgent } from '../../agents/types';
import { freshnessClass } from '../../agents/types';
import { ASSET_META, STATE_META, freshnessTextClass } from './agentMeta';
import { fmtAgeMs } from '../../agents/format';

interface HealthOrbProps {
  agent: AssetAgent;
  size?: number;
  onSelect?: (agent: AssetAgent) => void;
  className?: string;
}

export const HealthOrb = memo(function HealthOrb({ agent, size = 96, onSelect, className = '' }: HealthOrbProps) {
  const meta = STATE_META[agent.state];
  const assetMeta = ASSET_META[agent.asset];
  const evalCls = freshnessClass(agent.heartbeat.last_eval_ms);
  const ring = Math.max(3, size * 0.045);

  const inner = (
    <>
      <span
        className="relative inline-flex items-center justify-center rounded-full"
        style={{
          width: size,
          height: size,
          border: `${ring}px solid ${meta.hex}`,
          boxShadow: meta.pulse ? `0 0 ${size * 0.25}px ${meta.hex}55, inset 0 0 ${size * 0.18}px ${meta.hex}33` : `inset 0 0 ${size * 0.18}px ${meta.hex}22`,
          background: 'radial-gradient(circle at 35% 30%, rgba(30,41,59,0.9), rgba(2,6,23,0.95))',
        }}
      >
        {meta.pulse && (
          <span
            className="motion-safe:animate-ping absolute inset-0 rounded-full opacity-30"
            style={{ border: `${ring}px solid ${meta.hex}` }}
            aria-hidden="true"
          />
        )}
        <span className="flex flex-col items-center leading-none">
          <span className="font-bold tabular-nums" style={{ fontSize: size * 0.30, color: assetMeta.hex }}>
            {assetMeta.glyph}
          </span>
          <span className="text-slate-500 font-semibold tabular-nums" style={{ fontSize: size * 0.115 }}>
            {agent.asset}
          </span>
        </span>
      </span>
      <span className="flex flex-col items-center mt-1.5 leading-tight">
        <span className={`tabular-nums font-semibold ${freshnessTextClass(evalCls)}`} style={{ fontSize: size * 0.14 }}>
          {agent.heartbeat.last_eval_ms != null ? fmtAgeMs(agent.heartbeat.last_eval_ms) : 'n/a'}
        </span>
        <span className="text-slate-600" style={{ fontSize: size * 0.10 }}>
          {meta.label}
        </span>
      </span>
    </>
  );

  const cls = `inline-flex flex-col items-center ${className}`;
  if (onSelect) {
    return (
      <button
        type="button"
        onClick={() => onSelect(agent)}
        className={`${cls} rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500/50`}
        aria-label={`${agent.asset} agent, state ${meta.label}`}
      >
        {inner}
      </button>
    );
  }
  return <div className={cls} role="img" aria-label={`${agent.asset} agent, state ${meta.label}`}>{inner}</div>;
});

export default HealthOrb;
