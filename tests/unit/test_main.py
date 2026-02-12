"""Tests for main.py orchestration logic."""

from unittest.mock import AsyncMock, MagicMock, patch

from youtube_summary_notify.config import ApplicationConfig, Secrets
from youtube_summary_notify.main import (
    FailedVideo,
    _build_error_message,
    _build_notifiers,
    _detect_new_videos,
    _summarize_videos,
    run,
)
from youtube_summary_notify.notifiers.base import VideoInfo
from youtube_summary_notify.store.config_store import (
    Channel,
    Config,
    ConfigError,
    Notification,
    Summarization,
)
from youtube_summary_notify.summarizer import SummarizerError, SummaryResult
from youtube_summary_notify.youtube_client import Video, YouTubeClientError

# --- Fixtures / helpers ---


def _make_config(
    channels: list[Channel] | None = None,
    notifications: list[Notification] | None = None,
) -> Config:
    return Config(
        channels=channels
        or [
            Channel(id="UCxxxxxxxxxxxxxxxxxxxxxx", name="Channel A"),
        ],
        summarization=Summarization(
            model="gemini-2.5-flash",
            language="en",
            prompt_template="Summarize in {language}: {video_url}",
        ),
        notifications=notifications
        or [
            Notification(
                name="team-slack",
                platform="slack",
                secret_key="slack_webhook_team",
                message_template="*{title}*\n{summary}",
            ),
        ],
    )


def _make_secrets(webhook_urls: dict[str, str] | None = None) -> Secrets:
    return Secrets(
        gemini_api_key="test-gemini-key",
        youtube_api_key="test-youtube-key",
        webhook_urls=webhook_urls or {"slack_webhook_team": "https://hooks.slack.com/services/T/B/x"},
    )


def _make_app_config(
    config: Config | None = None,
    secrets: Secrets | None = None,
    execution_interval_minutes: int = 60,
) -> ApplicationConfig:
    return ApplicationConfig(
        execution_interval_minutes=execution_interval_minutes,
        deployment_id="test-deployment",
        secrets=secrets or _make_secrets(),
        user_config=config or _make_config(),
        lookback_window_minutes=execution_interval_minutes * 2.0,
    )


def _make_video(video_id: str = "vid_1", title: str = "Test Video") -> Video:
    return Video(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel_name="Channel A",
        published_at="2026-02-12T10:00:00Z",
    )


def _make_summary_result(video_id: str = "vid_1", title: str = "Test Video") -> SummaryResult:
    return SummaryResult(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel_name="Channel A",
        published_at="2026-02-12T10:00:00Z",
        summary="A great summary.",
    )


def _make_mock_loader(app_config: ApplicationConfig | None = None) -> MagicMock:
    loader = MagicMock()
    loader.load = AsyncMock(return_value=app_config or _make_app_config())
    loader.state_table = "test-table"
    loader.deployment_id = "test-deployment"
    return loader


# --- Tests ---


class TestBuildNotifiers:
    def test_creates_slack_notifier(self):
        app_config = _make_app_config()
        notifiers = _build_notifiers(app_config)
        assert len(notifiers) == 1
        assert notifiers[0].name == "team-slack"

    def test_creates_multiple_notifiers(self):
        config = _make_config(
            notifications=[
                Notification(
                    name="n1", platform="slack", secret_key="slack_webhook_team", message_template="{summary}"
                ),
                Notification(name="n2", platform="slack", secret_key="slack_webhook_2", message_template="{summary}"),
            ]
        )
        secrets = _make_secrets(
            webhook_urls={
                "slack_webhook_team": "https://hooks.slack.com/1",
                "slack_webhook_2": "https://hooks.slack.com/2",
            }
        )
        app_config = _make_app_config(config=config, secrets=secrets)
        notifiers = _build_notifiers(app_config)
        assert len(notifiers) == 2
        assert {n.name for n in notifiers} == {"n1", "n2"}


class TestDetectNewVideos:
    async def test_returns_new_videos_only(self):
        yt_client = MagicMock()
        yt_client.fetch_recent_videos = AsyncMock(
            return_value=[_make_video("vid_1"), _make_video("vid_2"), _make_video("vid_3")]
        )
        state_store = MagicMock()
        state_store.get_notified_ids = AsyncMock(return_value={"vid_1"})

        app_config = _make_app_config()
        videos = await _detect_new_videos(yt_client, app_config, state_store)

        assert len(videos) == 2
        assert {v.video_id for v in videos} == {"vid_2", "vid_3"}

    async def test_returns_empty_when_all_notified(self):
        yt_client = MagicMock()
        yt_client.fetch_recent_videos = AsyncMock(return_value=[_make_video("vid_1")])
        state_store = MagicMock()
        state_store.get_notified_ids = AsyncMock(return_value={"vid_1"})

        app_config = _make_app_config()
        videos = await _detect_new_videos(yt_client, app_config, state_store)
        assert videos == []

    async def test_returns_empty_when_no_recent_videos(self):
        yt_client = MagicMock()
        yt_client.fetch_recent_videos = AsyncMock(return_value=[])
        state_store = MagicMock()
        state_store.get_notified_ids = AsyncMock(return_value=set())

        app_config = _make_app_config()
        videos = await _detect_new_videos(yt_client, app_config, state_store)
        assert videos == []

    async def test_channel_error_skipped_others_continue(self):
        """If one channel fails, other channels still return videos."""
        config = _make_config(
            channels=[
                Channel(id="UCxxxxxxxxxxxxxxxxxxxxxx", name="Good Channel"),
                Channel(id="UCyyyyyyyyyyyyyyyyyyyyyy", name="Bad Channel"),
            ]
        )
        app_config = _make_app_config(config=config)

        yt_client = MagicMock()

        async def _fetch(channel_id: str, channel_name: str, lookback: float) -> list[Video]:
            if channel_id == "UCyyyyyyyyyyyyyyyyyyyyyy":
                raise YouTubeClientError("API error")
            return [_make_video("vid_1")]

        yt_client.fetch_recent_videos = AsyncMock(side_effect=_fetch)
        state_store = MagicMock()
        state_store.get_notified_ids = AsyncMock(return_value=set())

        videos = await _detect_new_videos(yt_client, app_config, state_store)
        assert len(videos) == 1
        assert videos[0].video_id == "vid_1"

    async def test_fetches_all_channels_concurrently(self):
        config = _make_config(
            channels=[
                Channel(id="UCaaaaaaaaaaaaaaaaaaaaa1", name="Ch1"),
                Channel(id="UCbbbbbbbbbbbbbbbbbbbbb2", name="Ch2"),
            ]
        )
        app_config = _make_app_config(config=config)

        yt_client = MagicMock()
        yt_client.fetch_recent_videos = AsyncMock(return_value=[])
        state_store = MagicMock()
        state_store.get_notified_ids = AsyncMock(return_value=set())

        await _detect_new_videos(yt_client, app_config, state_store)
        assert yt_client.fetch_recent_videos.call_count == 2


class TestSummarizeVideos:
    async def test_all_succeed(self):
        summarizer = MagicMock()
        summarizer.summarize = AsyncMock(side_effect=[_make_summary_result("v1"), _make_summary_result("v2")])

        videos = [_make_video("v1"), _make_video("v2")]
        app_config = _make_app_config()
        successes, failures = await _summarize_videos(summarizer, videos, app_config)

        assert len(successes) == 2
        assert len(failures) == 0

    async def test_partial_failure(self):
        summarizer = MagicMock()
        summarizer.summarize = AsyncMock(
            side_effect=[
                _make_summary_result("v1"),
                SummarizerError("Gemini error"),
            ]
        )

        videos = [_make_video("v1"), _make_video("v2", title="Failed Video")]
        app_config = _make_app_config()
        successes, failures = await _summarize_videos(summarizer, videos, app_config)

        assert len(successes) == 1
        assert successes[0].video_id == "v1"
        assert len(failures) == 1
        assert failures[0].title == "Failed Video"
        assert "Gemini error" in failures[0].error

    async def test_all_fail(self):
        summarizer = MagicMock()
        summarizer.summarize = AsyncMock(side_effect=SummarizerError("fail"))

        videos = [_make_video("v1"), _make_video("v2")]
        app_config = _make_app_config()
        successes, failures = await _summarize_videos(summarizer, videos, app_config)

        assert len(successes) == 0
        assert len(failures) == 2

    async def test_passes_prompt_and_language(self):
        summarizer = MagicMock()
        summarizer.summarize = AsyncMock(return_value=_make_summary_result("v1"))

        videos = [_make_video("v1")]
        app_config = _make_app_config()
        await _summarize_videos(summarizer, videos, app_config)

        call_kwargs = summarizer.summarize.call_args.kwargs
        assert call_kwargs["prompt_template"] == "Summarize in {language}: {video_url}"
        assert call_kwargs["language"] == "en"


class TestBuildErrorMessage:
    def test_includes_counts(self):
        successes = [_make_summary_result("v1")]
        failures = [FailedVideo(title="Bad Video", url="https://yt/bad", error="API error")]
        msg = _build_error_message(successes, failures)
        assert "1 succeeded" in msg
        assert "1 failed" in msg

    def test_includes_failed_video_details(self):
        failures = [
            FailedVideo(title="Video A", url="https://yt/a", error="Rate limited"),
            FailedVideo(title="Video B", url="https://yt/b", error="Timeout"),
        ]
        msg = _build_error_message([], failures)
        assert "Video A" in msg
        assert "https://yt/a" in msg
        assert "Rate limited" in msg
        assert "Video B" in msg
        assert "Timeout" in msg


class TestRunFullPipeline:
    async def test_happy_path_end_to_end(self):
        """Full pipeline: 1 new video → summarized → notified → state updated."""
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)
        notifier = MagicMock()
        notifier.send_summary = AsyncMock(return_value=True)
        notifier.send_error = AsyncMock(return_value=True)
        notifier.name = "test"

        video = _make_video("vid_new")
        summary = _make_summary_result("vid_new")

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[notifier]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[video])
            MockSummarizer.return_value.summarize = AsyncMock(return_value=summary)

            await run(config_loader=loader)

        # Notification sent
        notifier.send_summary.assert_called_once()
        sent_info = notifier.send_summary.call_args[0][0]
        assert isinstance(sent_info, VideoInfo)
        assert sent_info.title == "Test Video"
        assert sent_info.summary == "A great summary."

        # State updated with the notified video
        state_instance.put_notified_ids.assert_called_once_with(["vid_new"])

        # No error notification
        notifier.send_error.assert_not_called()

    async def test_no_new_videos_skips_remaining_steps(self):
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[])

            await run(config_loader=loader)

        # Summarizer never called
        MockSummarizer.return_value.summarize.assert_not_called()
        # State not updated
        state_instance.put_notified_ids.assert_not_called()

    async def test_config_error_aborts(self):
        loader = MagicMock()
        loader.load = AsyncMock(side_effect=ConfigError("bad config"))

        with (
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
        ):
            await run(config_loader=loader)

        # Nothing else called
        MockYT.assert_not_called()
        MockSummarizer.assert_not_called()

    async def test_partial_summarization_failure_sends_error_and_updates_state(self):
        """Some videos fail summarization → error notification sent, only successes written to state."""
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)
        notifier = MagicMock()
        notifier.send_summary = AsyncMock(return_value=True)
        notifier.send_error = AsyncMock(return_value=True)
        notifier.name = "test"

        vid_ok = _make_video("vid_ok", title="Good Video")
        vid_fail = _make_video("vid_fail", title="Bad Video")
        summary_ok = _make_summary_result("vid_ok", title="Good Video")

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[notifier]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[vid_ok, vid_fail])

            async def _summarize(**kwargs):
                if kwargs["video_id"] == "vid_fail":
                    raise SummarizerError("Gemini timeout")
                return summary_ok

            MockSummarizer.return_value.summarize = AsyncMock(side_effect=_summarize)

            await run(config_loader=loader)

        # Summary notification sent for the good video
        assert notifier.send_summary.call_count == 1

        # Error notification sent
        notifier.send_error.assert_called_once()
        error_msg = notifier.send_error.call_args[0][0]
        assert "1 succeeded" in error_msg
        assert "1 failed" in error_msg
        assert "Bad Video" in error_msg

        # Only the successful video written to state
        state_instance.put_notified_ids.assert_called_once_with(["vid_ok"])

    async def test_all_summarization_fails_no_state_update(self):
        """All videos fail → error notification sent, state NOT updated."""
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)
        notifier = MagicMock()
        notifier.send_summary = AsyncMock(return_value=True)
        notifier.send_error = AsyncMock(return_value=True)
        notifier.name = "test"

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[notifier]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[_make_video("v1")])
            MockSummarizer.return_value.summarize = AsyncMock(side_effect=SummarizerError("fail"))

            await run(config_loader=loader)

        notifier.send_summary.assert_not_called()
        notifier.send_error.assert_called_once()
        state_instance.put_notified_ids.assert_not_called()

    async def test_multiple_notifiers_all_receive_messages(self):
        """All notification targets receive summaries and error messages."""
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)

        notifier_a = MagicMock()
        notifier_a.send_summary = AsyncMock(return_value=True)
        notifier_a.send_error = AsyncMock(return_value=True)
        notifier_a.name = "a"

        notifier_b = MagicMock()
        notifier_b.send_summary = AsyncMock(return_value=True)
        notifier_b.send_error = AsyncMock(return_value=True)
        notifier_b.name = "b"

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[notifier_a, notifier_b]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[_make_video("v1")])
            MockSummarizer.return_value.summarize = AsyncMock(return_value=_make_summary_result("v1"))

            await run(config_loader=loader)

        notifier_a.send_summary.assert_called_once()
        notifier_b.send_summary.assert_called_once()

    async def test_notifier_failure_does_not_block_state_update(self):
        """Webhook failure still writes state to avoid re-summarization."""
        app_config = _make_app_config()
        loader = _make_mock_loader(app_config)
        notifier = MagicMock()
        notifier.send_summary = AsyncMock(return_value=False)  # fails
        notifier.send_error = AsyncMock(return_value=True)
        notifier.name = "test"

        with (
            patch("youtube_summary_notify.main.VideoStateStore") as MockState,
            patch("youtube_summary_notify.main.YouTubeClient") as MockYT,
            patch("youtube_summary_notify.main.Summarizer") as MockSummarizer,
            patch("youtube_summary_notify.main._build_notifiers", return_value=[notifier]),
        ):
            state_instance = MockState.return_value
            state_instance.get_notified_ids = AsyncMock(return_value=set())
            state_instance.put_notified_ids = AsyncMock()

            MockYT.return_value.fetch_recent_videos = AsyncMock(return_value=[_make_video("v1")])
            MockSummarizer.return_value.summarize = AsyncMock(return_value=_make_summary_result("v1"))

            await run(config_loader=loader)

        # State is still updated despite notifier failure
        state_instance.put_notified_ids.assert_called_once_with(["v1"])


class TestHandler:
    def test_handler_returns_200(self):
        with patch("youtube_summary_notify.main.run", new_callable=AsyncMock) as mock_run:
            from youtube_summary_notify.main import handler

            result = handler({}, None)
            assert result == {"statusCode": 200}
            mock_run.assert_called_once()
