/**
 * GateFunnel — SVG flow of a CycleDecision through the canonical entry-gate
 * order: eligibility -> price -> moneyness -> tail_lcb -> ev -> slots ->
 * shard_collateral -> order.
 *
 * Truthfulness contract:
 *  - When `decision.gates` is present we render the real trace.
 *  - When absent we DERIVE the last known veto stage from rejection_reason
 *    keywords and label the whole thing 'derived' — never a fake full trace.
 */

import { memo, useMemo } from 'react';
import type { CycleDecision, GateStep } from '../../agents/types';

export type GateStatus = 'pass' | 'fail' | 'unknown';

const GATE_KEYS = [
  'eligibility', 'price', 'moneyness', 'tail_lcb', 'ev', 'slots', 'shard_collateral', 'order',
] as const;

const GATE_LABELS: Record<string, string> = {
  eligibility: 'ELIG',
  price: 'PRICE',
  moneyness: 'MONEY',
  tail_lcb: 'TAIL',
  ev: 'EV',
  slots: 'SLOTS',
  shard_collateral: 'SHARD',
  order: 'ORDER',
};

/** Map a free-form gate/reason string to a canonical gate index. */
function canonicalGateIndex(name: string): number {
  const r = name.toLowerCase().replace(/[\s-]+/g, '_');
  // Order matters: specific gates before generic ones.
  if (/shard|collateral|insufficient|fund/.test(r)) return 6;
  if (/tail|lcb/.test(r)) return 3;
  if (/moneyness|money|band|pocket|cap|strike/.test(r)) return 2;
  if (/slot|position|exposure|alloc/.test(r)) return 5;
  if (/^ev|edge|expect|threshold|net/.test(r)) return 4;
  if (/order|submit|route|size|qty|count/.test(r)) return 7;
  if (/price|quote|book|stale|spread|fresh|depth|watermark|feed/.test(r)) return 1;
  if (/elig|halt|enable|disable|guard|kill|circuit|market|active|final|window/.test(r)) return 0;
  return -1;
}

interface GateNode {
  key: string;
  label: string;
  status: GateStatus;
  detail?: string;
}

function deriveNodes(decision: CycleDecision | null | undefined): { nodes: GateNode[]; derived: boolean; failDetail?: string } {
  const nodes: GateNode[] = GATE_KEYS.map((k) => ({ key: k, label: GATE_LABELS[k], status: 'unknown' as GateStatus }));
  if (!decision) return { nodes, derived: false };

  // Real trace available?
  if (decision.gates && decision.gates.length > 0) {
    const byIdx = new Map<number, GateStep>();
    decision.gates.forEach((g, i) => {
      const idx = canonicalGateIndex(g.gate);
      byIdx.set(idx === -1 ? Math.min(i, GATE_KEYS.length - 1) : idx, g);
    });
    let failDetail: string | undefined;
    nodes.forEach((n, i) => {
      const g = byIdx.get(i);
      if (g) {
        n.status = g.passed ? 'pass' : 'fail';
        n.detail = g.detail;
        if (!g.passed && !failDetail) failDetail = g.detail ?? g.gate;
      }
    });
    return { nodes, derived: false, failDetail };
  }

  // Derived trace from action + rejection_reason.
  const action = (decision.action ?? '').toLowerCase();
  const isEnter = /enter|order|fill|buy/.test(action) && !/veto|reject|skip/.test(action);
  if (isEnter) {
    nodes.forEach((n) => { n.status = 'pass'; });
    return { nodes, derived: false };
  }
  const reason = decision.rejection_reason ?? '';
  const failIdx = reason ? canonicalGateIndex(reason) : -1;
  if (failIdx >= 0) {
    nodes.forEach((n, i) => {
      if (i < failIdx) n.status = 'pass';
      else if (i === failIdx) { n.status = 'fail'; n.detail = reason; }
    });
    return { nodes, derived: true, failDetail: reason };
  }
  if (/veto|reject|skip/.test(action) || reason) {
    // Vetoed but stage unknown — mark the eligibility gate as the last known.
    nodes[0].status = 'fail';
    nodes[0].detail = reason || 'veto (stage unknown)';
    return { nodes, derived: true, failDetail: reason || 'veto' };
  }
  return { nodes, derived: false };
}

const STATUS_STYLE: Record<GateStatus, { fill: string; stroke: string; text: string }> = {
  pass: { fill: 'rgba(16,185,129,0.14)', stroke: '#10b981', text: '#34d399' },
  fail: { fill: 'rgba(239,68,68,0.28)', stroke: '#ef4444', text: '#fca5a5' },
  unknown: { fill: 'rgba(100,116,139,0.08)', stroke: '#475569', text: '#64748b' },
};

interface GateFunnelProps {
  decision?: CycleDecision | null;
  /** svg width in px — the viewBox scales down gracefully. */
  width?: number;
  className?: string;
}

export const GateFunnel = memo(function GateFunnel({ decision, width = 620, className = '' }: GateFunnelProps) {
  const { nodes, derived, failDetail } = useMemo(() => deriveNodes(decision), [decision]);

  const nodeW = 64;
  const nodeH = 24;
  const gap = 12;
  const svgW = nodes.length * nodeW + (nodes.length - 1) * gap;
  const svgH = nodeH + 8;
  const scale = Math.min(1, width / svgW);
  const w = svgW * scale;
  const h = svgH * scale;

  return (
    <div className={className}>
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${svgW} ${svgH}`}
        role="img"
        aria-label={failDetail ? `decision gates, failed at ${failDetail}` : 'decision gate flow'}
      >
        {nodes.map((n, i) => {
          const x = i * (nodeW + gap);
          const st = STATUS_STYLE[n.status];
          return (
            <g key={n.key}>
              {i > 0 && (
                <line
                  x1={x - gap + 1}
                  x2={x - 1}
                  y1={4 + nodeH / 2}
                  y2={4 + nodeH / 2}
                  stroke={nodes[i - 1].status === 'pass' && n.status !== 'unknown' ? '#10b981' : '#334155'}
                  strokeWidth="1.5"
                />
              )}
              <rect
                x={x}
                y={4}
                width={nodeW}
                height={nodeH}
                rx={5}
                fill={st.fill}
                stroke={st.stroke}
                strokeWidth={n.status === 'fail' ? 1.8 : 1}
                strokeDasharray={n.status === 'unknown' ? '3 2' : undefined}
                style={n.status === 'fail' ? { filter: 'drop-shadow(0 0 5px rgba(239,68,68,0.6))' } : undefined}
              />
              <text
                x={x + nodeW / 2}
                y={4 + nodeH / 2}
                dy="0.32em"
                textAnchor="middle"
                fontSize="9"
                fontWeight="700"
                fill={st.text}
                className="tabular-nums"
              >
                {n.label}
              </text>
              {n.detail && (
                <title>{`${n.key}: ${n.detail}`}</title>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex items-center justify-between mt-0.5 text-[9px]">
        <span className={failDetail ? 'text-red-400/90' : 'text-slate-600'}>
          {failDetail ? `veto: ${failDetail}` : decision ? 'flow complete' : 'no decision data'}
        </span>
        {derived && (
          <span className="text-slate-600 italic">last known veto stage — derived</span>
        )}
      </div>
    </div>
  );
});

export default GateFunnel;
