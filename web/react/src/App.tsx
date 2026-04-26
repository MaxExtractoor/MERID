import React, { useState, useRef, useCallback } from "react";
import { useFillToast } from "./hooks/useFillToast";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Logs from "./views/Logs";
import Settings from "./views/Settings";

// Consolidated Unified Views (Stages 1, 4, 5, 6, 7, 8)
import DiscoverView from "./views/DiscoverView";
import SizeView from "./views/SizeView";
import ExecuteView from "./views/ExecuteView";
import MonitorView from "./views/MonitorView";
import PromoteView from "./views/PromoteView";
import ProtectView from "./views/ProtectView";

// Individual Stage Views (Stages 2, 3)
import KalshiAgentPerformanceView from "./views/KalshiAgentPerformanceView";
import KalshiSentimentView from "./views/KalshiSentimentView";
import KalshiVolDashboardView from "./views/KalshiVolDashboardView";
import SwarmConsensusMatrix from "./views/SwarmConsensusMatrix";
import CalibrationDashboardView from "./views/CalibrationDashboardView";
import OperatorDashboard from "./views/OperatorDashboard";

// Optimized UI Components
import ErrorBoundary from "./components/ErrorBoundary";
import CommandPalette from "./components/CommandPalette";
import { OfflineIndicator } from "./components/OfflineIndicator";
import { StubRegistryProvider } from "./components/GlobalStubBanner";
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
const VIEW_COMPONENTS: Record<string, React.LazyExoticComponent<React.ComponentType<any>> | React.ComponentType<any>> = {
  // System Views
  overview: Overview,
  operator: OperatorDashboard,
  logs: Logs,
  settings: Settings,
  
  // Stage 1: Discover (Unified Consolidated View)
  discover: DiscoverView,
  
  // Stage 2: Analyze (Individual Views)
  "analyze-edge": KalshiVolDashboardView,  // Edge signals use vol dashboard
  "analyze-sentiment": KalshiSentimentView,
  "analyze-vol": KalshiVolDashboardView,
  
  // Stage 3: Consensus (Individual Views)
  "consensus-swarm": SwarmConsensusMatrix,
  "consensus-debates": SwarmConsensusMatrix,
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
    <StubRegistryProvider>
    <KalshiModeProvider>
    <ToastProvider>
      <div className="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
        {/* Optimized background - single layer */}
        <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 pointer-events-none" />
        
        {/* Sidebar - hidden on mobile, shown on desktop */}
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

        {/* Command Palette (Ctrl+K) */}
        <CommandPalette
          onNavigate={handleNavigate}
          onOpen={(fn) => { openPaletteRef.current = fn; }}
        />

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden relative z-10">
          <TopBar
            onMenuClick={() => setSidebarOpen(true)}
            onNavigate={handleNavigate}
            onOpenSearch={() => openPaletteRef.current?.()}
          />
          <RealtimeDisconnectedBanner />
          <ExecutionBlockedBanner />
          <OfflineIndicator />
          
          {/* Per-view error boundaries — one crash doesn't take down the whole dashboard */}
          <main className="flex-1 overflow-auto p-4 lg:p-6">
            <ErrorBoundary viewName={view}>
              <ViewRenderer view={view} onNavigate={handleNavigate} />
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <FillToastWatcher />
      <GateChangeToast />
    </ToastProvider>
    </KalshiModeProvider>
    </StubRegistryProvider>
    </NetworkProvider>
    </ThemeProvider>
  );
}
