#!/usr/bin/env python3
"""
Live Data Integration Validation Script

This script validates the transition from mock to live data and ensures:
1. Schema compliance
2. Data freshness
3. Minimum viability requirements
4. Performance benchmarks

Usage:
    python validate_live_integration.py [--compare] [--output report.json]
"""

import requests
import json
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any
import sys

class LiveIntegrationValidator:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "validation_results": {},
            "comparison_results": {},
            "overall_status": "unknown"
        }
    
    def validate_live_data(self) -> Dict[str, Any]:
        """Validate live data integration."""
        print("🔍 Validating Live Data Integration")
        print("=" * 50)
        
        # Test the arbitrage endpoint
        endpoint = "/api/v1/institutional/predictions/arbitrage"
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Validate schema
                schema_validation = self._validate_schema(data)
                
                # Validate data quality
                quality_validation = self._validate_data_quality(data)
                
                # Validate freshness
                freshness_validation = self._validate_freshness(data)
                
                # Validate performance
                performance_validation = self._validate_performance(response)
                
                result = {
                    "status": "success",
                    "schema_validation": schema_validation,
                    "quality_validation": quality_validation,
                    "freshness_validation": freshness_validation,
                    "performance_validation": performance_validation,
                    "sample_data": data.get("opportunities", [])[:2]  # First 2 opportunities
                }
                
                self.results["validation_results"] = result
                return result
                
            else:
                error_result = {
                    "status": "error",
                    "status_code": response.status_code,
                    "error": response.text
                }
                self.results["validation_results"] = error_result
                return error_result
                
        except Exception as e:
            error_result = {
                "status": "error",
                "error": str(e)
            }
            self.results["validation_results"] = error_result
            return error_result
    
    def _validate_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate response schema matches requirements."""
        validation = {
            "has_status": "status" in data,
            "has_opportunities": "opportunities" in data,
            "has_count": "count" in data,
            "has_data_freshness": "data_freshness" in data,
            "status_is_success": data.get("status") == "success",
            "count_matches_opportunities": data.get("count", 0) == len(data.get("opportunities", [])),
            "opportunity_fields": []
        }
        
        # Check opportunity fields
        opportunities = data.get("opportunities", [])
        if opportunities:
            sample = opportunities[0]
            required_fields = ["id", "canonical_question", "markets", "max_probability", "min_probability", "spread_probability"]
            validation["opportunity_fields"] = [field for field in required_fields if field in sample]
        
        return validation
    
    def _validate_data_quality(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data quality meets minimum requirements."""
        opportunities = data.get("opportunities", [])
        
        quality = {
            "has_opportunities": len(opportunities) > 0,
            "opportunity_count": len(opportunities),
            "meets_minimum_spread": False,
            "meets_minimum_liquidity": False,
            "valid_probabilities": True,
            "valid_timestamps": True
        }
        
        # Check minimum requirements
        for opp in opportunities:
            # Check spread
            if opp.get("spread_probability", 0) >= 0.05:
                quality["meets_minimum_spread"] = True
            
            # Check liquidity/profit
            if opp.get("profit_potential", 0) >= 50000:
                quality["meets_minimum_liquidity"] = True
            
            # Check probability ranges
            max_prob = opp.get("max_probability", 0)
            min_prob = opp.get("min_probability", 0)
            if not (0 <= max_prob <= 1 and 0 <= min_prob <= 1):
                quality["valid_probabilities"] = False
            
            # Check timestamp
            timestamp = opp.get("timestamp")
            if timestamp:
                try:
                    datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except ValueError:
                    quality["valid_timestamps"] = False
        
        return quality
    
    def _validate_freshness(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data freshness meets SLO."""
        freshness = {
            "has_freshness_info": "data_freshness" in data,
            "max_age_specified": False,
            "last_update_present": False,
            "age_seconds": None,
            "meets_slo": False
        }
        
        if "data_freshness" in data:
            freshness_info = data["data_freshness"]
            freshness["max_age_specified"] = "max_age_seconds" in freshness_info
            freshness["last_update_present"] = "last_update" in freshness_info
            
            if "last_update" in freshness_info:
                try:
                    last_update = datetime.fromisoformat(freshness_info["last_update"].replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - last_update).total_seconds()
                    freshness["age_seconds"] = round(age, 2)
                    
                    max_age = freshness_info.get("max_age_seconds", 30)
                    freshness["meets_slo"] = age <= max_age
                except ValueError:
                    pass
        
        return freshness
    
    def _validate_performance(self, response: requests.Response) -> Dict[str, Any]:
        """Validate response performance meets requirements."""
        return {
            "response_time_ms": response.elapsed.total_seconds() * 1000,
            "meets_slo": response.elapsed.total_seconds() <= 5.0  # 5 second SLO
        }
    
    def compare_with_mock(self) -> Dict[str, Any]:
        """Compare live data with mock data baseline."""
        print("\n🔄 Comparing Live vs Mock Data")
        print("=" * 30)
        
        # Get live data
        live_result = self.validate_live_data()
        
        # Get mock data (switch to mock mode temporarily)
        mock_result = self._get_mock_data()
        
        comparison = {
            "live_opportunities": live_result.get("sample_data", []),
            "mock_opportunities": mock_result.get("sample_data", []),
            "schema_consistency": self._compare_schemas(live_result, mock_result),
            "data_volume_comparison": {
                "live_count": len(live_result.get("sample_data", [])),
                "mock_count": len(mock_result.get("sample_data", []))
            },
            "performance_comparison": {
                "live_response_time": live_result.get("performance_validation", {}).get("response_time_ms", 0),
                "mock_response_time": mock_result.get("performance_validation", {}).get("response_time_ms", 0)
            }
        }
        
        self.results["comparison_results"] = comparison
        return comparison
    
    def _get_mock_data(self) -> Dict[str, Any]:
        """Get mock data for comparison."""
        # This would call the mock endpoint
        endpoint = "/api/v1/institutional/predictions/arbitrage"
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "success",
                    "sample_data": data.get("opportunities", [])[:2],
                    "performance_validation": {"response_time_ms": response.elapsed.total_seconds() * 1000}
                }
        except Exception as e:
            pass
        
        return {"status": "error", "sample_data": []}
    
    def _compare_schemas(self, live_result: Dict, mock_result: Dict) -> Dict[str, Any]:
        """Compare schema consistency between live and mock data."""
        live_schema = live_result.get("schema_validation", {})
        mock_schema = mock_result.get("schema_validation", {})
        
        return {
            "both_have_status": live_schema.get("has_status") and mock_schema.get("has_status"),
            "both_have_opportunities": live_schema.get("has_opportunities") and mock_schema.get("has_opportunities"),
            "both_have_count": live_schema.get("has_count") and mock_schema.get("has_count"),
            "field_consistency": len(set(live_schema.get("opportunity_fields", [])) & set(mock_schema.get("opportunity_fields", [])))
        }
    
    def generate_report(self, output_file: str = None) -> str:
        """Generate comprehensive validation report."""
        report = {
            "summary": {
                "timestamp": self.results["timestamp"],
                "validation_status": self.results["validation_results"].get("status", "unknown"),
                "schema_compliant": self.results["validation_results"].get("schema_validation", {}).get("status_is_success", False),
                "data_quality_acceptable": self.results["validation_results"].get("quality_validation", {}).get("meets_minimum_spread", False) and self.results["validation_results"].get("quality_validation", {}).get("meets_minimum_liquidity", False),
                "freshness_slo_met": self.results["validation_results"].get("freshness_validation", {}).get("meets_slo", False),
                "performance_slo_met": self.results["validation_results"].get("performance_validation", {}).get("meets_slo", False)
            },
            "validation_results": self.results["validation_results"],
            "comparison_results": self.results.get("comparison_results", {}),
            "recommendations": self._generate_recommendations()
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n📄 Validation report saved to: {output_file}")
        
        return json.dumps(report, indent=2)
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on validation results."""
        recommendations = []
        
        validation = self.results.get("validation_results", {})
        
        if validation.get("status") != "success":
            recommendations.append("❌ Critical: Fix API endpoint errors before proceeding")
        
        schema = validation.get("schema_validation", {})
        if not schema.get("status_is_success", False):
            recommendations.append("🔧 Fix schema compliance issues")
        
        quality = validation.get("quality_validation", {})
        if not quality.get("meets_minimum_spread", False):
            recommendations.append("📊 Ensure minimum spread of 0.05 is met")
        if not quality.get("meets_minimum_liquidity", False):
            recommendations.append("💰 Ensure minimum liquidity/profit of $50,000")
        
        freshness = validation.get("freshness_validation", {})
        if not freshness.get("meets_slo", False):
            recommendations.append("⏰ Improve data freshness to meet 30-second SLO")
        
        performance = validation.get("performance_validation", {})
        if not performance.get("meets_slo", False):
            recommendations.append("🚀 Optimize response time to meet 5-second SLO")
        
        if not recommendations:
            recommendations.append("✅ All validation criteria met - ready for production!")
        
        return recommendations

def main():
    parser = argparse.ArgumentParser(description="Validate MERID Live Data Integration")
    parser.add_argument("--compare", action="store_true", help="Compare live data with mock baseline")
    parser.add_argument("--output", help="Output file for validation report")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL for API")
    
    args = parser.parse_args()
    
    validator = LiveIntegrationValidator(base_url=args.base_url)
    
    # Run validation
    validator.validate_live_data()
    
    # Run comparison if requested
    if args.compare:
        validator.compare_with_mock()
    
    # Generate report
    report = validator.generate_report(args.output)
    
    # Print summary
    print("\n🎯 Validation Summary:")
    print("=" * 20)
    print(report)
    
    # Exit with appropriate code
    validation = validator.results.get("validation_results", {})
    if validation.get("status") == "success":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
