"""Tests for YouTubeClient (YouTube Data API v3)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from youtube_summary_notify.youtube_client import YouTubeClient, YouTubeClientError

CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"
CHANNEL_NAME = "Test Channel"
LOOKBACK_MINUTES = 120.0
API_KEY = "test-api-key"


def _make_playlist_response(items: list[dict]) -> dict:
    """Build a YouTube playlistItems.list API response."""
    return {"items": items}


def _make_item(video_id: str, title: str, published_at: str) -> dict:
    """Build a single playlist item matching the YouTube API format."""
    return {
        "snippet": {
            "publishedAt": published_at,
            "title": title,
            "resourceId": {"videoId": video_id},
        }
    }


def _recent_timestamp(minutes_ago: float = 30) -> str:
    """Return an ISO 8601 timestamp for `minutes_ago` minutes in the past."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _old_timestamp(minutes_ago: float = 300) -> str:
    """Return an ISO 8601 timestamp for `minutes_ago` minutes in the past (outside lookback)."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_transport(response_data: dict, status_code: int = 200) -> httpx.MockTransport:
    """Create an httpx MockTransport that returns the given JSON response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=response_data)

    return httpx.MockTransport(handler)


class TestChannelToPlaylistId:
    def test_converts_uc_to_uu(self):
        """Converts 'UC' channel prefix to 'UU' uploads playlist prefix."""
        assert YouTubeClient._channel_to_playlist_id("UCxxxxxxxxxxxxxxxxxxxxxx") == "UUxxxxxxxxxxxxxxxxxxxxxx"

    def test_preserves_remaining_chars(self):
        """Only the first two characters change; the rest stay the same."""
        assert YouTubeClient._channel_to_playlist_id("UCabcdefghijklmnopqrstuv") == "UUabcdefghijklmnopqrstuv"


class TestFetchRecentVideosHappyPath:
    async def test_returns_videos_within_lookback(self):
        """Returns videos published within the lookback window."""
        recent = _recent_timestamp(30)
        items = [_make_item("vid_1", "Recent Video", recent)]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert len(videos) == 1
        assert videos[0].video_id == "vid_1"
        assert videos[0].title == "Recent Video"
        assert videos[0].url == "https://www.youtube.com/watch?v=vid_1"
        assert videos[0].channel_name == CHANNEL_NAME
        assert videos[0].published_at == recent

    async def test_filters_out_old_videos(self):
        """Excludes videos published before the lookback window."""
        recent = _recent_timestamp(30)
        old = _old_timestamp(300)
        items = [
            _make_item("vid_recent", "Recent", recent),
            _make_item("vid_old", "Old", old),
        ]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert len(videos) == 1
        assert videos[0].video_id == "vid_recent"

    async def test_returns_empty_list_when_no_recent_videos(self):
        """Returns empty list when all videos are outside the lookback window."""
        old = _old_timestamp(300)
        items = [_make_item("vid_old", "Old", old)]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert videos == []

    async def test_returns_empty_list_for_empty_response(self):
        """Returns empty list when the API returns no items."""
        transport = _mock_transport(_make_playlist_response([]))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert videos == []

    async def test_multiple_videos_all_recent(self):
        """Returns all videos when all are within the lookback window."""
        items = [
            _make_item("vid_1", "Video 1", _recent_timestamp(10)),
            _make_item("vid_2", "Video 2", _recent_timestamp(20)),
            _make_item("vid_3", "Video 3", _recent_timestamp(60)),
        ]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert len(videos) == 3
        assert {v.video_id for v in videos} == {"vid_1", "vid_2", "vid_3"}


class TestFetchRecentVideosEdgeCases:
    async def test_skips_item_with_missing_published_at(self):
        """Skips items missing the publishedAt field."""
        items = [{"snippet": {"title": "No Date", "resourceId": {"videoId": "vid_nodate"}}}]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert videos == []

    async def test_skips_item_with_missing_video_id(self):
        """Skips items missing the videoId in resourceId."""
        recent = _recent_timestamp(30)
        items = [{"snippet": {"publishedAt": recent, "title": "No ID", "resourceId": {}}}]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert videos == []

    async def test_skips_item_with_invalid_date_format(self):
        """Skips items with unparseable date strings."""
        items = [_make_item("vid_bad_date", "Bad Date", "not-a-date")]
        transport = _mock_transport(_make_playlist_response(items))
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            videos = await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert videos == []


class TestFetchRecentVideosAPIErrors:
    async def test_http_403_raises_youtube_client_error(self):
        """Wraps HTTP 403 responses as YouTubeClientError."""
        transport = _mock_transport({"error": {"message": "Forbidden"}}, status_code=403)
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            with pytest.raises(YouTubeClientError, match="403"):
                await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

    async def test_http_404_raises_youtube_client_error(self):
        """Wraps HTTP 404 responses as YouTubeClientError."""
        transport = _mock_transport({"error": {"message": "Not Found"}}, status_code=404)
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            with pytest.raises(YouTubeClientError, match="404"):
                await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

    async def test_network_error_raises_youtube_client_error(self):
        """Wraps network-level failures as YouTubeClientError."""
        def raise_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(raise_error)
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            with pytest.raises(YouTubeClientError, match="request failed"):
                await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)


class TestAPIRequestParameters:
    async def test_sends_correct_params(self):
        """Verify the request is sent with the correct query parameters."""
        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json=_make_playlist_response([]))

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            yt = YouTubeClient(api_key=API_KEY, http_client=client)
            await yt.fetch_recent_videos(CHANNEL_ID, CHANNEL_NAME, LOOKBACK_MINUTES)

        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert "playlistItems" in str(req.url)
        assert req.url.params["part"] == "snippet"
        assert req.url.params["playlistId"] == "UUxxxxxxxxxxxxxxxxxxxxxx"
        assert req.url.params["maxResults"] == "50"
        assert req.url.params["key"] == API_KEY
