#!/usr/bin/env python3
"""Start and maintain risk monitoring service."""

import asyncio
import threading
import time
from datetime import datetime

class RiskMonitoringService:
    """Service to maintain risk monitoring."""
    
    def __init__(self):
        self.running = False
        self.task = None
        
    async def start_monitoring(self):
        """Start risk monitoring loop."""
        print("🚀 Starting Risk Monitoring Service...")
        
        try:
            # Import required modules
            from core.automated_risk_controls import get_risk_coordinator
            
            # Get coordinator
            coordinator = get_risk_coordinator()
            print("  ✅ Risk coordinator obtained")
            
            # Start monitoring
            await coordinator.start_monitoring(interval=2.0)
            print("  ✅ Risk monitoring started")
            
            # Keep the service running
            self.running = True
            while self.running:
                try:
                    # Check status every 10 seconds
                    status = coordinator.get_comprehensive_risk_status()
                    monitoring_active = status.get('monitoring_active', False)
                    can_trade = status.get('can_trade', False)
                    
                    if monitoring_active:
                        print(f"  📊 Risk monitoring active - Can trade: {can_trade}")
                    else:
                        print("  ⚠️  Risk monitoring stopped, restarting...")
                        await coordinator.start_monitoring(interval=2.0)
                    
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    print(f"  ❌ Error in monitoring loop: {e}")
                    await asyncio.sleep(5)
                    
        except Exception as e:
            print(f"  ❌ Failed to start risk monitoring: {e}")
            
    def stop(self):
        """Stop the monitoring service."""
        self.running = False
        if self.task:
            self.task.cancel()

def start_risk_monitoring_thread():
    """Start risk monitoring in a background thread."""
    print("🔧 Starting risk monitoring background thread...")
    
    async def run_monitoring():
        service = RiskMonitoringService()
        await service.start_monitoring()
    
    # Run in background thread
    def thread_target():
        asyncio.run(run_monitoring())
    
    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()
    
    print("  ✅ Risk monitoring thread started")
    return thread

def main():
    """Main function."""
    print("🎯 RISK MONITORING SERVICE STARTER")
    print("=" * 50)
    
    try:
        # Start monitoring in background
        thread = start_risk_monitoring_thread()
        
        # Give it time to start
        print("⏳ Waiting for monitoring to initialize...")
        time.sleep(5)
        
        # Test the API endpoints
        print("\n🔍 Testing risk API endpoints...")
        import requests
        
        try:
            response = requests.get('http://localhost:8000/api/v1/risk/summary', timeout=10)
            if response.status_code == 200:
                data = response.json()
                monitoring_active = data.get('monitoring_active', False)
                can_trade = data.get('can_trade', False)
                portfolio_value = data.get('portfolio_risk', {}).get('portfolio_value', 0)
                
                print(f"  ✅ Risk Summary API working")
                print(f"    - Monitoring active: {monitoring_active}")
                print(f"    - Can trade: {can_trade}")
                print(f"    - Portfolio value: ${portfolio_value:,.2f}")
                
                if monitoring_active:
                    print(f"\n🎉 RISK MONITORING IS NOW ACTIVE!")
                    print(f"   The UI should show proper risk data.")
                else:
                    print(f"\n⚠️  Risk monitoring still initializing...")
                    
            else:
                print(f"  ❌ Risk Summary API failed: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ API test failed: {e}")
        
        print(f"\n📋 Service Status:")
        print(f"  - Risk monitoring thread: {'✅ Running' if thread.is_alive() else '❌ Stopped'}")
        print(f"  - Service will continue running in background")
        
        print(f"\n🎯 NEXT STEPS:")
        print(f"  1. Refresh the UI to see updated risk data")
        print(f"  2. Test the risk protections modal")
        print(f"  3. Check operator dashboard for risk status")
        
        # Keep the main thread alive for a bit to show status
        print(f"\n⏳ Monitoring service will continue in background...")
        time.sleep(10)
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to start risk monitoring service: {e}")
        return False

if __name__ == "__main__":
    main()
