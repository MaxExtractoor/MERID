import React, { useState, useRef, useCallback, lazy, Suspense } from "react";
import { useFillToast } from "./hooks/useFillToast";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";

// Lazy-loaded views for code splitting (Tier 1 optimization)
const Overview = lazy(() => import("./views/Overview"));
const Logs = lazy(() => import("./views/Logs"));
const Settings = lazy(() => import("./views/Settings"));

// Consolidated Unified Views (Stages 1, 4, 5, 6, 7, 8)
const DiscoverView = lazy(() => import("./views/DiscoverView"));
const SizeView = lazy(() => import("./views/SizeView"));
const ExecuteView = lazy(() => import("./views/ExecuteView"));
const MonitorView = lazy(() => import("./views/MonitorView"));
const PromoteView = lazy(() => import("./views/PromoteView"));
const ProtectView = lazy(() => import("./views/ProtectView"));

// Individual Stage Views (Stages 2, 3)
const KalshiAgentPerformanceView = lazy(() => import("./views/KalshiAgentPerformanceView"));
const KalshiSentimentView = lazy(() => import("./views/KalshiSentimentView"));
const KalshiVolDashboardView = lazy(() => import("./views/KalshiVolDashboardView"));
const SwarmConsensusMatrix = lazy(() => import("./views/SwarmConsensusMatrix"));
const CalibrationDashboardView = lazy(() => import("./views/CalibrationDashboardView"));
const OperatorDashboard = lazy(() => import("./views/OperatorDashboard"));

// Optimized UI Components
import ErrorBoundary from "./components/ErrorBoundary";
import KalshiErrorBoundary from "./components/KalshiErrorBoundary";
import CommandPalette from "./components/CommandPalette";
import { OfflineIndicator } from "./components/OfflineIndicator";
import KalshiLoadingSkeleton from "./components/KalshiLoadingSkeleton";
import { KalshiModeProvider } from "./context/KalshiModeContext";
import { NetworkProvider } from "./hooks/useNetworkStatusProvider";
import { RealtimeDisconnectedBanner } from "./components/RealtimeDisconnectedBanner";
import { ExecutionBlockedBanner } from "./components/ExecutionBlockedBanner";
import { GateChangeToast } from "./components/GateChangeToast";
import { ThemeProvider } from "./theme";
import ToastProvider from "./components/ToastProvider";

import type { View } from "./types/views";
import { LEGACY_VIEW_MAP } from "./types/views";

// Zero-lag view loader with preloading
// Consolidated architecture: Stages 1, 5, 8 use unified views
// All views are now lazy-loaded for code splitting (Tier 1 optimization)
const VIEW_COMPONENTS: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  // System Views
  overview: Overview,
  operator: OperatorDashboard,
  logs: Logs,
  settings: Settings,
  
  // Stage 1: Discover (Unified Consolidated View)
  discover: DiscoverView,
  
  // Stage 2: Analyze (Individual Views)
  "analyze-sentiment": KalshiSentimentView,
  "analyze-vol": KalshiVolDashboardView,  // Also used for edge signals
  
  // Stage 3: Consensus (Individual Views)
  "consensus-swarm": SwarmConsensusMatrix,  // Also shows debates
  "consensus-performance": KalshiAgentPerformanceView,
  "consensus-calibration": CalibrationDashboardView,
  
  // Stage 4: Size (Unified Consolidated View)
  size: SizeView,
  
  // Stage 5: Execute (Unified Consolidated View)
  execute: ExecuteView,
  
  // Stage 6: Monitor (Unified Consolidated View)
  monitor: MonitorView,
  
  // Stage 7: Promote (Unified Consolidated View)
  promote: PromoteView,
  
  // Stage 8: Protect (Unified Consolidated View)
  protect: ProtectView,
};

// Legacy view compatibility layer for transition period
function resolveView(view: View): View {
  // Check if it's a legacy view that needs mapping
  if (view in LEGACY_VIEW_MAP) {
    return LEGACY_VIEW_MAP[view];
  }
  return view;
}

function FillToastWatcher() {
  useFillToast();
  return null;
}

// Zero-lag view renderer with memoization
const ViewRenderer = React.memo(({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) => {
  const resolvedView = resolveView(view);
  const Component = VIEW_COMPONENTS[resolvedView];
  
  if (!Component) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-slate-300 mb-2">View Not Found</h2>
          <p className="text-slate-500">The view &quot;{view}&quot; is not yet implemented in the 8-stage workflow.</p>
          <button
            onClick={() => onNavigate('overview')}
            className="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
          >
            Return to Overview
          </button>
        </div>
      </div>
    );
  }
  
  const viewProps = ['execute-positions', 'positions'].includes(resolvedView) ? { onNavigate } : 
                   ['kalshi-risk-context', 'protect-alerts'].includes(resolvedView) ? { onNavigate: (v: string) => onNavigate(v as View) } : 
                   {};
  
  return <Component {...viewProps} />;
});
ViewRenderer.displayName = 'ViewRenderer';

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('merid-sidebar-collapsed') === 'true'; } catch { return false; }
  });
  const openPaletteRef = useRef<(() => void) | null>(null);

  const toggleSidebarCollapse = useCallback(() => {
    setSidebarCollapsed(prev => {
      const next = !prev;
      try { localStorage.setItem('merid-sidebar-collapsed', String(next)); } catch { /* ignore storage errors */ }
      return next;
    });
  }, []);

  const handleNavigate = useCallback((newView: View) => {
    setView(newView);
    setSidebarOpen(false);
  }, []);

  return (
    <ThemeProvider>
    <NetworkProvider>
    <KalshiModeProvider>
    <ToastProvider>
      <div className="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
        {/* Optimized background - single layer */}
        <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 pointer-events-none" />
        
        {/* Sidebar - hidden on mobile, shown on desktop */}
        <ErrorBoundary viewName="Sidebar" enhanced={false}>
          <Sidebar 
            current={view} 
            onChange={handleNavigate}
            collapsed={sidebarCollapsed}
            onToggleCollapse={toggleSidebarCollapse}
            className="hidden md:flex relative z-10"
          />

          {/* Mobile sidebar drawer */}
          {sidebarOpen && (
            <>
              <button
                type="button"
                className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden"
                onClick={() => setSidebarOpen(false)}
                aria-label="Close sidebar"
              />
              <Sidebar
                current={view}
                onChange={handleNavigate}
                className="fixed inset-y-0 left-0 z-50 w-64 md:hidden shadow-2xl"
              />
            </>
          )}
        </ErrorBoundary>

        {/* Command Palette (Ctrl+K) */}
        <CommandPalette
          onNavigate={handleNavigate}
          onOpen={(fn) => { openPaletteRef.current = fn; }}
        />

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden relative z-10">
          <ErrorBoundary viewName="TopBar" enhanced={false}>
            <TopBar
              onMenuClick={() => setSidebarOpen(true)}
              onNavigate={handleNavigate}
              onOpenSearch={() => openPaletteRef.current?.()}
            />
          </ErrorBoundary>
          
          <ErrorBoundary viewName="StatusBanners" enhanced={false}>
            <RealtimeDisconnectedBanner />
            <ExecutionBlockedBanner />
            <OfflineIndicator />
          </ErrorBoundary>
          
          {/* Per-view error boundaries — one crash doesn't take down the whole dashboard */}
          <main className="flex-1 overflow-auto p-4 lg:p-6">
            <KalshiErrorBoundary 
              viewName={view}
              onGoHome={() => setView('overview')}
            >
              <Suspense fallback={<KalshiLoadingSkeleton />}>
                <ViewRenderer view={view} onNavigate={handleNavigate} />
              </Suspense>
            </KalshiErrorBoundary>
          </main>
        </div>
      </div>
      <FillToastWatcher />
      <GateChangeToast />
    </ToastProvider>
    </KalshiModeProvider>
    </NetworkProvider>
    </ThemeProvider>
  );
}
