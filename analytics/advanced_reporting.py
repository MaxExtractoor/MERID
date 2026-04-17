"""
Advanced Reporting for MERID Advanced Analytics

Provides comprehensive reporting capabilities with
customizable templates and US-compliant configuration.

Features:
- Performance reporting
- Risk reporting
- Compliance reporting
- Custom report templates
- Automated report generation
- US-compliant disclosures
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum
import json

from utils.logger import get_logger

logger = get_logger("analytics.advanced_reporting")

class ReportType(Enum):
    """Report type enumeration."""
    PERFORMANCE = "performance"
    RISK = "risk"
    COMPLIANCE = "compliance"
    ATTRIBUTION = "attribution"
    PORTFOLIO = "portfolio"
    STRATEGY = "strategy"
    CUSTOM = "custom"

class ReportFormat(Enum):
    """Report format enumeration."""
    PDF = "pdf"
    HTML = "html"
    EXCEL = "excel"
    JSON = "json"
    CSV = "csv"

class ReportFrequency(Enum):
    """Report frequency enumeration."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"
    ON_DEMAND = "on_demand"

@dataclass
class ReportTemplate:
    """Report template definition."""
    template_id: str
    template_name: str
    report_type: ReportType
    sections: List[Dict[str, Any]]
    format: ReportFormat
    frequency: ReportFrequency
    recipients: List[str]
    auto_generate: bool
    config: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ReportSection:
    """Report section definition."""
    section_id: str
    section_name: str
    section_type: str
    data_source: str
    config: Dict[str, Any]
    content: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GeneratedReport:
    """Generated report definition."""
    report_id: str
    template_id: str
    report_type: ReportType
    title: str
    period_start: datetime
    period_end: datetime
    format: ReportFormat
    sections: List[ReportSection]
    content: Union[str, bytes, Dict[str, Any]]
    file_path: Optional[str]
    generated_at: datetime
    file_size: int
    metadata: Dict[str, Any] = field(default_factory=dict)

class AdvancedReporting:
    """
    Comprehensive advanced reporting system for MERID.
    
    Provides customizable reporting with multiple formats
    and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Report templates
        self.templates: Dict[str, ReportTemplate] = {}
        
        # Generated reports
        self.reports: deque = deque(maxlen=1000)
        
        # Report sections
        self.section_types = {
            "performance_summary": {
                "description": "Portfolio performance summary",
                "required_data": ["returns", "volatility", "sharpe_ratio"]
            },
            "risk_analysis": {
                "description": "Risk analysis and metrics",
                "required_data": ["var", "drawdown", "exposure"]
            },
            "attribution_analysis": {
                "description": "Performance attribution analysis",
                "required_data": ["attribution_factors", "allocation_effect"]
            },
            "compliance_disclosure": {
                "description": "Regulatory compliance disclosures",
                "required_data": ["holdings", "risk_metrics", "compliance_checks"]
            },
            "market_commentary": {
                "description": "Market commentary and analysis",
                "required_data": ["market_data", "economic_indicators"]
            },
            "forward_outlook": {
                "description": "Forward-looking outlook and projections",
                "required_data": ["projections", "scenarios", "assumptions"]
            }
        }
        
        # Report configuration
        self.report_config = config.get("reporting", {
            "output_directory": "./reports",
            "max_file_size": 50 * 1024 * 1024,  # 50MB
            "retention_days": 365,
            "compression": True,
            "encryption": True
        })
        
        # Default templates
        self.default_templates = {
            "monthly_performance": {
                "template_name": "Monthly Performance Report",
                "report_type": ReportType.PERFORMANCE,
                "sections": [
                    {"section_id": "executive_summary", "section_type": "performance_summary"},
                    {"section_id": "risk_metrics", "section_type": "risk_analysis"},
                    {"section_id": "attribution", "section_type": "attribution_analysis"}
                ],
                "format": ReportFormat.PDF,
                "frequency": ReportFrequency.MONTHLY,
                "recipients": ["portfolio_manager", "compliance_officer"],
                "auto_generate": True
            },
            "quarterly_risk": {
                "template_name": "Quarterly Risk Report",
                "report_type": ReportType.RISK,
                "sections": [
                    {"section_id": "risk_overview", "section_type": "risk_analysis"},
                    {"section_id": "stress_testing", "section_type": "risk_analysis"},
                    {"section_id": "compliance_disclosure", "section_type": "compliance_disclosure"}
                ],
                "format": ReportFormat.PDF,
                "frequency": ReportFrequency.QUARTERLY,
                "recipients": ["risk_manager", "compliance_officer"],
                "auto_generate": True
            },
            "annual_compliance": {
                "template_name": "Annual Compliance Report",
                "report_type": ReportType.COMPLIANCE,
                "sections": [
                    {"section_id": "compliance_overview", "section_type": "compliance_disclosure"},
                    {"section_id": "holdings_disclosure", "section_type": "compliance_disclosure"},
                    {"section_id": "risk_disclosure", "section_type": "compliance_disclosure"}
                ],
                "format": ReportFormat.PDF,
                "frequency": ReportFrequency.ANNUALLY,
                "recipients": ["compliance_officer", "regulatory_affairs"],
                "auto_generate": True
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "disclosure_requirements": True,
            "performance_standards": True,
            "risk_disclosure": True,
            "audit_reports": True
        })
        
        # Background generation task
        self.generation_task: Optional[asyncio.Task] = None
        
        logger.info("AdvancedReporting initialized")
    
    async def create_template(self, template_id: str, template_name: str, 
                            report_type: ReportType, sections: List[Dict[str, Any]],
                            format: ReportFormat, frequency: ReportFrequency,
                            recipients: List[str], auto_generate: bool = True,
                            config: Optional[Dict[str, Any]] = None) -> bool:
        """Create a report template."""
        try:
            # Validate template configuration
            if not self._validate_template_config(report_type, sections, recipients):
                logger.error(f"Invalid template configuration: {template_id}")
                return False
            
            # Create template
            template = ReportTemplate(
                template_id=template_id,
                template_name=template_name,
                report_type=report_type,
                sections=sections,
                format=format,
                frequency=frequency,
                recipients=recipients,
                auto_generate=auto_generate,
                config=config or {}
            )
            
            # Store template
            self.templates[template_id] = template
            
            # Record for compliance
            if self.us_compliance.get("audit_reports", True):
                await self._record_template_creation(template)
            
            logger.info(f"Report template created: {template_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create template {template_id}: {e}")
            return False
    
    def _validate_template_config(self, report_type: ReportType, 
                                sections: List[Dict[str, Any]], 
                                recipients: List[str]) -> bool:
        """Validate template configuration."""
        try:
            # Check sections
            if not sections:
                return False
            
            # Validate each section
            for section in sections:
                if "section_id" not in section or "section_type" not in section:
                    return False
                
                section_type = section["section_type"]
                if section_type not in self.section_types:
                    return False
            
            # Check recipients
            if not recipients:
                return False
            
            # US compliance checks
            if self.us_compliance.get("disclosure_requirements", True):
                if report_type == ReportType.COMPLIANCE:
                    required_sections = ["compliance_disclosure"]
                    has_required = any(s["section_type"] in required_sections for s in sections)
                    if not has_required:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Template configuration validation error: {e}")
            return False
    
    async def generate_report(self, template_id: str, period_start: datetime, 
                           period_end: datetime, data_sources: Dict[str, Any],
                           custom_params: Optional[Dict[str, Any]] = None) -> Optional[GeneratedReport]:
        """Generate a report from template."""
        try:
            start_time = time.time()
            
            # Get template
            if template_id not in self.templates:
                logger.error(f"Template {template_id} not found")
                return None
            
            template = self.templates[template_id]
            
            # Generate report sections
            sections = []
            for section_config in template.sections:
                section = await self._generate_section(section_config, data_sources, custom_params)
                if section:
                    sections.append(section)
            
            # Generate report content
            content = await self._generate_report_content(template, sections, custom_params)
            
            # Create report
            report = GeneratedReport(
                report_id=f"report_{int(time.time())}",
                template_id=template_id,
                report_type=template.report_type,
                title=f"{template.template_name} - {period_start.strftime('%Y-%m-%d')}",
                period_start=period_start,
                period_end=period_end,
                format=template.format,
                sections=sections,
                content=content,
                file_path=None,  # Will be set when saved
                generated_at=datetime.now(),
                file_size=0,  # Will be set when saved
                metadata={
                    "generation_time": time.time() - start_time,
                    "template_name": template.template_name,
                    "section_count": len(sections)
                }
            )
            
            # Save report
            if await self._save_report(report):
                # Store report
                self.reports.append(report)
                
                # Record for compliance
                if self.us_compliance.get("audit_reports", True):
                    await self._record_report_generation(report)
                
                logger.info(f"Report generated: {report.report_id}")
                return report
            else:
                logger.error(f"Failed to save report: {report.report_id}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return None
    
    async def _generate_section(self, section_config: Dict[str, Any], 
                             data_sources: Dict[str, Any], 
                             custom_params: Optional[Dict[str, Any]]) -> Optional[ReportSection]:
        """Generate a report section."""
        try:
            section_id = section_config["section_id"]
            section_type = section_config["section_type"]
            data_source = section_config.get("data_source", "default")
            
            # Get section data
            section_data = await self._get_section_data(section_type, data_sources, custom_params)
            
            # Generate section content
            content = await self._generate_section_content(section_type, section_data, section_config)
            
            section = ReportSection(
                section_id=section_id,
                section_name=section_config.get("section_name", section_id.title()),
                section_type=section_type,
                data_source=data_source,
                config=section_config,
                content=content
            )
            
            return section
            
        except Exception as e:
            logger.error(f"Failed to generate section {section_config.get('section_id', 'unknown')}: {e}")
            return None
    
    async def _get_section_data(self, section_type: str, data_sources: Dict[str, Any], 
                             custom_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Get data for a section type."""
        try:
            # Mock data generation based on section type
            if section_type == "performance_summary":
                return await self._get_performance_data(data_sources)
            elif section_type == "risk_analysis":
                return await self._get_risk_data(data_sources)
            elif section_type == "attribution_analysis":
                return await self._get_attribution_data(data_sources)
            elif section_type == "compliance_disclosure":
                return await self._get_compliance_data(data_sources)
            elif section_type == "market_commentary":
                return await self._get_market_data(data_sources)
            elif section_type == "forward_outlook":
                return await self._get_outlook_data(data_sources)
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to get section data for {section_type}: {e}")
            return {}
    
    async def _get_performance_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get performance data."""
        try:
            # Mock performance data
            return {
                "total_return": 0.12,
                "annualized_return": 0.15,
                "volatility": 0.18,
                "sharpe_ratio": 0.83,
                "max_drawdown": -0.08,
                "var_95": -0.02,
                "benchmark_return": 0.10,
                "alpha": 0.02,
                "beta": 1.1,
                "tracking_error": 0.03,
                "information_ratio": 0.67
            }
            
        except Exception as e:
            logger.error(f"Performance data error: {e}")
            return {}
    
    async def _get_risk_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get risk data."""
        try:
            # Mock risk data
            return {
                "portfolio_var": 0.02,
                "expected_shortfall": -0.025,
                "concentration_risk": 0.15,
                "sector_exposure": {
                    "technology": 0.35,
                    "healthcare": 0.20,
                    "financial": 0.15,
                    "consumer": 0.15,
                    "industrial": 0.15
                },
                "geographic_exposure": {
                    "us": 0.60,
                    "europe": 0.25,
                    "asia": 0.15
                },
                "stress_test_results": {
                    "market_crash": -0.15,
                    "interest_rate_shock": -0.08,
                    "liquidity_crisis": -0.12
                }
            }
            
        except Exception as e:
            logger.error(f"Risk data error: {e}")
            return {}
    
    async def _get_attribution_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get attribution data."""
        try:
            # Mock attribution data
            return {
                "allocation_effect": 0.008,
                "selection_effect": 0.012,
                "interaction_effect": 0.002,
                "sector_attribution": {
                    "technology": 0.015,
                    "healthcare": 0.005,
                    "financial": -0.002
                },
                "factor_attribution": {
                    "market": 0.010,
                    "size": 0.003,
                    "value": 0.002,
                    "momentum": 0.005
                }
            }
            
        except Exception as e:
            logger.error(f"Attribution data error: {e}")
            return {}
    
    async def _get_compliance_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get compliance data."""
        try:
            # Mock compliance data
            return {
                "regulatory_compliance": True,
                "concentration_limits": {
                    "single_security_limit": 0.05,
                    "single_sector_limit": 0.25,
                    "current_max_concentration": 0.18
                },
                "leverage_limits": {
                    "max_leverage": 2.0,
                    "current_leverage": 1.3
                },
                "liquidity_requirements": {
                    "min_liquidity_ratio": 0.1,
                    "current_liquidity_ratio": 0.15
                },
                "disclosure_requirements": {
                    "holdings_disclosed": True,
                    "performance_disclosed": True,
                    "risk_disclosed": True
                }
            }
            
        except Exception as e:
            logger.error(f"Compliance data error: {e}")
            return {}
    
    async def _get_market_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get market data."""
        try:
            # Mock market data
            return {
                "market_overview": {
                    "snp_500_return": 0.08,
                    "volatility_index": 18.5,
                    "interest_rates": 0.045,
                    "inflation_rate": 0.032
                },
                "economic_indicators": {
                    "gdp_growth": 0.025,
                    "unemployment_rate": 0.038,
                    "consumer_confidence": 110.5,
                    "manufacturing_pmi": 52.3
                },
                "market_commentary": "Markets showed resilience despite geopolitical tensions..."
            }
            
        except Exception as e:
            logger.error(f"Market data error: {e}")
            return {}
    
    async def _get_outlook_data(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Get outlook data."""
        try:
            # Mock outlook data
            return {
                "forward_projections": {
                    "expected_return_1y": 0.08,
                    "expected_volatility_1y": 0.16,
                    "probability_of_positive_return": 0.65
                },
                "scenario_analysis": {
                    "base_case": 0.08,
                    "bull_case": 0.15,
                    "bear_case": -0.05
                },
                "key_assumptions": [
                    "Moderate economic growth",
                    "Stable interest rates",
                    "Normal market volatility"
                ],
                "risk_factors": [
                    "Geopolitical tensions",
                    "Inflation concerns",
                    "Supply chain disruptions"
                ]
            }
            
        except Exception as e:
            logger.error(f"Outlook data error: {e}")
            return {}
    
    async def _generate_section_content(self, section_type: str, section_data: Dict[str, Any], 
                                      section_config: Dict[str, Any]) -> str:
        """Generate content for a section."""
        try:
            # Generate HTML content
            content = f"<h2>{section_config.get('section_name', section_type.title())}</h2>\n"
            
            if section_type == "performance_summary":
                content += self._generate_performance_content(section_data)
            elif section_type == "risk_analysis":
                content += self._generate_risk_content(section_data)
            elif section_type == "attribution_analysis":
                content += self._generate_attribution_content(section_data)
            elif section_type == "compliance_disclosure":
                content += self._generate_compliance_content(section_data)
            elif section_type == "market_commentary":
                content += self._generate_market_content(section_data)
            elif section_type == "forward_outlook":
                content += self._generate_outlook_content(section_data)
            
            return content
            
        except Exception as e:
            logger.error(f"Failed to generate section content for {section_type}: {e}")
            return f"<p>Error generating {section_type} content</p>"
    
    def _generate_performance_content(self, data: Dict[str, Any]) -> str:
        """Generate performance section content."""
        try:
            content = "<div class='performance-metrics'>\n"
            
            # Key metrics table
            content += "<table class='metrics-table'>\n"
            content += "<tr><th>Metric</th><th>Value</th><th>Benchmark</th></tr>\n"
            
            metrics = [
                ("Total Return", f"{data.get('total_return', 0):.2%}", f"{data.get('benchmark_return', 0):.2%}"),
                ("Annualized Return", f"{data.get('annualized_return', 0):.2%}", ""),
                ("Volatility", f"{data.get('volatility', 0):.2%}", ""),
                ("Sharpe Ratio", f"{data.get('sharpe_ratio', 0):.2f}", ""),
                ("Max Drawdown", f"{data.get('max_drawdown', 0):.2%}", ""),
                ("Alpha", f"{data.get('alpha', 0):.2%}", ""),
                ("Beta", f"{data.get('beta', 0):.2f}", "")
            ]
            
            for metric, value, benchmark in metrics:
                benchmark_cell = f"<td>{benchmark}</td>" if benchmark else "<td>-</td>"
                content += f"<tr><td>{metric}</td><td>{value}</td>{benchmark_cell}</tr>\n"
            
            content += "</table>\n"
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Performance content generation error: {e}")
            return "<p>Error generating performance content</p>"
    
    def _generate_risk_content(self, data: Dict[str, Any]) -> str:
        """Generate risk section content."""
        try:
            content = "<div class='risk-analysis'>\n"
            
            # Risk metrics
            content += "<h3>Risk Metrics</h3>\n"
            content += "<table class='risk-table'>\n"
            content += "<tr><th>Metric</th><th>Value</th></tr>\n"
            
            risk_metrics = [
                ("Portfolio VaR (95%)", f"{data.get('portfolio_var', 0):.2%}"),
                ("Expected Shortfall", f"{data.get('expected_shortfall', 0):.2%}"),
                ("Concentration Risk", f"{data.get('concentration_risk', 0):.2%}")
            ]
            
            for metric, value in risk_metrics:
                content += f"<tr><td>{metric}</td><td>{value}</td></tr>\n"
            
            content += "</table>\n"
            
            # Sector exposure
            if "sector_exposure" in data:
                content += "<h3>Sector Exposure</h3>\n"
                content += "<ul>\n"
                for sector, exposure in data["sector_exposure"].items():
                    content += f"<li>{sector}: {exposure:.1%}</li>\n"
                content += "</ul>\n"
            
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Risk content generation error: {e}")
            return "<p>Error generating risk content</p>"
    
    def _generate_attribution_content(self, data: Dict[str, Any]) -> str:
        """Generate attribution section content."""
        try:
            content = "<div class='attribution-analysis'>\n"
            
            # Attribution effects
            content += "<h3>Attribution Effects</h3>\n"
            content += "<table class='attribution-table'>\n"
            content += "<tr><th>Effect</th><th>Contribution</th></tr>\n"
            
            effects = [
                ("Allocation Effect", f"{data.get('allocation_effect', 0):.2%}"),
                ("Selection Effect", f"{data.get('selection_effect', 0):.2%}"),
                ("Interaction Effect", f"{data.get('interaction_effect', 0):.2%}")
            ]
            
            for effect, contribution in effects:
                content += f"<tr><td>{effect}</td><td>{contribution}</td></tr>\n"
            
            content += "</table>\n"
            
            # Factor attribution
            if "factor_attribution" in data:
                content += "<h3>Factor Attribution</h3>\n"
                content += "<ul>\n"
                for factor, attribution in data["factor_attribution"].items():
                    content += f"<li>{factor}: {attribution:.2%}</li>\n"
                content += "</ul>\n"
            
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Attribution content generation error: {e}")
            return "<p>Error generating attribution content</p>"
    
    def _generate_compliance_content(self, data: Dict[str, Any]) -> str:
        """Generate compliance section content."""
        try:
            content = "<div class='compliance-disclosure'>\n"
            
            # Compliance status
            content += "<h3>Regulatory Compliance</h3>\n"
            compliance_status = data.get("regulatory_compliance", False)
            content += f"<p>Compliance Status: <strong>{'Compliant' if compliance_status else 'Non-Compliant'}</strong></p>\n"
            
            # Limits
            if "concentration_limits" in data:
                content += "<h3>Concentration Limits</h3>\n"
                limits = data["concentration_limits"]
                content += "<ul>\n"
                content += f"<li>Single Security Limit: {limits.get('single_security_limit', 0):.1%}</li>\n"
                content += f"<li>Current Max Concentration: {limits.get('current_max_concentration', 0):.1%}</li>\n"
                content += "</ul>\n"
            
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Compliance content generation error: {e}")
            return "<p>Error generating compliance content</p>"
    
    def _generate_market_content(self, data: Dict[str, Any]) -> str:
        """Generate market commentary content."""
        try:
            content = "<div class='market-commentary'>\n"
            
            # Market overview
            if "market_overview" in data:
                content += "<h3>Market Overview</h3>\n"
                overview = data["market_overview"]
                content += "<ul>\n"
                content += f"<li>S&P 500 Return: {overview.get('snp_500_return', 0):.1%}</li>\n"
                content += f"<li>VIX Index: {overview.get('volatility_index', 0):.1f}</li>\n"
                content += f"<li>Interest Rates: {overview.get('interest_rates', 0):.1%}</li>\n"
                content += "</ul>\n"
            
            # Commentary
            if "market_commentary" in data:
                content += f"<h3>Market Commentary</h3>\n"
                content += f"<p>{data['market_commentary']}</p>\n"
            
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Market content generation error: {e}")
            return "<p>Error generating market content</p>"
    
    def _generate_outlook_content(self, data: Dict[str, Any]) -> str:
        """Generate outlook content."""
        try:
            content = "<div class='forward-outlook'>\n"
            
            # Forward projections
            if "forward_projections" in data:
                content += "<h3>Forward Projections</h3>\n"
                projections = data["forward_projections"]
                content += "<ul>\n"
                content += f"<li>Expected Return (1Y): {projections.get('expected_return_1y', 0):.1%}</li>\n"
                content += f"<li>Expected Volatility (1Y): {projections.get('expected_volatility_1y', 0):.1%}</li>\n"
                content += f"<li>Probability of Positive Return: {projections.get('probability_of_positive_return', 0):.1%}</li>\n"
                content += "</ul>\n"
            
            # Key assumptions
            if "key_assumptions" in data:
                content += "<h3>Key Assumptions</h3>\n"
                content += "<ul>\n"
                for assumption in data["key_assumptions"]:
                    content += f"<li>{assumption}</li>\n"
                content += "</ul>\n"
            
            content += "</div>\n"
            
            return content
            
        except Exception as e:
            logger.error(f"Outlook content generation error: {e}")
            return "<p>Error generating outlook content</p>"
    
    async def _generate_report_content(self, template: ReportTemplate, 
                                     sections: List[ReportSection], 
                                     custom_params: Optional[Dict[str, Any]]) -> str:
        """Generate complete report content."""
        try:
            # Generate HTML report
            content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{template.template_name}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .header {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
                    .metrics-table, .risk-table, .attribution-table {{ 
                        border-collapse: collapse; width: 100%; margin: 10px 0; 
                    }}
                    .metrics-table th, .metrics-table td, 
                    .risk-table th, .risk-table td,
                    .attribution-table th, .attribution-table td {{ 
                        border: 1px solid #ddd; padding: 8px; text-align: left; 
                    }}
                    .metrics-table th, .risk-table th, .attribution-table th {{ 
                        background-color: #f2f2f2; 
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>{template.template_name}</h1>
                    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            """
            
            # Add sections
            for section in sections:
                content += section.content
            
            content += """
            </body>
            </html>
            """
            
            return content
            
        except Exception as e:
            logger.error(f"Report content generation error: {e}")
            return "<html><body><p>Error generating report content</p></body></html>"
    
    async def _save_report(self, report: GeneratedReport) -> bool:
        """Save report to file."""
        try:
            # Generate file path
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{report.report_id}_{timestamp}.html"
            file_path = f"{self.report_config['output_directory']}/{filename}"
            
            # Save content
            if isinstance(report.content, str):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(report.content)
                
                # Update report
                report.file_path = file_path
                report.file_size = len(report.content.encode('utf-8'))
                
                logger.info(f"Report saved: {file_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
            return False
    
    async def _record_template_creation(self, template: ReportTemplate):
        """Record template creation for compliance."""
        if not self.us_compliance.get("audit_reports", True):
            return
        
        audit_entry = {
            "action": "template_creation",
            "template_id": template.template_id,
            "template_name": template.template_name,
            "report_type": template.report_type.value,
            "frequency": template.frequency.value,
            "recipients": template.recipients,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Template creation audit entry: {audit_entry}")
    
    async def _record_report_generation(self, report: GeneratedReport):
        """Record report generation for compliance."""
        if not self.us_compliance.get("audit_reports", True):
            return
        
        audit_entry = {
            "action": "report_generation",
            "report_id": report.report_id,
            "template_id": report.template_id,
            "report_type": report.report_type.value,
            "format": report.format.value,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "file_path": report.file_path,
            "file_size": report.file_size,
            "timestamp": report.generated_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Report generation audit entry: {audit_entry}")
    
    def get_template(self, template_id: str) -> Optional[ReportTemplate]:
        """Get a report template."""
        return self.templates.get(template_id)
    
    def get_templates(self) -> Dict[str, ReportTemplate]:
        """Get all report templates."""
        return self.templates.copy()
    
    def get_report(self, report_id: str) -> Optional[GeneratedReport]:
        """Get a generated report."""
        for report in self.reports:
            if report.report_id == report_id:
                return report
        return None
    
    def get_reports(self, limit: int = 100) -> List[GeneratedReport]:
        """Get generated reports."""
        return list(self.reports)[-limit:]
    
    def get_reports_by_type(self, report_type: ReportType, limit: int = 50) -> List[GeneratedReport]:
        """Get reports by type."""
        reports = [r for r in self.reports if r.report_type == report_type]
        return reports[-limit:]
    
    def remove_template(self, template_id: str) -> bool:
        """Remove a report template."""
        try:
            if template_id in self.templates:
                del self.templates[template_id]
                logger.info(f"Template removed: {template_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove template {template_id}: {e}")
            return False
    
    def remove_report(self, report_id: str) -> bool:
        """Remove a generated report."""
        try:
            for i, report in enumerate(self.reports):
                if report.report_id == report_id:
                    del self.reports[i]
                    logger.info(f"Report removed: {report_id}")
                    return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove report {report_id}: {e}")
            return False
    
    def get_reporting_summary(self) -> Dict[str, Any]:
        """Get comprehensive reporting summary."""
        try:
            # Template distribution
            template_types = {}
            for template in self.templates.values():
                template_type = template.report_type.value
                template_types[template_type] = template_types.get(template_type, 0) + 1
            
            # Report distribution
            report_types = {}
            for report in self.reports:
                report_type = report.report_type.value
                report_types[report_type] = report_types.get(report_type, 0) + 1
            
            return {
                "total_templates": len(self.templates),
                "template_types": template_types,
                "total_reports": len(self.reports),
                "report_types": report_types,
                "auto_generate_templates": sum(1 for t in self.templates.values() if t.auto_generate),
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get reporting summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update reporting configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "reporting" in new_config:
            self.report_config.update(new_config["reporting"])
        
        logger.info("Advanced reporting configuration updated")
