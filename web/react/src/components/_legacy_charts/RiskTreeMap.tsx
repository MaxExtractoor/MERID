/**
 * Risk TreeMap Widget
 *
 * Hierarchical heatmap where tile size ~ exposure, color ~ PnL.
 * Uses Recharts Treemap with data from /api/metrics/heatmap.
 */

import { useMemo } from 'react';
import { ResponsiveContainer, Treemap } from 'recharts';
import { LayoutGrid } from 'lucide-react';
import { useApiData } from '../../hooks/useApiData';

interface HeatmapInstrument {
  symbol: string;
  pnl: number;
  exposure: number;
  side: string;
  risk_pct: number;
}

interface HeatmapData {
  sectors: Record<string, HeatmapInstrument[]>;
  sector_count: number;
  instrument_count: number;
}

interface RiskTreeMapProps {
  className?: string;
  height?: number;
}

function pnlToColor(pnl: number): string {
  if (pnl > 500) return '#059669';   // emerald-600
  if (pnl > 100) return '#10b981';   // emerald-500
  if (pnl > 0) return '#34d399';     // emerald-400
  if (pnl === 0) return '#475569';   // slate-600
  if (pnl > -100) return '#fb7185';  // rose-400
  if (pnl > -500) return '#f43f5e';  // rose-500
  return '#e11d48';                   // rose-600
}

interface TreemapContentProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  pnl?: number;
  exposure?: number;
}

// Custom content renderer for treemap tiles
function CustomContent({ x = 0, y = 0, width = 0, height = 0, name = '', pnl = 0, exposure = 0 }: TreemapContentProps) {

  if (width < 30 || height < 20) return null;

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={4}
        fill={pnlToColor(pnl)}
        stroke="#1e293b"
        strokeWidth={2}
      />
      {width > 40 && height > 25 && (
        <>
          <text
            x={x + 6}
            y={y + 14}
            fill="white"
            fontSize={11}
            fontWeight="bold"
          >
            {name}
          </text>
          {height > 40 && (
            <text
              x={x + 6}
              y={y + 28}
              fill="rgba(255,255,255,0.7)"
              fontSize={9}
            >
              {pnl >= 0 ? '+' : ''}{pnl.toFixed(0)} · ${exposure.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </text>
          )}
        </>
      )}
    </g>
  );
}

export function RiskTreeMap({ className = '', height = 260 }: RiskTreeMapProps) {
  const { data, loading } = useApiData<HeatmapData>(
    '/api/metrics/heatmap',
    { pollingInterval: 15000 },
  );

  // Transform to Recharts Treemap format
  const treeData = useMemo(() => {
    if (!data?.sectors) return [];

    return Object.entries(data.sectors).map(([sector, instruments]) => ({
      name: sector,
      children: instruments.map(inst => ({
        name: inst.symbol,
        // size drives tile area — use exposure, minimum 100 so empty tiles still show
        size: Math.max(inst.exposure, 100),
        pnl: inst.pnl,
        exposure: inst.exposure,
        side: inst.side,
      })),
    }));
  }, [data]);

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <LayoutGrid className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">Risk TreeMap</h3>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-600">
          <span>size = exposure</span>
          <span>·</span>
          <span>color = PnL</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm" style={{ background: '#059669' }} />
          <span className="text-[9px] text-slate-500">Profit</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm" style={{ background: '#475569' }} />
          <span className="text-[9px] text-slate-500">Flat</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-2 rounded-sm" style={{ background: '#e11d48' }} />
          <span className="text-[9px] text-slate-500">Loss</span>
        </div>
      </div>

      {loading && !data ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="animate-pulse text-sm text-slate-600">Loading heatmap...</div>
        </div>
      ) : treeData.length === 0 ? (
        <div className="flex items-center justify-center text-sm text-slate-600" style={{ height }}>
          No position data for heatmap
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <Treemap
            data={treeData}
            dataKey="size"
            aspectRatio={4 / 3}
            stroke="#1e293b"
            content={<CustomContent />}
          />
        </ResponsiveContainer>
      )}

      {data && (
        <div className="flex items-center justify-between mt-2 text-[10px] text-slate-600">
          <span>{data.sector_count} sectors</span>
          <span>{data.instrument_count} instruments</span>
        </div>
      )}
    </div>
  );
}
