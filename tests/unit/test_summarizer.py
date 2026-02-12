"""Tests for Summarizer (Gemini API summarization)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as genai_errors

from youtube_summary_notify.summarizer import Summarizer, SummarizerError, SummaryResult

VIDEO_ID = "dQw4w9WgXcQ"
TITLE = "Test Video"
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
CHANNEL_NAME = "Test Channel"
PUBLISHED_AT = "2026-02-12T10:00:00Z"
MODEL = "gemini-2.5-flash"
API_KEY = "test-api-key"
PROMPT_TEMPLATE = "Summarize this video in {language}: {video_url}"
LANGUAGE = "en"


def _make_mock_client(response_text: str | None = "This is a summary.") -> MagicMock:
    """Create a mock genai.Client with a preset response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    return mock_client


def _make_summarizer(client: MagicMock | None = None) -> Summarizer:
    """Create a Summarizer with an optional mock client."""
    mock_client = client or _make_mock_client()
    return Summarizer(api_key=API_KEY, model=MODEL, client=mock_client)


class TestSummarizeHappyPath:
    async def test_returns_summary_result(self):
        mock_client = _make_mock_client("A great summary of the video.")
        summarizer = _make_summarizer(mock_client)

        result = await summarizer.summarize(
            video_id=VIDEO_ID,
            title=TITLE,
            url=URL,
            channel_name=CHANNEL_NAME,
            published_at=PUBLISHED_AT,
            prompt_template=PROMPT_TEMPLATE,
            language=LANGUAGE,
        )

        assert isinstance(result, SummaryResult)
        assert result.video_id == VIDEO_ID
        assert result.title == TITLE
        assert result.url == URL
        assert result.channel_name == CHANNEL_NAME
        assert result.published_at == PUBLISHED_AT
        assert result.summary == "A great summary of the video."

    async def test_substitutes_prompt_template(self):
        mock_client = _make_mock_client("Summary text.")
        summarizer = _make_summarizer(mock_client)

        await summarizer.summarize(
            video_id=VIDEO_ID,
            title=TITLE,
            url=URL,
            channel_name=CHANNEL_NAME,
            published_at=PUBLISHED_AT,
            prompt_template=PROMPT_TEMPLATE,
            language=LANGUAGE,
        )

        mock_client.aio.models.generate_content.assert_called_once_with(
            model=MODEL,
            contents=f"Summarize this video in {LANGUAGE}: {URL}",
        )

    async def test_uses_configured_model(self):
        mock_client = _make_mock_client("Summary.")
        summarizer = Summarizer(api_key=API_KEY, model="gemini-2.0-flash", client=mock_client)

        await summarizer.summarize(
            video_id=VIDEO_ID,
            title=TITLE,
            url=URL,
            channel_name=CHANNEL_NAME,
            published_at=PUBLISHED_AT,
            prompt_template=PROMPT_TEMPLATE,
            language="ja",
        )

        mock_client.aio.models.generate_content.assert_called_once_with(
            model="gemini-2.0-flash",
            contents=f"Summarize this video in ja: {URL}",
        )


class TestSummarizeEmptyResponse:
    async def test_empty_text_raises_error(self):
        mock_client = _make_mock_client(response_text="")
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="empty response"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )

    async def test_none_text_raises_error(self):
        mock_client = _make_mock_client(response_text=None)
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="empty response"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )


class TestSummarizeAPIErrors:
    async def test_client_error_raises_summarizer_error(self):
        mock_client = _make_mock_client()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=genai_errors.ClientError(429, {"error": {"message": "Rate limited", "status": "RATE_LIMITED"}})
        )
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="client error"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )

    async def test_server_error_raises_summarizer_error(self):
        mock_client = _make_mock_client()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=genai_errors.ServerError(500, {"error": {"message": "Internal error", "status": "INTERNAL"}})
        )
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="server error"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )

    async def test_api_error_raises_summarizer_error(self):
        mock_client = _make_mock_client()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=genai_errors.APIError(403, {"error": {"message": "Forbidden", "status": "FORBIDDEN"}})
        )
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="API error"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )

    async def test_unexpected_exception_raises_summarizer_error(self):
        mock_client = _make_mock_client()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("Something broke"))
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match="Unexpected error"):
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )


class TestSummarizeErrorMessages:
    async def test_error_includes_video_title_and_id(self):
        mock_client = _make_mock_client()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("fail"))
        summarizer = _make_summarizer(mock_client)

        with pytest.raises(SummarizerError, match=TITLE) as exc_info:
            await summarizer.summarize(
                video_id=VIDEO_ID,
                title=TITLE,
                url=URL,
                channel_name=CHANNEL_NAME,
                published_at=PUBLISHED_AT,
                prompt_template=PROMPT_TEMPLATE,
                language=LANGUAGE,
            )

        assert VIDEO_ID in str(exc_info.value)
