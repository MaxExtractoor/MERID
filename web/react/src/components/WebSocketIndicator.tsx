/**
 * WebSocket Connection State Indicator
 * Shows real-time WebSocket connection status with visual feedback
 */

import { useKalshiStore, selectConnected } from '../store';
import { Wifi, WifiOff, Loader2 } from '../ui/icons';
import { Badge } from '../ui/Badge';

const WebSocketIndicator = () => {
  const connected = useKalshiStore(selectConnected);

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700">
      {connected === null ? (
        <>
          <Loader2 className="w-4 h-4 text-slate-400 animate-spin" />
          <span className="text-xs text-slate-400">Connecting...</span>
        </>
      ) : connected ? (
        <>
          <Wifi className="w-4 h-4 text-green-400" />
          <Badge variant="success" className="text-xs">Connected</Badge>
        </>
      ) : (
        <>
          <WifiOff className="w-4 h-4 text-red-400" />
          <Badge variant="danger" className="text-xs">Disconnected</Badge>
        </>
      )}
    </div>
  );
};

export default WebSocketIndicator;
