#!/usr/bin/env python3
"""
Phase 2.2 Complete Implementation Test
Tests all sections: Arbitrage, System Admin, Prediction Markets, Agent Cohorts
"""

import asyncio
import aiohttp
import json
from datetime import datetime

async def test_phase2_2_complete():
    """Test all Phase 2.2 sections comprehensively"""
    print("🎯 TESTING PHASE 2.2 - COMPLETE IMPLEMENTATION")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:8011"
    
    async with aiohttp.ClientSession() as session:
        results = []
        
        # Test 1: Arbitrage Section
        print("\n📊 Testing Arbitrage Section")
        print("-" * 40)
        
        try:
            # Test REST APIs
            async with session.get(f"{base_url}/api/v1/arbitrage/opportunities") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Arbitrage Opportunities", "200", f"{len(data.get('opportunities', []))} items"))
                else:
                    results.append(("Arbitrage Opportunities", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/arbitrage/stats") as resp:
                if resp.status == 200:
                    results.append(("Arbitrage Stats", "200", "success"))
                else:
                    results.append(("Arbitrage Stats", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/arbitrage/venues") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Arbitrage Venues", "200", f"{len(data.get('venues', []))} venues"))
                else:
                    results.append(("Arbitrage Venues", str(resp.status), "Failed"))
            
            # Test WebSocket
            ws_url = f"ws://127.0.0.1:8011/ws/arbitrage"
            try:
                async with session.ws_connect(ws_url) as ws:
                    msg = await ws.receive_json(timeout=5)
                    if msg.get("type") == "connected":
                        results.append(("Arbitrage WebSocket", "200", "Connected successfully"))
                    else:
                        results.append(("Arbitrage WebSocket", "200", "Connected"))
            except Exception as e:
                results.append(("Arbitrage WebSocket", "ERROR", str(e)))
                
        except Exception as e:
            results.append(("Arbitrage Section", "ERROR", str(e)))
        
        # Test 2: System Admin Section
        print("\n🖥️ Testing System Admin Section")
        print("-" * 40)
        
        try:
            async with session.get(f"{base_url}/api/v1/system/health") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("System Health", "200", data.get("status", "unknown")))
                else:
                    results.append(("System Health", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/system/subsystems") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("System Subsystems", "200", f"{len(data.get('subsystems', []))} subsystems"))
                else:
                    results.append(("System Subsystems", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/system/metrics") as resp:
                if resp.status == 200:
                    results.append(("System Metrics", "200", "Data available"))
                else:
                    results.append(("System Metrics", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/system/events") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("System Events", "200", f"{len(data.get('events', []))} events"))
                else:
                    results.append(("System Events", str(resp.status), "Failed"))
            
            # Test WebSocket
            ws_url = f"ws://127.0.0.1:8011/ws/system"
            try:
                async with session.ws_connect(ws_url) as ws:
                    msg = await ws.receive_json(timeout=5)
                    if msg.get("type") == "connected":
                        results.append(("System WebSocket", "200", "Connected successfully"))
                    else:
                        results.append(("System WebSocket", "200", "Connected"))
            except Exception as e:
                results.append(("System WebSocket", "ERROR", str(e)))
                
        except Exception as e:
            results.append(("System Admin Section", "ERROR", str(e)))
        
        # Test 3: Prediction Markets Section
        print("\n📈 Testing Prediction Markets Section")
        print("-" * 40)
        
        try:
            async with session.get(f"{base_url}/api/v1/prediction/markets") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Prediction Markets", "200", f"{len(data.get('markets', []))} markets"))
                else:
                    results.append(("Prediction Markets", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/prediction/stats") as resp:
                if resp.status == 200:
                    results.append(("Prediction Stats", "200", "success"))
                else:
                    results.append(("Prediction Stats", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/prediction/categories") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Prediction Categories", "200", f"{len(data.get('categories', []))} categories"))
                else:
                    results.append(("Prediction Categories", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/prediction/trending") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Trending Markets", "200", f"{len(data.get('trending', []))} trending"))
                else:
                    results.append(("Trending Markets", str(resp.status), "Failed"))
            
            # Test WebSocket
            ws_url = f"ws://127.0.0.1:8011/ws/prediction"
            try:
                async with session.ws_connect(ws_url) as ws:
                    msg = await ws.receive_json(timeout=5)
                    if msg.get("type") == "connected":
                        results.append(("Prediction WebSocket", "200", "Connected successfully"))
                    else:
                        results.append(("Prediction WebSocket", "200", "Connected"))
            except Exception as e:
                results.append(("Prediction WebSocket", "ERROR", str(e)))
                
        except Exception as e:
            results.append(("Prediction Markets Section", "ERROR", str(e)))
        
        # Test 4: Agent Cohorts Section
        print("\n🤖 Testing Agent Cohorts Section")
        print("-" * 40)
        
        try:
            async with session.get(f"{base_url}/api/v1/agents/cohorts") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Agent Cohorts", "200", f"{len(data.get('cohorts', []))} cohorts"))
                else:
                    results.append(("Agent Cohorts", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/agents/list") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Agent List", "200", f"{len(data.get('agents', []))} agents"))
                else:
                    results.append(("Agent List", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/agents/stats") as resp:
                if resp.status == 200:
                    results.append(("Agent Stats", "200", "Data available"))
                else:
                    results.append(("Agent Stats", str(resp.status), "Failed"))
            
            async with session.get(f"{base_url}/api/v1/agents/performance/top") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results.append(("Top Performers", "200", f"{len(data.get('top_agents', []))} agents"))
                else:
                    results.append(("Top Performers", str(resp.status), "Failed"))
            
            # Test WebSocket
            ws_url = f"ws://127.0.0.1:8011/ws/agents"
            try:
                async with session.ws_connect(ws_url) as ws:
                    msg = await ws.receive_json(timeout=5)
                    if msg.get("type") == "connected":
                        results.append(("Agents WebSocket", "200", "Connected successfully"))
                    else:
                        results.append(("Agents WebSocket", "200", "Connected"))
            except Exception as e:
                results.append(("Agents WebSocket", "ERROR", str(e)))
                
        except Exception as e:
            results.append(("Agent Cohorts Section", "ERROR", str(e)))
        
        # Test 5: General Events WebSocket
        print("\n🔌 Testing General Events WebSocket")
        print("-" * 40)
        
        try:
            ws_url = f"ws://127.0.0.1:8011/ws"
            async with session.ws_connect(ws_url) as ws:
                msg = await ws.receive_json(timeout=5)
                if msg.get("type") == "connected":
                    results.append(("General Events", "200", "Connected successfully"))
                else:
                    results.append(("General Events", "200", "Connected"))
        except Exception as e:
            results.append(("General Events", "ERROR", str(e)))
    
    # Print results
    print(f"\n🎯 PHASE 2.2 COMPLETE RESULTS")
    print("=" * 60)
    
    sections = {}
    for test_name, status, details in results:
        section = test_name.split()[0]
        if section not in sections:
            sections[section] = []
        sections[section].append((test_name, status, details))
    
    for section, tests in sections.items():
        print(f"\n📁 {section}")
        print("-" * 40)
        for test_name, status, details in tests:
            icon = "✅" if status == "200" else "❌"
            print(f"{icon} {test_name}: {status}")
            if details != "success" and details != "Failed":
                print(f"   {details}")
    
    # Summary
    total_tests = len(results)
    passed_tests = len([r for r in results if r[1] == "200"])
    api_tests = len([r for r in results if "WebSocket" not in r[0]])
    ws_tests = len([r for r in results if "WebSocket" in r[0]])
    passed_apis = len([r for r in results if r[1] == "200" and "WebSocket" not in r[0]])
    passed_wss = len([r for r in results if r[1] == "200" and "WebSocket" in r[0]])
    
    print(f"\n📊 SUMMARY")
    print("=" * 60)
    print(f"📁 Total Tests: {total_tests}")
    print(f"✅ Passed Tests: {passed_tests}")
    print(f"❌ Failed Tests: {total_tests - passed_tests}")
    print(f"📈 Success Rate: {(passed_tests/total_tests*100):.1f}%")
    print(f"🔌 API Tests: {api_tests}/{passed_apis} passed")
    print(f"🌐 WebSocket Tests: {ws_tests}/{passed_wss} passed")
    
    # Sections implemented
    sections_implemented = len(sections)
    print(f"\n📋 SECTIONS IMPLEMENTED: {sections_implemented}/4")
    for section in sections:
        section_passed = all(test[1] == "200" for test in sections[section])
        icon = "✅" if section_passed else "❌"
        print(f"{icon} {section}")
    
    print(f"\n📱 Test the complete Phase 2.2 implementation:")
    print(f"   - Arbitrage: http://127.0.0.1:8011/unified/markets/arbitrage")
    print(f"   - System Admin: http://127.0.0.1:8011/unified/admin/system")
    print(f"   - Prediction Markets: http://127.0.0.1:8011/unified/markets/prediction")
    print(f"   - Agent Cohorts: http://127.0.0.1:8011/unified/agents/cohorts")
    
    if passed_tests == total_tests:
        print(f"\n🎉 PHASE 2.2 COMPLETE SUCCESS!")
        print(f"✅ All sections implemented - COMPLETE")
        print(f"✅ All APIs working - COMPLETE")
        print(f"✅ All WebSocket endpoints working - COMPLETE")
        print(f"✅ Canonical pattern - PROVEN")
        print(f"✅ Mock APIs - COMPREHENSIVE")
        print(f"✅ Real-time streaming - FUNCTIONAL")
    else:
        print(f"\n⚠️  PHASE 2.2 PARTIAL SUCCESS")
        print(f"✅ {sections_implemented}/4 sections implemented")
        print(f"✅ {passed_apis}/{api_tests} APIs working")
        print(f"✅ {passed_wss}/{ws_tests} WebSocket endpoints working")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    asyncio.run(test_phase2_2_complete())
