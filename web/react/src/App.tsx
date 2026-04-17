import { useState, useRef } from "react";
import { useFillToast } from "./hooks/useFillToast";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Logs from "./views/Logs";
import Settings from "./views/Settings";
import KillSwitchView from "./views/KillSwitchView";
import KalshiGridView from "./views/KalshiGridView";
import KalshiAllMarketsView from "./views/KalshiAllMarketsView";
import KalshiDashboardView from "./views/KalshiDashboardView";
import KalshiPortfolioView from "./views/KalshiPortfolioView";
import PositionsView from "./views/PositionsView";
import OrdersView from "./views/OrdersView";
import KalshiVolDashboardView from "./views/KalshiVolDashboardView";
import KalshiTerminalView from "./views/KalshiTerminalView";
import KalshiAgentPerformanceView from "./views/KalshiAgentPerformanceView";
import KalshiSentimentView from "./views/KalshiSentimentView";
import LaneControlDashboard from "./views/LaneControlDashboard";
import SwarmConsensusMatrix from "./views/SwarmConsensusMatrix";
import CalibrationDashboardView from "./views/CalibrationDashboardView";
import OperatorDashboard from "./views/OperatorDashboard";
import KalshiRiskScreen from "./views/KalshiRiskScreen";
import KalshiRiskContextView from "./views/KalshiRiskContextView";
import ErrorBoundary from "./components/ErrorBoundary";
import CommandPalette from "./components/CommandPalette";
import { OfflineIndicator } from "./components/OfflineIndicator";
import { StubRegistryProvider } from "./components/GlobalStubBanner";
import { KalshiModeProvider } from "./context/KalshiModeContext";
import { RealtimeDisconnectedBanner } from "./components/RealtimeDisconnectedBanner";
import { ExecutionBlockedBanner } from "./components/ExecutionBlockedBanner";
import { GateChangeToast } from "./components/GateChangeToast";
import { ThemeProvider } from "./theme";
import ToastProvider from "./components/ToastProvider";
import type { View } from "./types/views";

function FillToastWatcher() {
  useFillToast();
  return null;
}

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('merid-sidebar-collapsed') === 'true'; } catch { return false; }
  });
  const openPaletteRef = useRef<(() => void) | null>(null);

  const toggleSidebarCollapse = () => {
    setSidebarCollapsed(prev => {
      const next = !prev;
      try { localStorage.setItem('merid-sidebar-collapsed', String(next)); } catch { /* ignore storage errors */ }
      return next;
    });
  };

  return (
    <ThemeProvider>
    <StubRegistryProvider>
    <KalshiModeProvider>
    <ToastProvider>
      <div className="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
        {/* Animated background gradient */}
        <div className="fixed inset-0 bg-gradient-to-br from-blue-950/20 via-purple-950/20 to-slate-950/20 animate-gradient bg-size-anim pointer-events-none" />
        
        {/* Sidebar - hidden on mobile, shown on desktop */}
        <Sidebar 
          current={view} 
          onChange={(v) => {
            setView(v);
            setSidebarOpen(false);
          }} 
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
              onChange={(v) => {
                setView(v);
                setSidebarOpen(false);
              }}
              className="fixed inset-y-0 left-0 z-50 w-64 md:hidden shadow-2xl"
            />
          </>
        )}

        {/* Command Palette (Ctrl+K) */}
        <CommandPalette
          onNavigate={(v) => { setView(v); setSidebarOpen(false); }}
          onOpen={(fn) => { openPaletteRef.current = fn; }}
        />

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden relative z-10">
          <TopBar
            onMenuClick={() => setSidebarOpen(true)}
            onNavigate={(v) => setView(v as View)}
            onOpenSearch={() => openPaletteRef.current?.()}
          />
          <RealtimeDisconnectedBanner />
          <ExecutionBlockedBanner />
          <OfflineIndicator />
          
          {/* T-033: Per-view error boundaries — one crash doesn't take down the whole dashboard */}
          <main className="flex-1 overflow-auto p-4 lg:p-6">
              {view === "overview" && <ErrorBoundary viewName="overview"><Overview /></ErrorBoundary>}
              {view === "kalshi-dashboard" && (
                <ErrorBoundary viewName="Kalshi Dashboard">
                  <KalshiDashboardView />
                </ErrorBoundary>
              )}
              {view === "kalshi-grid" && (
                <ErrorBoundary viewName="Kalshi Grid">
                  <KalshiGridView />
                </ErrorBoundary>
              )}
              {view === "kalshi-all-markets" && <ErrorBoundary viewName="kalshi-all-markets"><KalshiAllMarketsView /></ErrorBoundary>}
              {view === "kalshi-portfolio" && (
                <ErrorBoundary viewName="Kalshi Portfolio">
                  <KalshiPortfolioView />
                </ErrorBoundary>
              )}
              {view === "positions" && <ErrorBoundary viewName="positions"><PositionsView onNavigate={(v) => setView(v)} /></ErrorBoundary>}
              {view === "orders" && (
                <ErrorBoundary viewName="Orders">
                  <OrdersView />
                </ErrorBoundary>
              )}
              {view === "kalshi-vol-dashboard" && <ErrorBoundary viewName="kalshi-vol-dashboard"><KalshiVolDashboardView /></ErrorBoundary>}
              {view === "kalshi-risk-context" && <ErrorBoundary viewName="kalshi-risk-context"><KalshiRiskContextView onNavigate={(v) => setView(v as View)} /></ErrorBoundary>}
              {view === "kalshi-terminal" && <ErrorBoundary viewName="kalshi-terminal"><KalshiTerminalView /></ErrorBoundary>}
              {view === "kalshi-performance" && <ErrorBoundary viewName="kalshi-performance"><KalshiAgentPerformanceView /></ErrorBoundary>}
              {view === "kalshi-sentiment" && <ErrorBoundary viewName="kalshi-sentiment"><KalshiSentimentView /></ErrorBoundary>}
              {view === "lane-control" && <ErrorBoundary viewName="lane-control"><LaneControlDashboard /></ErrorBoundary>}
              {view === "swarm-consensus" && <ErrorBoundary viewName="swarm-consensus"><SwarmConsensusMatrix /></ErrorBoundary>}
              {view === "calibration-dashboard" && <ErrorBoundary viewName="calibration-dashboard"><CalibrationDashboardView /></ErrorBoundary>}
              {view === "operator" && (
                <ErrorBoundary viewName="Operator Dashboard">
                  <OperatorDashboard />
                </ErrorBoundary>
              )}
              {view === "kill-switch" && <ErrorBoundary viewName="kill-switch"><KillSwitchView /></ErrorBoundary>}
              {view === "kalshi-risk" && (
                <ErrorBoundary viewName="Kalshi Risk">
                  <KalshiRiskScreen />
                </ErrorBoundary>
              )}
              {view === "logs" && <ErrorBoundary viewName="logs"><Logs /></ErrorBoundary>}
              {view === "settings" && <ErrorBoundary viewName="settings"><Settings /></ErrorBoundary>}
          </main>
        </div>
      </div>
      <FillToastWatcher />
      <GateChangeToast />
    </ToastProvider>
    </KalshiModeProvider>
    </StubRegistryProvider>
    </ThemeProvider>
  );
}
