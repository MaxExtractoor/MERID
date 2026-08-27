import React, { useState, useRef, useCallback, lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFillToast } from "./hooks/useFillToast";
import { useKeyboardShortcuts, KeyboardShortcut } from "./hooks/useKeyboardShortcuts";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";

// 8-View Architecture - Only these views are functional
const Dashboard = lazy(() => import("./views/Dashboard"));
const Trade = lazy(() => import("./views/Trade"));
const Monitor = lazy(() => import("./views/Monitor"));
const Grid = lazy(() => import("./views/Grid"));
const Risk = lazy(() => import("./views/Risk"));
const Calibration = lazy(() => import("./views/Calibration"));
const Logs = lazy(() => import("./views/Logs"));
const Settings = lazy(() => import("./views/Settings"));

// Legacy Kalshi views retained for deep links
const KalshiDashboardView = lazy(() => import("./views/KalshiDashboardView"));
const KalshiPortfolioView = lazy(() => import("./views/KalshiPortfolioView"));

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

// 8-View Architecture - Clean mapping
const VIEW_COMPONENTS: Record<string, React.LazyExoticComponent<React.ComponentType<any>>> = {
  dashboard: Dashboard,
  trade: Trade,
  monitor: Monitor,
  grid: Grid,
  risk: Risk,
  calibration: Calibration,
  logs: Logs,
  settings: Settings,
  "kalshi-dashboard": KalshiDashboardView,
  "kalshi-portfolio": KalshiPortfolioView,
};

// Configure TanStack Query
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30 seconds
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function FillToastWatcher() {
  useFillToast();
  return null;
}

// Zero-lag view renderer with memoization
const ViewRenderer = React.memo(({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) => {
  // Legacy Kalshi deep-link views
  if (view === "kalshi-dashboard") return <KalshiDashboardView />;
  if (view === "kalshi-portfolio") return <KalshiPortfolioView />;

  const Component = VIEW_COMPONENTS[view];

  if (!Component) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-slate-300 mb-2">View Not Found</h2>
          <p className="text-slate-500">The view &quot;{view}&quot; is not yet implemented.</p>
          <button
            onClick={() => onNavigate('dashboard')}
            className="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
          >
            Return to Dashboard
          </button>
        </div>
      </div>
    );
  }
  
  return <Component />;
});
ViewRenderer.displayName = 'ViewRenderer';

export default function App() {
  const [view, setView] = useState<View>("dashboard");
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
    { key: '1', description: 'Navigate to Dashboard', action: () => handleNavigate('dashboard') },
    { key: '2', description: 'Navigate to Trade', action: () => handleNavigate('trade') },
    { key: '3', description: 'Navigate to Monitor', action: () => handleNavigate('monitor') },
    { key: '4', description: 'Navigate to Grid', action: () => handleNavigate('grid') },
    { key: '5', description: 'Navigate to Risk', action: () => handleNavigate('risk') },
    { key: '6', description: 'Navigate to Calibration', action: () => handleNavigate('calibration') },
    { key: '7', description: 'Navigate to Logs', action: () => handleNavigate('logs') },
    { key: '8', description: 'Navigate to Settings', action: () => handleNavigate('settings') },
    { key: 'k', ctrl: true, description: 'Open command palette', action: () => openPaletteRef.current?.() },
  ];

  useKeyboardShortcuts(shortcuts);

  return (
    <QueryClientProvider client={queryClient}>
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
    </QueryClientProvider>
  );
}
