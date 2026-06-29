"""Comprehensive Production Stack Monitoring

This script continuously monitors the entire production stack to verify
end-to-end wiring for signals, orders, and fills in LIVE mode.

It probes:
- Upstream: Market data availability and quality
- Midstream: Signal generation and agent grid status
- Downstream: Order routing and execution
- End-to-End: Complete signal-to-fill lifecycle
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import Dict, Any, List

SERVER_URL = "http://localhost:8011"

class ProductionStackMonitor:
    """Monitor the entire production stack end-to-end."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.check_count = 0
        self.signals_detected = []
        self.orders_submitted = []
        self.fills_received = []
        self.gaps_detected = []
        
    def log(self, message: str):
        """Log with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
        
    def check_server_health(self) -> Dict[str, Any]:
        """Check server health and basic status."""
        try:
            response = requests.get(f"{SERVER_URL}/api/v1/health", timeout=2)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.log(f"✗ Server health check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def check_market_data(self) -> Dict[str, Any]:
        """Check market data availability and quality."""
        try:
            response = requests.get(f"{SERVER_URL}/api/v1/md-debug", timeout=2)
            response.raise_for_status()
            md = response.json()
            
            tickers = md.get('tickers', {})
            executable_count = sum(1 for t in tickers.values() if t.get('executable', False))
            
            return {
                "status": "ok",
                "total_markets": len(tickers),
                "executable_markets": executable_count,
                "tickers": list(tickers.keys())
            }
        except Exception as e:
            self.log(f"✗ Market data check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def check_agent_grid(self) -> Dict[str, Any]:
        """Check agent grid status and signal generation."""
        try:
            response = requests.get(f"{SERVER_URL}/api/v1/agents", timeout=2)
            response.raise_for_status()
            agents_data = response.json()
            
            if 'agents_by_asset' in agents_data:
                agents_by_asset = agents_data['agents_by_asset']
                
                assets_with_signals = []
                total_positions = 0
                
                for asset, agent_info in agents_by_asset.items():
                    last_signal_ts = agent_info.get('last_signal_ts')
                    positions = agent_info.get('open_positions', 0)
                    total_positions += positions
                    
                    if last_signal_ts is not None:
                        assets_with_signals.append(asset)
                        self.signals_detected.append({
                            "asset": asset,
                            "timestamp": last_signal_ts,
                            "check_count": self.check_count
                        })
                
                return {
                    "status": "ok",
                    "total_agents": len(agents_by_asset),
                    "assets_with_signals": len(assets_with_signals),
                    "signal_assets": assets_with_signals,
                    "total_positions": total_positions
                }
            else:
                return {"status": "error", "error": "Unknown agent format"}
                
        except Exception as e:
            self.log(f"✗ Agent grid check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def check_loop_status(self) -> Dict[str, Any]:
        """Check trading loop status."""
        try:
            response = requests.get(f"{SERVER_URL}/api/v1/loop-status", timeout=2)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.log(f"✗ Loop status check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def check_trading_mode(self) -> Dict[str, Any]:
        """Check current trading mode configuration."""
        return {
            "MERID_PM_TRADING_MODE": os.getenv('MERID_PM_TRADING_MODE', 'NOT SET'),
            "MERID_ALLOW_LIVE_TRADES": os.getenv('MERID_ALLOW_LIVE_TRADES', 'NOT SET'),
            "MERID_PM_LIVE_ENABLED": os.getenv('MERID_PM_LIVE_ENABLED', 'NOT SET'),
            "KALSHI_ENV": os.getenv('KALSHI_ENV', 'NOT SET'),
            "KALSHI_USE_DEMO": os.getenv('KALSHI_USE_DEMO', 'NOT SET')
        }
    
    def probe_signal_generation(self) -> Dict[str, Any]:
        """Probe for signal generation activity from logs."""
        try:
            # Check centralized production log for signal generation
            log_file = "c:\\Dev\\MERID\\logs\\full.log"
            
            recent_signals = []
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()[-100:]  # Last 100 lines
                        for line in lines:
                            if 'SIGNAL' in line or 'signal' in line.lower():
                                recent_signals.append(line.strip())
            except Exception as e:
                # Silently skip log files that can't be read
                pass
            
            return {
                "status": "probing",
                "signals_detected_count": len(self.signals_detected),
                "last_signal": self.signals_detected[-1] if self.signals_detected else None,
                "recent_log_signals": len(recent_signals),
                "log_sample": recent_signals[-3:] if recent_signals else []
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def probe_order_routing(self) -> Dict[str, Any]:
        """Probe for order routing activity from logs."""
        try:
            # Check centralized production log for order routing
            log_file = "c:\\Dev\\MERID\\logs\\full.log"
            
            recent_orders = []
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()[-100:]  # Last 100 lines
                        for line in lines:
                            if 'ORDER' in line or 'order' in line.lower() or 'route_order' in line.lower():
                                recent_orders.append(line.strip())
            except Exception as e:
                # Silently skip log files that can't be read
                pass
            
            return {
                "status": "probing",
                "orders_submitted_count": len(self.orders_submitted),
                "last_order": self.orders_submitted[-1] if self.orders_submitted else None,
                "recent_log_orders": len(recent_orders),
                "log_sample": recent_orders[-3:] if recent_orders else []
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def probe_fill_execution(self) -> Dict[str, Any]:
        """Probe for fill execution activity from logs."""
        try:
            # Check centralized production log for fill execution
            log_file = "c:\\Dev\\MERID\\logs\\full.log"
            
            recent_fills = []
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()[-100:]  # Last 100 lines
                        for line in lines:
                            if 'FILL' in line or 'fill' in line.lower() or 'filled' in line.lower():
                                recent_fills.append(line.strip())
            except Exception as e:
                # Silently skip log files that can't be read
                pass
            
            return {
                "status": "probing",
                "fills_received_count": len(self.fills_received),
                "last_fill": self.fills_received[-1] if self.fills_received else None,
                "recent_log_fills": len(recent_fills),
                "log_sample": recent_fills[-3:] if recent_fills else []
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def check_gaps(self) -> List[str]:
        """Check for gaps in the production stack."""
        gaps = []
        
        # Check trading mode
        mode = os.getenv('MERID_PM_TRADING_MODE', 'paper').lower()
        if mode != 'live':
            gaps.append(f"Trading mode is {mode}, expected live")
        
        # Check live trading enabled
        allow_live = os.getenv('MERID_ALLOW_LIVE_TRADES', 'false').lower()
        if allow_live not in ('true', '1', 'yes'):
            gaps.append("MERID_ALLOW_LIVE_TRADES not enabled")
        
        # Check agent grid signals
        if self.check_count > 10 and len(self.signals_detected) == 0:
            gaps.append(f"No signals detected after {self.check_count} checks")
        
        return gaps
    
    def run_check(self) -> Dict[str, Any]:
        """Run a comprehensive check of the production stack."""
        self.check_count += 1
        
        self.log(f"=== Check #{self.check_count} ===")
        
        results = {
            "check_number": self.check_count,
            "timestamp": datetime.now().isoformat(),
            "server_health": self.check_server_health(),
            "market_data": self.check_market_data(),
            "agent_grid": self.check_agent_grid(),
            "loop_status": self.check_loop_status(),
            "trading_mode": self.check_trading_mode(),
            "signal_generation": self.probe_signal_generation(),
            "order_routing": self.probe_order_routing(),
            "fill_execution": self.probe_fill_execution(),
            "gaps": self.check_gaps()
        }
        
        # Log key metrics
        server_ok = results["server_health"].get("status") == "ok"
        md_ok = results["market_data"].get("status") == "ok"
        agents_ok = results["agent_grid"].get("status") == "ok"
        signals_count = results["agent_grid"].get("assets_with_signals", 0)
        positions = results["agent_grid"].get("total_positions", 0)
        
        self.log(f"Server: {'✓' if server_ok else '✗'} | MD: {'✓' if md_ok else '✗'} | Agents: {'✓' if agents_ok else '✗'}")
        self.log(f"Signals: {signals_count} | Positions: {positions} | Gaps: {len(results['gaps'])}")
        
        if results["gaps"]:
            for gap in results["gaps"]:
                self.log(f"  ⚠ GAP: {gap}")
                self.gaps_detected.append(gap)
        
        return results
    
    def print_summary(self):
        """Print monitoring summary."""
        elapsed = datetime.now() - self.start_time
        self.log("=" * 80)
        self.log("MONITORING SUMMARY")
        self.log("=" * 80)
        self.log(f"Duration: {elapsed}")
        self.log(f"Total checks: {self.check_count}")
        self.log(f"Signals detected: {len(self.signals_detected)}")
        self.log(f"Orders submitted: {len(self.orders_submitted)}")
        self.log(f"Fills received: {len(self.fills_received)}")
        self.log(f"Gaps detected: {len(self.gaps_detected)}")
        
        if self.signals_detected:
            self.log("Signal details:")
            for signal in self.signals_detected:
                self.log(f"  {signal}")
        
        if self.gaps_detected:
            self.log("Gap details:")
            for gap in self.gaps_detected:
                self.log(f"  {gap}")
        
        self.log("=" * 80)

def main():
    """Main monitoring loop."""
    print("=" * 80)
    print("PRODUCTION STACK MONITORING")
    print("=" * 80)
    print("Monitoring entire production stack for signal-to-fill lifecycle")
    print("Press Ctrl+C to stop")
    print("=" * 80)
    
    monitor = ProductionStackMonitor()
    
    try:
        while True:
            results = monitor.run_check()
            
            # Check if we have signals
            if results["agent_grid"].get("assets_with_signals", 0) > 0:
                print("\n" + "=" * 80)
                print("🎉 SIGNAL DETECTED!")
                print("=" * 80)
                print(f"Assets with signals: {results['agent_grid']['signal_assets']}")
                print("Monitoring for order submission and fills...")
                
                # Increase monitoring frequency when signals detected
                time.sleep(5)
            else:
                # Normal monitoring frequency
                time.sleep(10)
                
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        monitor.print_summary()
    except Exception as e:
        print(f"\nMonitoring error: {e}")
        import traceback
        traceback.print_exc()
        monitor.print_summary()

if __name__ == "__main__":
    main()
