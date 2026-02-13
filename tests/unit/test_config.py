"""Tests for ConfigLoader (unified configuration aggregation)."""

import json
import os

import pytest

from tests.conftest import (
    TEST_BUCKET,
    TEST_DEPLOYMENT_ID,
    TEST_SECRETS_ARN,
    TEST_TABLE,
)
from youtube_summary_notify.config import ConfigLoader
from youtube_summary_notify.store.config_store import ConfigError


@pytest.fixture()
def env_vars():
    """Set required environment variables for ConfigLoader."""
    os.environ["CONFIG_BUCKET"] = TEST_BUCKET
    os.environ["STATE_TABLE"] = TEST_TABLE
    os.environ["SECRETS_ARN"] = TEST_SECRETS_ARN
    os.environ["DEPLOYMENT_ID"] = TEST_DEPLOYMENT_ID
    os.environ["EXECUTION_INTERVAL_MINUTES"] = "60"
    yield
    for key in ("CONFIG_BUCKET", "STATE_TABLE", "SECRETS_ARN", "DEPLOYMENT_ID", "EXECUTION_INTERVAL_MINUTES"):
        os.environ.pop(key, None)


class TestHappyPath:
    async def test_load_returns_application_config(self, all_aws, env_vars):
        """Loads all config sections into a unified ApplicationConfig."""
        loader = ConfigLoader()
        app_config = await loader.load()

        assert app_config.execution_interval_minutes == 60
        assert app_config.deployment_id == TEST_DEPLOYMENT_ID
        assert app_config.secrets.gemini_api_key == "test-gemini-key"
        assert app_config.secrets.youtube_api_key == "test-youtube-key"
        assert "slack_webhook_team" in app_config.secrets.webhook_urls
        assert len(app_config.user_config.channels) == 2
        assert app_config.user_config.summarization.model == "gemini-2.5-flash"

    async def test_lookback_window_is_double_interval(self, all_aws, env_vars):
        """Lookback window defaults to 2x the execution interval."""
        loader = ConfigLoader()
        app_config = await loader.load()
        assert app_config.lookback_window_minutes == 120.0

    async def test_lookback_window_with_custom_interval(self, all_aws, env_vars):
        """Lookback window scales with a custom interval (30min -> 60min)."""
        os.environ["EXECUTION_INTERVAL_MINUTES"] = "30"
        loader = ConfigLoader()
        app_config = await loader.load()
        assert app_config.lookback_window_minutes == 60.0

    async def test_state_table_property(self, all_aws, env_vars):
        """Exposes the DynamoDB table name from environment."""
        loader = ConfigLoader()
        assert loader.state_table == TEST_TABLE

    async def test_deployment_id_property(self, all_aws, env_vars):
        """Exposes the deployment ID from environment."""
        loader = ConfigLoader()
        assert loader.deployment_id == TEST_DEPLOYMENT_ID


class TestMissingEnvVars:
    def test_missing_config_bucket(self, env_vars):
        """Raises ConfigError when CONFIG_BUCKET is not set."""
        os.environ.pop("CONFIG_BUCKET")
        with pytest.raises(ConfigError, match="CONFIG_BUCKET"):
            ConfigLoader()

    def test_missing_state_table(self, env_vars):
        """Raises ConfigError when STATE_TABLE is not set."""
        os.environ.pop("STATE_TABLE")
        with pytest.raises(ConfigError, match="STATE_TABLE"):
            ConfigLoader()

    def test_missing_secrets_arn(self, env_vars):
        """Raises ConfigError when SECRETS_ARN is not set."""
        os.environ.pop("SECRETS_ARN")
        with pytest.raises(ConfigError, match="SECRETS_ARN"):
            ConfigLoader()

    def test_missing_deployment_id(self, env_vars):
        """Raises ConfigError when DEPLOYMENT_ID is not set."""
        os.environ.pop("DEPLOYMENT_ID")
        with pytest.raises(ConfigError, match="DEPLOYMENT_ID"):
            ConfigLoader()

    def test_missing_execution_interval(self, env_vars):
        """Raises ConfigError when EXECUTION_INTERVAL_MINUTES is not set."""
        os.environ.pop("EXECUTION_INTERVAL_MINUTES")
        with pytest.raises(ConfigError, match="EXECUTION_INTERVAL_MINUTES"):
            ConfigLoader()


class TestSecretsErrors:
    async def test_missing_gemini_api_key(self, all_aws, env_vars):
        """Raises ConfigError when gemini_api_key is absent from secrets."""
        # Re-create secret without gemini_api_key
        sm = all_aws["secretsmanager"]
        sm.delete_secret(SecretId=TEST_SECRETS_ARN, ForceDeleteWithoutRecovery=True)
        incomplete_secrets = {"youtube_api_key": "test-key"}
        sm.create_secret(Name=TEST_SECRETS_ARN, SecretString=json.dumps(incomplete_secrets))

        loader = ConfigLoader()
        with pytest.raises(ConfigError, match="gemini_api_key"):
            await loader.load()

    async def test_missing_youtube_api_key(self, all_aws, env_vars):
        """Raises ConfigError when youtube_api_key is absent from secrets."""
        sm = all_aws["secretsmanager"]
        sm.delete_secret(SecretId=TEST_SECRETS_ARN, ForceDeleteWithoutRecovery=True)
        incomplete_secrets = {"gemini_api_key": "test-key"}
        sm.create_secret(Name=TEST_SECRETS_ARN, SecretString=json.dumps(incomplete_secrets))

        loader = ConfigLoader()
        with pytest.raises(ConfigError, match="youtube_api_key"):
            await loader.load()


class TestWebhookCrossValidation:
    async def test_missing_webhook_secret_key(self, all_aws, env_vars):
        """Raises ConfigError when a notification's secret_key has no matching secret."""
        # Config references 'slack_webhook_team' but secrets only has API keys
        sm = all_aws["secretsmanager"]
        sm.delete_secret(SecretId=TEST_SECRETS_ARN, ForceDeleteWithoutRecovery=True)
        secrets_without_webhook = {
            "gemini_api_key": "test-key",
            "youtube_api_key": "test-key",
        }
        sm.create_secret(Name=TEST_SECRETS_ARN, SecretString=json.dumps(secrets_without_webhook))

        loader = ConfigLoader()
        with pytest.raises(ConfigError, match="slack_webhook_team"):
            await loader.load()
