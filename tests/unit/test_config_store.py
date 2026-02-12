"""Tests for ConfigStore (S3 config loading and validation)."""

import copy

import pytest
import yaml

from tests.conftest import TEST_BUCKET, VALID_CONFIG
from youtube_summary_notify.store.config_store import ConfigError, ConfigStore


@pytest.fixture()
def store(s3_bucket):
    """ConfigStore pointed at the mocked S3 bucket."""
    return ConfigStore(s3_bucket=TEST_BUCKET)


def _put_config(s3_client, config: dict) -> None:
    """Helper to upload a config dict to the mocked S3 bucket."""
    s3_client.put_object(
        Bucket=TEST_BUCKET,
        Key="config.yaml",
        Body=yaml.dump(config).encode(),
    )


class TestLoadConfigHappyPath:
    async def test_returns_correct_channels(self, store):
        config = await store.load_config()
        assert len(config.channels) == 2
        assert config.channels[0].id == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert config.channels[0].name == "Test Channel"

    async def test_returns_correct_summarization(self, store):
        config = await store.load_config()
        assert config.summarization.model == "gemini-2.5-flash"
        assert config.summarization.language == "en"
        assert "{video_url}" in config.summarization.prompt_template
        assert "{language}" in config.summarization.prompt_template

    async def test_returns_correct_notifications(self, store):
        config = await store.load_config()
        assert len(config.notifications) == 1
        n = config.notifications[0]
        assert n.name == "team-updates"
        assert n.platform == "slack"
        assert n.secret_key == "slack_webhook_team"
        assert "{summary}" in n.message_template


class TestLoadConfigS3Errors:
    async def test_missing_file_raises_config_error(self, s3_bucket):
        store = ConfigStore(s3_bucket=TEST_BUCKET, config_key="nonexistent.yaml")
        with pytest.raises(ConfigError, match="Config file not found"):
            await store.load_config()

    async def test_invalid_yaml_raises_config_error(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=TEST_BUCKET,
            Key="config.yaml",
            Body=b"{{invalid: yaml: [",
        )
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="Invalid YAML"):
            await store.load_config()


class TestLoadConfigValidation:
    async def test_missing_channels_key(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        del cfg["channels"]
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="Missing required top-level key: 'channels'"):
            await store.load_config()

    async def test_missing_summarization_key(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        del cfg["summarization"]
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="Missing required top-level key: 'summarization'"):
            await store.load_config()

    async def test_missing_notifications_key(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        del cfg["notifications"]
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="Missing required top-level key: 'notifications'"):
            await store.load_config()

    async def test_invalid_channel_id_wrong_prefix(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["channels"] = [{"id": "XXxxxxxxxxxxxxxxxxxxxxxx", "name": "Bad"}]
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="invalid channel ID"):
            await store.load_config()

    async def test_invalid_channel_id_wrong_length(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["channels"] = [{"id": "UCshort", "name": "Bad"}]
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="invalid channel ID"):
            await store.load_config()

    async def test_prompt_template_missing_video_url(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["summarization"]["prompt_template"] = "Summarize in {language}"
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="\\{video_url\\}"):
            await store.load_config()

    async def test_prompt_template_missing_language(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["summarization"]["prompt_template"] = "Summarize {video_url}"
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="\\{language\\}"):
            await store.load_config()

    async def test_message_template_missing_summary(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["notifications"][0]["message_template"] = "No summary here"
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="\\{summary\\}"):
            await store.load_config()

    async def test_invalid_platform(self, s3_bucket):
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["notifications"][0]["platform"] = "telegram"
        _put_config(s3_bucket, cfg)
        store = ConfigStore(s3_bucket=TEST_BUCKET)
        with pytest.raises(ConfigError, match="unsupported platform 'telegram'"):
            await store.load_config()
