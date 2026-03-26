"""
Compatibility shim for tests expecting a top-level `merid_metrics` module.
Delegates primarily to `core.merid_metrics`, with legacy helpers from
`archive/legacy_scripts/merid_metrics` when needed.
"""

from core.merid_metrics import *  # noqa: F401,F403

# Legacy helpers used by ROI/analytics tests
try:
    import builtins
    from pathlib import Path

    _legacy_file = Path(__file__).parent / "archive" / "legacy_scripts" / "merid_metrics.py"
    if _legacy_file.exists():
        legacy_namespace: dict = {"__file__": str(_legacy_file), "__name__": "legacy_merid_metrics"}
        exec(_legacy_file.read_text(), legacy_namespace)
        for _name in (
            "load_and_evaluate_csv",
            "plot_reliability",
            "plot_calibration",
            "validate_reference_implementation",
            "evaluate_forecast",
            "compute_brier",
            "compute_bss",
            "brier_decomposition",
            "test_edge_cases",
        ):
            if _name in legacy_namespace:
                globals()[_name] = legacy_namespace[_name]
except Exception:  # pragma: no cover - optional legacy dependency
    load_and_evaluate_csv = None  # type: ignore

if "load_and_evaluate_csv" not in globals() or load_and_evaluate_csv is None:  # type: ignore
    def load_and_evaluate_csv(*args, **kwargs):  # type: ignore
        raise ImportError("legacy load_and_evaluate_csv unavailable")
