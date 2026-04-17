"""
Risk of Ruin Visualization Charts in Streamlit

Streamlit components for visualizing risk-of-ruin analysis results.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def show_risk_of_ruin_chart(ror_table: List[Dict[str, Any]], 
                             chart_type: str = "bar",
                             title: str = "Risk of Ruin Analysis") -> None:
    """
    Display risk-of-ruin charts in Streamlit.
    
    Args:
        ror_table: List of dicts with keys: 'fraction','ruin_level','risk_of_ruin'
        chart_type: Type of chart ('bar', 'line', 'heatmap')
        title: Chart title
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
    
    st.subheader(title)
    
    if chart_type == "bar":
        _show_bar_charts(df)
    elif chart_type == "line":
        _show_line_charts(df)
    elif chart_type == "heatmap":
        _show_heatmap(df)
    else:
        st.error(f"Unknown chart type: {chart_type}")

def _show_bar_charts(df: pd.DataFrame) -> None:
    """Show bar charts for each ruin level."""
    # Create one chart per ruin level
    ruin_levels = sorted(df["ruin_level"].unique())
    
    for rl in ruin_levels:
        st.subheader(f"Risk of ruin (capital < {int(rl*100)}%)")
        
        sub = df[df["ruin_level"] == rl].copy()
        sub["fraction_label"] = sub["fraction"].map(lambda x: f"{x:.2f}")
        
        # Create bar chart
        fig = px.bar(
            sub,
            x="fraction_label",
            y="risk_of_ruin",
            title=f"Risk of Ruin at {int(rl*100)}% Capital Level",
            labels={"fraction_label": "Kelly Fraction", "risk_of_ruin": "Risk of Ruin"},
            color="risk_of_ruin",
            color_continuous_scale="Reds",
            range_color=[0, 1]
        )
        
        fig.update_layout(
            xaxis_title="Kelly Fraction",
            yaxis_title="Risk of Ruin",
            yaxis_tickformat=".1%",
            showlegend=False
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Add summary stats
        max_risk = sub["risk_of_ruin"].max()
        min_risk = sub["risk_of_ruin"].min()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Max Risk", f"{max_risk:.1%}")
        with col2:
            st.metric("Min Risk", f"{min_risk:.1%}")
        with col3:
            st.metric("Risk Range", f"{max_risk - min_risk:.1%}")

def _show_line_charts(df: pd.DataFrame) -> None:
    """Show line charts for risk-of-ruin curves."""
    fig = go.Figure()
    
    # Create line chart for each ruin level
    ruin_levels = sorted(df["ruin_level"].unique())
    colors = px.colors.qualitative.Set1
    
    for i, rl in enumerate(ruin_levels):
        sub = df[df["ruin_level"] == rl].sort_values("fraction")
        
        fig.add_trace(go.Scatter(
            x=sub["fraction"],
            y=sub["risk_of_ruin"],
            mode="lines+markers",
            name=f"{int(rl*100)}% Capital",
            line=dict(color=colors[i % len(colors)]),
            marker=dict(size=6)
        ))
    
    fig.update_layout(
        title="Risk of Ruin vs Kelly Fraction",
        xaxis_title="Kelly Fraction",
        yaxis_title="Risk of Ruin",
        yaxis_tickformat=".1%",
        legend=dict(x=0.01, y=0.99)
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Add threshold lines
    st.subheader("Risk Thresholds")
    
    col1, col2 = st.columns(2)
    
    with col1:
        threshold = st.slider("Risk Threshold (%)", 0.0, 20.0, 5.0, 0.5)
        
        # Find safe fractions
        safe_fractions = []
        for rl in ruin_levels:
            sub = df[df["ruin_level"] == rl]
            safe = sub[sub["risk_of_ruin"] <= threshold/100]
            if not safe.empty:
                safe_fractions.extend(safe["fraction"].tolist())
        
        if safe_fractions:
            st.success(f"Safe fractions below {threshold}%: {len(set(safe_fractions))}")
            st.write(list(set(safe_fractions)))
        else:
            st.warning(f"No fractions below {threshold}% risk threshold")
    
    with col2:
        max_acceptable = st.slider("Max Acceptable Risk (%)", 0.0, 50.0, 10.0, 1.0)
        
        # Show worst-case risk
        worst_case = df.groupby("fraction")["risk_of_ruin"].max()
        acceptable = worst_case[worst_case <= max_acceptable/100]
        
        if not acceptable.empty:
            st.success(f"Fractions with ≤{max_acceptable}% worst-case risk: {len(acceptable)}")
            st.write(list(acceptable.index))
        else:
            st.warning(f"No fractions with ≤{max_acceptable}% worst-case risk")

def _show_heatmap(df: pd.DataFrame) -> None:
    """Show risk-of-ruin heatmap."""
    # Pivot data for heatmap
    pivot_df = df.pivot(index="fraction", columns="ruin_level", values="risk_of_ruin")
    
    # Create heatmap
    fig = px.imshow(
        pivot_df,
        text_auto=".1%",
        color_continuous_scale="Reds",
        title="Risk of Ruin Heatmap",
        labels=dict(x="Ruin Level", y="Kelly Fraction", color="Risk of Ruin")
    )
    
    fig.update_layout(
        xaxis_title="Ruin Level",
        yaxis_title="Kelly Fraction"
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Add summary statistics
    st.subheader("Heatmap Analysis")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        avg_risk = pivot_df.mean().mean()
        st.metric("Average Risk", f"{avg_risk:.1%}")
    
    with col2:
        max_risk = pivot_df.max().max()
        st.metric("Maximum Risk", f"{max_risk:.1%}")
    
    with col3:
        min_risk = pivot_df.min().min()
        st.metric("Minimum Risk", f"{min_risk:.1%}")

def show_risk_summary(ror_table: List[Dict[str, Any]]) -> None:
    """
    Display comprehensive risk-of-ruin summary.
    
    Args:
        ror_table: Risk-of-ruin table data
    """
    if not ror_table:
        st.warning("No risk-of-ruin data available")
        return
    
    df = pd.DataFrame(ror_table)
    
    st.subheader("Risk of Ruin Summary")
    
    # Overall statistics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        max_risk = df["risk_of_ruin"].max()
        st.metric("Worst Case Risk", f"{max_risk:.1%}")
    
    with col2:
        min_risk = df["risk_of_ruin"].min()
        st.metric("Best Case Risk", f"{min_risk:.1%}")
    
    with col3:
        avg_risk = df["risk_of_ruin"].mean()
        st.metric("Average Risk", f"{avg_risk:.1%}")
    
    with col4:
        risk_range = max_risk - min_risk
        st.metric("Risk Range", f"{risk_range:.1%}")
    
    # Risk level analysis
    st.subheader("Risk Level Analysis")
    
    risk_levels = sorted(df["ruin_level"].unique())
    
    for rl in risk_levels:
        sub = df[df["ruin_level"] == rl]
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(f"{int(rl*100)}% Capital", f"{sub['risk_of_ruin'].mean():.1%}")
        
        with col2:
            safe_fractions = sub[sub["risk_of_ruin"] < 0.05]
            st.metric("Safe Fractions (<5%)", len(safe_fractions))
        
        with col3:
            best_fraction = sub.loc[sub["risk_of_ruin"].idxmin(), "fraction"]
            st.metric("Best Fraction", f"{best_fraction:.2f}")

def show_risk_recommendations(ror_table: List[Dict[str, Any]], 
                               max_risk_tolerance: float = 0.05) -> None:
    """
    Display risk management recommendations.
    
    Args:
        ror_table: Risk-of-ruin table data
        max_risk_tolerance: Maximum acceptable risk (0.05 = 5%)
    """
    if not ror_table:
        st.warning("No risk-of-ruin data available")
        return
    
    df = pd.DataFrame(ror_table)
    
    st.subheader("Risk Management Recommendations")
    
    # Find safe fractions
    safe_fractions = []
    for fraction in df["fraction"].unique():
        max_risk = df[df["fraction"] == fraction]["risk_of_ruin"].max()
        if max_risk <= max_risk_tolerance:
            safe_fractions.append(fraction)
    
    if safe_fractions:
        st.success(f"✅ {len(safe_fractions)} fractions meet {max_risk_tolerance:.1%} risk tolerance")
        st.write("Recommended fractions:")
        for frac in sorted(safe_fractions):
            st.write(f"• {frac:.2f} Kelly")
    else:
        st.warning(f"⚠️ No fractions meet {max_risk_tolerance:.1%} risk tolerance")
        st.write("Consider:")
        st.write("• Reducing position size further")
        st.write("• Improving strategy win rate")
        st.write("• Using additional risk controls")
    
    # Risk assessment
    max_risk = df["risk_of_ruin"].max()
    
    if max_risk < 0.01:
        st.success("🟢 Very Low Risk Strategy")
        st.write("Strategy shows excellent risk characteristics")
    elif max_risk < 0.05:
        st.success("🟡 Low Risk Strategy")
        st.write("Strategy has acceptable risk levels")
    elif max_risk < 0.15:
        st.warning("🟠 Moderate Risk Strategy")
        st.write("Strategy has moderate risk - monitor closely")
    else:
        st.error("🔴 High Risk Strategy")
        st.write("Strategy has high risk - use conservative sizing")

# Example usage in Streamlit:
"""
import streamlit as st
import pandas as pd
import numpy as np

# Generate sample risk-of-ruin table
np.random.seed(42)
fractions = [0.125, 0.25, 0.5, 0.75, 1.0]
ruin_levels = [0.8, 0.6, 0.4, 0.2]

ror_table = []
for f in fractions:
    for rl in ruin_levels:
        risk = np.random.uniform(0.01, 0.3)  # Simulated risk
        ror_table.append({
            'fraction': f,
            'ruin_level': rl,
            'risk_of_ruin': risk
        })

# Streamlit app
st.title("Risk of Ruin Analysis")

# Chart selection
chart_type = st.selectbox("Chart Type", ["bar", "line", "heatmap"])

# Display charts
show_risk_of_ruin_chart(ror_table, chart_type=chart_type)

# Summary and recommendations
show_risk_summary(ror_table)
show_risk_recommendations(ror_table, max_risk_tolerance=0.05)
"""
