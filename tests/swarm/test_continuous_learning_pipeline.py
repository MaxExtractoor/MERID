"""Tests for swarm.continuous_learning_pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from swarm.continuous_learning_pipeline import (
    ContinuousLearningPipeline,
    DatasetSplit,
    DeploymentStage,
    ValidationStatus,
)


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    pipeline_dir = tmp_path / "pipeline"
    pipeline_dir.mkdir()
    # Ensure pipeline writes into tmp directory
    monkeypatch.setattr(
        "swarm.continuous_learning_pipeline.Path",
        lambda p: Path(pipeline_dir) if p == "swarm/continuous_learning" else Path(p),
    )
    return ContinuousLearningPipeline(pipeline_dir=str(pipeline_dir))


def make_data_points(pipeline, count=10):
    points = []
    base = datetime.utcnow() - timedelta(hours=count)
    for idx in range(count):
        point = pipeline.ingest_data_point(
            features={"x": idx},
            label=idx % 2,
            regime="bull" if idx % 2 == 0 else "bear",
            entropy=0.5,
        )
        point.timestamp = base + timedelta(minutes=idx)
        points.append(point)
    return points


def test_create_training_dataset_splits_time_aware(pipeline):
    points = make_data_points(pipeline, count=20)
    dataset = pipeline.create_training_dataset("dataset", points)

    assert len(dataset.splits[DatasetSplit.TRAIN]) == 14
    assert dataset.splits[DatasetSplit.TRAIN][0] == points[0].data_id
    assert dataset.regime_distribution["bull"] >= 1


def test_train_and_validate_model_version(pipeline):
    dataset = pipeline.create_training_dataset("dataset", make_data_points(pipeline))
    version = pipeline.train_model_version(
        model_type="transformer",
        model_name="alpha",
        dataset_id=dataset.dataset_id,
        hyperparameters={"epochs": 50},
    )

    status, failed = pipeline.validate_model_version(version.version_id)
    assert status in {ValidationStatus.PASSED, ValidationStatus.WARNING}
    if status is ValidationStatus.PASSED:
        assert version.deployment_stage == DeploymentStage.VALIDATION


def test_deployment_flow_and_canary(pipeline):
    dataset = pipeline.create_training_dataset("dataset", make_data_points(pipeline))
    version = pipeline.train_model_version("transformer", "alpha", dataset.dataset_id, {})
    status, _ = pipeline.validate_model_version(version.version_id)
    if status is not ValidationStatus.PASSED:
        version.validation_status = ValidationStatus.PASSED
        version.deployment_stage = DeploymentStage.VALIDATION
    pipeline.deploy_to_simulation(version.version_id)
    pipeline.deploy_to_paper(version.version_id)

    control = pipeline.train_model_version("transformer", "control", dataset.dataset_id, {})
    status_control, _ = pipeline.validate_model_version(control.version_id)
    if status_control is not ValidationStatus.PASSED:
        control.validation_status = ValidationStatus.PASSED
        control.deployment_stage = DeploymentStage.VALIDATION
    pipeline.deploy_to_simulation(control.version_id)
    pipeline.deploy_to_paper(control.version_id)

    canary = pipeline.start_canary_deployment(version.version_id, control.version_id, capital_allocation=1_000_000, traffic_percentage=5.0)
    passed, passed_gates, failed_gates = pipeline.evaluate_canary(
        canary.canary_id,
        canary_metrics={"sharpe_ratio": 1.1, "max_drawdown": 0.1, "action_entropy": 0.4, "kl_divergence": 0.05, "anomaly_count": 0},
        control_metrics={"sharpe_ratio": 1.0, "max_drawdown": 0.09, "action_entropy": 0.35, "kl_divergence": 0.04, "anomaly_count": 0},
    )
    assert passed is True
    assert "performance_gate" in passed_gates

    version.deployment_stage = DeploymentStage.CANARY
    pipeline.promote_to_production(version.version_id)
    pipeline.rollback_version(version.version_id, reason="regression")
    assert version.deployment_stage == DeploymentStage.ROLLED_BACK


def test_meta_checkpoints_and_summary(pipeline):
    checkpoint = pipeline.create_meta_checkpoint(
        name="MultiAsset",
        model_type="transformer",
        learned_priors={"alpha": 0.1},
        applicable_assets=["BTC", "ETH"],
        applicable_venues=["cex", "dex"],
        applicable_regimes=["bull", "bear"],
    )
    checkpoint.success_rate = 0.8
    matches = pipeline.get_applicable_checkpoints("transformer", "BTC", "cex", "bull")
    assert matches[0].checkpoint_id == checkpoint.checkpoint_id

    summary = pipeline.get_pipeline_summary()
    assert "datasets" in summary
    assert "model_versions" in summary


def test_get_continuous_learning_pipeline_singleton(monkeypatch):
    monkeypatch.setattr("swarm.continuous_learning_pipeline._continuous_learning_pipeline", None)
    from swarm.continuous_learning_pipeline import get_continuous_learning_pipeline

    first = get_continuous_learning_pipeline()
    second = get_continuous_learning_pipeline()
    assert first is second
