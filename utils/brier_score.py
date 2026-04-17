"""
Brier Score Implementation for MERID

Proper Brier score calculation following the standard definition:
BS = mean((p_i - o_i)^2) where p_i are predicted probabilities and o_i are binary outcomes (0 or 1)
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass

@dataclass
class BinaryOutcome:
    """Binary outcome for Brier score calculation"""
    predicted_probability: float
    actual_outcome: int  # 0 or 1

def brier_score(y_true: List[int], y_prob: List[float]) -> float:
    """
    Calculate Brier score for binary events.
    
    Args:
        y_true: List of actual outcomes (0 or 1)
        y_prob: List of predicted probabilities for class 1
    
    Returns:
        Brier score (lower is better, 0 = perfect, 1 = worst)
    """
    if len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must have the same length")
    
    if not y_true:
        raise ValueError("Cannot calculate Brier score for empty data")
    
    y_true_array = np.asarray(y_true, dtype=float)
    y_prob_array = np.asarray(y_prob, dtype=float)
    
    # Validate inputs
    if not np.all((y_true_array == 0) | (y_true_array == 1)):
        raise ValueError("y_true must contain only 0 or 1")
    if not np.all((y_prob_array >= 0) & (y_prob_array <= 1)):
        raise ValueError("y_prob must contain only valid probabilities [0, 1]")
    
    return np.mean((y_prob_array - y_true_array) ** 2)

def brier_skill_score(model_brier: float, reference_brier: float) -> float:
    """
    Calculate Brier Skill Score (BSS) comparing model to reference.
    
    Args:
        model_brier: Brier score of the model
        reference_brier: Brier score of the reference model
    
    Returns:
        BSS (1 = perfect, 0 = no improvement, < 0 = worse than reference)
    """
    if reference_brier == 0:
        raise ValueError("Reference Brier score cannot be zero")
    
    return (reference_brier - model_brier) / reference_brier

def decompose_brier_score(y_true: List[int], y_prob: List[float], n_bins: int = 10) -> dict:
    """
    Decompose Brier score into reliability, resolution, and uncertainty components.
    
    Args:
        y_true: List of actual outcomes (0 or 1)
        y_prob: List of predicted probabilities
        n_bins: Number of probability bins for decomposition
    
    Returns:
        Dictionary with decomposition components
    """
    if len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must have the same length")
    
    # Create probability bins
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    
    # Assign predictions to bins
    bin_indices = np.digitize(y_prob, bin_edges) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)
    
    # Calculate components
    reliability = 0.0
    resolution = 0.0
    uncertainty = 0.0
    total_count = len(y_true)
    
    # Base rate (overall outcome frequency)
    base_rate = np.mean(y_true)
    
    for i in range(n_bins):
        # Get data in this bin
        mask = bin_indices == i
        if not np.any(mask):
            continue
            
        bin_y_true = np.array(y_true)[mask]
        bin_y_prob = np.array(y_prob)[mask]
        bin_count = len(bin_y_true)
        
        # Empirical frequency in this bin
        empirical_freq = np.mean(bin_y_true)
        predicted_freq = bin_centers[i]
        
        # Reliability component (calibration)
        reliability += bin_count * (predicted_freq - empirical_freq) ** 2
        
        # Resolution component (how well forecasts separate outcomes)
        resolution += bin_count * (empirical_freq - base_rate) ** 2
    
    # Uncertainty component (inherent difficulty)
    uncertainty = base_rate * (1 - base_rate)
    
    # Normalize by total count
    reliability /= total_count
    resolution /= total_count
    
    # Verify decomposition: BS = reliability - resolution + uncertainty
    total_brier = brier_score(y_true, y_prob)
    decomposed_brier = reliability - resolution + uncertainty
    
    return {
        "brier_score": total_brier,
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "decomposition_check": decomposed_brier,
        "base_rate": base_rate,
        "n_bins": n_bins
    }

def interpret_brier_score(brier: float, reference_brier: Optional[float] = None) -> dict:
    """
    Interpret Brier score with context.
    
    Args:
        brier: Brier score to interpret
        reference_brier: Optional reference Brier score for skill assessment
    
    Returns:
        Dictionary with interpretation
    """
    interpretation = {
        "brier_score": brier,
        "quality": "excellent" if brier < 0.1 else "good" if brier < 0.2 else "fair" if brier < 0.3 else "poor",
        "interpretation": "Lower is better (0 = perfect, 1 = worst)"
    }
    
    if reference_brier is not None:
        bss = brier_skill_score(brier, reference_brier)
        interpretation["brier_skill_score"] = bss
        interpretation["skill_interpretation"] = (
            "perfect" if bss == 1.0 else
            "excellent" if bss > 0.5 else
            "good" if bss > 0.25 else
            "minimal" if bss > 0 else
            "worse" if bss < 0 else "unknown"
        )
    
    return interpretation

# Example usage and test cases
def example_brier_calculation():
    """Example from the documentation"""
    # Example: rain forecasts
    y_true = [1, 1, 0, 1]  # Rain occurred on days 1, 2, 4
    y_prob = [0.27, 0.67, 0.83, 0.90]  # Forecast probabilities
    
    bs = brier_score(y_true, y_prob)
    print(f"Brier score: {bs:.4f}")  # Should be ~0.3352
    
    # Manual calculation verification
    manual_errors = [(0.27 - 1)**2, (0.67 - 1)**2, (0.83 - 0)**2, (0.90 - 1)**2]
    manual_bs = sum(manual_errors) / len(manual_errors)
    print(f"Manual Brier score: {manual_bs:.4f}")
    
    # Brier Skill Score example
    reference_bs = 0.4421  # Climatology reference
    bss = brier_skill_score(bs, reference_bs)
    print(f"Brier Skill Score: {bss:.4f}")  # Should be ~0.2418
    
    # Decomposition
    decomposition = decompose_brier_score(y_true, y_prob)
    print(f"Decomposition: {decomposition}")

if __name__ == "__main__":
    example_brier_calculation()
