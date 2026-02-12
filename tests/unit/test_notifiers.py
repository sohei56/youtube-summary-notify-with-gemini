"""Tests for BaseNotifier and SlackNotifier."""

import json

import httpx
import pytest

from youtube_summary_notify.notifiers.base import BaseNotifier, VideoInfo
from youtube_summary_notify.notifiers.slack import SlackNotifier

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/xxx"
NAME = "team-updates"
MESSAGE_TEMPLATE = "*{title}*\nChannel: {channel}\nPublished: {published_at}\n{url}\n\n{summary}"

VIDEO = VideoInfo(
    channel="Test Channel",
    title="Test Video Title",
    url="https://www.youtube.com/watch?v=abc123",
    published_at="2026-02-12T10:00:00Z",
    summary="This is a great summary of the video.",
)


def _mock_transport(status_code: int = 200, body: str = "ok") -> httpx.MockTransport:
    """Create a MockTransport that returns the given status and body."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status_code=status_code, text=body)

    transport = httpx.MockTransport(handler)
    transport.captured = captured  # type: ignore[attr-defined]
    return transport


class TestBaseNotifierInterface:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseNotifier(name="test", webhook_url="http://x", message_template="{summary}")

    def test_name_property(self):
        class ConcreteNotifier(BaseNotifier):
            async def send_summary(self, video: VideoInfo) -> bool:
                return True

            async def send_error(self, message: str) -> bool:
                return True

        notifier = ConcreteNotifier(name="my-target", webhook_url="http://x", message_template="{summary}")
        assert notifier.name == "my-target"

    def test_format_message_substitutes_all_fields(self):
        class ConcreteNotifier(BaseNotifier):
            async def send_summary(self, video: VideoInfo) -> bool:
                return True

            async def send_error(self, message: str) -> bool:
                return True

        notifier = ConcreteNotifier(name="test", webhook_url="http://x", message_template=MESSAGE_TEMPLATE)
        result = notifier._format_message(VIDEO)

        assert "Test Video Title" in result
        assert "Test Channel" in result
        assert "2026-02-12T10:00:00Z" in result
        assert "https://www.youtube.com/watch?v=abc123" in result
        assert "This is a great summary of the video." in result


class TestSlackSendSummary:
    async def test_success_returns_true(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_summary(VIDEO)

        assert result is True

    async def test_posts_formatted_message(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            await notifier.send_summary(VIDEO)

        assert len(transport.captured) == 1
        req = transport.captured[0]
        body = json.loads(req.content)
        assert "text" in body
        assert "Test Video Title" in body["text"]
        assert "This is a great summary of the video." in body["text"]

    async def test_posts_to_webhook_url(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            await notifier.send_summary(VIDEO)

        req = transport.captured[0]
        assert str(req.url) == WEBHOOK_URL

    async def test_http_error_returns_false(self):
        transport = _mock_transport(500, "internal error")
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_summary(VIDEO)

        assert result is False

    async def test_network_error_returns_false(self):
        def raise_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(raise_error)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_summary(VIDEO)

        assert result is False


class TestSlackSendError:
    async def test_success_returns_true(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_error("Something went wrong")

        assert result is True

    async def test_posts_error_message_directly(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            await notifier.send_error("3 videos failed summarization")

        req = transport.captured[0]
        body = json.loads(req.content)
        assert body["text"] == "3 videos failed summarization"

    async def test_http_error_returns_false(self):
        transport = _mock_transport(403, "forbidden")
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_error("error message")

        assert result is False

    async def test_network_error_returns_false(self):
        def raise_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(raise_error)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            result = await notifier.send_error("error message")

        assert result is False


class TestSlackMessageFormat:
    async def test_all_template_variables_substituted(self):
        template = "{channel} | {title} | {url} | {published_at} | {summary}"
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(name=NAME, webhook_url=WEBHOOK_URL, message_template=template, http_client=client)
            await notifier.send_summary(VIDEO)

        body = json.loads(transport.captured[0].content)
        expected = (
            "Test Channel | Test Video Title | https://www.youtube.com/watch?v=abc123"
            " | 2026-02-12T10:00:00Z | This is a great summary of the video."
        )
        assert body["text"] == expected

    async def test_json_content_type(self):
        transport = _mock_transport(200)
        async with httpx.AsyncClient(transport=transport) as client:
            notifier = SlackNotifier(
                name=NAME, webhook_url=WEBHOOK_URL, message_template=MESSAGE_TEMPLATE, http_client=client
            )
            await notifier.send_summary(VIDEO)

        req = transport.captured[0]
        assert "application/json" in req.headers["content-type"]
