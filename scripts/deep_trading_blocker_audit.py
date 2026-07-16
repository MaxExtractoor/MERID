#!/usr/bin/env python3
"""
Deep Trading Blocker Audit Script

This script performs an exhaustive, paranoid audit of the 15m Kalshi crypto trading system
to identify all potential blockers preventing agents from selecting YES/NO contracts every 15 minutes.

Audit areas:
1. Spread filtering enforcement across all components
2. Price range enforcement (10-50c sweet spot)
3. Market data pipeline (bid/ask spreads, liquidity)
4. Candidate filtering logic
5. YES/NO contract selection logic
6. Profile configuration consistency
7. Any embedded bugs or discrepancies

Author: Cascade Deep Audit
Date: 2026-07-10
"""

import os
import sys
import re
import ast
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class AuditFinding:
    """Represents a single audit finding."""
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    component: str
    file_path: str
    line_number: int
    issue: str
    impact: str
    recommendation: str


@dataclass
class ComponentConfig:
    """Configuration values for a component."""
    component_name: str
    file_path: str
    max_spread_cents: Optional[int] = None
    min_price_cents: Optional[int] = None
    max_price_cents: Optional[int] = None
    min_depth: Optional[int] = None
    source: str = "code"  # code, profile, env


class DeepTradingBlockerAudit:
    """Comprehensive audit of trading blockers."""
    
    def __init__(self):
        self.findings: List[AuditFinding] = []
        self.component_configs: Dict[str, ComponentConfig] = {}
        self.profile_config: Dict[str, Any] = {}
        
    def run_full_audit(self) -> List[AuditFinding]:
        """Run the complete audit and return all findings."""
        print("=" * 80)
        print("DEEP TRADING BLOCKER AUDIT")
        print("=" * 80)
        
        # Phase 1: Profile configuration audit
        self.audit_profile_config()
        
        # Phase 2: Spread filtering audit
        self.audit_spread_filtering()
        
        # Phase 3: Price range enforcement audit
        self.audit_price_range_enforcement()
        
        # Phase 4: Market data pipeline audit
        self.audit_market_data_pipeline()
        
        # Phase 5: YES/NO selection logic audit
        self.audit_yes_no_selection()
        
        # Phase 6: Candidate filtering audit
        self.audit_candidate_filtering()
        
        # Phase 7: Cross-component consistency check
        self.audit_cross_component_consistency()
        
        # Phase 8: Embedded bug detection
        self.audit_embedded_bugs()
        
        # Generate report
        self.generate_report()
        
        return self.findings
    
    def audit_profile_config(self):
        """Audit profile YAML configuration."""
        print("\n[PHASE 1] AUDITING PROFILE CONFIGURATION")
        print("-" * 80)
        
        profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            self.add_finding(
                category="Profile Config",
                severity="CRITICAL",
                component="Profile YAML",
                file_path=str(profile_path),
                line_number=0,
                issue="Profile YAML file not found",
                impact="System cannot load configuration",
                recommendation="Create kalshi_crypto_15m_v2.yaml or verify correct path"
            )
            return
        
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                import yaml
                self.profile_config = yaml.safe_load(f)
            
            # Check guardrails max_spread_cents
            guardrails = self.profile_config.get('guardrails', {})
            max_spread = guardrails.get('max_spread_cents')
            
            if max_spread is None:
                self.add_finding(
                    category="Profile Config",
                    severity="HIGH",
                    component="guardrails.max_spread_cents",
                    file_path=str(profile_path),
                    line_number=0,
                    issue="guardrails.max_spread_cents not defined in profile",
                    impact="Spread filtering may use incorrect default",
                    recommendation="Add max_spread_cents to guardrails section (expected: 30c)"
                )
            else:
                print(f"✓ guardrails.max_spread_cents = {max_spread}c")
                if max_spread != 30:
                    self.add_finding(
                        category="Profile Config",
                        severity="MEDIUM",
                        component="guardrails.max_spread_cents",
                        file_path=str(profile_path),
                        line_number=0,
                        issue=f"guardrails.max_spread_cents = {max_spread}c (expected 30c)",
                        impact="Spread threshold may not align with 10-50c sweet spot",
                        recommendation="Set max_spread_cents to 30c to harmonize with 10-50c entry price"
                    )
            
            # Check price_range
            price_range = self.profile_config.get('price_range', {})
            min_price = price_range.get('min_price_cents')
            max_price = price_range.get('max_price_cents')
            
            if min_price is None or max_price is None:
                self.add_finding(
                    category="Profile Config",
                    severity="HIGH",
                    component="price_range",
                    file_path=str(profile_path),
                    line_number=0,
                    issue="price_range min_price_cents or max_price_cents not defined",
                    impact="Price range filtering may use incorrect defaults",
                    recommendation="Add min_price_cents=10 and max_price_cents=75 to price_range"
                )
            else:
                print(f"✓ price_range.min_price_cents = {min_price}c")
                print(f"✓ price_range.max_price_cents = {max_price}c")
                
                if min_price != 10:
                    self.add_finding(
                        category="Profile Config",
                        severity="MEDIUM",
                        component="price_range.min_price_cents",
                        file_path=str(profile_path),
                        line_number=0,
                        issue=f"price_range.min_price_cents = {min_price}c (expected 10c)",
                        impact="May block valid 10-14c entries in sweet spot",
                        recommendation="Set min_price_cents to 10c for momentum-based trading"
                    )
                
                if max_price != 50:
                    self.add_finding(
                        category="Profile Config",
                        severity="MEDIUM",
                        component="price_range.max_price_cents",
                        file_path=str(profile_path),
                        line_number=0,
                        issue=f"price_range.max_price_cents = {max_price}c (expected 75c)",
                        impact="May allow entries above 75c with poor risk/reward",
                        recommendation="Set max_price_cents to 75c for canonical range"
                    )
            
            # Check universe config
            universe = self.profile_config.get('universe', {})
            universe_max_spread = universe.get('max_spread_cents')
            
            if universe_max_spread is not None:
                print(f"✓ universe.max_spread_cents = {universe_max_spread}c")
                if universe_max_spread != 30:
                    self.add_finding(
                        category="Profile Config",
                        severity="MEDIUM",
                        component="universe.max_spread_cents",
                        file_path=str(profile_path),
                        line_number=0,
                        issue=f"universe.max_spread_cents = {universe_max_spread}c (expected 30c)",
                        impact="Universe filtering may be inconsistent with guardrails",
                        recommendation="Align universe.max_spread_cents with guardrails.max_spread_cents"
                    )
            
            # Check market_microstructure config
            market_microstructure = self.profile_config.get('market_microstructure', {})
            if market_microstructure:
                mm_max_spread = market_microstructure.get('max_spread_cents')
                if mm_max_spread is not None:
                    print(f"✓ market_microstructure.max_spread_cents = {mm_max_spread}c")
                    if mm_max_spread != 30:
                        self.add_finding(
                            category="Profile Config",
                            severity="MEDIUM",
                            component="market_microstructure.max_spread_cents",
                            file_path=str(profile_path),
                            line_number=0,
                            issue=f"market_microstructure.max_spread_cents = {mm_max_spread}c (expected 30c)",
                            impact="Microstructure filtering may be inconsistent with guardrails",
                            recommendation="Align market_microstructure.max_spread_cents with guardrails"
                        )
        
        except Exception as e:
            self.add_finding(
                category="Profile Config",
                severity="HIGH",
                component="Profile YAML",
                file_path=str(profile_path),
                line_number=0,
                issue=f"Failed to parse profile YAML: {e}",
                impact="Profile configuration unavailable",
                recommendation="Fix YAML syntax or verify file format"
            )
    
    def audit_spread_filtering(self):
        """Audit spread filtering across all components."""
        print("\n[PHASE 2] AUDITING SPREAD FILTERING")
        print("-" * 80)
        
        # Key files to audit
        files_to_audit = [
            ("merid/prediction/candidate_optimizer.py", "candidate_optimizer"),
            ("merid/prediction/spread_optimizer.py", "spread_optimizer"),
            ("merid/event_venues/kalshi/market_filter.py", "market_filter"),
            ("merid/event_venues/kalshi/universe.py", "universe"),
            ("merid/event_venues/kalshi/order_router.py", "order_router"),
            ("merid/prediction/agent_grid_15m.py", "agent_grid"),
        ]
        
        for file_path, component_name in files_to_audit:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find spread threshold assignments
                spread_pattern = r'(?:max_spread_cents|MAX_SPREAD_CENTS|max_spread)\s*=\s*(\d+)'
                matches = re.finditer(spread_pattern, content)
                
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    spread_value = int(match.group(1))
                    
                    # Check for discrepancies
                    if spread_value != 30:
                        severity = "HIGH" if spread_value > 50 else "MEDIUM"
                        self.add_finding(
                            category="Spread Filtering",
                            severity=severity,
                            component=component_name,
                            file_path=file_path,
                            line_number=line_num,
                            issue=f"Spread threshold = {spread_value}c (expected 30c)",
                            impact="Spread filtering may be too strict or too loose",
                            recommendation="Align with profile guardrails.max_spread_cents = 30c"
                        )
                    else:
                        print(f"✓ {component_name}: spread threshold = {spread_value}c (line {line_num})")
            
            except Exception as e:
                self.add_finding(
                    category="Spread Filtering",
                    severity="LOW",
                    component=component_name,
                    file_path=file_path,
                    line_number=0,
                    issue=f"Failed to audit spread filtering: {e}",
                    impact="Unable to verify spread threshold",
                    recommendation="Manual review required"
                )
    
    def audit_price_range_enforcement(self):
        """Audit price range enforcement (10-50c sweet spot)."""
        print("\n[PHASE 3] AUDITING PRICE RANGE ENFORCEMENT")
        print("-" * 80)
        
        files_to_audit = [
            ("merid/prediction/agent_grid_15m.py", "agent_grid"),
            ("merid/event_venues/kalshi/market_filter.py", "market_filter"),
            ("merid/risk/profiles/global_allocator.py", "global_allocator"),
            ("merid/risk/profiles/crypto_15m_profile.py", "crypto_15m_profile"),
        ]
        
        for file_path, component_name in files_to_audit:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find min_price_cents assignments
                min_price_pattern = r'(?:min_price_cents|ENTRY_MIN_PRICE_CENTS)\s*=\s*(\d+)'
                min_matches = re.finditer(min_price_pattern, content)
                
                for match in min_matches:
                    line_num = content[:match.start()].count('\n') + 1
                    min_value = int(match.group(1))
                    
                    if min_value != 10:
                        self.add_finding(
                            category="Price Range",
                            severity="HIGH",
                            component=component_name,
                            file_path=file_path,
                            line_number=line_num,
                            issue=f"min_price_cents = {min_value}c (expected 10c)",
                            impact="May block valid 10-14c entries in sweet spot",
                            recommendation="Set min_price_cents to 10c for momentum-based trading"
                        )
                    else:
                        print(f"✓ {component_name}: min_price_cents = {min_value}c (line {line_num})")
                
                # Find max_price_cents assignments
                max_price_pattern = r'(?:max_price_cents|ENTRY_MAX_PRICE_CENTS)\s*=\s*(\d+)'
                max_matches = re.finditer(max_price_pattern, content)
                
                for match in max_matches:
                    line_num = content[:match.start()].count('\n') + 1
                    max_value = int(match.group(1))
                    
                    if max_value != 50:
                        self.add_finding(
                            category="Price Range",
                            severity="HIGH",
                            component=component_name,
                            file_path=file_path,
                            line_number=line_num,
                            issue=f"max_price_cents = {max_value}c (expected 75c)",
                            impact="May allow entries above 75c with poor risk/reward",
                            recommendation="Set max_price_cents to 75c for canonical range"
                        )
                    else:
                        print(f"✓ {component_name}: max_price_cents = {max_value}c (line {line_num})")
            
            except Exception as e:
                self.add_finding(
                    category="Price Range",
                    severity="LOW",
                    component=component_name,
                    file_path=file_path,
                    line_number=0,
                    issue=f"Failed to audit price range: {e}",
                    impact="Unable to verify price range enforcement",
                    recommendation="Manual review required"
                )
    
    def audit_market_data_pipeline(self):
        """Audit market data pipeline for bid/ask spread and liquidity data."""
        print("\n[PHASE 4] AUDITING MARKET DATA PIPELINE")
        print("-" * 80)
        
        # Check market_state.py for bid/ask field definitions
        market_state_path = project_root / "merid/event_venues/kalshi/market_state.py"
        if market_state_path.exists():
            try:
                with open(market_state_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for best_bid_cents and best_ask_cents fields
                if 'best_bid_cents' in content and 'best_ask_cents' in content:
                    print("✓ market_state.py has best_bid_cents and best_ask_cents fields")
                else:
                    self.add_finding(
                        category="Market Data",
                        severity="CRITICAL",
                        component="market_state",
                        file_path="merid/event_venues/kalshi/market_state.py",
                        line_number=0,
                        issue="Missing best_bid_cents or best_ask_cents fields",
                        impact="Spread calculation may fail",
                        recommendation="Add best_bid_cents and best_ask_cents fields to KalshiMarketState"
                    )
                
                # Check for spread_cents field
                if 'spread_cents' in content:
                    print("✓ market_state.py has spread_cents field")
                else:
                    self.add_finding(
                        category="Market Data",
                        severity="HIGH",
                        component="market_state",
                        file_path="merid/event_venues/kalshi/market_state.py",
                        line_number=0,
                        issue="Missing spread_cents field",
                        impact="Spread data may not be available",
                        recommendation="Add spread_cents field to KalshiMarketState"
                    )
            
            except Exception as e:
                self.add_finding(
                    category="Market Data",
                    severity="LOW",
                    component="market_state",
                    file_path="merid/event_venues/kalshi/market_state.py",
                    line_number=0,
                    issue=f"Failed to audit market_state.py: {e}",
                    impact="Unable to verify market data fields",
                    recommendation="Manual review required"
                )
        
        # Check for (0,100) anomaly detection
        files_to_check = [
            "merid/event_venues/kalshi/market_state.py",
            "merid/event_venues/kalshi/invariants.py",
        ]
        
        for file_path in files_to_check:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for (0,100) pattern detection
                if 'best_bid_cents == 0 and best_ask_cents == 100' in content:
                    print(f"✓ {file_path} has (0,100) anomaly detection")
                else:
                    self.add_finding(
                        category="Market Data",
                        severity="MEDIUM",
                        component="market_data",
                        file_path=file_path,
                        line_number=0,
                        issue="Missing (0,100) anomaly detection",
                        impact="May not detect empty orderbooks",
                        recommendation="Add check for best_bid_cents == 0 and best_ask_cents == 100"
                    )
            
            except Exception as e:
                pass
    
    def audit_yes_no_selection(self):
        """Audit YES/NO contract selection logic."""
        print("\n[PHASE 5] AUDITING YES/NO SELECTION LOGIC")
        print("-" * 80)
        
        agent_grid_path = project_root / "merid/prediction/agent_grid_15m.py"
        if not agent_grid_path.exists():
            self.add_finding(
                category="YES/NO Selection",
                severity="CRITICAL",
                component="agent_grid",
                file_path="merid/prediction/agent_grid_15m.py",
                line_number=0,
                issue="agent_grid_15m.py not found",
                impact="Signal generation logic unavailable",
                recommendation="Verify file exists"
            )
            return
        
        try:
            with open(agent_grid_path, 'r') as f:
                content = f.read()
            
            # Check for dual-side evaluation
            if 'yes_price_cents' in content and 'no_price_cents' in content:
                print("✓ agent_grid_15m.py has dual-side price evaluation")
            else:
                self.add_finding(
                    category="YES/NO Selection",
                    severity="HIGH",
                    component="agent_grid",
                    file_path="merid/prediction/agent_grid_15m.py",
                    line_number=0,
                    issue="Missing dual-side price evaluation",
                    impact="May not evaluate both YES and NO contracts",
                    recommendation="Add yes_price_cents and no_price_cents evaluation logic"
                )
            
            # Check for price range check (10-50c)
            if '10 <= yes_price_cents <= 50' in content or '10 <= no_price_cents <= 50' in content:
                print("✓ agent_grid_15m.py has 10-50c price range check")
            else:
                self.add_finding(
                    category="YES/NO Selection",
                    severity="HIGH",
                    component="agent_grid",
                    file_path="merid/prediction/agent_grid_15m.py",
                    line_number=0,
                    issue="Missing 10-50c price range check",
                    impact="May trade outside sweet spot range",
                    recommendation="Add price range check: 10 <= price_cents <= 50"
                )
            
            # Check for sides_to_evaluate logic
            if 'sides_to_evaluate' in content:
                print("✓ agent_grid_15m.py has sides_to_evaluate logic")
            else:
                self.add_finding(
                    category="YES/NO Selection",
                    severity="MEDIUM",
                    component="agent_grid",
                    file_path="merid/prediction/agent_grid_15m.py",
                    line_number=0,
                    issue="Missing sides_to_evaluate logic",
                    impact="May not properly evaluate both sides",
                    recommendation="Add sides_to_evaluate list to track which sides to evaluate"
                )
            
            # Check for PRICE-FILTER-REJECT logic
            if 'PRICE-FILTER-REJECT' in content or 'both sides outside' in content:
                print("✓ agent_grid_15m.py has price filter rejection logic")
            else:
                self.add_finding(
                    category="YES/NO Selection",
                    severity="MEDIUM",
                    component="agent_grid",
                    file_path="merid/prediction/agent_grid_15m.py",
                    line_number=0,
                    issue="Missing price filter rejection logic",
                    impact="May not skip when both sides are outside range",
                    recommendation="Add logic to skip when both YES and NO are outside 10-50c range"
                )
        
        except Exception as e:
            self.add_finding(
                category="YES/NO Selection",
                severity="LOW",
                component="agent_grid",
                file_path="merid/prediction/agent_grid_15m.py",
                line_number=0,
                issue=f"Failed to audit YES/NO selection: {e}",
                impact="Unable to verify selection logic",
                recommendation="Manual review required"
            )
    
    def audit_candidate_filtering(self):
        """Audit candidate filtering logic."""
        print("\n[PHASE 6] AUDITING CANDIDATE FILTERING")
        print("-" * 80)
        
        candidate_optimizer_path = project_root / "merid/prediction/candidate_optimizer.py"
        if not candidate_optimizer_path.exists():
            self.add_finding(
                category="Candidate Filtering",
                severity="HIGH",
                component="candidate_optimizer",
                file_path="merid/prediction/candidate_optimizer.py",
                line_number=0,
                issue="candidate_optimizer.py not found",
                impact="Candidate generation logic unavailable",
                recommendation="Verify file exists"
            )
            return
        
        try:
            with open(candidate_optimizer_path, 'r') as f:
                content = f.read()
            
            # Check for spread filtering
            if 'spread_cents > self.max_spread_cents' in content:
                print("✓ candidate_optimizer.py has spread filtering")
            else:
                self.add_finding(
                    category="Candidate Filtering",
                    severity="HIGH",
                    component="candidate_optimizer",
                    file_path="merid/prediction/candidate_optimizer.py",
                    line_number=0,
                    issue="Missing spread filtering in candidate generation",
                    impact="May generate candidates with wide spreads",
                    recommendation="Add spread filter: spread_cents > self.max_spread_cents"
                )
            
            # Check for depth filtering
            if 'total_depth < self.MIN_DEPTH_LEVELS' in content:
                print("✓ candidate_optimizer.py has depth filtering")
            else:
                self.add_finding(
                    category="Candidate Filtering",
                    severity="MEDIUM",
                    component="candidate_optimizer",
                    file_path="merid/prediction/candidate_optimizer.py",
                    line_number=0,
                    issue="Missing depth filtering in candidate generation",
                    impact="May generate candidates with insufficient liquidity",
                    recommendation="Add depth filter: total_depth < self.MIN_DEPTH_LEVELS"
                )
            
            # Check for edge threshold filter
            if '_filter_by_edge_threshold' in content:
                print("✓ candidate_optimizer.py has edge threshold filter")
                # Check if it's disabled
                if 'edge threshold filter disabled' in content.lower():
                    print("  ⚠ Edge threshold filter is DISABLED")
                    self.add_finding(
                        category="Candidate Filtering",
                        severity="MEDIUM",
                        component="candidate_optimizer",
                        file_path="merid/prediction/candidate_optimizer.py",
                        line_number=0,
                        issue="Edge threshold filter is disabled",
                        impact="May generate low-edge candidates",
                        recommendation="Enable edge threshold filter or verify this is intentional"
                    )
            else:
                self.add_finding(
                    category="Candidate Filtering",
                    severity="MEDIUM",
                    component="candidate_optimizer",
                    file_path="merid/prediction/candidate_optimizer.py",
                    line_number=0,
                    issue="Missing edge threshold filter",
                    impact="May not filter by edge quality",
                    recommendation="Add edge threshold filter to _filter_by_edge_threshold"
                )
        
        except Exception as e:
            self.add_finding(
                category="Candidate Filtering",
                severity="LOW",
                component="candidate_optimizer",
                file_path="merid/prediction/candidate_optimizer.py",
                line_number=0,
                issue=f"Failed to audit candidate filtering: {e}",
                impact="Unable to verify filtering logic",
                recommendation="Manual review required"
            )
    
    def audit_cross_component_consistency(self):
        """Audit cross-component consistency."""
        print("\n[PHASE 7] AUDITING CROSS-COMPONENT CONSISTENCY")
        print("-" * 80)
        
        # Collect all spread thresholds
        spread_thresholds = {}
        
        files_to_check = [
            ("merid/prediction/candidate_optimizer.py", "candidate_optimizer"),
            ("merid/prediction/spread_optimizer.py", "spread_optimizer"),
            ("merid/event_venues/kalshi/market_filter.py", "market_filter"),
            ("merid/event_venues/kalshi/universe.py", "universe"),
            ("merid/event_venues/kalshi/order_router.py", "order_router"),
        ]
        
        for file_path, component_name in files_to_check:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find spread threshold assignments
                spread_pattern = r'(?:max_spread_cents|MAX_SPREAD_CENTS)\s*=\s*(\d+)'
                matches = re.finditer(spread_pattern, content)
                
                for match in matches:
                    spread_value = int(match.group(1))
                    if component_name not in spread_thresholds:
                        spread_thresholds[component_name] = []
                    spread_thresholds[component_name].append(spread_value)
            
            except Exception as e:
                pass
        
        # Check for inconsistencies
        unique_values = set()
        for component, values in spread_thresholds.items():
            for value in values:
                unique_values.add(value)
        
        if len(unique_values) > 1:
            self.add_finding(
                category="Cross-Component",
                severity="HIGH",
                component="spread_thresholds",
                file_path="multiple",
                line_number=0,
                issue=f"Inconsistent spread thresholds across components: {unique_values}",
                impact="Spread filtering may behave differently in different parts of system",
                recommendation="Standardize all spread thresholds to 30c (from profile guardrails)"
            )
            print(f"⚠ Inconsistent spread thresholds found: {unique_values}")
        else:
            print(f"✓ All components use consistent spread threshold: {unique_values}")
    
    def audit_embedded_bugs(self):
        """Audit for embedded bugs."""
        print("\n[PHASE 8] AUDITING EMBEDDED BUGS")
        print("-" * 80)
        
        # Check for hardcoded values that should come from profile
        files_to_check = [
            "merid/prediction/agent_grid_15m.py",
            "merid/prediction/candidate_optimizer.py",
            "merid/prediction/spread_optimizer.py",
        ]
        
        for file_path in files_to_check:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for hardcoded spread thresholds without profile fallback
                hardcoded_pattern = r'max_spread_cents\s*=\s*(\d+)\s*#.*hardcoded'
                matches = re.finditer(hardcoded_pattern, content, re.IGNORECASE)
                
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    self.add_finding(
                        category="Embedded Bug",
                        severity="MEDIUM",
                        component=file_path,
                        file_path=file_path,
                        line_number=line_num,
                        issue="Hardcoded spread threshold without profile fallback",
                        impact="May not respect profile configuration",
                        recommendation="Add profile fallback or load from profile"
                    )
                
                # Check for hardcoded price ranges without profile fallback
                hardcoded_price_pattern = r'(?:ENTRY_MIN_PRICE_CENTS|ENTRY_MAX_PRICE_CENTS)\s*=\s*(\d+)\s*#.*hardcoded'
                price_matches = re.finditer(hardcoded_price_pattern, content, re.IGNORECASE)
                
                for match in price_matches:
                    line_num = content[:match.start()].count('\n') + 1
                    self.add_finding(
                        category="Embedded Bug",
                        severity="MEDIUM",
                        component=file_path,
                        file_path=file_path,
                        line_number=line_num,
                        issue="Hardcoded price range without profile fallback",
                        impact="May not respect profile configuration",
                        recommendation="Add profile fallback or load from profile"
                    )
            
            except Exception as e:
                pass
        
        # Check for common bug patterns
        bug_patterns = [
            (r'if\s+velocity\s*==\s*0', "velocity == 0 check (should use tolerance)"),
            (r'if\s+spread\s*==\s*0', "spread == 0 check (should use tolerance)"),
            (r'if\s+depth\s*==\s*0', "depth == 0 check (should use >= 1)"),
            (r'price_cents\s*=\s*50\s*#.*fallback', "50c fallback (should be 42c midpoint for 10-75c range)"),
        ]
        
        for file_path in files_to_check:
            full_path = project_root / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for pattern, description in bug_patterns:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        self.add_finding(
                            category="Embedded Bug",
                            severity="LOW",
                            component=file_path,
                            file_path=file_path,
                            line_number=line_num,
                            issue=f"Potential bug pattern: {description}",
                            impact="May cause edge case failures",
                            recommendation="Review and fix if applicable"
                        )
            
            except Exception as e:
                pass
    
    def add_finding(self, category, severity, component, file_path, line_number, issue, impact, recommendation):
        """Add an audit finding."""
        finding = AuditFinding(
            category=category,
            severity=severity,
            component=component,
            file_path=file_path,
            line_number=line_number,
            issue=issue,
            impact=impact,
            recommendation=recommendation
        )
        self.findings.append(finding)
    
    def generate_report(self):
        """Generate audit report."""
        print("\n" + "=" * 80)
        print("AUDIT REPORT")
        print("=" * 80)
        
        # Group findings by severity
        by_severity = defaultdict(list)
        for finding in self.findings:
            by_severity[finding.severity].append(finding)
        
        # Print findings by severity
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if severity in by_severity:
                print(f"\n{severity} SEVERITY ({len(by_severity[severity])} findings):")
                print("-" * 80)
                for finding in by_severity[severity]:
                    print(f"\nComponent: {finding.component}")
                    print(f"File: {finding.file_path}:{finding.line_number}")
                    print(f"Issue: {finding.issue}")
                    print(f"Impact: {finding.impact}")
                    print(f"Recommendation: {finding.recommendation}")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total findings: {len(self.findings)}")
        print(f"  CRITICAL: {len(by_severity.get('CRITICAL', []))}")
        print(f"  HIGH: {len(by_severity.get('HIGH', []))}")
        print(f"  MEDIUM: {len(by_severity.get('MEDIUM', []))}")
        print(f"  LOW: {len(by_severity.get('LOW', []))}")
        
        # Save to JSON
        output_path = project_root / "output" / "deep_trading_blocker_audit_report.json"
        output_path.parent.mkdir(exist_ok=True)
        
        report_data = {
            "timestamp": str(datetime.now()),
            "total_findings": len(self.findings),
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "component": f.component,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "issue": f.issue,
                    "impact": f.impact,
                    "recommendation": f.recommendation
                }
                for f in self.findings
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    from datetime import datetime
    
    auditor = DeepTradingBlockerAudit()
    findings = auditor.run_full_audit()
    
    # Exit with error code if CRITICAL or HIGH findings
    critical_count = sum(1 for f in findings if f.severity in ["CRITICAL", "HIGH"])
    if critical_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)
