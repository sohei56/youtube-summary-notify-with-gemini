"""Core orchestration logic and Lambda handler."""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from youtube_summary_notify.config import ApplicationConfig, ConfigLoader
from youtube_summary_notify.notifiers.base import BaseNotifier, VideoInfo
from youtube_summary_notify.notifiers.slack import SlackNotifier
from youtube_summary_notify.store.config_store import ConfigError, Notification
from youtube_summary_notify.store.video_state_store import VideoStateStore
from youtube_summary_notify.summarizer import Summarizer, SummarizerError, SummaryResult
from youtube_summary_notify.youtube_client import Video, YouTubeClient, YouTubeClientError

logger = logging.getLogger(__name__)

SEMAPHORE_SIZE = 5


@dataclass
class FailedVideo:
    """A video that failed summarization."""

    title: str
    url: str
    error: str


async def run(
    config_loader: ConfigLoader | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Execute the full pipeline: detect → summarize → notify → update state.

    Args:
        config_loader: Optional pre-built ConfigLoader (for testing).
        http_client: Optional shared httpx.AsyncClient (for testing).
    """
    logger.info("Execution started")

    # Step 1: Initialize
    try:
        loader = config_loader or ConfigLoader()
        app_config = await loader.load()
    except ConfigError:
        logger.error("Configuration loading failed; aborting execution", exc_info=True)
        return

    state_store = VideoStateStore(
        table_name=loader.state_table,
        deployment_id=app_config.deployment_id,
    )

    notifiers = _build_notifiers(app_config, http_client)

    # Step 2: Detect new videos
    logger.info("Checking %d channel(s)", len(app_config.user_config.channels))
    yt_client = YouTubeClient(api_key=app_config.secrets.youtube_api_key, http_client=http_client)
    all_videos = await _detect_new_videos(yt_client, app_config, state_store)

    if not all_videos:
        logger.info("No new videos detected; execution complete")
        return

    logger.info("Detected %d new video(s) to process", len(all_videos))

    # Step 3: Summarize videos
    summarizer = Summarizer(
        api_key=app_config.secrets.gemini_api_key,
        model=app_config.user_config.summarization.model,
    )
    successes, failures = await _summarize_videos(summarizer, all_videos, app_config)

    logger.info("Summarization complete: %d succeeded, %d failed", len(successes), len(failures))

    # Step 4: Send notifications
    for result in successes:
        video_info = VideoInfo(
            channel=result.channel_name,
            title=result.title,
            url=result.url,
            published_at=result.published_at,
            summary=result.summary,
        )
        for notifier in notifiers:
            await notifier.send_summary(video_info)

    if failures:
        error_message = _build_error_message(successes, failures)
        for notifier in notifiers:
            await notifier.send_error(error_message)

    # Step 5: Update state (only successfully notified videos)
    if successes:
        notified_ids = [r.video_id for r in successes]
        await state_store.put_notified_ids(notified_ids)

    logger.info("Execution complete")


def _build_notifiers(
    app_config: ApplicationConfig,
    http_client: httpx.AsyncClient | None = None,
) -> list[BaseNotifier]:
    """Create notifier instances from configuration."""
    notifiers: list[BaseNotifier] = []
    for notification in app_config.user_config.notifications:
        webhook_url = app_config.secrets.webhook_urls[notification.secret_key]
        notifier = _create_notifier(notification, webhook_url, http_client)
        notifiers.append(notifier)
    return notifiers


def _create_notifier(
    notification: Notification,
    webhook_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> BaseNotifier:
    """Create a single notifier instance based on platform type."""
    if notification.platform == "slack":
        return SlackNotifier(
            name=notification.name,
            webhook_url=webhook_url,
            message_template=notification.message_template,
            http_client=http_client,
        )
    raise ConfigError(f"Unsupported notification platform: {notification.platform}")


async def _detect_new_videos(
    yt_client: YouTubeClient,
    app_config: ApplicationConfig,
    state_store: VideoStateStore,
) -> list[Video]:
    """Fetch recent videos from all channels and filter out already-notified ones."""
    channels = app_config.user_config.channels
    lookback = app_config.lookback_window_minutes

    # Fetch from all channels concurrently
    tasks = [_fetch_channel_videos(yt_client, channel.id, channel.name, lookback) for channel in channels]
    results = await asyncio.gather(*tasks)

    all_videos: list[Video] = []
    for videos in results:
        all_videos.extend(videos)

    if not all_videos:
        return []

    # Filter out already-notified videos
    notified_ids = await state_store.get_notified_ids()
    new_videos = [v for v in all_videos if v.video_id not in notified_ids]

    logger.debug(
        "Found %d total recent videos, %d already notified, %d new",
        len(all_videos),
        len(all_videos) - len(new_videos),
        len(new_videos),
    )
    return new_videos


async def _fetch_channel_videos(
    yt_client: YouTubeClient,
    channel_id: str,
    channel_name: str,
    lookback_minutes: float,
) -> list[Video]:
    """Fetch videos from a single channel, returning empty list on error."""
    try:
        return await yt_client.fetch_recent_videos(channel_id, channel_name, lookback_minutes)
    except YouTubeClientError:
        logger.error("Failed to fetch videos for channel '%s' (%s); skipping", channel_name, channel_id, exc_info=True)
        return []


async def _summarize_videos(
    summarizer: Summarizer,
    videos: list[Video],
    app_config: ApplicationConfig,
) -> tuple[list[SummaryResult], list[FailedVideo]]:
    """Summarize all videos concurrently with semaphore-bounded concurrency."""
    semaphore = asyncio.Semaphore(SEMAPHORE_SIZE)
    prompt_template = app_config.user_config.summarization.prompt_template
    language = app_config.user_config.summarization.language

    async def _summarize_one(video: Video) -> SummaryResult | FailedVideo:
        async with semaphore:
            try:
                return await summarizer.summarize(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    channel_name=video.channel_name,
                    published_at=video.published_at,
                    prompt_template=prompt_template,
                    language=language,
                )
            except SummarizerError as exc:
                logger.error("Summarization failed for '%s' (%s)", video.title, video.video_id, exc_info=True)
                return FailedVideo(title=video.title, url=video.url, error=str(exc))

    results = await asyncio.gather(*[_summarize_one(v) for v in videos])

    successes: list[SummaryResult] = []
    failures: list[FailedVideo] = []
    for result in results:
        if isinstance(result, SummaryResult):
            successes.append(result)
        else:
            failures.append(result)

    return successes, failures


def _build_error_message(successes: list[SummaryResult], failures: list[FailedVideo]) -> str:
    """Build the error summary message sent to notification targets."""
    lines = [
        f"Execution completed with errors: {len(successes)} succeeded, {len(failures)} failed.",
        "",
        "Failed videos:",
    ]
    for f in failures:
        lines.append(f"- {f.title} ({f.url}): {f.error}")
    return "\n".join(lines)


def handler(event: dict, context: object) -> dict:
    """AWS Lambda entry point."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
    return {"statusCode": 200}
