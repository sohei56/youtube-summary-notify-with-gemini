"""Abstract notifier interface for notification platforms."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoInfo:
    """Video metadata and summary for notification dispatch."""

    channel: str
    title: str
    url: str
    published_at: str
    summary: str


class BaseNotifier(ABC):
    """Abstract base class for notification platform implementations.

    Each notifier instance holds its own message template and webhook URL.
    Subclasses construct the final message by substituting VideoInfo fields
    into the template.
    """

    def __init__(self, name: str, webhook_url: str, message_template: str) -> None:
        self._name = name
        self._webhook_url = webhook_url
        self._message_template = message_template

    @property
    def name(self) -> str:
        """Unique identifier for this notification target."""
        return self._name

    @abstractmethod
    async def send_summary(self, video: VideoInfo) -> bool:
        """Build message from template and send notification.

        Args:
            video: Video metadata and summary to include in the message.

        Returns:
            True on success, False on failure.
        """
        ...

    @abstractmethod
    async def send_error(self, message: str) -> bool:
        """Send an error notification message.

        Args:
            message: Error message text.

        Returns:
            True on success, False on failure.
        """
        ...

    def _format_message(self, video: VideoInfo) -> str:
        """Substitute VideoInfo fields into the message template."""
        return self._message_template.format(
            channel=video.channel,
            title=video.title,
            url=video.url,
            published_at=video.published_at,
            summary=video.summary,
        )
