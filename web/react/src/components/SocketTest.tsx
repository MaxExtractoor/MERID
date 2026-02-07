import { useEffect } from 'react';
import { useMeridSocket } from '../hooks/useMeridSocket';

export default function SocketTest() {
  const { socket, connected } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // Subscribe to price updates when connected
    if (connected) {
      socket.emit("subscribe_prices", ["BTC-USD", "ETH-USD"]);
      console.log("Subscribed to price updates");
    }

    // Listen for price ticks
    const handlePriceTick = (data: any) => {
      console.log("Price tick received:", data);
    };

    socket.on("price_tick", handlePriceTick);

    return () => {
      socket.off("price_tick", handlePriceTick);
    };
  }, [socket, connected]);

  return (
    <div className="p-6 bg-slate-900 rounded-xl border border-slate-800">
      <h3 className="text-lg font-semibold text-white mb-4">MERID Socket Test</h3>
      
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-sm font-mono text-slate-300">
            Status: {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
        
        <div className="text-sm font-mono text-slate-400">
          Socket: {socket ? "Available" : "N/A"}
        </div>
        
        <div className="text-xs text-slate-500">
          <p>Test Steps:</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>Log in normally - should see "Connected"</li>
            <li>Wait for token expiry (60s in dev)</li>
            <li>Should see auto-reconnect after refresh</li>
            <li>Price ticks should resume automatically</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
