#!/usr/bin/env python3
"""
MERID Predictions Integration Test Script

This script validates the predictions API integration and can be used to:
1. Test current mock data endpoints
2. Validate live data integration once available
3. Monitor data freshness and quality
4. Generate integration reports

Usage:
    python test_predictions_integration.py [--mode mock|live] [--output report.json]
"""

import requests
import json
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any
import sys

class PredictionsIntegrationTester:
    def __init__(self, base_url: str = "http://localhost:8000", mode: str = "mock"):
        self.base_url = base_url
        self.mode = mode
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "endpoints": {},
            "overall_status": "unknown"
        }
    
    def test_endpoint(self, endpoint: str, expected_min_items: int = 1) -> Dict[str, Any]:
        """Test a specific predictions endpoint."""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            response = requests.get(url, timeout=10)
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                data = response.json()
                
                # Validate response structure
                validation = self.validate_response_structure(endpoint, data)
                
                # Check data quantity
                data_key = self.get_data_key(endpoint)
                items = data.get(data_key, [])
                item_count = len(items)
                
                # Check freshness for live mode
                freshness = self.check_freshness(endpoint, data) if self.mode == "live" else None
                
                result = {
                    "status": "success",
                    "status_code": response.status_code,
                    "response_time_ms": round(response_time, 2),
                    "item_count": item_count,
                    "expected_min_items": expected_min_items,
                    "meets_minimum": item_count >= expected_min_items,
                    "validation": validation,
                    "freshness": freshness,
                    "sample_data": items[0] if items else None
                }
                
                self.results["endpoints"][endpoint] = result
                return result
                
            else:
                error_result = {
                    "status": "error",
                    "status_code": response.status_code,
                    "response_time_ms": round(response_time, 2),
                    "error": response.text
                }
                self.results["endpoints"][endpoint] = error_result
                return error_result
                
        except requests.exceptions.RequestException as e:
            error_result = {
                "status": "error",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
            self.results["endpoints"][endpoint] = error_result
            return error_result
    
    def get_data_key(self, endpoint: str) -> str:
        """Get the key that contains the main data array for each endpoint."""
        if "/markets" in endpoint:
            return "markets"
        elif "/drift" in endpoint:
            return "signals"
        elif "/arbitrage" in endpoint:
            return "opportunities"
        else:
            return "data"
    
    def validate_response_structure(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the response structure matches expected schema."""
        validation = {
            "has_status": "status" in data,
            "has_count": "count" in data,
            "has_data_key": self.get_data_key(endpoint) in data,
            "status_is_success": data.get("status") == "success",
            "count_matches_items": False,
            "required_fields_present": []
        }
        
        data_key = self.get_data_key(endpoint)
        items = data.get(data_key, [])
        
        if "count" in data:
            validation["count_matches_items"] = data["count"] == len(items)
        
        # Check required fields in items
        if items and "/arbitrage" in endpoint:
            item = items[0]
            required_fields = ["id", "canonical_question", "markets", "max_probability", "min_probability"]
            validation["required_fields_present"] = [field for field in required_fields if field in item]
        
        return validation
    
    def check_freshness(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check data freshness for live mode."""
        freshness = {
            "has_freshness_info": "data_freshness" in data,
            "max_age_seconds": None,
            "is_fresh": False,
            "age_seconds": None
        }
        
        if "data_freshness" in data:
            freshness_info = data["data_freshness"]
            freshness["max_age_seconds"] = freshness_info.get("max_age_seconds")
            
            if "last_update" in freshness_info:
                try:
                    last_update = datetime.fromisoformat(freshness_info["last_update"].replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - last_update).total_seconds()
                    freshness["age_seconds"] = round(age, 2)
                    freshness["is_fresh"] = age <= (freshness.get("max_age_seconds", 60))
                except ValueError:
                    freshness["is_fresh"] = False
        
        return freshness
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all predictions endpoint tests."""
        print(f"🧪 Testing MERID Predictions Integration (Mode: {self.mode.upper()})")
        print("=" * 60)
        
        # Test all endpoints
        endpoints = [
            ("/api/v1/institutional/predictions/markets", 1),
            ("/api/v1/institutional/predictions/drift", 1),
            ("/api/v1/institutional/predictions/arbitrage", 1)
        ]
        
        results = []
        for endpoint, min_items in endpoints:
            print(f"Testing {endpoint}...")
            result = self.test_endpoint(endpoint, min_items)
            results.append(result)
            
            status_icon = "✅" if result["status"] == "success" else "❌"
            print(f"{status_icon} {endpoint}: {result['status']} ({result.get('item_count', 0)} items)")
            
            if result["status"] == "success":
                print(f"   Response time: {result['response_time_ms']}ms")
                if result.get("freshness"):
                    fresh_icon = "✅" if result["freshness"]["is_fresh"] else "⚠️"
                    print(f"   Freshness: {fresh_icon} {result['freshness'].get('age_seconds', 'N/A')}s old")
        
        # Calculate overall status
        success_count = sum(1 for r in results if r["status"] == "success")
        total_count = len(results)
        
        if success_count == total_count:
            self.results["overall_status"] = "success"
            print(f"\n✅ All {total_count} endpoints working correctly!")
        elif success_count > 0:
            self.results["overall_status"] = "partial"
            print(f"\n⚠️ {success_count}/{total_count} endpoints working")
        else:
            self.results["overall_status"] = "failed"
            print(f"\n❌ All endpoints failed")
        
        return self.results
    
    def generate_report(self, output_file: str = None) -> str:
        """Generate a detailed integration report."""
        report = {
            "summary": {
                "timestamp": self.results["timestamp"],
                "mode": self.results["mode"],
                "overall_status": self.results["overall_status"],
                "total_endpoints": len(self.results["endpoints"]),
                "successful_endpoints": sum(1 for e in self.results["endpoints"].values() if e["status"] == "success"),
                "average_response_time": sum(e.get("response_time_ms", 0) for e in self.results["endpoints"].values()) / len(self.results["endpoints"])
            },
            "endpoints": self.results["endpoints"]
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n📄 Report saved to: {output_file}")
        
        return json.dumps(report, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Test MERID Predictions API Integration")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="Test mode (mock or live data)")
    parser.add_argument("--output", help="Output file for JSON report")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL for API")
    
    args = parser.parse_args()
    
    tester = PredictionsIntegrationTester(base_url=args.base_url, mode=args.mode)
    results = tester.run_all_tests()
    
    if args.output:
        tester.generate_report(args.output)
    
    # Exit with appropriate code
    if results["overall_status"] == "success":
        sys.exit(0)
    elif results["overall_status"] == "partial":
        sys.exit(1)
    else:
        sys.exit(2)

if __name__ == "__main__":
    main()
