import { useState } from "react";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Trading from "./views/Trading";
import Agents from "./views/Agents";
import Predictions from "./views/Predictions";
import PredictionConsensusView from "./views/PredictionConsensusView";
import Risk from "./views/Risk";
import Health from "./views/Health";
import ApiDashboard from "./views/ApiDashboard";
import Research from "./views/Research";
import Logs from "./views/Logs";
import Settings from "./views/Settings";
import Wallet from "./views/Wallet";
import Treasury from "./views/Treasury";
import Social from "./views/Social";
import Betting from "./views/Betting";
import BettingConsensusView from "./views/BettingConsensusView";
import Mining from "./views/Mining";
import Institutional from "./views/Institutional";
import Plugins from "./views/Plugins";
import OperatorDashboard from "./views/OperatorDashboard";
import TradeFloor from "./views/TradeFloor";
import DevSwarm from "./views/DevSwarm";
import Positions from "./views/Positions";
import Orders from "./views/Orders";
import Rewards from "./views/Rewards";
import { ThemeProvider } from "./theme";

type View = "overview" | "trading" | "agents" | "predictions" | "prediction-consensus" | "risk" | "health" | "api" | "research" | "logs" | "settings" | "analytics" | "wallet" | "treasury" | "social" | "betting" | "betting-consensus" | "mining" | "institutional" | "plugins" | "operator" | "tradefloor" | "devswarm" | "positions" | "orders" | "rewards";

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <ThemeProvider>
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
          className="hidden md:flex relative z-10"
        />

        {/* Mobile sidebar drawer */}
        {sidebarOpen && (
          <>
            <div 
              className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden"
              onClick={() => setSidebarOpen(false)}
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

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden relative z-10">
          <TopBar onMenuClick={() => setSidebarOpen(true)} />
          
          <main className="flex-1 overflow-auto p-4 lg:p-6">
            {view === "overview" && <Overview />}
            {view === "trading" && <Trading />}
            {view === "agents" && <Agents />}
            {view === "predictions" && <Predictions />}
            {view === "prediction-consensus" && <PredictionConsensusView />}
            {view === "risk" && <Risk />}
            {view === "health" && <Health />}
            {view === "api" && <ApiDashboard />}
            {view === "research" && <Research />}
            {view === "analytics" && <Research />}
            {view === "logs" && <Logs />}
            {view === "settings" && <Settings />}
            {view === "wallet" && <Wallet />}
            {view === "treasury" && <Treasury />}
            {view === "social" && <Social />}
            {view === "betting" && <Betting />}
            {view === "betting-consensus" && <BettingConsensusView />}
            {view === "mining" && <Mining />}
            {view === "institutional" && <Institutional />}
            {view === "plugins" && <Plugins />}
            {view === "operator" && <OperatorDashboard />}
            {view === "tradefloor" && <TradeFloor />}
            {view === "devswarm" && <DevSwarm />}
            {view === "positions" && <Positions />}
            {view === "orders" && <Orders />}
            {view === "rewards" && <Rewards />}
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}
