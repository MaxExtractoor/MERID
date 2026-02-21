#!/usr/bin/env python3
"""Phase 7 Production Scaling Playbook - Combined Strategy + Execution Lane in Limited Production."""

import json
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("swarm.phase7_playbook")

def generate_phase7_playbook():
    """Generate Phase 7 Production Scaling playbook."""
    
    playbook = {
        "phase": "Phase 7",
        "domain": "production_scaling_combined",
        "batch_id": "phase7_production_combined",
        "target_date": "2026-01-25",
        "risk_level": "high",
        "description": "Deploy combined strategy + execution lane to limited production with strict capital and risk constraints",
        
        "entry_criteria": {
            "phase6_status": "promoted_governed_lane",
            "phase6_gates": "all_passed_with_margins",
            "recent_slo_window": {
                "duration_days": 7,
                "latency_slo": "green",
                "error_rate_slo": "green", 
                "drawdown_slo": "green",
                "incident_rate": "zero"
            },
            "incident_backlog": "zero_open_incidents",
            "production_readiness": {
                "infrastructure_health": "green",
                "monitoring_coverage": "complete",
                "alerting_configured": "true",
                "rollback_procedures": "tested"
            },
            "human_signoff": {
                "risk_committee": "approved_limited_scope",
                "engineering_lead": "production_ready",
                "operations_lead": "monitoring_ready"
            },
            "capital_approval": {
                "max_notional_approved": "0.5% of total_capital",
                "venue_approvals": "limited_venue_list",
                "time_window_approved": "pilot_period_2_weeks"
            }
        },

        "scope_constraints": {
            "capital_limits": {
                "max_notional_per_lane": "$50,000",
                "max_notional_per_strategy": "$25,000",
                "max_daily_exposure": "$100,000",
                "max_concurrent_positions": 5
            },
            "venue_constraints": {
                "allowed_venues": [
                    "binance_spot",
                    "coinbase_pro",
                    "kraken_spot"
                ],
                "excluded_venues": [
                    "derivatives",
                    "decentralized",
                    "high_volatility_altcoins"
                ],
                "product_restrictions": [
                    "major_pairs_only",
                    "no_leverage",
                    "no_shorting"
                ]
            },
            "time_constraints": {
                "trading_hours": "09:00-17:00 UTC",
                "excluded_periods": [
                    "major_news_events",
                    "weekend_high_volatility",
                    "maintenance_windows"
                ],
                "pilot_duration": "14_days",
                "review_checkpoints": "daily"
            },
            "regime_constraints": {
                "market_volatility": "vix_below_30",
                "liquidity_requirements": "min_10mm_daily_volume",
                "correlation_limits": "max_0.7_pair_correlation"
            }
        },

        "production_specific_gates": {
            "volume_gate": {
                "target_hours": 16.0,
                "min_effective": 15.0,
                "epsilon": 1e-6,
                "description": "Production hours saved with real capital impact"
            },
            "roi_gate": {
                "target_score": 98.0,
                "min_acceptable": 97.0,
                "description": "Higher ROI threshold for production environment"
            },
            "pnl_gate": {
                "max_daily_loss": "$500",
                "max_drawdown_percent": 0.02,
                "required_profit_ratio": 0.6,
                "description": "Real P&L constraints with loss limits"
            },
            "production_slo_gate": {
                "decision_latency_ms": 100,
                "execution_latency_ms": 200,
                "error_rate_percent": 0.1,
                "slippage_bps": 5,
                "description": "Stricter production SLOs"
            },
            "risk_gate": {
                "max_position_concentration": 0.4,
                "max_venue_exposure": 0.6,
                "var_limit_percent": 0.01,
                "description": "Production risk management limits"
            },
            "incident_gate": {
                "max_incidents": 0,
                "max_near_misses": 1,
                "auto_halt_triggers": [
                    "pnl_loss_exceeds_$500",
                    "latency_exceeds_500ms",
                    "error_rate_exceeds_1%",
                    "venue_api_failure"
                ],
                "description": "Zero-tolerance incident policy for production"
            }
        },

        "task_backlog": {
            "strategy_code": [
                {
                    "task_id": "phase7_prod_strategy_deployment",
                    "title": "Production strategy deployment with capital constraints",
                    "description": "Deploy validated strategies to production with strict notional and venue limits",
                    "module": "swarm/strategy",
                    "risk_level": "high",
                    "baseline_hours": 4.0,
                    "dependencies": [
                        "phase6_joint_lane_promotion"
                    ],
                    "explicit_rollback": "disable_production_strategies_revert_config",
                    "production_constraints": [
                        "max_notional_$25k_per_strategy",
                        "major_pairs_only",
                        "no_leverage_products"
                    ]
                },
                {
                    "task_id": "phase7_prod_risk_monitoring",
                    "title": "Production risk monitoring and kill-switch setup",
                    "description": "Implement real-time risk monitoring with automated kill-switches",
                    "module": "swarm/risk",
                    "risk_level": "high",
                    "baseline_hours": 3.5,
                    "dependencies": [
                        "phase7_prod_strategy_deployment"
                    ],
                    "explicit_rollback": "disable_risk_monitors_revert_manual",
                    "production_constraints": [
                        "real_time_pnl_tracking",
                        "position_concentration_limits",
                        "drawdown_monitoring"
                    ]
                }
            ],
            "execution_tuning": [
                {
                    "task_id": "phase7_prod_execution_optimization",
                    "title": "Production execution with venue-specific tuning",
                    "description": "Optimize execution for production venues with latency and slippage constraints",
                    "module": "swarm/execution",
                    "risk_level": "high",
                    "baseline_hours": 3.5,
                    "dependencies": [
                        "phase7_prod_strategy_deployment"
                    ],
                    "explicit_rollback": "fallback_to_manual_execution",
                    "production_constraints": [
                        "max_slippage_5bps",
                        "execution_latency_200ms",
                        "venue_rate_limits"
                    ]
                },
                {
                    "task_id": "phase7_prod_monitoring_dashboards",
                    "title": "Production monitoring and alerting setup",
                    "description": "Deploy production monitoring dashboards with real-time alerts",
                    "module": "swarm/observability",
                    "risk_level": "medium_high",
                    "baseline_hours": 3.0,
                    "dependencies": [
                        "phase7_prod_execution_optimization"
                    ],
                    "explicit_rollback": "disable_alerts_revert_to_basic",
                    "production_constraints": [
                        "real_time_pnl_alerts",
                        "slo_breach_notifications",
                        "kill_switch_status"
                    ]
                }
            ]
        },

        "execution_plan": {
            "week_1": {
                "focus": "Production deployment preparation",
                "tasks": [
                    "phase7_prod_strategy_deployment",
                    "phase7_prod_risk_monitoring"
                ],
                "target_hours": 7.5,
                "risk_profile": "high",
                "milestone": "Production strategies live with risk controls"
            },
            "week_2": {
                "focus": "Production execution and monitoring",
                "tasks": [
                    "phase7_prod_execution_optimization",
                    "phase7_prod_monitoring_dashboards"
                ],
                "target_hours": 6.5,
                "risk_profile": "high",
                "milestone": "Full production lane operational"
            }
        },

        "production_roi_requirements": {
            "mandatory_fields": [
                "task_type",
                "risk_level",
                "production_constraints",
                "pnl_metrics",
                "risk_metrics",
                "slo_metrics",
                "incident_data",
                "rollback_plan",
                "evidence_links"
            ],
            "task_type_values": [
                "strategy_deployment",
                "risk_monitoring", 
                "execution_optimization",
                "monitoring_setup"
            ],
            "batch_id": "phase7_production_combined",
            "production_metrics": {
                "real_pnl_usd": "required",
                "drawdown_percent": "required",
                "slippage_bps": "required",
                "execution_latency_ms": "required",
                "decision_latency_ms": "required",
                "error_rate_percent": "required",
                "position_concentration": "required",
                "venue_exposure": "required"
            },
            "evidence_requirements": [
                "production_config_diff",
                "risk_monitor_setup_proof",
                "execution_optimization_results",
                "dashboard_screenshots",
                "kill_switch_test_results"
            ]
        },

        "production_gate_plan": {
            "volume_gate": "target_16h_min_15h_production",
            "roi_gate": "production_roi>=97",
            "pnl_gate": "daily_loss<=$500 AND drawdown<=2%",
            "slo_gate": "latency<=200ms AND error_rate<=0.1%",
            "risk_gate": "concentration<=40% AND var<=1%",
            "incident_gate": "zero_incidents_production",
            "kill_switch_gate": "all_kill_switches_tested_and_ready"
        },

        "kill_switch_configuration": {
            "automatic_triggers": [
                "daily_pnl_loss_exceeds_$500",
                "cumulative_drawdown_exceeds_2%",
                "decision_latency_exceeds_500ms",
                "execution_latency_exceeds_1000ms",
                "error_rate_exceeds_1%",
                "venue_api_failure_rate_exceeds_5%",
                "position_concentration_exceeds_60%"
            ],
            "manual_triggers": [
                "risk_manager_manual_halt",
                "operations_manual_halt", 
                "engineering_manual_halt"
            ],
            "halt_actions": [
                "cancel_all_pending_orders",
                "disable_new_strategy_signals",
                "close_positions_gracefully",
                "notify_all_stakeholders",
                "log_incident_report"
            ],
            "recovery_procedures": [
                "incident_investigation_complete",
                "root_cause_identified",
                "fixes_implemented_and_tested",
                "risk_committee_approval",
                "gradual_ramp_up_restart"
            ]
        },

        "monitoring_plan": {
            "real_time": [
                "pnl_and_drawdown",
                "position_concentration", 
                "execution_latency",
                "error_rates",
                "venue_connectivity",
                "kill_switch_status"
            ],
            "per_trade": [
                "slippage_calculation",
                "execution_quality_score",
                "risk_limit_check",
                "compliance_validation"
            ],
            "daily": [
                "production_roi_vs_gate",
                "hours_saved_vs_gate",
                "pnl_vs_limits",
                "slo_compliance_report",
                "risk_metrics_summary"
            ],
            "weekly": [
                "Production performance review",
                "Risk committee update",
                "Infrastructure health check",
                "Kill switch drill results"
            ],
            "halt_triggers": [
                "any_production_incident",
                "pnl_loss_exceeds_limits",
                "slo_breach_critical",
                "risk_limit_violation",
                "manual_intervention"
            ]
        },

        "incident_policy": {
            "policy": "production_zero_tolerance",
            "rules": [
                "Any production incident triggers immediate lane halt",
                "P&L loss exceeding $500 triggers automatic kill-switch",
                "SLO breach (latency >500ms, error >1%) triggers halt",
                "Risk limit violation triggers immediate position unwind",
                "Manual halt available from risk_manager, operations, engineering",
                "Restart requires incident investigation + risk committee approval"
            ],
            "escalation": {
                "level_1": "automatic_kill_switch",
                "level_2": "operations_team_notification", 
                "level_3": "risk_committee_alert",
                "level_4": "executive_management_notification"
            }
        },

        "promotion_checklist": {
            "requirements": [
                "Two consecutive passes of all production gates",
                "Zero production incidents for 14-day pilot",
                "Kill switch drills completed successfully",
                "Real P&L positive or within acceptable loss",
                "All production SLOs green for pilot duration",
                "Risk committee sign-off for expanded scope",
                "Production monitoring dashboards fully operational",
                "Phase 7 completion report generated"
            ]
        }
    }
    
    # Save playbook
    playbook_path = Path("phase7_production_scaling_playbook.json")
    with playbook_path.open("w", encoding="utf-8") as fh:
        json.dump(playbook, fh, indent=2)
    
    logger.info(f"Phase 7 playbook saved to {playbook_path}")
    
    # Print summary
    print("=" * 70)
    print("PHASE 7 PRODUCTION SCALING PLAYBOOK")
    print("=" * 70)
    print(f"Domain: {playbook['domain']}")
    print(f"Batch ID: {playbook['batch_id']}")
    print(f"Risk Level: {playbook['risk_level']}")
    print(f"Target Date: {playbook['target_date']}")
    print()
    
    print("ENTRY CRITERIA:")
    print("-" * 40)
    for criteria, value in playbook["entry_criteria"].items():
        print(f"✓ {criteria}: {value}")
    print()
    
    print("SCOPE CONSTRAINTS:")
    print("-" * 40)
    print(f"✓ Max Notional: {playbook['scope_constraints']['capital_limits']['max_notional_per_lane']}")
    print(f"✓ Allowed Venues: {', '.join(playbook['scope_constraints']['venue_constraints']['allowed_venues'])}")
    print(f"✓ Trading Hours: {playbook['scope_constraints']['time_constraints']['trading_hours']}")
    print(f"✓ Pilot Duration: {playbook['scope_constraints']['time_constraints']['pilot_duration']}")
    print()
    
    print("PRODUCTION GATES:")
    print("-" * 40)
    for gate, config in playbook["production_specific_gates"].items():
        if isinstance(config, dict) and "target" in str(config):
            print(f"✓ {gate}: {config}")
    print()
    
    print("KILL SWITCH TRIGGERS:")
    print("-" * 40)
    for trigger in playbook["kill_switch_configuration"]["automatic_triggers"]:
        print(f"✓ {trigger}")
    print()
    
    print("✅ Playbook saved to phase7_production_scaling_playbook.json")
    print("Next: Implement Phase 7 executor with production constraints")
    
    return playbook


if __name__ == "__main__":
    generate_phase7_playbook()
