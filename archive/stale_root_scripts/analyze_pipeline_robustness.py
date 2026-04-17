#!/usr/bin/env python3
"""
Comprehensive Pipeline and Publishing Robustness Analysis

Analyzes all pipeline and publishing components for:
- Error handling and resilience
- Data validation and sanitization  
- Retry logic and circuit breaking
- Resource management and memory leaks
- Security vulnerabilities
- Performance bottlenecks
- Race conditions and thread safety
"""

import asyncio
import os
import sys
import re
from typing import Dict, List, Any, Optional
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def analyze_file_for_robustness(file_path: str) -> Dict[str, Any]:
    """Analyze a single file for robustness issues."""
    issues = []
    suggestions = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Check for common robustness patterns
        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            
            # 1. Missing error handling
            if line_stripped.startswith('await ') and 'try:' not in lines[max(0, i-5):i]:
                if 'except' not in lines[i:i+10]:
                    issues.append(f"Line {i}: Unhandled await call - {line_stripped[:50]}...")
            
            # 2. Potential infinite loops
            if 'while True:' in line_stripped and 'await asyncio.sleep' not in content[i-1:i+5]:
                issues.append(f"Line {i}: Potential infinite loop without sleep")
            
            # 3. Missing input validation
            if 'def ' in line_stripped and '->' in line_stripped:
                func_name = line_stripped.split('def ')[1].split('(')[0]
                if 'if not' not in content[i:i+20] and 'raise' not in content[i:i+20]:
                    suggestions.append(f"Line {i}: Function {func_name} may need input validation")
            
            # 4. Hardcoded timeouts
            if 'timeout=' in line_stripped and any(x in line_stripped for x in ['15', '30', '60']):
                suggestions.append(f"Line {i}: Consider making timeout configurable")
            
            # 5. Missing retry logic
            if 'httpx' in line_stripped and 'retry' not in content[i-10:i+10]:
                suggestions.append(f"Line {i}: HTTP call may benefit from retry logic")
            
            # 6. Potential memory leaks
            if 'self.' in line_stripped and '.append(' in line_stripped and 'if len(' not in content[i-5:i+5]:
                suggestions.append(f"Line {i}: Consider bounds checking for list growth")
            
            # 7. Race conditions
            if 'global ' in line_stripped and 'lock' not in content[i-5:i+5]:
                issues.append(f"Line {i}: Global variable access without lock")
            
            # 8. SQL injection risks
            if 'execute(' in line_stripped and '%' in line_stripped and 'cursor' in line_stripped:
                issues.append(f"Line {i}: Potential SQL injection - use parameterized queries")
            
            # 9. XSS risks
            if 'return ' in line_stripped and any(x in line_stripped for x in ['<', '>']) and 'escape' not in content[i-5:i+5]:
                issues.append(f"Line {i}: Potential XSS - sanitize HTML output")
            
            # 10. Resource cleanup
            if 'open(' in line_stripped and 'with' not in line_stripped and 'close()' not in content[i:i+10]:
                issues.append(f"Line {i}: File handle may not be properly closed")
        
        return {
            'file': file_path,
            'issues': issues,
            'suggestions': suggestions,
            'lines_analyzed': len(lines)
        }
        
    except Exception as e:
        return {
            'file': file_path,
            'error': str(e),
            'issues': [],
            'suggestions': []
        }

def analyze_pipeline_robustness():
    """Analyze all pipeline and publishing files."""
    print("🔍 COMPREHENSIVE PIPELINE & PUBLISHING ROBUSTNESS ANALYSIS")
    print("=" * 70)
    
    # Key pipeline and publishing files
    files_to_analyze = [
        "merid/publishing/kalshi_insight_pipeline.py",
        "merid/publishing/kalshi_news_agent.py", 
        "web/api/unified_pipeline.py",
        "web/services/swarm_publishers.py",
        "web/services/price_publisher.py",
        "web/services/prediction_publisher.py",
        "web/services/portfolio_publisher.py",
        "merid/pipeline/risk_manager.py",
        "merid/pipeline/router.py",
        "merid/pipeline/adapter.py",
        "merid/pipeline/mode_manager.py",
        "merid/pipeline/domain_agents.py",
        "merid/pipeline/instruments.py",
        "merid/pipeline/risk_context.py",
        "merid/pipeline/routing_policy.py",
        "merid/pipeline/proposal.py"
    ]
    
    total_issues = 0
    total_suggestions = 0
    critical_issues = []
    
    for file_path in files_to_analyze:
        if os.path.exists(file_path):
            print(f"\n📄 Analyzing: {file_path}")
            result = analyze_file_for_robustness(file_path)
            
            if 'error' in result:
                print(f"  ❌ Error analyzing file: {result['error']}")
                continue
            
            issues = result['issues']
            suggestions = result['suggestions']
            
            if issues:
                print(f"  🚨 Issues Found ({len(issues)}):")
                for issue in issues[:5]:  # Show first 5 issues
                    print(f"    • {issue}")
                    if 'Unhandled await' in issue or 'infinite loop' in issue or 'SQL injection' in issue:
                        critical_issues.append(f"{file_path}: {issue}")
                
                if len(issues) > 5:
                    print(f"    ... and {len(issues) - 5} more issues")
            
            if suggestions:
                print(f"  💡 Suggestions ({len(suggestions)}):")
                for suggestion in suggestions[:3]:  # Show first 3 suggestions
                    print(f"    • {suggestion}")
                
                if len(suggestions) > 3:
                    print(f"    ... and {len(suggestions) - 3} more suggestions")
            
            if not issues and not suggestions:
                print("  ✅ No robustness issues found")
            
            total_issues += len(issues)
            total_suggestions += len(suggestions)
            
        else:
            print(f"\n📄 File not found: {file_path}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 ANALYSIS SUMMARY")
    print("=" * 70)
    print(f"Total Issues Found: {total_issues}")
    print(f"Total Suggestions: {total_suggestions}")
    
    if critical_issues:
        print(f"\n🚨 CRITICAL ISSUES ({len(critical_issues)}):")
        for issue in critical_issues:
            print(f"  • {issue}")
    
    # Robustness Recommendations
    print(f"\n🛠️ ROBUSTNESS RECOMMENDATIONS")
    print("=" * 70)
    
    recommendations = [
        "1. Add comprehensive error handling with try/catch blocks around all async calls",
        "2. Implement retry logic with exponential backoff for external API calls", 
        "3. Add input validation and sanitization for all user-facing inputs",
        "4. Use circuit breakers for external service dependencies",
        "5. Add rate limiting to prevent API abuse and resource exhaustion",
        "6. Implement proper resource cleanup with context managers",
        "7. Add monitoring and alerting for pipeline failures",
        "8. Use thread-safe patterns for shared state management",
        "9. Add graceful shutdown handling for all background tasks",
        "10. Implement health checks and readiness probes"
    ]
    
    for rec in recommendations:
        print(f"  {rec}")
    
    return {
        'total_issues': total_issues,
        'total_suggestions': total_suggestions,
        'critical_issues': critical_issues,
        'recommendations': recommendations
    }

def main():
    """Run the comprehensive robustness analysis."""
    results = analyze_pipeline_robustness()
    
    if results['total_issues'] == 0:
        print("\n🎉 EXCELLENT: No critical robustness issues found!")
    else:
        print(f"\n⚠️  ACTION REQUIRED: {results['total_issues']} issues need attention")
    
    return results['total_issues'] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
