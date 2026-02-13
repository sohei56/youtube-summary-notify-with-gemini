"""DynamoDB video state store for tracking notified video IDs."""

import asyncio
import logging
import time
from decimal import Decimal

import boto3

logger = logging.getLogger(__name__)


class StateError(Exception):
    """Raised when video state operations fail."""


MAX_ENTRIES = 500


class VideoStateStore:
    """Manages notified video state in DynamoDB with automatic cleanup of old entries."""

    def __init__(self, table_name: str, deployment_id: str) -> None:
        self._table_name = table_name
        self._deployment_id = deployment_id
        self._dynamodb = boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(table_name)

    async def get_notified_ids(self) -> set[str]:
        """Return the set of video IDs that have already been notified.

        On failure, logs a warning and returns an empty set so processing can continue.
        """
        try:
            items = await self._query_all_items()
            return {item["video_id"] for item in items}
        except Exception:
            logger.warning("Failed to read video state from DynamoDB; treating as empty", exc_info=True)
            return set()

    async def put_notified_ids(self, video_ids: list[str]) -> None:
        """Write new video IDs to DynamoDB, then enforce the entry limit.

        On failure, logs an error but does not raise so processing can continue.
        """
        if not video_ids:
            return

        try:
            await self._batch_write(video_ids)
            await self._enforce_limit()
        except Exception:
            logger.error("Failed to write video state to DynamoDB", exc_info=True)

    async def _batch_write(self, video_ids: list[str]) -> None:
        """Batch-write video IDs with current timestamp."""
        now = Decimal(str(time.time()))

        def _write() -> None:
            with self._table.batch_writer() as batch:
                for video_id in video_ids:
                    batch.put_item(
                        Item={
                            "deployment_id": self._deployment_id,
                            "video_id": video_id,
                            "notified_at": now,
                        }
                    )

        await asyncio.to_thread(_write)

    async def _query_all_items(self) -> list[dict]:
        """Query all items for this deployment."""

        def _query() -> list[dict]:
            items: list[dict] = []
            kwargs = {
                "KeyConditionExpression": boto3.dynamodb.conditions.Key("deployment_id").eq(self._deployment_id),
            }
            while True:
                response = self._table.query(**kwargs)
                items.extend(response["Items"])
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                kwargs["ExclusiveStartKey"] = last_key
            return items

        return await asyncio.to_thread(_query)

    async def _enforce_limit(self) -> None:
        """Delete oldest entries if total count exceeds MAX_ENTRIES."""
        items = await self._query_all_items()
        if len(items) <= MAX_ENTRIES:
            return

        sorted_items = sorted(items, key=lambda x: x["notified_at"])
        to_delete = sorted_items[: len(items) - MAX_ENTRIES]

        def _delete() -> None:
            with self._table.batch_writer() as batch:
                for item in to_delete:
                    batch.delete_item(
                        Key={
                            "deployment_id": item["deployment_id"],
                            "video_id": item["video_id"],
                        }
                    )

        await asyncio.to_thread(_delete)
        logger.info("Cleaned up %d old video state entries", len(to_delete))
