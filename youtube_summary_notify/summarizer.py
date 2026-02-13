"""Gemini API summarization module for YouTube videos."""

import logging
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors
from google.genai.types import Part

logger = logging.getLogger(__name__)


class SummarizerError(Exception):
    """Raised when video summarization fails."""


@dataclass(frozen=True)
class SummaryResult:
    """Result of a video summarization attempt."""

    video_id: str
    title: str
    url: str
    channel_name: str
    published_at: str
    summary: str


class Summarizer:
    """Generates video summaries using the Gemini API."""

    def __init__(self, api_key: str, model: str, client: genai.Client | None = None) -> None:
        self._client = client or genai.Client(api_key=api_key)
        self._model = model

    async def summarize(
        self,
        video_id: str,
        title: str,
        url: str,
        channel_name: str,
        published_at: str,
        prompt_template: str,
        language: str,
    ) -> SummaryResult:
        """Summarize a YouTube video using Gemini.

        Args:
            video_id: YouTube video ID.
            title: Video title.
            url: Full YouTube video URL.
            channel_name: Name of the channel that published the video.
            published_at: ISO 8601 publish timestamp.
            prompt_template: Prompt template containing {language} placeholder.
            language: Language for the summary.

        Returns:
            SummaryResult with the generated summary text.

        Raises:
            SummarizerError: If the API call fails or returns no text.
        """
        prompt = prompt_template.format(language=language)

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    Part.from_uri(file_uri=url, mime_type="video/mp4"),
                    prompt,
                ],
            )
        except genai_errors.ClientError as exc:
            raise SummarizerError(f"Gemini API client error for '{title}' ({video_id}): {exc}") from exc
        except genai_errors.ServerError as exc:
            raise SummarizerError(f"Gemini API server error for '{title}' ({video_id}): {exc}") from exc
        except genai_errors.APIError as exc:
            raise SummarizerError(f"Gemini API error for '{title}' ({video_id}): {exc}") from exc
        except Exception as exc:
            raise SummarizerError(f"Unexpected error summarizing '{title}' ({video_id}): {exc}") from exc

        text = response.text
        if not text:
            raise SummarizerError(
                f"Gemini returned empty response for '{title}' ({video_id}); content may have been filtered"
            )

        logger.info("Successfully summarized '%s' (%s)", title, video_id)
        return SummaryResult(
            video_id=video_id,
            title=title,
            url=url,
            channel_name=channel_name,
            published_at=published_at,
            summary=text,
        )
