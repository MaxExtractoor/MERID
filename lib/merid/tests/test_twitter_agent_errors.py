import pytest
from unittest.mock import MagicMock

from twitter_agent import MERIDTwitterAgent
from merid_core import ExternalServiceError


def test_twitter_agent_handles_errors(monkeypatch):
    class BadClient:
        def search_recent_tweets(self, **kwargs):
            raise RuntimeError("api fail")

    monkeypatch.setenv("X_BEARER_TOKEN", "t")
    # inject bad client into instance
    inst = MERIDTwitterAgent()
    inst.client = BadClient()

    with pytest.raises(ExternalServiceError):
        inst.get_market_sentiment("bitcoin")
