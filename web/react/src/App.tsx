import React, { useState, useRef, useCallback, useEffect, lazy, Suspense } from "react";
import { useFillToast } from "./hooks/useFillToast";
import { useKalshiStore } from "./store";
import { useKeyboardShortcuts, KeyboardShortcut } from "./hooks/useKeyboardShortcuts";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";

// Consolidated 7-view architecture — every key in types/views.ts maps here
const AgentWall = lazy(() => import("./views/AgentWall"));
const AgentDetail = lazy(() => import("./views/AgentDetail"));
const MissionControl = lazy(() => import("./views/MissionControl"));
const Terminal = lazy(() => import("./views/Terminal"));
const Portfolio = lazy(() => import("./views/Portfolio"));
const Risk = lazy(() => import("./views/Risk"));
const System = lazy(() => import("./views/System"));

// Optimized UI Components
import ErrorBoundary from "./components/ErrorBoundary";
import KalshiErrorBoundary from "./components/KalshiErrorBoundary";
import CommandPalette from "./components/CommandPalette";
import { OfflineIndicator } from "./components/OfflineIndicator";
import KalshiLoadingSkeleton from "./components/KalshiLoadingSkeleton";
import { RealtimeDisconnectedBanner } from "./components/RealtimeDisconnectedBanner";
import { ExecutionBlockedBanner } from "./components/ExecutionBlockedBanner";
import { GateChangeToast } from "./components/GateChangeToast";
import { ThemeProvider } from "./theme";
import ToastProvider from "./components/ToastProvider";

import type { View } from "./types/views";

import { ASSETS, type AssetSymbol } from "./agents/types";

// 7-View Architecture - Clean mapping
const VIEW_COMPONENTS: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  "agent-wall": AgentWall,
  "mission-control": MissionControl,
  terminal: Terminal,
  portfolio: Portfolio,
  risk: Risk,
  system: System,
};

function FillToastWatcher() {
  useFillToast();
  return null;
}

/**
 * Single store poller — the ONLY place refreshAll() runs on an interval.
 * Views must consume the store, never mount their own refreshAll loop
 * (previously every view ran a private 30s × 12-endpoint probe fan-out).
 */
function StorePoller() {
  const refreshAll = useKalshiStore((s) => s.refreshAll);
  useEffect(() => {
    void refreshAll();
    const id = window.setInterval(() => { void refreshAll(); }, 15_000);
    return () => window.clearInterval(id);
  }, [refreshAll]);
  return null;
}

// Zero-lag view renderer with memoization
const ViewRenderer = React.memo(({ view, onNavigate, agentAsset, onAssetChange }: {
  view: View;
  onNavigate: (v: View) => void;
  agentAsset: AssetSymbol;
  onAssetChange: (a: AssetSymbol) => void;
}) => {
  // Per-asset detail page gets its asset prop + a switcher row
  if (view === "agent-detail") {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          {ASSETS.map((a) => (
            <button
              key={a}
              onClick={() => onAssetChange(a)}
              className={`px-3 py-1 rounded-md text-sm font-semibold transition-colors ${
                a === agentAsset
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'bg-slate-800/60 text-slate-400 border border-slate-700/50 hover:text-slate-200'
              }`}
            >
              {a}
            </button>
          ))}
        </div>
        <AgentDetail asset={agentAsset} />
      </div>
    );
  }

  const Component = VIEW_COMPONENTS[view];

  if (!Component) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-slate-300 mb-2">View Not Found</h2>
          <p className="text-slate-500">The view &quot;{view}&quot; is not yet implemented.</p>
          <button
            onClick={() => onNavigate('agent-wall')}
            className="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
          >
            Return to Agent Wall
          </button>
        </div>
      </div>
    );
  }

  return <Component />;
});
ViewRenderer.displayName = 'ViewRenderer';

export default function App() {
  const [view, setView] = useState<View>("agent-wall");
  const [agentAsset, setAgentAsset] = useState<AssetSymbol>('BTC');
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

  // Keyboard shortcuts for navigation
  const shortcuts: KeyboardShortcut[] = [
    { key: '0', description: 'Navigate to Agent Wall', action: () => handleNavigate('agent-wall') },
    { key: '1', description: 'Navigate to Mission Control', action: () => handleNavigate('mission-control') },
    { key: '2', description: 'Navigate to Agent Detail', action: () => handleNavigate('agent-detail') },
    { key: '3', description: 'Navigate to Terminal', action: () => handleNavigate('terminal') },
    { key: '4', description: 'Navigate to Portfolio', action: () => handleNavigate('portfolio') },
    { key: '5', description: 'Navigate to Risk', action: () => handleNavigate('risk') },
    { key: '6', description: 'Navigate to System', action: () => handleNavigate('system') },
    { key: 'k', ctrl: true, description: 'Open command palette', action: () => openPaletteRef.current?.() },
  ];

  useKeyboardShortcuts(shortcuts);

  return (
    <ThemeProvider>
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
              onGoHome={() => setView('agent-wall')}
            >
              <Suspense fallback={<KalshiLoadingSkeleton />}>
                <ViewRenderer
                  view={view}
                  onNavigate={handleNavigate}
                  agentAsset={agentAsset}
                  onAssetChange={setAgentAsset}
                />
              </Suspense>
            </KalshiErrorBoundary>
          </main>
        </div>
      </div>
      <StorePoller />
      <FillToastWatcher />
      <GateChangeToast />
    </ToastProvider>
    </ThemeProvider>
  );
}
