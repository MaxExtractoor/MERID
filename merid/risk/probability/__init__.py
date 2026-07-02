"""
Probability calibration module for MERID.

This module provides probability calibration functionality using Platt scaling
(logistic regression) to improve model probability estimates.
"""

from .platt_scaler import PlattScaler

__all__ = ["PlattScaler"]
