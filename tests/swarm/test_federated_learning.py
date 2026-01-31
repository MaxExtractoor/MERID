"""Tests for swarm.federated_learning."""

from __future__ import annotations

import pytest

from swarm import federated_learning as fl


@pytest.fixture()
def coordinator():
    coord = fl.FederatedLearningCoordinator()
    coord._models.clear()
    coord._rounds.clear()
    coord._privacy_budgets.clear()
    return coord


class TestPrivacyBudget:
    def test_has_budget_within_limits(self):
        budget = fl.PrivacyBudget(
            budget_id="test",
            total_epsilon=10.0,
            total_delta=1e-4,
        )

        assert budget.has_budget(epsilon=1.0, delta=1e-5) is True

    def test_has_budget_exceeds_epsilon(self):
        budget = fl.PrivacyBudget(
            budget_id="test",
            total_epsilon=10.0,
            total_delta=1e-4,
            consumed_epsilon=9.5,
        )

        assert budget.has_budget(epsilon=1.0, delta=1e-5) is False

    def test_has_budget_exceeds_delta(self):
        budget = fl.PrivacyBudget(
            budget_id="test",
            total_epsilon=10.0,
            total_delta=1e-4,
            consumed_delta=9e-5,
        )

        assert budget.has_budget(epsilon=1.0, delta=2e-5) is False

    def test_consume_updates_budget(self):
        budget = fl.PrivacyBudget(
            budget_id="test",
            total_epsilon=10.0,
            total_delta=1e-4,
        )

        budget.consume(epsilon=1.0, delta=1e-5)

        assert budget.consumed_epsilon == 1.0
        assert budget.consumed_delta == 1e-5


class TestFederatedLearningCoordinator:
    def test_create_federated_model(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={"layers": [64, 32, 16]},
            description="Test model",
            owner_did="did:owner:123",
        )

        assert model.model_type == fl.ModelType.TRADING_STRATEGY
        assert model.owner_did == "did:owner:123"
        assert model.model_id in coordinator._models
        assert model.model_id in coordinator._privacy_budgets

    def test_authorize_contributor(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.RISK_MODEL,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )

        coordinator.authorize_contributor(model.model_id, "did:agent:456")

        assert "did:agent:456" in model.authorized_contributors

    def test_authorize_contributor_invalid_model(self, coordinator):
        with pytest.raises(ValueError, match="not found"):
            coordinator.authorize_contributor("nonexistent", "did:agent:456")

    def test_start_learning_round(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["agent-1", "agent-2", "agent-3"],
            min_participants=2,
        )

        assert round_obj.status == fl.RoundStatus.IN_PROGRESS
        assert round_obj.model_id == model.model_id
        assert len(round_obj.invited_agents) == 3

    def test_start_learning_round_insufficient_privacy_budget(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )

        budget = coordinator._privacy_budgets[model.model_id]
        budget.consumed_epsilon = 9.5

        with pytest.raises(ValueError, match="Insufficient privacy budget"):
            coordinator.start_learning_round(
                model_id=model.model_id,
                invited_agents=["agent-1", "agent-2"],
                epsilon=1.0,
            )

    def test_submit_model_update(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )
        coordinator.authorize_contributor(model.model_id, "did:agent:1")

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1"],
            min_participants=2,
        )

        update = coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:1",
            gradients={"layer1": [0.1, 0.2, 0.3]},
            num_samples=100,
            training_loss=0.5,
        )

        assert update.contributor_did == "did:agent:1"
        assert update.num_samples == 100
        assert len(round_obj.received_updates) == 1

    def test_submit_model_update_unauthorized(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1"],
        )

        with pytest.raises(ValueError, match="not authorized"):
            coordinator.submit_model_update(
                round_id=round_obj.round_id,
                contributor_did="did:agent:1",
                gradients={"layer1": [0.1]},
                num_samples=100,
                training_loss=0.5,
            )

    def test_aggregation_triggers_on_min_participants(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )
        coordinator.authorize_contributor(model.model_id, "did:agent:1")
        coordinator.authorize_contributor(model.model_id, "did:agent:2")

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1", "did:agent:2"],
            min_participants=2,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:1",
            gradients={"layer1": [0.1, 0.2]},
            num_samples=100,
            training_loss=0.5,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:2",
            gradients={"layer1": [0.3, 0.4]},
            num_samples=200,
            training_loss=0.4,
        )

        assert round_obj.status == fl.RoundStatus.COMPLETED
        assert round_obj.aggregated_update is not None
        assert round_obj.aggregated_update.total_samples == 300

    def test_federated_averaging_weighted(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )
        coordinator.authorize_contributor(model.model_id, "did:agent:1")
        coordinator.authorize_contributor(model.model_id, "did:agent:2")

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1", "did:agent:2"],
            min_participants=2,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:1",
            gradients={"layer1": [1.0]},
            num_samples=100,
            training_loss=0.5,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:2",
            gradients={"layer1": [2.0]},
            num_samples=300,
            training_loss=0.3,
        )

        agg = round_obj.aggregated_update
        expected = (1.0 * 100 + 2.0 * 300) / 400
        assert agg.aggregated_gradients["layer1"][0] == pytest.approx(expected)

    def test_privacy_budget_consumed_after_aggregation(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )
        coordinator.authorize_contributor(model.model_id, "did:agent:1")
        coordinator.authorize_contributor(model.model_id, "did:agent:2")

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1", "did:agent:2"],
            min_participants=2,
            epsilon=0.5,
            delta=1e-6,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:1",
            gradients={"layer1": [0.1]},
            num_samples=100,
            training_loss=0.5,
        )
        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:2",
            gradients={"layer1": [0.2]},
            num_samples=100,
            training_loss=0.4,
        )

        budget = coordinator.get_privacy_budget(model.model_id)
        assert budget.consumed_epsilon == 0.5
        assert budget.consumed_delta == 1e-6

    def test_model_version_incremented(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )
        coordinator.authorize_contributor(model.model_id, "did:agent:1")
        coordinator.authorize_contributor(model.model_id, "did:agent:2")

        initial_version = model.current_version

        round_obj = coordinator.start_learning_round(
            model_id=model.model_id,
            invited_agents=["did:agent:1", "did:agent:2"],
            min_participants=2,
        )

        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:1",
            gradients={"layer1": [0.1]},
            num_samples=100,
            training_loss=0.5,
        )
        coordinator.submit_model_update(
            round_id=round_obj.round_id,
            contributor_did="did:agent:2",
            gradients={"layer1": [0.2]},
            num_samples=100,
            training_loss=0.4,
        )

        assert model.current_version != initial_version

    def test_get_federated_learning_stats(self, coordinator):
        model = coordinator.create_federated_model(
            model_type=fl.ModelType.TRADING_STRATEGY,
            architecture={},
            description="Test",
            owner_did="did:owner:123",
        )

        stats = coordinator.get_federated_learning_stats()

        assert stats["models"]["total"] == 1
        assert stats["rounds"]["total"] == 0
        assert "privacy" in stats
