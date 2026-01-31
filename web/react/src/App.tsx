import { useState } from "react";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Trading from "./views/Trading";
import Agents from "./views/Agents";
import Predictions from "./views/Predictions";
import Risk from "./views/Risk";
import Health from "./views/Health";
import ApiDashboard from "./views/ApiDashboard";
import Research from "./views/Research";
import Logs from "./views/Logs";
import Settings from "./views/Settings";
import { ThemeProvider } from "./theme";

type View = "overview" | "trading" | "agents" | "predictions" | "risk" | "health" | "api" | "research" | "logs" | "settings" | "analytics";

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <ThemeProvider>
      <div className="flex h-screen">
        {/* Sidebar - hidden on mobile, shown on desktop */}
        <Sidebar 
          current={view} 
          onChange={(v) => {
            setView(v);
            setSidebarOpen(false);
          }} 
          className="hidden md:flex"
        />

        {/* Mobile sidebar drawer */}
        {sidebarOpen && (
          <Sidebar
            current={view}
            onChange={(v) => {
              setView(v);
              setSidebarOpen(false);
            }}
            className="fixed inset-y-0 left-0 z-50 w-64 md:hidden"
          />
        )}

        {/* Main content area */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopBar onMenuClick={() => setSidebarOpen(true)} />
          
          <main className="flex-1 overflow-auto p-4 lg:p-6">
            {view === "overview" && <Overview />}
            {view === "trading" && <Trading />}
            {view === "agents" && <Agents />}
            {view === "predictions" && <Predictions />}
            {view === "risk" && <Risk />}
            {view === "health" && <Health />}
            {view === "api" && <ApiDashboard />}
            {view === "research" && <Research />}
            {view === "analytics" && <Logs />}
            {view === "logs" && <Logs />}
            {view === "settings" && <Settings />}
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}
