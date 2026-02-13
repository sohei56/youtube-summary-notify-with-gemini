"""Configuration loader that aggregates env vars, Secrets Manager, and S3 config."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass

import boto3

from youtube_summary_notify.store.config_store import Config, ConfigError, ConfigStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Secrets:
    """API keys and webhook URLs from Secrets Manager."""

    gemini_api_key: str
    youtube_api_key: str
    webhook_urls: dict[str, str]


@dataclass(frozen=True)
class ApplicationConfig:
    """Unified application configuration from all sources."""

    execution_interval_minutes: int
    deployment_id: str
    secrets: Secrets
    user_config: Config
    lookback_window_minutes: float


class ConfigLoader:
    """Loads and validates configuration from environment variables, Secrets Manager, and S3."""

    def __init__(self) -> None:
        self._config_bucket = self._require_env("CONFIG_BUCKET")
        self._state_table = self._require_env("STATE_TABLE")
        self._secrets_arn = self._require_env("SECRETS_ARN")
        self._deployment_id = self._require_env("DEPLOYMENT_ID")
        self._execution_interval_minutes = int(self._require_env("EXECUTION_INTERVAL_MINUTES"))

    @staticmethod
    def _require_env(name: str) -> str:
        """Read a required environment variable or raise ConfigError."""
        value = os.environ.get(name)
        if not value:
            raise ConfigError(f"Missing required environment variable: {name}")
        return value

    async def load(self) -> ApplicationConfig:
        """Load secrets and user config, validate cross-references, and return unified config."""
        secrets = await self._load_secrets()
        config_store = ConfigStore(s3_bucket=self._config_bucket)
        user_config = await config_store.load_config()

        self._validate_webhook_references(user_config, secrets)

        return ApplicationConfig(
            execution_interval_minutes=self._execution_interval_minutes,
            deployment_id=self._deployment_id,
            secrets=secrets,
            user_config=user_config,
            lookback_window_minutes=self._execution_interval_minutes * 2.0,
        )

    async def _load_secrets(self) -> Secrets:
        """Load and parse secrets from AWS Secrets Manager."""
        client = boto3.client("secretsmanager")

        try:
            response = await asyncio.to_thread(
                client.get_secret_value,
                SecretId=self._secrets_arn,
            )
        except Exception as exc:
            raise ConfigError(f"Failed to load secrets from Secrets Manager: {exc}") from exc

        try:
            data = json.loads(response["SecretString"])
        except (json.JSONDecodeError, KeyError) as exc:
            raise ConfigError(f"Invalid secret format: {exc}") from exc

        for required_key in ("gemini_api_key", "youtube_api_key"):
            if required_key not in data:
                raise ConfigError(f"Missing required secret: '{required_key}'")

        gemini_api_key = data.pop("gemini_api_key")
        youtube_api_key = data.pop("youtube_api_key")
        webhook_urls = {k: v for k, v in data.items()}

        return Secrets(
            gemini_api_key=gemini_api_key,
            youtube_api_key=youtube_api_key,
            webhook_urls=webhook_urls,
        )

    @staticmethod
    def _validate_webhook_references(user_config: Config, secrets: Secrets) -> None:
        """Validate that every notification target's secret_key exists in secrets."""
        for notification in user_config.notifications:
            if notification.secret_key not in secrets.webhook_urls:
                raise ConfigError(
                    f"Notification '{notification.name}' references secret_key "
                    f"'{notification.secret_key}' which is not present in Secrets Manager"
                )

    @property
    def state_table(self) -> str:
        """DynamoDB table name for video state."""
        return self._state_table

    @property
    def deployment_id(self) -> str:
        """Deployment identifier."""
        return self._deployment_id
