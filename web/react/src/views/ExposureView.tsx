import { BarChart3, Clock } from 'lucide-react';
import { useState } from 'react';
import { LiveRiskStrip } from './LiveRiskStrip';
import { EquityPnLChart } from '../components/charts/EquityPnLChart';
import { RiskLimitBars } from '../components/charts/RiskLimitBars';
import { DrawdownCard } from '../components/charts/DrawdownCard';
import { RiskHeatmapWidget } from '../components/charts/RiskHeatmapWidget';
import VenueExposureCard from '../components/VenueExposureCard';
import DomainPnLChart from '../components/DomainPnLChart';
import type { TimeRange } from '../components/DomainPnLChart';
import { StalenessIndicator } from '../components/StalenessIndicator';
import { useApiData } from '../hooks/useApiData';
import { useFeatureFlags } from '../config/featureFlags';

export default function ExposureView() {
  const { kalshiOnly } = useFeatureFlags();
  const [timeRange, setTimeRange] = useState<TimeRange>('24h');
  const { lastUpdated } = useApiData<unknown>(
    kalshiOnly ? '' : '/api/v1/operator/summary',
    { pollingInterval: kalshiOnly ? 0 : 15000 }
  );

  // Crypto-only view - redirect or show message
  if (kalshiOnly) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <BarChart3 className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-slate-400 mb-2">Crypto-Only View</h2>
          <p className="text-slate-500">This view is not available in Kalshi mode.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BarChart3 className="w-6 h-6 text-purple-400" />
        <h1 className="text-xl font-bold text-slate-100">Exposure & PnL</h1>
        <div className="ml-auto flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-slate-500" />
          {(['1h', '4h', '24h', '7d'] as const).map(r => (
            <button type="button" key={r}
              onClick={() => setTimeRange(r)}
              className={`px-2 py-1 text-[11px] rounded transition-colors ${
                timeRange === r ? 'bg-blue-600/30 text-blue-400 border border-blue-500/30' : 'bg-slate-800 text-slate-500 hover:text-slate-300 border border-transparent'
              }`}
            >{r}</button>
          ))}
          <StalenessIndicator
            lastUpdated={lastUpdated ? new Date(lastUpdated) : null}
            thresholdMs={10000}
            criticalThresholdMs={30000}
            label="Exposure"
          />
        </div>
      </div>

      {/* Live Risk Strip */}
      <LiveRiskStrip />

      {/* Equity Chart */}
      <EquityPnLChart externalWindow={timeRange} />

      {/* Risk Limit Bars + Heatmap + Drawdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <RiskLimitBars />
        <RiskHeatmapWidget />
        <DrawdownCard />
      </div>

      {/* Domain PnL */}
      <DomainPnLChart externalTimeRange={timeRange} />

      {/* Venue Exposure */}
      <VenueExposureCard />
    </div>
  );
}
