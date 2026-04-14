import { useState, useEffect } from "react";
import { logUxEvent } from "./utils/uxTelemetry";
import { useFillToast } from "./hooks/useFillToast";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Logs from "./views/Logs";
import Settings from "./views/Settings";
import KillSwitchView from "./views/KillSwitchView";
import KalshiGridView from "./views/KalshiGridView";
import KalshiDashboardView from "./views/KalshiDashboardView";
import KalshiPortfolioView from "./views/KalshiPortfolioView";
import KalshiVolDashboardView from "./views/KalshiVolDashboardView";
import KalshiTerminalView from "./views/KalshiTerminalView";
import KalshiAgentPerformanceView from "./views/KalshiAgentPerformanceView";
import KalshiSentimentView from "./views/KalshiSentimentView";
import LaneControlDashboard from "./views/LaneControlDashboard";
import SwarmConsensusMatrix from "./views/SwarmConsensusMatrix";
import CalibrationDashboardView from "./views/CalibrationDashboardView";
import OperatorDashboard from "./views/OperatorDashboard";
import RiskControlView from "./views/RiskControlView";
import RiskDashboardView from "./views/RiskDashboardView";
import PositionSizingView from "./views/PositionSizingView";
import PromotionStatusView from "./views/PromotionStatusView";
import ErrorBoundary from "./components/ErrorBoundary";
import CommandPalette from "./components/CommandPalette";
import { StubRegistryProvider } from "./components/GlobalStubBanner";
import { KalshiModeProvider } from "./context/KalshiModeContext";
import { RealtimeDisconnectedBanner } from "./components/RealtimeDisconnectedBanner";
import { ExecutionBlockedBanner } from "./components/ExecutionBlockedBanner";
import SystemServicesBanner from "./components/SystemServicesBanner";
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

  // ─── View-impression telemetry ──────────────────────────────────────────────
  // Fires logUxEvent('view_impression', view) on every route navigation.
  // Events buffer in memory and flush to localStorage every 10 s
  // (key: 'merid:ux_telemetry' — see utils/uxTelemetry.ts).
  //
  // This is the authoritative source of truth for the zombie-feature review
  // process.  After ≥ 14 days of data, run getUxStats() to classify low-usage
  // views.  See docs/UX_Zombie_Features.md for the full decision playbook.
  // ────────────────────────────────────────────────────────────────────────────
  useEffect(() => { logUxEvent('view_impression', view); }, [view]);

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
        <div className="fixed inset-0 bg-gradient-to-br from-blue-950/20 via-purple-950/20 to-slate-950/20 animate-gradient pointer-events-none" 
             style={{ backgroundSize: '400% 400%' }} />
        
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
        <CommandPalette onNavigate={(v) => { setView(v); setSidebarOpen(false); }} />

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden relative z-10">
          <TopBar onMenuClick={() => setSidebarOpen(true)} />
          {/* GAP-D1: alert when critical backend services stop */}
          <SystemServicesBanner />
          <RealtimeDisconnectedBanner />
          <ExecutionBlockedBanner />
          
          <main className="flex-1 overflow-auto p-4 lg:p-6">
            <ErrorBoundary viewName={view}>
              {view === "overview" && <Overview />}
              {view === "kalshi-dashboard" && <KalshiDashboardView />}
              {view === "kalshi-grid" && <KalshiGridView />}
              {view === "kalshi-portfolio" && <KalshiPortfolioView />}
              {view === "positions" && <KalshiPortfolioView initialTab="positions" />}
              {view === "orders" && <KalshiPortfolioView initialTab="orders" />}
              {view === "kalshi-vol-dashboard" && <KalshiVolDashboardView />}
              {view === "kalshi-terminal" && <KalshiTerminalView />}
              {view === "kalshi-performance" && <KalshiAgentPerformanceView />}
              {view === "kalshi-sentiment" && <KalshiSentimentView />}
              {view === "lane-control" && <LaneControlDashboard />}
              {view === "swarm-consensus" && <SwarmConsensusMatrix />}
              {view === "calibration-dashboard" && <CalibrationDashboardView />}
              {view === "operator" && <OperatorDashboard />}
              {view === "kill-switch" && <KillSwitchView />}
              {view === "risk-control" && <RiskControlView />}
              {view === "risk-dashboard" && <RiskDashboardView />}
              {view === "position-sizing" && <PositionSizingView />}
              {view === "promotion-status" && <PromotionStatusView />}
              {view === "logs" && <Logs />}
              {view === "settings" && <Settings />}
            </ErrorBoundary>
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
