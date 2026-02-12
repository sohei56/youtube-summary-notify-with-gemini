"""E2E tests: real code paths with moto AWS and httpx.MockTransport."""

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import yaml
from moto import mock_aws

from tests.conftest import (
    TEST_BUCKET,
    TEST_DEPLOYMENT_ID,
    TEST_SECRETS_ARN,
    TEST_TABLE,
    VALID_CONFIG,
    VALID_SECRETS,
)
from youtube_summary_notify.main import run
from youtube_summary_notify.summarizer import SummarizerError, SummaryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_env(monkeypatch):
    """Set all required environment variables for ConfigLoader."""
    monkeypatch.setenv("CONFIG_BUCKET", TEST_BUCKET)
    monkeypatch.setenv("STATE_TABLE", TEST_TABLE)
    monkeypatch.setenv("SECRETS_ARN", TEST_SECRETS_ARN)
    monkeypatch.setenv("DEPLOYMENT_ID", TEST_DEPLOYMENT_ID)
    monkeypatch.setenv("EXECUTION_INTERVAL_MINUTES", "60")


def _recent_timestamp():
    """Return an ISO 8601 timestamp 30 minutes ago (within lookback window)."""
    ts = datetime.now(timezone.utc).timestamp() - 30 * 60
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_youtube_item(video_id, title, published_at):
    """Build a YouTube playlistItems.list response item."""
    return {
        "snippet": {
            "resourceId": {"videoId": video_id},
            "title": title,
            "publishedAt": published_at,
        }
    }


def _make_http_transport(youtube_items_by_playlist, slack_status=200):
    """Create an httpx.MockTransport routing YouTube and Slack requests.

    Args:
        youtube_items_by_playlist: dict mapping playlistId → list of item dicts.
        slack_status: HTTP status code for Slack webhook responses.

    Returns:
        An httpx.MockTransport with a ``captured_slack`` list of (url, body) tuples.
    """
    captured_slack = []

    def _handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        # YouTube playlistItems endpoint
        if "googleapis.com/youtube/v3/playlistItems" in url_str:
            parsed = urlparse(url_str)
            qs = parse_qs(parsed.query)
            playlist_id = qs.get("playlistId", [""])[0]
            items = youtube_items_by_playlist.get(playlist_id, [])
            return httpx.Response(200, json={"items": items})

        # Slack webhook
        if "hooks.slack.com" in url_str:
            body = json.loads(request.content)
            captured_slack.append((url_str, body))
            if slack_status >= 400:
                return httpx.Response(slack_status, text="error")
            return httpx.Response(slack_status, text="ok")

        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(_handler)
    transport.captured_slack = captured_slack  # type: ignore[attr-defined]
    return transport


def _make_mock_summarizer(side_effect=None):
    """Patch youtube_summary_notify.main.Summarizer and configure summarize method.

    Args:
        side_effect: A callable(video_id, title, url, channel_name, published_at,
                     prompt_template, language) or list of return/exception values.

    Returns:
        The patcher context manager.
    """
    if side_effect is None:

        async def _default_side_effect(**kwargs):
            return SummaryResult(
                video_id=kwargs["video_id"],
                title=kwargs["title"],
                url=kwargs["url"],
                channel_name=kwargs["channel_name"],
                published_at=kwargs["published_at"],
                summary=f"Summary of {kwargs['title']}",
            )

        side_effect = _default_side_effect

    patcher = patch("youtube_summary_notify.main.Summarizer")
    return patcher, side_effect


def _dynamo_video_ids(table, deployment_id=TEST_DEPLOYMENT_ID):
    """Query all video_ids from DynamoDB for the given deployment."""
    import boto3 as _boto3

    resp = table.query(
        KeyConditionExpression=_boto3.dynamodb.conditions.Key("deployment_id").eq(deployment_id),
    )
    return {item["video_id"] for item in resp["Items"]}


def _setup_aws(s3_client, dynamodb_resource, sm_client, config=None, secrets=None):
    """Provision S3 bucket, DynamoDB table, and Secrets Manager secret."""
    # S3
    s3_client.create_bucket(Bucket=TEST_BUCKET)
    s3_client.put_object(
        Bucket=TEST_BUCKET,
        Key="config.yaml",
        Body=yaml.dump(config or VALID_CONFIG).encode(),
    )
    # DynamoDB
    table = dynamodb_resource.create_table(
        TableName=TEST_TABLE,
        KeySchema=[
            {"AttributeName": "deployment_id", "KeyType": "HASH"},
            {"AttributeName": "video_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "deployment_id", "AttributeType": "S"},
            {"AttributeName": "video_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    # Secrets Manager
    sm_client.create_secret(
        Name=TEST_SECRETS_ARN,
        SecretString=json.dumps(secrets or VALID_SECRETS),
    )
    return table


# Channel IDs matching VALID_CONFIG
CHANNEL_A_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"
CHANNEL_A_PLAYLIST = "UUxxxxxxxxxxxxxxxxxxxxxx"


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_end_to_end_detect_summarize_notify_update(self, aws_credentials, monkeypatch):
        """Full pipeline: 2 new videos → summarized → notified → state updated."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # Slack received 2 summary notifications
            assert len(transport.captured_slack) == 2
            texts = [body["text"] for _, body in transport.captured_slack]
            assert any("Video One" in t for t in texts)
            assert any("Video Two" in t for t in texts)

            # DynamoDB has 2 entries
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1", "vid_2"}

    async def test_second_execution_skips_already_notified(self, aws_credentials, monkeypatch):
        """Second run with same videos should not re-summarize or re-notify."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                mock_summarize = AsyncMock(side_effect=side_effect)
                MockSummarizer.return_value.summarize = mock_summarize

                # Run 1
                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

                assert len(transport.captured_slack) == 2
                assert mock_summarize.call_count == 2

                # Reset captures for run 2
                transport.captured_slack.clear()
                mock_summarize.reset_mock()

                # Run 2 — same videos
                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

                # No new summarizations or notifications
                assert mock_summarize.call_count == 0
                assert len(transport.captured_slack) == 0

            # DynamoDB still has exactly 2 entries
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1", "vid_2"}

    async def test_multiple_notification_targets(self, aws_credentials, monkeypatch):
        """Two notification targets should both receive the same summary."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()

        config = {
            **VALID_CONFIG,
            "notifications": [
                {
                    "name": "team-a",
                    "platform": "slack",
                    "secret_key": "slack_webhook_team_a",
                    "message_template": "*{title}*\n{summary}\n{url}",
                },
                {
                    "name": "team-b",
                    "platform": "slack",
                    "secret_key": "slack_webhook_team_b",
                    "message_template": "*{title}*\n{summary}\n{url}",
                },
            ],
        }
        secrets = {
            **VALID_SECRETS,
            "slack_webhook_team_a": "https://hooks.slack.com/services/T00/A00/aaa",
            "slack_webhook_team_b": "https://hooks.slack.com/services/T00/B00/bbb",
        }

        yt_items = {CHANNEL_A_PLAYLIST: [_make_youtube_item("vid_1", "Video One", ts)]}
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
                config=config,
                secrets=secrets,
            )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # 2 Slack POST requests (one per target)
            assert len(transport.captured_slack) == 2
            urls = {url for url, _ in transport.captured_slack}
            assert "https://hooks.slack.com/services/T00/A00/aaa" in urls
            assert "https://hooks.slack.com/services/T00/B00/bbb" in urls
            # Both contain the same video
            for _, body in transport.captured_slack:
                assert "Video One" in body["text"]


class TestNoNewVideos:
    async def test_all_videos_already_in_state(self, aws_credentials, monkeypatch):
        """Videos already in DynamoDB are skipped entirely."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            # Pre-populate DynamoDB with the same video IDs
            now = Decimal(str(time.time()))
            with table.batch_writer() as batch:
                for vid_id in ("vid_1", "vid_2"):
                    batch.put_item(
                        Item={
                            "deployment_id": TEST_DEPLOYMENT_ID,
                            "video_id": vid_id,
                            "notified_at": now,
                        }
                    )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                mock_summarize = AsyncMock(side_effect=side_effect)
                MockSummarizer.return_value.summarize = mock_summarize

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

                # Summarizer never called
                assert mock_summarize.call_count == 0

            # No Slack notifications
            assert len(transport.captured_slack) == 0

            # DynamoDB unchanged
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1", "vid_2"}


class TestConfigFailure:
    async def test_missing_s3_config_aborts(self, aws_credentials, monkeypatch):
        """Pipeline aborts when config.yaml is missing from S3."""
        _set_env(monkeypatch)
        transport = _make_http_transport({})

        with mock_aws():
            import boto3

            # Create S3 bucket but do NOT upload config.yaml
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=TEST_BUCKET)

            # DynamoDB table
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName=TEST_TABLE,
                KeySchema=[
                    {"AttributeName": "deployment_id", "KeyType": "HASH"},
                    {"AttributeName": "video_id", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "deployment_id", "AttributeType": "S"},
                    {"AttributeName": "video_id", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            # Secrets Manager
            sm = boto3.client("secretsmanager", region_name="us-east-1")
            sm.create_secret(
                Name=TEST_SECRETS_ARN,
                SecretString=json.dumps(VALID_SECRETS),
            )

            async with httpx.AsyncClient(transport=transport) as client:
                await run(http_client=client)

            # No YouTube or Slack calls made
            assert len(transport.captured_slack) == 0

    async def test_missing_secret_key_aborts(self, aws_credentials, monkeypatch):
        """Pipeline aborts when a required webhook secret_key is missing."""
        _set_env(monkeypatch)

        # Secrets without the webhook URL referenced by config
        secrets_without_webhook = {
            "gemini_api_key": "test-gemini-key",
            "youtube_api_key": "test-youtube-key",
            # Missing: slack_webhook_team
        }
        transport = _make_http_transport({})

        with mock_aws():
            import boto3

            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=TEST_BUCKET)
            s3.put_object(
                Bucket=TEST_BUCKET,
                Key="config.yaml",
                Body=yaml.dump(VALID_CONFIG).encode(),
            )

            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName=TEST_TABLE,
                KeySchema=[
                    {"AttributeName": "deployment_id", "KeyType": "HASH"},
                    {"AttributeName": "video_id", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "deployment_id", "AttributeType": "S"},
                    {"AttributeName": "video_id", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            sm = boto3.client("secretsmanager", region_name="us-east-1")
            sm.create_secret(
                Name=TEST_SECRETS_ARN,
                SecretString=json.dumps(secrets_without_webhook),
            )

            async with httpx.AsyncClient(transport=transport) as client:
                await run(http_client=client)

            # No YouTube/Slack calls
            assert len(transport.captured_slack) == 0


class TestSummarizationFailure:
    async def test_partial_failure_notifies_error_and_updates_state_selectively(self, aws_credentials, monkeypatch):
        """Partial summarization failure: successes notified + state written, error sent for failures."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
                _make_youtube_item("vid_3", "Video Three", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        async def _partial_side_effect(**kwargs):
            if kwargs["video_id"] == "vid_2":
                raise SummarizerError("Gemini timeout")
            return SummaryResult(
                video_id=kwargs["video_id"],
                title=kwargs["title"],
                url=kwargs["url"],
                channel_name=kwargs["channel_name"],
                published_at=kwargs["published_at"],
                summary=f"Summary of {kwargs['title']}",
            )

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher = patch("youtube_summary_notify.main.Summarizer")
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=_partial_side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # 2 summary notifications + 1 error notification = 3 Slack calls
            assert len(transport.captured_slack) == 3

            # Find the error notification
            error_msgs = [body["text"] for _, body in transport.captured_slack if "failed" in body["text"].lower()]
            assert len(error_msgs) == 1
            assert "2 succeeded" in error_msgs[0]
            assert "1 failed" in error_msgs[0]
            assert "Video Two" in error_msgs[0]

            # DynamoDB contains only successes
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1", "vid_3"}

    async def test_all_fail_sends_error_no_state_written(self, aws_credentials, monkeypatch):
        """All summarizations fail → error notification sent, no state written."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher = patch("youtube_summary_notify.main.Summarizer")
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=SummarizerError("fail"))

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # 1 error notification (no summaries)
            assert len(transport.captured_slack) == 1
            error_text = transport.captured_slack[0][1]["text"]
            assert "0 succeeded" in error_text
            assert "2 failed" in error_text

            # DynamoDB empty
            ids = _dynamo_video_ids(table)
            assert ids == set()

    async def test_failed_videos_retried_on_next_execution(self, aws_credentials, monkeypatch):
        """Failed videos are not in state and get retried on next execution."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [
                _make_youtube_item("vid_1", "Video One", ts),
                _make_youtube_item("vid_2", "Video Two", ts),
            ],
        }
        transport = _make_http_transport(yt_items)

        call_count_by_vid = {"vid_1": 0, "vid_2": 0}

        async def _run1_side_effect(**kwargs):
            vid = kwargs["video_id"]
            call_count_by_vid[vid] += 1
            if vid == "vid_2":
                raise SummarizerError("fail")
            return SummaryResult(
                video_id=vid,
                title=kwargs["title"],
                url=kwargs["url"],
                channel_name=kwargs["channel_name"],
                published_at=kwargs["published_at"],
                summary=f"Summary of {kwargs['title']}",
            )

        async def _run2_side_effect(**kwargs):
            vid = kwargs["video_id"]
            call_count_by_vid[vid] += 1
            return SummaryResult(
                video_id=vid,
                title=kwargs["title"],
                url=kwargs["url"],
                channel_name=kwargs["channel_name"],
                published_at=kwargs["published_at"],
                summary=f"Summary of {kwargs['title']}",
            )

        with mock_aws():
            import boto3

            _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher = patch("youtube_summary_notify.main.Summarizer")
            with patcher as MockSummarizer:
                # Run 1: vid_2 fails
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=_run1_side_effect)
                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

                # Run 2: vid_2 retried
                transport.captured_slack.clear()
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=_run2_side_effect)
                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # vid_1 called once (run 1), vid_2 called twice (run 1 fail + run 2 retry)
            assert call_count_by_vid["vid_1"] == 1
            assert call_count_by_vid["vid_2"] == 2


class TestYouTubeFailure:
    async def test_channel_failure_skipped_others_continue(self, aws_credentials, monkeypatch):
        """One channel fails (403), other channel still processes successfully."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()

        # Config with 2 channels
        config = {
            **VALID_CONFIG,
            "channels": [
                {"id": "UCxxxxxxxxxxxxxxxxxxxxxx", "name": "Good Channel"},
                {"id": "UCyyyyyyyyyyyyyyyyyyyyyy", "name": "Bad Channel"},
            ],
        }
        bad_playlist = "UUyyyyyyyyyyyyyyyyyyyyyy"

        captured_slack = []

        def _handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)

            if "googleapis.com/youtube/v3/playlistItems" in url_str:
                parsed = urlparse(url_str)
                qs = parse_qs(parsed.query)
                playlist_id = qs.get("playlistId", [""])[0]
                if playlist_id == bad_playlist:
                    return httpx.Response(403, json={"error": {"message": "Forbidden"}})
                items = [
                    _make_youtube_item("vid_1", "Video One", ts),
                    _make_youtube_item("vid_2", "Video Two", ts),
                ]
                return httpx.Response(200, json={"items": items})

            if "hooks.slack.com" in url_str:
                body = json.loads(request.content)
                captured_slack.append((url_str, body))
                return httpx.Response(200, text="ok")

            return httpx.Response(404, text="not found")

        transport = httpx.MockTransport(_handler)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
                config=config,
            )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # 2 videos from the good channel
            assert len(captured_slack) == 2
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1", "vid_2"}


class TestNotificationFailure:
    async def test_webhook_failure_does_not_block_state_update(self, aws_credentials, monkeypatch):
        """Slack returns 500 but DynamoDB state is still updated."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {CHANNEL_A_PLAYLIST: [_make_youtube_item("vid_1", "Video One", ts)]}
        transport = _make_http_transport(yt_items, slack_status=500)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # DynamoDB still updated
            ids = _dynamo_video_ids(table)
            assert ids == {"vid_1"}


class TestStateBehavior:
    async def test_500_entry_limit_enforced(self, aws_credentials, monkeypatch):
        """DynamoDB is cleaned to 500 entries when exceeding the limit."""
        _set_env(monkeypatch)
        ts = _recent_timestamp()
        yt_items = {
            CHANNEL_A_PLAYLIST: [_make_youtube_item(f"new_{i}", f"New Video {i}", ts) for i in range(5)],
        }
        transport = _make_http_transport(yt_items)

        with mock_aws():
            import boto3

            table = _setup_aws(
                boto3.client("s3", region_name="us-east-1"),
                boto3.resource("dynamodb", region_name="us-east-1"),
                boto3.client("secretsmanager", region_name="us-east-1"),
            )

            # Pre-populate with 498 old entries (timestamps in the past)
            base_time = time.time() - 86400  # 24 hours ago
            with table.batch_writer() as batch:
                for i in range(498):
                    batch.put_item(
                        Item={
                            "deployment_id": TEST_DEPLOYMENT_ID,
                            "video_id": f"old_{i:04d}",
                            "notified_at": Decimal(str(base_time + i)),
                        }
                    )

            patcher, side_effect = _make_mock_summarizer()
            with patcher as MockSummarizer:
                MockSummarizer.return_value.summarize = AsyncMock(side_effect=side_effect)

                async with httpx.AsyncClient(transport=transport) as client:
                    await run(http_client=client)

            # Total should be 500 (498 + 5 = 503, cleaned to 500)
            ids = _dynamo_video_ids(table)
            assert len(ids) == 500

            # All 5 new entries present
            for i in range(5):
                assert f"new_{i}" in ids

            # 3 oldest entries deleted (old_0000, old_0001, old_0002)
            assert "old_0000" not in ids
            assert "old_0001" not in ids
            assert "old_0002" not in ids

            # Remaining old entries still present
            assert "old_0003" in ids
            assert "old_0497" in ids
