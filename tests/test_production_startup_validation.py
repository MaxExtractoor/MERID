"""Acceptance tests for explicit production vs testing environment policy."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.startup_validations import StartupValidationError, validate_production_startup, validate_hybrid_signal_audit


# ---------------------------------------------------------------------------
# Startup hard-fail checks
# ---------------------------------------------------------------------------

def test_production_startup_rejects_pytest_current_test(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test")
    with pytest.raises(StartupValidationError, match="PYTEST_CURRENT_TEST"):
        validate_production_startup()


def test_production_startup_rejects_debug_manual_orders(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "true")
    with pytest.raises(StartupValidationError, match="DEBUG_ALLOW_MANUAL_ORDERS"):
        validate_production_startup()


def test_production_startup_rejects_allow_direct_execution(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_DIRECT_EXECUTION", "true")
    with pytest.raises(StartupValidationError, match="ALLOW_DIRECT_EXECUTION"):
        validate_production_startup()


def test_production_startup_rejects_ct_script_bypass(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_ALLOW_CT_SCRIPT_BYPASS", "1")
    with pytest.raises(StartupValidationError, match="MERID_ALLOW_CT_SCRIPT_BYPASS"):
        validate_production_startup()


def test_production_startup_rejects_firewall_observe_only(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "true")
    with pytest.raises(StartupValidationError, match="MERID_EXIT_FIREWALL_OBSERVE_ONLY"):
        validate_production_startup()


def test_production_startup_rejects_missing_exit_parentage(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    monkeypatch.delenv("MERID_REQUIRE_EXIT_PARENTAGE", raising=False)
    with pytest.raises(StartupValidationError, match="MERID_REQUIRE_EXIT_PARENTAGE"):
        validate_production_startup()


def test_production_startup_passes_when_clean(monkeypatch):
    _clean_prod(monkeypatch)
    validate_production_startup()


def test_testing_env_not_inherited_from_dotenv():
    """conftest must set MERID_ENV=testing and .env must not override it."""
    assert os.environ.get("MERID_ENV") == "testing"


def _clean_prod(monkeypatch):
    """Set a fully clean 15m production environment."""
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_KALSHI_ENV", "prod")
    monkeypatch.delenv("KALSHI_ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("DEBUG_ALLOW_MANUAL_ORDERS", raising=False)
    monkeypatch.delenv("ALLOW_DIRECT_EXECUTION", raising=False)
    monkeypatch.delenv("MERID_ALLOW_CT_SCRIPT_BYPASS", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    monkeypatch.setenv("MERID_REQUIRE_EXIT_PARENTAGE", "1")
    monkeypatch.setenv("MERID_CIRCUIT_BREAKER_DISABLED", "0")
    for var in ["BINANCE_API_KEY", "COINBASE_API_KEY", "KRAKEN_API_KEY", "ALPACA_API_KEY", "POLYMARKET_API_KEY"]:
        monkeypatch.delenv(var, raising=False)


def test_production_startup_rejects_missing_kalshi_env(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.delenv("MERID_KALSHI_ENV", raising=False)
    monkeypatch.setenv("KALSHI_ENV", "live")
    with pytest.raises(StartupValidationError, match="KALSHI_ENV"):
        validate_production_startup()


def test_production_startup_rejects_kalshi_env_conflict(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("KALSHI_ENV", "demo")
    with pytest.raises(StartupValidationError, match="KALSHI_ENV"):
        validate_production_startup()


def test_production_startup_rejects_legacy_exchange_credentials(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("BINANCE_API_KEY", "leaked")
    with pytest.raises(StartupValidationError, match="BINANCE_API_KEY"):
        validate_production_startup()


def test_production_startup_rejects_circuit_breaker_disabled(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_CIRCUIT_BREAKER_DISABLED", "1")
    with pytest.raises(StartupValidationError, match="MERID_CIRCUIT_BREAKER_DISABLED"):
        validate_production_startup()


def test_production_startup_rejects_invalid_exit_parentage(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_REQUIRE_EXIT_PARENTAGE", "0")
    with pytest.raises(StartupValidationError, match="MERID_REQUIRE_EXIT_PARENTAGE"):
        validate_production_startup()


def test_production_startup_passes_with_canonical_env(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("KALSHI_ENV", "live")
    validate_production_startup()


def test_production_startup_rejects_dirty_tree_in_live_mode(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setattr(
        "merid.startup_validations._get_live_path_git_status",
        lambda: [(" M", "merid/event_venues/kalshi/order_router.py")],
    )
    with pytest.raises(StartupValidationError, match="uncommitted"):
        validate_production_startup()


def test_production_startup_allows_dirty_tree_with_override(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_ALLOW_DIRTY_TREE", "1")
    monkeypatch.setattr(
        "merid.startup_validations._get_live_path_git_status",
        lambda: [(" M", "merid/event_venues/kalshi/order_router.py")],
    )
    validate_production_startup()


def test_production_startup_skips_dirty_tree_in_paper_mode(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_TRADE_MODE", "paper")
    monkeypatch.setattr(
        "merid.startup_validations._get_live_path_git_status",
        lambda: [(" M", "merid/event_venues/kalshi/order_router.py")],
    )
    validate_production_startup()


def test_production_startup_skips_dirty_tree_in_testing_env(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "testing")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setattr(
        "merid.startup_validations._get_live_path_git_status",
        lambda: [(" M", "merid/event_venues/kalshi/order_router.py")],
    )
    validate_production_startup()


def test_validate_dirty_tree_blocks_real_uncommitted_live_path(tmp_path, monkeypatch):
    """The dirty-tree gate must detect a real uncommitted live-path file in a real git repo."""
    import subprocess

    repo = tmp_path / "fake_repo"
    repo.mkdir()
    (repo / "merid" / "event_venues" / "kalshi").mkdir(parents=True)
    live_file = repo / "merid" / "event_venues" / "kalshi" / "order_router.py"
    live_file.write_text("uncommitted change")

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_REPO_ROOT", str(repo))

    from merid.startup_validations import validate_dirty_tree
    with pytest.raises(StartupValidationError, match="uncommitted"):
        validate_dirty_tree()


def test_validate_dirty_tree_passes_real_clean_live_path(tmp_path, monkeypatch):
    """The dirty-tree gate must pass when the live-path files are committed."""
    import subprocess

    repo = tmp_path / "fake_repo"
    repo.mkdir()
    (repo / "merid" / "event_venues" / "kalshi").mkdir(parents=True)
    live_file = repo / "merid" / "event_venues" / "kalshi" / "order_router.py"
    live_file.write_text("committed version")

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_REPO_ROOT", str(repo))

    from merid.startup_validations import validate_dirty_tree
    validate_dirty_tree()


def test_get_repo_root_ignores_process_cwd(monkeypatch, tmp_path):
    """_get_repo_root must discover the repo from the module location, not the cwd."""
    import os
    import subprocess

    monkeypatch.delenv("MERID_REPO_ROOT", raising=False)
    from merid.startup_validations import _get_repo_root

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)  # a non-repo directory; this is the failure mode from the live restart
        root = _get_repo_root()
    finally:
        os.chdir(original_cwd)

    # The real MERID checkout should be discoverable from the module location.
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, check=True, capture_output=True)
    assert (root / ".git").exists()


def test_get_repo_root_uses_env_override(tmp_path, monkeypatch):
    """_get_repo_root must honor MERID_REPO_ROOT when set."""
    import subprocess

    repo = tmp_path / "fake_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    monkeypatch.setenv("MERID_REPO_ROOT", str(repo))
    from merid.startup_validations import _get_repo_root
    assert _get_repo_root() == repo


def test_validate_dirty_tree_fails_closed_for_bad_repo_root(monkeypatch, tmp_path):
    """The dirty-tree gate must fail closed when MERID_REPO_ROOT points to a non-repo."""
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_REPO_ROOT", str(tmp_path))
    from merid.startup_validations import validate_dirty_tree, StartupValidationError
    with pytest.raises(StartupValidationError, match="Could not verify live-path git status"):
        validate_dirty_tree()


# ---------------------------------------------------------------------------
# Direct submission policy
# ---------------------------------------------------------------------------

@pytest.fixture
def _prod_client():
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.kalshi_config import KalshiConfig

    config = KalshiConfig(
        env="prod",
        rest_base_url="https://external-api.kalshi.com/trade-api/v2",
        ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        api_key_id="test_key_12345",
        private_key_path="/path/to/key.pem",
        public_rest_api_url="https://api.kalshi.com/public-api/v2",
        private_key_pem="-----BEGIN RSA PRIVATE KEY-----\nMIICXgIBAAJBAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9\nz9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0CAwEAAQJBAKjM3mLw\nP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F\n9z9F9z9F9z9F9z9F9z9F9z0CIQDP8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9\nF9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0IfwIX\nAAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9\nz9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0=\n-----END RSA PRIVATE KEY-----",
    )
    client = KalshiVenueClient(config)
    client._http_client = AsyncMock()
    client._http_client.is_closed = False
    client._auth_mode = "rsa"
    client._private_key = MagicMock()
    client._private_key.sign.return_value = b"mock_signature"
    yield client


@pytest.mark.asyncio
async def test_direct_place_order_in_prod_rejected_even_with_pytest_current_test(
    _prod_client, monkeypatch
):
    """A direct client.place_order attempt in MERID_ENV=prod is rejected even if
    a PYTEST_CURRENT_TEST artifact is present."""
    from merid.settings import settings
    from merid.event_venues.base import VenueOrder

    monkeypatch.setattr(settings, "MERID_ENV", "prod", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test")
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "false")
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")

    order = VenueOrder(
        market_id="KXBTC15M-001",
        side="sell",
        outcome_id="yes",
        size=Decimal("1"),
        price=Decimal("0.55"),
        order_type="limit",
        client_order_id="unapproved_coid_prod_001",
        reduce_only=True,
    )

    result = await _prod_client.place_order_result(order)
    assert not result.success
    assert "Manual order placement blocked" in (result.error or "") or "firewall" in (result.error or "")
    assert not _prod_client._http_client.request.called


@pytest.mark.asyncio
async def test_direct_place_order_allowed_in_testing_with_explicit_capability(
    _prod_client, monkeypatch
):
    """In MERID_ENV=testing, direct submission is allowed only when the explicit
    test-only capability DEBUG_ALLOW_MANUAL_ORDERS=true is set."""
    from merid.settings import settings
    from merid.event_venues.base import VenueOrder

    monkeypatch.setattr(settings, "MERID_ENV", "testing", raising=False)
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "true")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    response = MagicMock(
        status_code=201,
        json=MagicMock(return_value={"order": {"order_id": "o1", "ticker": "KXBTC15M-001", "status": "resting"}}),
        headers={},
        text="",
    )
    _prod_client._http_client.request = AsyncMock(return_value=response)

    order = VenueOrder(
        market_id="KXBTC15M-001",
        side="buy",
        outcome_id="yes",
        size=Decimal("1"),
        price=Decimal("0.55"),
        order_type="limit",
        client_order_id="test_coid_001",
    )

    result = await _prod_client.place_order_result(order)
    assert result.success
    assert _prod_client._http_client.request.called


# ---------------------------------------------------------------------------
# Hybrid signal audit gate
# ---------------------------------------------------------------------------

def test_hybrid_signal_audit_allows_non_live_without_artifact(monkeypatch):
    """Paper/shadow modes may run signal_mode=hybrid to generate the audit."""
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_TRADE_MODE", "paper")
    monkeypatch.delenv("MERID_ALLOW_LIVE_TRADES", raising=False)

    from types import SimpleNamespace
    from unittest.mock import patch

    with patch(
        "merid.risk.profiles.crypto_15m_profile.get_crypto_15m_profile",
        return_value=SimpleNamespace(signal_mode="hybrid"),
    ):
        validate_hybrid_signal_audit()


def test_hybrid_signal_audit_blocks_live_without_artifact(monkeypatch):
    """Live signal_mode=hybrid without an audit artifact must fail closed."""
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")

    from types import SimpleNamespace
    from unittest.mock import patch

    with patch(
        "merid.risk.profiles.crypto_15m_profile.get_crypto_15m_profile",
        return_value=SimpleNamespace(signal_mode="hybrid"),
    ):
        with pytest.raises(StartupValidationError, match="audit artifact not found"):
            validate_hybrid_signal_audit()


def test_hybrid_signal_audit_blocks_live_expired_artifact(monkeypatch, tmp_path):
    """Live signal_mode=hybrid with an expired audit must fail closed."""
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")

    audit = tmp_path / "expired_audit.json"
    from datetime import datetime, timedelta, timezone
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    audit.write_text(json.dumps({"valid_until": expired}))
    monkeypatch.setenv("MERID_HYBRID_SIGNAL_AUDIT_PATH", str(audit))

    from types import SimpleNamespace
    from unittest.mock import patch

    with patch(
        "merid.risk.profiles.crypto_15m_profile.get_crypto_15m_profile",
        return_value=SimpleNamespace(signal_mode="hybrid"),
    ):
        with pytest.raises(StartupValidationError, match="expired"):
            validate_hybrid_signal_audit()


def test_hybrid_signal_audit_passes_live_with_passing_artifact(monkeypatch, tmp_path):
    """Live signal_mode=hybrid with a passing audit artifact is approved."""
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")

    from datetime import datetime, timedelta, timezone
    valid_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    audit = tmp_path / "passing_audit.json"
    audit.write_text(json.dumps({
        "model_signature": "pre-registered-v1",
        "hold_out_set_size": 500,
        "brier_score": 0.18,
        "brier_baseline": "venue_implied",
        "expected_calibration_error": 0.05,
        "reliability_plot": [
            {"predicted_prob": 0.1, "observed_freq": 0.08, "n_trades": 100},
            {"predicted_prob": 0.5, "observed_freq": 0.52, "n_trades": 100},
            {"predicted_prob": 0.9, "observed_freq": 0.91, "n_trades": 100},
        ],
        "pbo": 0.25,
        "deflated_sharpe_ratio": 0.96,
        "walk_forward_efficiency": 0.35,
        "mean_net_edge_per_bucket_cents": 1.5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "valid_until": valid_until,
        "auditor": "risk-committee",
    }))
    monkeypatch.setenv("MERID_HYBRID_SIGNAL_AUDIT_PATH", str(audit))

    from types import SimpleNamespace
    from unittest.mock import patch

    with patch(
        "merid.risk.profiles.crypto_15m_profile.get_crypto_15m_profile",
        return_value=SimpleNamespace(signal_mode="hybrid"),
    ):
        validate_hybrid_signal_audit()
