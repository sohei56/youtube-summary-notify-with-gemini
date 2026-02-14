"""S3 configuration store for loading and validating config.yaml."""

import asyncio
import logging
from dataclasses import dataclass

import boto3
import yaml

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("slack", "discord")


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass(frozen=True)
class Channel:
    """A YouTube channel to monitor."""

    id: str
    name: str


@dataclass(frozen=True)
class Summarization:
    """Settings for video summarization via Gemini."""

    model: str
    language: str
    prompt_template: str


@dataclass(frozen=True)
class Notification:
    """A notification target configuration."""

    name: str
    platform: str
    secret_key: str
    message_template: str


@dataclass(frozen=True)
class Config:
    """User-editable configuration loaded from config.yaml in S3."""

    channels: list[Channel]
    summarization: Summarization
    notifications: list[Notification]


class ConfigStore:
    """Loads and validates configuration from an S3-hosted config.yaml file."""

    def __init__(self, s3_bucket: str, config_key: str = "config.yaml") -> None:
        self._s3_bucket = s3_bucket
        self._config_key = config_key
        self._s3 = boto3.client("s3")

    async def load_config(self) -> Config:
        """Load config.yaml from S3, parse, validate, and return typed Config."""
        raw = await self._fetch_yaml()
        return self._parse_and_validate(raw)

    async def _fetch_yaml(self) -> dict:
        """Fetch and parse YAML from S3."""
        try:
            response = await asyncio.to_thread(
                self._s3.get_object,
                Bucket=self._s3_bucket,
                Key=self._config_key,
            )
        except self._s3.exceptions.NoSuchKey as exc:
            raise ConfigError(f"Config file not found: s3://{self._s3_bucket}/{self._config_key}") from exc
        except Exception as exc:
            raise ConfigError(f"Failed to read config from S3: {exc}") from exc

        body = await asyncio.to_thread(response["Body"].read)
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in config file: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError("Config file must be a YAML mapping")

        return data

    def _parse_and_validate(self, raw: dict) -> Config:
        """Parse raw YAML dict into validated Config dataclass."""
        for key in ("channels", "summarization", "notifications"):
            if key not in raw:
                raise ConfigError(f"Missing required top-level key: '{key}'")

        channels = self._validate_channels(raw["channels"])
        summarization = self._validate_summarization(raw["summarization"])
        notifications = self._validate_notifications(raw["notifications"])

        return Config(channels=channels, summarization=summarization, notifications=notifications)

    def _validate_channels(self, raw_channels: list) -> list[Channel]:
        """Validate and parse channel entries."""
        if not isinstance(raw_channels, list) or len(raw_channels) == 0:
            raise ConfigError("'channels' must be a non-empty list")

        channels = []
        for i, ch in enumerate(raw_channels):
            if not isinstance(ch, dict):
                raise ConfigError(f"channels[{i}]: must be a mapping")
            for field in ("id", "name"):
                if field not in ch:
                    raise ConfigError(f"channels[{i}]: missing required field '{field}'")

            channel_id = str(ch["id"])
            if not channel_id.startswith("UC") or len(channel_id) != 24:
                raise ConfigError(
                    f"channels[{i}]: invalid channel ID '{channel_id}' (must start with 'UC' and be 24 characters)"
                )

            channels.append(Channel(id=channel_id, name=str(ch["name"])))

        return channels

    def _validate_summarization(self, raw: dict) -> Summarization:
        """Validate and parse summarization settings."""
        if not isinstance(raw, dict):
            raise ConfigError("'summarization' must be a mapping")

        for field in ("model", "language", "prompt_template"):
            if field not in raw:
                raise ConfigError(f"summarization: missing required field '{field}'")

        prompt_template = str(raw["prompt_template"])
        if "{language}" not in prompt_template:
            raise ConfigError("summarization.prompt_template must contain '{language}'")

        return Summarization(
            model=str(raw["model"]),
            language=str(raw["language"]),
            prompt_template=prompt_template,
        )

    def _validate_notifications(self, raw_notifications: list) -> list[Notification]:
        """Validate and parse notification entries."""
        if not isinstance(raw_notifications, list) or len(raw_notifications) == 0:
            raise ConfigError("'notifications' must be a non-empty list")

        notifications = []
        for i, n in enumerate(raw_notifications):
            if not isinstance(n, dict):
                raise ConfigError(f"notifications[{i}]: must be a mapping")
            for field in ("name", "platform", "secret_key", "message_template"):
                if field not in n:
                    raise ConfigError(f"notifications[{i}]: missing required field '{field}'")

            platform = str(n["platform"])
            if platform not in SUPPORTED_PLATFORMS:
                raise ConfigError(
                    f"notifications[{i}]: unsupported platform '{platform}' "
                    f"(supported: {', '.join(SUPPORTED_PLATFORMS)})"
                )

            message_template = str(n["message_template"])
            if "{summary}" not in message_template:
                raise ConfigError(f"notifications[{i}]: message_template must contain '{{summary}}'")

            notifications.append(
                Notification(
                    name=str(n["name"]),
                    platform=platform,
                    secret_key=str(n["secret_key"]),
                    message_template=message_template,
                )
            )

        return notifications
