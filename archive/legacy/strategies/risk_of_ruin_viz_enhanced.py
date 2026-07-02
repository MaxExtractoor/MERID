"""
Visualize Risk of Ruin Results in Streamlit - Enhanced Version

Interactive visualization components for risk-of-ruin analysis results with advanced charts.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional
import numpy as np
import logging

logger = logging.getLogger(__name__)

def show_ror_results_enhanced(ror_table: List[Dict[str, Any]], 
                             chart_type: str = "bar",
                             title_prefix: str = "Risk of Ruin Analysis") -> None:
    """
    Enhanced display of risk-of-ruin results with interactive charts.
    
    Args:
        ror_table: List of dicts with keys: 'fraction','ruin_level','risk_of_ruin'
        chart_type: Type of chart ('bar', 'line', 'heatmap', '3d_surface')
        title_prefix: Prefix for chart titles
    """
    if not ror_table:
        st.warning("No risk-of-ruin data available")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(ror_table)
    
    # Validate required columns
    required_cols = ['fraction', 'ruin_level', 'risk_of_ruin']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        st.error(f"Missing required columns: {missing_cols}")
        return
    
    st.subheader(f"📊 {title_prefix}")
    
    if chart_type == "bar":
        _show_enhanced_bar_charts(df, title_prefix)
    elif chart_type == "line":
        _show_enhanced_line_charts(df, title_prefix)
    elif chart_type == "heatmap":
        _show_enhanced_heatmap(df, title_prefix)
    elif chart_type == "3d_surface":
        _show_enhanced_3d_surface(df, title_prefix)
    else:
        st.error(f"Unknown chart type: {chart_type}")

def _show_enhanced_bar_charts(df: pd.DataFrame, title_prefix: str) -> None:
    """Show enhanced bar charts for each ruin level."""
    ruin_levels = sorted(df["ruin_level"].unique())
    
    for rl in ruin_levels:
        sub = df[df["ruin_level"] == rl].copy()
        sub["Kelly fraction"] = sub["fraction"].map(lambda x: f"{x:.2f}")
        
        # Create bar chart with enhanced styling
        fig = px.bar(
            sub,
            x="Kelly fraction",
            y="risk_of_ruin",
            title=f"{title_prefix}: Capital < {int(rl*100)}%",
            labels={"risk_of_ruin": "Risk of Ruin"},
            color="risk_of_ruin",
            color_continuous_scale="Reds",
            range_color=[0, 1],
            text_auto=".1%"
        )
        
        fig.update_yaxes(tickformat=".0%")
        fig.update_layout(
            height=450,
            showlegend=False,
            uniformtext_mode='hide',
            uniformtext_minsize=8
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Enhanced summary stats
        max_risk = sub["risk_of_ruin"].max()
        min_risk = sub["risk_of_ruin"].min()
        avg_risk = sub["risk_of_ruin"].mean()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Max Risk", f"{max_risk:.1%}")
        with col2:
            st.metric("Min Risk", f"{min_risk:.1%}")
        with col3:
            st.metric("Avg Risk", f"{avg_risk:.1%}")
        with col4:
            st.metric("Risk Range", f"{max_risk - min_risk:.1%}")

def _show_enhanced_line_charts(df: pd.DataFrame, title_prefix: str) -> None:
    """Show enhanced line charts for risk-of-ruin curves."""
    fig = go.Figure()
    
    ruin_levels = sorted(df["ruin_level"].unique())
    colors = px.colors.qualitative.Set1
    
    for i, rl in enumerate(ruin_levels):
        sub = df[df["ruin_level"] == rl].sort_values("fraction")
        
        fig.add_trace(go.Scatter(
            x=sub["fraction"],
            y=sub["risk_of_ruin"],
            mode="lines+markers",
            name=f"{int(rl*100)}% Capital",
            line=dict(color=colors[i % len(colors)], width=3),
            marker=dict(size=8, line=dict(width=2, color='white')),
            hovertemplate="<b>%{fullData.name}</b><br>" +
                         "Fraction: %{x:.2f}<br>" +
                         "Risk: %{y:.1%}<extra></extra>"
        ))
    
    fig.update_layout(
        title=f"{title_prefix}: Risk vs Kelly Fraction",
        xaxis_title="Kelly Fraction",
        yaxis_title="Risk of Ruin",
        yaxis_tickformat=".0%",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
        height=600,
        hovermode="x unified"
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Enhanced threshold analysis
    _show_enhanced_threshold_analysis(df)

def _show_enhanced_threshold_analysis(df: pd.DataFrame) -> None:
    """Show enhanced threshold analysis with interactive controls."""
    st.subheader("🎯 Risk Threshold Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        threshold = st.slider("Risk Threshold (%)", 0.0, 20.0, 5.0, 0.5,
                            help="Maximum acceptable risk of ruin")
        
        # Find safe fractions
        safe_fractions = []
        ruin_levels = sorted(df["ruin_level"].unique())
        
        for rl in ruin_levels:
            sub = df[df["ruin_level"] == rl]
            safe = sub[sub["risk_of_ruin"] <= threshold/100]
            if not safe.empty:
                safe_fractions.extend(safe["fraction"].tolist())
        
        if safe_fractions:
            unique_safe = list(set(safe_fractions))
            st.success(f"✅ {len(unique_safe)} safe fractions below {threshold}%")
            
            # Show safe fractions with confidence
            safe_df = pd.DataFrame({
                'Fraction': sorted(unique_safe),
                'Confidence': ['High' if f <= 0.25 else 'Medium' if f <= 0.5 else 'Low' for f in sorted(unique_safe)]
            })
            
            st.dataframe(safe_df, use_container_width=True)
        else:
            st.warning(f"⚠️ No fractions below {threshold}% risk threshold")
    
    with col2:
        max_acceptable = st.slider("Max Acceptable Risk (%)", 0.0, 50.0, 10.0, 1.0,
                                  help="Maximum acceptable worst-case risk")
        
        # Show worst-case risk analysis
        worst_case = df.groupby("fraction")["risk_of_ruin"].max()
        acceptable = worst_case[worst_case <= max_acceptable/100]
        
        if not acceptable.empty:
            st.success(f"✅ {len(acceptable)} fractions with ≤{max_acceptable}% worst-case risk")
            
            # Create acceptable fractions chart
            fig = px.bar(
                x=acceptable.index,
                y=acceptable.values,
                title=f"Acceptable Fractions (≤{max_acceptable}% Risk)",
                labels={"x": "Kelly Fraction", "y": "Worst-Case Risk"},
                color=acceptable.values,
                color_continuous_scale="Greens",
                range_color=[0, max_acceptable/100]
            )
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(f"⚠️ No fractions with ≤{max_acceptable}% worst-case risk")

def _show_enhanced_heatmap(df: pd.DataFrame, title_prefix: str) -> None:
    """Show enhanced risk-of-ruin heatmap."""
    # Pivot data for heatmap
    pivot_df = df.pivot(index="fraction", columns="ruin_level", values="risk_of_ruin")
    
    # Create enhanced heatmap
    fig = px.imshow(
        pivot_df,
        text_auto=".1%",
        color_continuous_scale="Reds",
        title=f"{title_prefix}: Risk Heatmap",
        labels=dict(x="Ruin Level", y="Kelly Fraction", color="Risk of Ruin"),
        aspect="auto"
    )
    
    fig.update_layout(
        height=500,
        xaxis_title="Ruin Level",
        yaxis_title="Kelly Fraction"
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Enhanced analysis
    _show_enhanced_heatmap_analysis(pivot_df)

def _show_enhanced_heatmap_analysis(pivot_df: pd.DataFrame) -> None:
    """Show enhanced heatmap analysis."""
    st.subheader("📈 Heatmap Analysis")
    
    # Calculate statistics
    avg_risk = pivot_df.mean().mean()
    max_risk = pivot_df.max().max()
    min_risk = pivot_df.min().min()
    
    # Risk zones
    low_risk = (pivot_df < 0.05).sum().sum()
    medium_risk = ((pivot_df >= 0.05) & (pivot_df < 0.15)).sum().sum()
    high_risk = (pivot_df >= 0.15).sum().sum()
    total_cells = len(pivot_df) * len(pivot_df.columns)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Average Risk", f"{avg_risk:.1%}")
    with col2:
        st.metric("Maximum Risk", f"{max_risk:.1%}")
    with col3:
        st.metric("Minimum Risk", f"{min_risk:.1%}")
    with col4:
        st.metric("Risk Range", f"{max_risk - min_risk:.1%}")
    
    # Risk zones chart
    st.subheader("🎯 Risk Zones")
    
    zones_data = {
        'Risk Zone': ['Low Risk (<5%)', 'Medium Risk (5-15%)', 'High Risk (>15%)'],
        'Cells': [low_risk, medium_risk, high_risk],
        'Percentage': [low_risk/total_cells*100, medium_risk/total_cells*100, high_risk/total_cells*100]
    }
    
    zones_df = pd.DataFrame(zones_data)
    
    fig = px.bar(
        zones_df,
        x="Risk Zone",
        y="Cells",
        color="Percentage",
        title="Risk Distribution",
        labels={"Cells": "Number of Cells"},
        color_continuous_scale="RdYlGn_r"
    )
    
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

def _show_enhanced_3d_surface(df: pd.DataFrame, title_prefix: str) -> None:
    """Show enhanced 3D surface plot of risk-of-ruin."""
    # Pivot data for surface plot
    pivot_df = df.pivot(index="fraction", columns="ruin_level", values="risk_of_ruin")
    
    # Create enhanced 3D surface
    fig = go.Figure(data=[go.Surface(
        z=pivot_df.values,
        x=pivot_df.columns,
        y=pivot_df.index,
        colorscale="Reds",
        colorbar=dict(title="Risk of Ruin"),
        contours=dict(
            z=dict(show=True, usecolormap=True, highlightcolor="limegreen", project=dict(z=True))
        )
    )])
    
    fig.update_layout(
        title=f"{title_prefix}: 3D Risk Surface",
        scene=dict(
            xaxis_title="Ruin Level",
            yaxis_title="Kelly Fraction",
            zaxis_title="Risk of Ruin",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.5))
        ),
        height=700
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Surface analysis
    st.subheader("🔍 Surface Analysis")
    
    # Find optimal regions
    low_risk_regions = (pivot_df < 0.05).stack()
    if len(low_risk_regions) > 0:
        st.success(f"✅ Found {len(low_risk_regions)} low-risk regions (<5%)")
        
        # Show top low-risk combinations
        top_low_risk = low_risk_regions.nsmallest(5)
        st.write("Top low-risk combinations:")
        for (fraction, ruin_level), risk in top_low_risk.items():
            st.write(f"• Fraction: {fraction:.2f}, Ruin Level: {ruin_level:.0%}, Risk: {risk:.1%}")

def show_ror_recommendations_enhanced(ror_table: List[Dict[str, Any]], 
                                     max_risk_tolerance: float = 0.05,
                                     strategy_name: str = "Current Strategy") -> None:
    """
    Enhanced risk management recommendations.
    
    Args:
        ror_table: Risk-of-ruin table data
        max_risk_tolerance: Maximum acceptable risk (0.05 = 5%)
        strategy_name: Name of the strategy being analyzed
    """
    if not ror_table:
        st.warning("No risk-of-ruin data available for recommendations")
        return
    
    df = pd.DataFrame(ror_table)
    
    st.subheader(f"🛡️ Risk Management Recommendations: {strategy_name}")
    
    # Find safe fractions
    safe_fractions = []
    for fraction in df["fraction"].unique():
        max_risk = df[df["fraction"] == fraction]["risk_of_ruin"].max()
        if max_risk <= max_risk_tolerance:
            safe_fractions.append(fraction)
    
    # Recommendations panel
    if safe_fractions:
        st.success(f"✅ {len(safe_fractions)} fractions meet {max_risk_tolerance:.1%} risk tolerance")
        
        # Best recommendation with confidence scoring
        best_fraction = max(safe_fractions)
        
        # Calculate confidence score
        confidence_scores = {}
        for frac in safe_fractions:
            risks = df[df["fraction"] == frac]["risk_of_ruin"]
            avg_risk = risks.mean()
            max_risk = risks.max()
            
            # Higher confidence for lower average risk and max risk
            confidence = (1 - avg_risk) * (1 - max_risk)
            confidence_scores[frac] = confidence
        
        best_confidence = max(confidence_scores.values())
        best_fraction_conf = max(confidence_scores, key=confidence_scores.get)
        
        st.info(f"🏆 **Best recommendation**: {best_fraction_conf:.2f} Kelly (confidence: {best_confidence:.1%})")
        
        # Show all safe options with confidence
        safe_options = []
        for frac in sorted(safe_fractions):
            risks = df[df["fraction"] == frac]["risk_of_ruin"]
            avg_risk = risks.mean()
            max_risk = risks.max()
            confidence = confidence_scores.get(frac, 0)
            
            safe_options.append({
                "Fraction": f"{frac:.2f}",
                "Avg Risk": f"{avg_risk:.1%}",
                "Max Risk": f"{max_risk:.1%}",
                "Confidence": f"{confidence:.1%}"
            })
        
        safe_df = pd.DataFrame(safe_options)
        st.dataframe(safe_df, use_container_width=True)
        
    else:
        st.warning(f"⚠️ No fractions meet {max_risk_tolerance:.1%} risk tolerance")
        st.write("Consider:")
        st.write("• Reducing position size further")
        st.write("• Improving strategy win rate")
        st.write("• Using additional risk controls")
    
    # Risk assessment with visual indicators
    max_risk = df["risk_of_ruin"].max()
    
    if max_risk < 0.01:
        risk_level = "Very Low"
        risk_emoji = "🟢"
        risk_color = "green"
        risk_desc = "Strategy shows excellent risk characteristics"
    elif max_risk < 0.05:
        risk_level = "Low"
        risk_emoji = "🟢"
        risk_color = "green"
        risk_desc = "Strategy has acceptable risk levels"
    elif max_risk < 0.15:
        risk_level = "Medium"
        risk_emoji = "🟡"
        risk_color = "orange"
        risk_desc = "Strategy has moderate risk - monitor closely"
    else:
        risk_level = "High"
        risk_emoji = "🔴"
        risk_color = "red"
        risk_desc = "Strategy has high risk - use conservative sizing"
    
    # Visual risk indicator
    st.markdown(f"### {risk_emoji} Risk Assessment: {risk_level}")
    st.markdown(f'<div style="background-color: {risk_color}; color: white; padding: 10px; border-radius: 5px;">{risk_desc}</div>', unsafe_allow_html=True)

# Example usage in Streamlit:
"""
import streamlit as st
import numpy as np

# Generate sample risk-of-ruin data
fractions = [0.125, 0.25, 0.5, 0.75, 1.0]
ruin_levels = [0.8, 0.6, 0.4, 0.2]

ror_table = []
for f in fractions:
    for rl in ruin_levels:
        base_risk = 0.3 * f
        risk = base_risk * (1 + np.random.normal(0, 0.1))
        risk = max(0, min(1, risk))
        
        ror_table.append({
            'fraction': f,
            'ruin_level': rl,
            'risk_of_ruin': risk
        })

# Streamlit app
st.title("Enhanced Risk of Ruin Visualization")

# Enhanced visualization
chart_type = st.selectbox("Chart Type", ["bar", "line", "heatmap", "3d_surface"])
show_ror_results_enhanced(ror_table, chart_type=chart_type)

# Enhanced recommendations
show_ror_recommendations_enhanced(ror_table, max_risk_tolerance=0.05, strategy_name="Enhanced Strategy")
"""
