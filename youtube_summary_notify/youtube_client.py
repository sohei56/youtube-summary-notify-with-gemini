"""YouTube Data API v3 client for detecting new videos from monitored channels."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeClientError(Exception):
    """Raised when YouTube API calls fail."""


@dataclass(frozen=True)
class Video:
    """Metadata for a YouTube video detected from a channel's uploads."""

    video_id: str
    title: str
    url: str
    channel_name: str
    published_at: str


class YouTubeClient:
    """Fetches recent videos from YouTube channels using the Data API v3."""

    def __init__(self, api_key: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._owns_client = http_client is None

    async def fetch_recent_videos(
        self,
        channel_id: str,
        channel_name: str,
        lookback_minutes: float,
    ) -> list[Video]:
        """Fetch videos published within the lookback window from a channel.

        Args:
            channel_id: YouTube channel ID (starts with "UC", 24 chars).
            channel_name: Display name of the channel (used in returned Video objects).
            lookback_minutes: Only return videos published within this many minutes ago.

        Returns:
            List of Video objects for videos within the lookback window.

        Raises:
            YouTubeClientError: If the API call fails.
        """
        playlist_id = self._channel_to_playlist_id(channel_id)
        items = await self._fetch_playlist_items(playlist_id)
        cutoff = datetime.now(timezone.utc).timestamp() - (lookback_minutes * 60)
        videos = []
        for item in items:
            snippet = item.get("snippet", {})
            published_str = snippet.get("publishedAt", "")
            if not published_str:
                continue
            try:
                published_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Skipping item with unparseable publishedAt: %s", published_str)
                continue

            if published_dt.timestamp() < cutoff:
                continue

            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue

            title = snippet.get("title", "")
            videos.append(
                Video(
                    video_id=video_id,
                    title=title,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    channel_name=channel_name,
                    published_at=published_str,
                )
            )

        logger.info(
            "Channel '%s' (%s): found %d videos within lookback window",
            channel_name,
            channel_id,
            len(videos),
        )
        return videos

    async def _fetch_playlist_items(self, playlist_id: str) -> list[dict]:
        """Fetch items from a YouTube playlist via the playlistItems.list endpoint."""
        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.get(
                f"{YOUTUBE_API_BASE}/playlistItems",
                params={
                    "part": "snippet",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                    "key": self._api_key,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
        except httpx.HTTPStatusError as exc:
            raise YouTubeClientError(
                f"YouTube API returned {exc.response.status_code} for playlist {playlist_id}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise YouTubeClientError(f"YouTube API request failed for playlist {playlist_id}: {exc}") from exc
        finally:
            if self._owns_client:
                await client.aclose()

    @staticmethod
    def _channel_to_playlist_id(channel_id: str) -> str:
        """Convert a channel ID (UC...) to its uploads playlist ID (UU...)."""
        return "UU" + channel_id[2:]
