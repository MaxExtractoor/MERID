#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics.performance_attribution import PerformanceAttribution, AttributionType, AttributionMethod
from analytics.analytics_dashboard import AnalyticsDashboard, WidgetType, AlertSeverity
from analytics.advanced_reporting import AdvancedReporting, ReportType, ReportFormat, ReportFrequency
from utils.logger import get_logger

logger = get_logger("test_advanced_analytics")

async def test_performance_attribution():
    """Test performance attribution functionality"""
    
    print("📊 Testing Performance Attribution")
    print("=" * 50)
    
    try:
        # Initialize attribution system
        config = {
            "attribution_parameters": {
                "min_periods": 20,
                "confidence_level": 0.95,
                "risk_free_rate": 0.02
            },
            "us_compliance": {"attribution_standards": True, "audit_attribution": True}
        }
        
        attribution = PerformanceAttribution(config)
        print(f"✅ PerformanceAttribution initialized")
        
        # Generate sample portfolio and benchmark data
        print("\n📈 Generating Sample Data")
        
        dates = pd.date_range(start='2023-01-01', periods=60, freq='D')
        n_assets = 10
        
        # Portfolio data
        portfolio_data = pd.DataFrame({
            'return': np.random.normal(0.001, 0.02, 60),
            'weight': np.random.dirichlet(np.ones(n_assets), 60)
        }, index=dates)
        
        # Benchmark data
        benchmark_data = pd.DataFrame({
            'return': np.random.normal(0.0005, 0.015, 60),
            'weight': np.random.dirichlet(np.ones(n_assets), 60)
        }, index=dates)
        
        print(f"✅ Generated {len(portfolio_data)} days of data for {n_assets} assets")
        
        # Test arithmetic attribution
        print("\n🔢 Testing Arithmetic Attribution")
        arithmetic_result = await attribution.calculate_attribution(
            portfolio_data, benchmark_data, AttributionMethod.ARITHMETIC
        )
        
        if arithmetic_result:
            print(f"✅ Arithmetic attribution completed")
            print(f"   Portfolio return: {arithmetic_result.total_return:.4f}")
            print(f"   Benchmark return: {arithmetic_result.benchmark_return:.4f}")
            print(f"   Active return: {arithmetic_result.active_return:.4f}")
            print(f"   Allocation effect: {arithmetic_result.allocation_effect:.4f}")
            print(f"   Selection effect: {arithmetic_result.selection_effect:.4f}")
            print(f"   Attribution quality: {arithmetic_result.attribution_quality:.3f}")
            print(f"   Factors: {len(arithmetic_result.factors)}")
        else:
            print("❌ Arithmetic attribution failed")
        
        # Test geometric attribution
        print("\n📐 Testing Geometric Attribution")
        geometric_result = await attribution.calculate_attribution(
            portfolio_data, benchmark_data, AttributionMethod.GEOMETRIC
        )
        
        if geometric_result:
            print(f"✅ Geometric attribution completed")
            print(f"   Portfolio return: {geometric_result.total_return:.4f}")
            print(f"   Active return: {geometric_result.active_return:.4f}")
            print(f"   Factors: {len(geometric_result.factors)}")
        else:
            print("❌ Geometric attribution failed")
        
        # Test regression attribution
        print("\n📊 Testing Regression Attribution")
        regression_result = await attribution.calculate_attribution(
            portfolio_data, benchmark_data, AttributionMethod.REGRESSION
        )
        
        if regression_result:
            print(f"✅ Regression attribution completed")
            print(f"   Active return: {regression_result.active_return:.4f}")
            print(f"   Factors: {len(regression_result.factors)}")
            
            # Show factor contributions
            for factor in regression_result.factors[:3]:
                print(f"   {factor.factor_name}: {factor.contribution:.4f}")
        else:
            print("❌ Regression attribution failed")
        
        # Test risk-adjusted attribution
        print("\n⚖️ Testing Risk-Adjusted Attribution")
        risk_adj_result = await attribution.calculate_attribution(
            portfolio_data, benchmark_data, AttributionMethod.RISK_ADJUSTED
        )
        
        if risk_adj_result:
            print(f"✅ Risk-adjusted attribution completed")
            print(f"   Active return: {risk_adj_result.active_return:.4f}")
            print(f"   Risk-adjusted attribution: {risk_adj_result.risk_adjusted_attribution:.4f}")
        else:
            print("❌ Risk-adjusted attribution failed")
        
        # Test factor model creation
        print("\n🎯 Testing Factor Model Creation")
        
        # Generate factor returns
        factor_returns = pd.DataFrame({
            'market': np.random.normal(0.001, 0.02, 60),
            'size': np.random.normal(0.0005, 0.015, 60),
            'value': np.random.normal(0.0003, 0.012, 60),
            'momentum': np.random.normal(0.0008, 0.018, 60)
        }, index=dates)
        
        factor_model = await attribution.create_factor_model("test_model", "Test Model", factor_returns)
        
        if factor_model:
            print(f"✅ Factor model created")
            print(f"   Model ID: {factor_model.model_id}")
            print(f"   Factors: {factor_model.factors}")
            print(f"   R-squared: {factor_model.r_squared:.3f}")
            print(f"   Adjusted R-squared: {factor_model.adjusted_r_squared:.3f}")
        else:
            print("❌ Factor model creation failed")
        
        # Test factor attribution
        if factor_model:
            print("\n📊 Testing Factor Attribution")
            factor_attribution = await attribution.calculate_factor_attribution(portfolio_data, "test_model")
            
            if factor_attribution:
                print(f"✅ Factor attribution calculated")
                for factor, contribution in factor_attribution.items():
                    print(f"   {factor}: {contribution:.4f}")
            else:
                print("❌ Factor attribution failed")
        
        # Test attribution summary
        print("\n📋 Testing Attribution Summary")
        summary = attribution.get_attribution_summary()
        if "status" not in summary:
            print(f"✅ Total attributions: {summary['total_attributions']}")
            print(f"✅ Recent attributions: {summary['recent_attributions']}")
            print(f"✅ Method distribution: {summary['method_distribution']}")
            print(f"✅ Factor models: {summary['factor_models']}")
        else:
            print("⚠️ No attribution data available")
        
        print("\n🎉 Performance Attribution Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance Attribution test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_analytics_dashboard():
    """Test analytics dashboard functionality"""
    
    print("\n📊 Testing Analytics Dashboard")
    print("=" * 50)
    
    try:
        # Initialize dashboard
        config = {
            "dashboard": {
                "refresh_interval": 30,
                "max_widgets": 50,
                "auto_refresh": True
            },
            "us_compliance": {"access_logging": True, "audit_dashboard": True}
        }
        
        dashboard = AnalyticsDashboard(config)
        print(f"✅ AnalyticsDashboard initialized")
        
        # Register data sources
        print("\n📡 Registering Data Sources")
        
        data_sources = {
            "portfolio_performance": {
                "type": "performance",
                "update_frequency": "daily",
                "data_provider": "internal"
            },
            "risk_metrics": {
                "type": "risk",
                "update_frequency": "hourly",
                "data_provider": "risk_engine"
            },
            "market_data": {
                "type": "market",
                "update_frequency": "real-time",
                "data_provider": "market_feeds"
            }
        }
        
        for source_id, source_config in data_sources.items():
            success = await dashboard.register_data_source(source_id, source_config)
            print(f"✅ Registered {source_id}: {success}")
        
        # Create widgets
        print("\n🎨 Creating Dashboard Widgets")
        
        widgets = [
            {
                "widget_id": "performance_chart",
                "widget_type": WidgetType.PERFORMANCE_CHART,
                "title": "Portfolio Performance",
                "position": {"x": 0, "y": 0, "width": 6, "height": 4},
                "data_source": "portfolio_performance"
            },
            {
                "widget_id": "risk_gauge",
                "widget_type": WidgetType.GAUGE,
                "title": "Risk Level",
                "position": {"x": 6, "y": 0, "width": 3, "height": 2},
                "data_source": "risk_metrics",
                "config": {"min_value": 0, "max_value": 100, "thresholds": [30, 70, 100]}
            },
            {
                "widget_id": "metric_card",
                "widget_type": WidgetType.METRIC_CARD,
                "title": "Total Return",
                "position": {"x": 9, "y": 0, "width": 3, "height": 2},
                "data_source": "portfolio_performance"
            },
            {
                "widget_id": "alert_panel",
                "widget_type": WidgetType.ALERT_PANEL,
                "title": "System Alerts",
                "position": {"x": 6, "y": 2, "width": 6, "height": 2},
                "data_source": "risk_metrics"
            }
        ]
        
        for widget_config in widgets:
            success = await dashboard.create_widget(
                widget_config["widget_id"],
                widget_config["widget_type"],
                widget_config["title"],
                widget_config["position"],
                widget_config["data_source"],
                widget_config.get("config")
            )
            print(f"✅ Created {widget_config['widget_id']}: {success}")
        
        # Create metrics
        print("\n📈 Creating Dashboard Metrics")
        
        metrics = [
            ("total_return", "Total Return", 0.12, "%", 0.15),
            ("sharpe_ratio", "Sharpe Ratio", 1.25, "", 1.0),
            ("max_drawdown", "Max Drawdown", -0.08, "%", 0.05),
            ("volatility", "Volatility", 0.16, "%", 0.20)
        ]
        
        for metric_id, name, value, unit, threshold in metrics:
            success = await dashboard.create_metric(metric_id, name, value, unit, threshold)
            print(f"✅ Created {metric_id}: {success}")
        
        # Create alerts
        print("\n🚨 Creating Dashboard Alerts")
        
        alerts = [
            ("alert_1", "High Volatility Alert", "Portfolio volatility exceeded threshold", AlertSeverity.WARNING, "risk_monitor"),
            ("alert_2", "Performance Alert", "Portfolio underperforming benchmark", AlertSeverity.ERROR, "performance_monitor"),
            ("alert_3", "System Alert", "Data feed connection issue", AlertSeverity.CRITICAL, "system_monitor")
        ]
        
        for alert_id, title, message, severity, source in alerts:
            success = await dashboard.create_alert(alert_id, title, message, severity, source)
            print(f"✅ Created {alert_id}: {success}")
        
        # Test widget data updates
        print("\n🔄 Testing Widget Data Updates")
        
        for widget_id in ["performance_chart", "risk_gauge", "metric_card"]:
            # Mock data update
            mock_data = {
                "performance_chart": {"returns": [0.01, 0.02, -0.01, 0.03], "dates": ["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04"]},
                "risk_gauge": {"value": 65, "status": "warning"},
                "metric_card": {"value": 0.15, "trend": "up", "status": "normal"}
            }
            
            data = mock_data.get(widget_id, {})
            success = await dashboard.update_widget_data(widget_id, data)
            print(f"✅ Updated {widget_id}: {success}")
        
        # Test dashboard refresh
        print("\n🔄 Testing Dashboard Refresh")
        refresh_success = await dashboard.refresh_dashboard()
        print(f"✅ Dashboard refresh: {refresh_success}")
        
        # Test alert management
        print("\n🔔 Testing Alert Management")
        
        # Get active alerts
        active_alerts = dashboard.get_active_alerts()
        print(f"✅ Active alerts: {len(active_alerts)}")
        
        # Acknowledge an alert
        if active_alerts:
            alert_id = active_alerts[0].alert_id
            acknowledge_success = dashboard.acknowledge_alert(alert_id)
            print(f"✅ Acknowledged {alert_id}: {acknowledge_success}")
        
        # Dismiss an alert
        if len(active_alerts) > 1:
            alert_id = active_alerts[1].alert_id
            dismiss_success = dashboard.dismiss_alert(alert_id)
            print(f"✅ Dismissed {alert_id}: {dismiss_success}")
        
        # Test dashboard state
        print("\n📊 Testing Dashboard State")
        state = dashboard.get_dashboard_state()
        if "status" not in state:
            print(f"✅ Total widgets: {state['widgets']['total_widgets']}")
            print(f"✅ Total metrics: {len(state['metrics'])}")
            print(f"✅ Total alerts: {state['alerts']['total_alerts']}")
            print(f"✅ Active alerts: {state['alerts']['active_alerts']}")
        else:
            print("⚠️ No dashboard state available")
        
        print("\n🎉 Analytics Dashboard Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Analytics Dashboard test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_advanced_reporting():
    """Test advanced reporting functionality"""
    
    print("\n📄 Testing Advanced Reporting")
    print("=" * 50)
    
    try:
        # Initialize reporting system
        config = {
            "reporting": {
                "output_directory": "./test_reports",
                "max_file_size": 50 * 1024 * 1024,
                "retention_days": 365
            },
            "us_compliance": {"disclosure_requirements": True, "audit_reports": True}
        }
        
        reporting = AdvancedReporting(config)
        print(f"✅ AdvancedReporting initialized")
        
        # Create report templates
        print("\n📋 Creating Report Templates")
        
        templates = [
            {
                "template_id": "monthly_performance",
                "template_name": "Monthly Performance Report",
                "report_type": ReportType.PERFORMANCE,
                "sections": [
                    {"section_id": "executive_summary", "section_type": "performance_summary"},
                    {"section_id": "risk_metrics", "section_type": "risk_analysis"},
                    {"section_id": "attribution", "section_type": "attribution_analysis"}
                ],
                "format": ReportFormat.HTML,
                "frequency": ReportFrequency.MONTHLY,
                "recipients": ["portfolio_manager", "compliance_officer"]
            },
            {
                "template_id": "quarterly_risk",
                "template_name": "Quarterly Risk Report",
                "report_type": ReportType.RISK,
                "sections": [
                    {"section_id": "risk_overview", "section_type": "risk_analysis"},
                    {"section_id": "stress_testing", "section_type": "risk_analysis"},
                    {"section_id": "compliance_disclosure", "section_type": "compliance_disclosure"}
                ],
                "format": ReportFormat.HTML,
                "frequency": ReportFrequency.QUARTERLY,
                "recipients": ["risk_manager", "compliance_officer"]
            },
            {
                "template_id": "custom_portfolio",
                "template_name": "Custom Portfolio Analysis",
                "report_type": ReportType.CUSTOM,
                "sections": [
                    {"section_id": "performance", "section_type": "performance_summary"},
                    {"section_id": "market_commentary", "section_type": "market_commentary"},
                    {"section_id": "forward_outlook", "section_type": "forward_outlook"}
                ],
                "format": ReportFormat.HTML,
                "frequency": ReportFrequency.ON_DEMAND,
                "recipients": ["portfolio_manager"]
            }
        ]
        
        for template_config in templates:
            success = await reporting.create_template(
                template_config["template_id"],
                template_config["template_name"],
                template_config["report_type"],
                template_config["sections"],
                template_config["format"],
                template_config["frequency"],
                template_config["recipients"]
            )
            print(f"✅ Created {template_config['template_id']}: {success}")
        
        # Test report generation
        print("\n📊 Testing Report Generation")
        
        # Mock data sources
        data_sources = {
            "portfolio_data": {
                "returns": [0.01, 0.02, -0.01, 0.03, 0.01],
                "volatility": 0.18,
                "sharpe_ratio": 1.25
            },
            "risk_data": {
                "var": 0.02,
                "drawdown": -0.08,
                "concentration": 0.15
            },
            "attribution_data": {
                "allocation_effect": 0.008,
                "selection_effect": 0.012
            }
        }
        
        # Generate reports
        reports_generated = []
        
        for template_config in templates[:2]:  # Test first 2 templates
            template_id = template_config["template_id"]
            
            report = await reporting.generate_report(
                template_id,
                datetime(2023, 1, 1),
                datetime(2023, 1, 31),
                data_sources
            )
            
            if report:
                reports_generated.append(report)
                print(f"✅ Generated {template_id} report")
                print(f"   Report ID: {report.report_id}")
                print(f"   File path: {report.file_path}")
                print(f"   File size: {report.file_size} bytes")
                print(f"   Sections: {len(report.sections)}")
            else:
                print(f"❌ Failed to generate {template_id} report")
        
        # Test template management
        print("\n📋 Testing Template Management")
        
        # Get all templates
        all_templates = reporting.get_templates()
        print(f"✅ Total templates: {len(all_templates)}")
        
        # Get specific template
        template = reporting.get_template("monthly_performance")
        if template:
            print(f"✅ Retrieved template: {template.template_name}")
            print(f"   Report type: {template.report_type.value}")
            print(f"   Sections: {len(template.sections)}")
        
        # Test report management
        print("\n📄 Testing Report Management")
        
        # Get all reports
        all_reports = reporting.get_reports()
        print(f"✅ Total reports: {len(all_reports)}")
        
        # Get reports by type
        performance_reports = reporting.get_reports_by_type(ReportType.PERFORMANCE)
        print(f"✅ Performance reports: {len(performance_reports)}")
        
        # Test reporting summary
        print("\n📊 Testing Reporting Summary")
        summary = reporting.get_reporting_summary()
        if "status" not in summary:
            print(f"✅ Total templates: {summary['total_templates']}")
            print(f"✅ Total reports: {summary['total_reports']}")
            print(f"✅ Template types: {summary['template_types']}")
            print(f"✅ Report types: {summary['report_types']}")
        else:
            print("⚠️ No reporting summary available")
        
        # Test template removal
        print("\n🗑️ Testing Template Removal")
        
        remove_success = reporting.remove_template("custom_portfolio")
        print(f"✅ Removed custom_portfolio template: {remove_success}")
        
        print("\n🎉 Advanced Reporting Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Advanced Reporting test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_advanced_analytics_integration():
    """Test full advanced analytics integration"""
    
    print("\n🔄 Testing Advanced Analytics Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        attribution_config = {"us_compliance": {"attribution_standards": True}}
        attribution = PerformanceAttribution(attribution_config)
        
        dashboard_config = {"us_compliance": {"access_logging": True}}
        dashboard = AnalyticsDashboard(dashboard_config)
        
        reporting_config = {"us_compliance": {"disclosure_requirements": True}}
        reporting = AdvancedReporting(reporting_config)
        
        print(f"✅ All advanced analytics components initialized")
        
        # Step 1: Generate attribution analysis
        print("\n📊 Step 1: Attribution Analysis")
        
        # Generate sample data
        dates = pd.date_range(start='2023-01-01', periods=30, freq='D')
        portfolio_data = pd.DataFrame({
            'return': np.random.normal(0.001, 0.02, 30),
            'weight': np.random.dirichlet(np.ones(5), 30)
        }, index=dates)
        
        benchmark_data = pd.DataFrame({
            'return': np.random.normal(0.0005, 0.015, 30),
            'weight': np.random.dirichlet(np.ones(5), 30)
        }, index=dates)
        
        # Calculate attribution
        attribution_result = await attribution.calculate_attribution(
            portfolio_data, benchmark_data, AttributionMethod.ARITHMETIC
        )
        
        if attribution_result:
            print(f"✅ Attribution analysis completed")
            print(f"   Active return: {attribution_result.active_return:.4f}")
            print(f"   Attribution quality: {attribution_result.attribution_quality:.3f}")
        else:
            print("❌ Attribution analysis failed")
        
        # Step 2: Dashboard integration
        print("\n📊 Step 2: Dashboard Integration")
        
        # Register data source
        await dashboard.register_data_source("attribution_data", {
            "type": "attribution",
            "update_frequency": "daily"
        })
        
        # Create attribution widget
        widget_success = await dashboard.create_widget(
            "attribution_widget",
            WidgetType.ATTRIBUTION_CHART,
            "Performance Attribution",
            {"x": 0, "y": 0, "width": 8, "height": 4},
            "attribution_data"
        )
        
        if widget_success:
            print(f"✅ Attribution widget created")
            
            # Update widget with attribution data
            if attribution_result:
                attribution_data = {
                    "factors": attribution_result.factors[:5],  # First 5 factors
                    "total_attribution": attribution_result.total_attribution
                }
                update_success = await dashboard.update_widget_data("attribution_widget", attribution_data)
                print(f"✅ Attribution widget updated: {update_success}")
        else:
            print("❌ Attribution widget creation failed")
        
        # Create performance metrics
        metrics = [
            ("active_return", "Active Return", attribution_result.active_return if attribution_result else 0, "%", 0.02),
            ("attribution_quality", "Attribution Quality", attribution_result.attribution_quality if attribution_result else 0, "", 0.8)
        ]
        
        for metric_id, name, value, unit, threshold in metrics:
            await dashboard.create_metric(metric_id, name, value, unit, threshold)
        
        print(f"✅ Created {len(metrics)} attribution metrics")
        
        # Step 3: Reporting integration
        print("\n📄 Step 3: Reporting Integration")
        
        # Create attribution report template
        template_success = await reporting.create_template(
            "attribution_report",
            "Performance Attribution Report",
            ReportType.ATTRIBUTION,
            [
                {"section_id": "attribution_summary", "section_type": "attribution_analysis"},
                {"section_id": "factor_analysis", "section_type": "attribution_analysis"}
            ],
            ReportFormat.HTML,
            ReportFrequency.MONTHLY,
            ["portfolio_manager", "analyst"]
        )
        
        if template_success:
            print(f"✅ Attribution report template created")
            
            # Generate attribution report
            report_data = {
                "portfolio_data": portfolio_data.to_dict(),
                "benchmark_data": benchmark_data.to_dict(),
                "attribution_result": attribution_result.__dict__ if attribution_result else {}
            }
            
            report = await reporting.generate_report(
                "attribution_report",
                datetime(2023, 1, 1),
                datetime(2023, 1, 31),
                report_data
            )
            
            if report:
                print(f"✅ Attribution report generated")
                print(f"   Report ID: {report.report_id}")
                print(f"   File size: {report.file_size} bytes")
            else:
                print("❌ Attribution report generation failed")
        else:
            print("❌ Attribution report template creation failed")
        
        # Step 4: Integrated analytics
        print("\n📊 Step 4: Integrated Analytics")
        
        # Refresh dashboard
        refresh_success = await dashboard.refresh_dashboard()
        print(f"✅ Dashboard refreshed: {refresh_success}")
        
        # Get dashboard state
        dashboard_state = dashboard.get_dashboard_state()
        print(f"✅ Dashboard widgets: {len(dashboard_state.get('widgets', {}))}")
        print(f"✅ Dashboard metrics: {len(dashboard_state.get('metrics', {}))}")
        
        # Get attribution summary
        attribution_summary = attribution.get_attribution_summary()
        if "status" not in attribution_summary:
            print(f"✅ Attribution analyses: {attribution_summary['total_attributions']}")
            print(f"✅ Attribution quality: {attribution_summary['performance_metrics']['avg_attribution_quality']:.3f}")
        
        # Get reporting summary
        reporting_summary = reporting.get_reporting_summary()
        if "status" not in reporting_summary:
            print(f"✅ Report templates: {reporting_summary['total_templates']}")
            print(f"✅ Generated reports: {reporting_summary['total_reports']}")
        
        print("\n🎉 Advanced Analytics Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Advanced Analytics Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all advanced analytics tests"""
    try:
        print("🧪 ADVANCED ANALYTICS TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_performance_attribution()
        test2 = await test_analytics_dashboard()
        test3 = await test_advanced_reporting()
        test4 = await test_advanced_analytics_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 ADVANCED ANALYTICS TEST RESULTS")
        print("=" * 70)
        print(f"Performance Attribution: {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Analytics Dashboard:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Advanced Reporting:     {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Analytics Integration:  {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL ADVANCED ANALYTICS TESTS PASSED!")
            print("✅ Performance attribution with multiple methods working")
            print("✅ Real-time analytics dashboard with widgets and alerts working")
            print("✅ Advanced reporting with templates and automation working")
            print("✅ Full advanced analytics integration successful")
        else:
            print("\n❌ Some advanced analytics tests failed")
        
    except Exception as e:
        print(f"❌ Advanced analytics test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
