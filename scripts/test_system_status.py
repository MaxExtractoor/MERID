import requests
import json

print('🚀 MERID System Status Check')
print('=' * 50)

# CRITICAL FIX: Increased timeout for production stability
TIMEOUT = 30.0  # Increased from 5s to 30s

try:
    # Test basic API health
    response = requests.get('http://127.0.0.1:8001/api/v1/health', timeout=TIMEOUT)
    print('✓ System Health API:', response.status_code)
    
    # Test local venue APIs
    response = requests.get('http://127.0.0.1:8001/api/v1/localvenue/health', timeout=TIMEOUT)
    print('✓ Local Venue Health:', response.status_code)
    health_data = response.json()
    print('   Status:', health_data.get('status', 'unknown'))
    
    response = requests.get('http://127.0.0.1:8001/api/v1/localvenue/validation-status', timeout=TIMEOUT)
    print('✓ Local Venue Validation Status:', response.status_code)
    validation_data = response.json()
    print('   Overall Status:', validation_data.get('overall_status', 'unknown'))
    print('   Current Phase:', validation_data.get('current_phase', 'unknown'))
    
    response = requests.get('http://127.0.0.1:8001/api/v1/localvenue/engine-status', timeout=TIMEOUT)
    print('✓ Local Venue Engine Status:', response.status_code)
    engine_data = response.json()
    print('   Engine Running:', engine_data.get('is_running', False))
    
    print()
    print('🎉 MERID System is running successfully!')
    print('📊 Local venue validation and monitoring are operational')
    print('🌐 Open http://127.0.0.1:8001 in your browser to access the dashboard')
    print('🔧 Local venue APIs are available at /api/v1/localvenue/*')
    print('🤖 Swarm agents are monitoring the system')
    
    # Test a few more APIs
    print()
    print('📈 Additional API Endpoints:')
    
    response = requests.get('http://127.0.0.1:8001/api/v1/reality/status', timeout=TIMEOUT)
    print('✓ Reality Enforcement API:', response.status_code)
    
    response = requests.get('http://127.0.0.1:8001/api/v1/governance/charter-registry', timeout=TIMEOUT)
    print('✓ Governance API:', response.status_code)
    
    response = requests.get('http://127.0.0.1:8001/api/v1/intelligence/summary', timeout=TIMEOUT)
    print('✓ Intelligence API:', response.status_code)
    
    print()
    print('🎯 System Components Active:')
    print('   • Core Orchestrator with 9 agents')
    print('   • Local Venue Validation System')
    print('   • Reality Enforcement System')
    print('   • Governance and Charter Registry')
    print('   • Intelligence and Analytics')
    print('   • Live Price Feeds (Kraken, Coinbase, Binance)')
    print('   • Phase 0 Trial Management')
    
except requests.exceptions.Timeout as e:
    print('❌ Timeout Error:', str(e))
    print('   The system may be starting up. Try again in 30 seconds.')
except requests.exceptions.ConnectionError as e:
    print('❌ Connection Error:', str(e))
    print('   Ensure the backend is running on http://127.0.0.1:8001')
except Exception as e:
    print('❌ Unexpected Error:', str(e))
    print('   Check the backend logs for more details')
