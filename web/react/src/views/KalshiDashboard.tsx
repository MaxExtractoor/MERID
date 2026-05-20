/**
 * KalshiDashboard — Unified Kalshi Dashboard (Phase 8)
 *
 * Composes all new Kalshi UI components into a single dashboard.
 * Uses canonical state model via useKalshiUIState hook.
 * Progressive disclosure: overview → activity stream → detail drawer → troubleshooting.
 * 
 * Layout:
 * - Top: KalshiCompactOverview (system status, capital, markets, risk, grid)
 * - Middle: KalshiActivityStream (real-time event stream)
 * - Bottom: KalshiActionArea (primary controls)
 * - Right: KalshiTroubleshootingView (logs, failures, reconciliation)
 * - Drawer: KalshiDetailDrawer (progressive disclosure)
 * 
 * Design principles:
 * - Single source of truth from /api/v1/kalshi/ui-state
 * - WebSocket sync for real-time updates
 * - Progressive disclosure for details
 * - Operational signals (connection status, last refresh)
 */

import { useState } from 'react';
import { LayoutDashboard } from '../ui/icons';
import KalshiCompactOverview from '../components/KalshiCompactOverview';
import KalshiActivityStream from '../components/KalshiActivityStream';
import KalshiDetailDrawer from '../components/KalshiDetailDrawer';
import KalshiTroubleshootingView from '../components/KalshiTroubleshootingView';
import KalshiActionArea from '../components/KalshiActionArea';

type DetailType = 'market' | 'order' | 'trade' | 'agent' | null;
type ViewMode = 'overview' | 'activity' | 'troubleshooting';

export default function KalshiDashboard() {
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailType, setDetailType] = useState<DetailType>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('overview');

  const handleCloseDetail = () => {
    setDetailOpen(false);
    setDetailType(null);
    setDetailId(null);
  };

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <LayoutDashboard className="w-6 h-6 text-blue-400" />
            <h1 className="text-xl font-bold text-slate-100">Kalshi Dashboard</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setViewMode('overview')}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                viewMode === 'overview'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              Overview
            </button>
            <button
              onClick={() => setViewMode('activity')}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                viewMode === 'activity'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              Activity
            </button>
            <button
              onClick={() => setViewMode('troubleshooting')}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                viewMode === 'troubleshooting'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              Troubleshooting
            </button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="p-6 space-y-6">
        {/* Overview Mode */}
        {viewMode === 'overview' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <KalshiCompactOverview />
              <KalshiActivityStream />
            </div>
            <div className="space-y-6">
              <KalshiActionArea />
              <KalshiTroubleshootingView />
            </div>
          </div>
        )}

        {/* Activity Mode */}
        {viewMode === 'activity' && (
          <div className="max-w-4xl mx-auto">
            <KalshiActivityStream />
          </div>
        )}

        {/* Troubleshooting Mode */}
        {viewMode === 'troubleshooting' && (
          <div className="max-w-4xl mx-auto">
            <KalshiTroubleshootingView />
          </div>
        )}
      </div>

      {/* Detail Drawer */}
      <KalshiDetailDrawer
        isOpen={detailOpen}
        onClose={handleCloseDetail}
        type={detailType}
        id={detailId}
      />
    </div>
  );
}
