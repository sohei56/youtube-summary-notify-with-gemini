"""Slack notifier using Incoming Webhooks."""

import logging

import httpx

from youtube_summary_notify.notifiers.base import BaseNotifier, VideoInfo

logger = logging.getLogger(__name__)


class SlackNotifier(BaseNotifier):
    """Sends notifications to Slack via Incoming Webhooks."""

    def __init__(
        self,
        name: str,
        webhook_url: str,
        message_template: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(name=name, webhook_url=webhook_url, message_template=message_template)
        self._http_client = http_client
        self._owns_client = http_client is None

    async def send_summary(self, video: VideoInfo) -> bool:
        """Format the summary message and POST to Slack webhook.

        Args:
            video: Video metadata and summary to include in the message.

        Returns:
            True on success, False on failure.
        """
        text = self._format_message(video)
        return await self._post(text)

    async def send_error(self, message: str) -> bool:
        """POST an error message to Slack webhook.

        Args:
            message: Error message text.

        Returns:
            True on success, False on failure.
        """
        return await self._post(message)

    async def _post(self, text: str) -> bool:
        """Send a text payload to the Slack webhook URL."""
        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.post(
                self._webhook_url,
                json={"text": text},
            )
            response.raise_for_status()
            logger.info("Slack notification sent successfully to target '%s'", self._name)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Slack webhook returned %d for target '%s': %s",
                exc.response.status_code,
                self._name,
                exc.response.text,
            )
            return False
        except httpx.HTTPError as exc:
            logger.error("Slack webhook request failed for target '%s': %s", self._name, exc)
            return False
        finally:
            if self._owns_client:
                await client.aclose()
