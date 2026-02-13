"""Tests for VideoStateStore (DynamoDB video state tracking)."""

import pytest

from tests.conftest import TEST_DEPLOYMENT_ID, TEST_TABLE
from youtube_summary_notify.store.video_state_store import VideoStateStore


@pytest.fixture()
def store(dynamodb_table):
    """VideoStateStore pointed at the mocked DynamoDB table."""
    return VideoStateStore(table_name=TEST_TABLE, deployment_id=TEST_DEPLOYMENT_ID)


class TestGetNotifiedIds:
    async def test_empty_table_returns_empty_set(self, store):
        """Returns empty set when no videos have been notified."""
        result = await store.get_notified_ids()
        assert result == set()

    async def test_returns_written_ids(self, store):
        """Returns all previously stored video IDs."""
        await store.put_notified_ids(["vid_1", "vid_2", "vid_3"])
        result = await store.get_notified_ids()
        assert result == {"vid_1", "vid_2", "vid_3"}


class TestPutNotifiedIds:
    async def test_empty_list_is_noop(self, store):
        """Writing an empty list does not create any records."""
        await store.put_notified_ids([])
        result = await store.get_notified_ids()
        assert result == set()

    async def test_multiple_puts_accumulate(self, store):
        """Successive writes accumulate video IDs."""
        await store.put_notified_ids(["vid_1", "vid_2"])
        await store.put_notified_ids(["vid_3", "vid_4"])
        result = await store.get_notified_ids()
        assert result == {"vid_1", "vid_2", "vid_3", "vid_4"}

    async def test_duplicate_ids_handled(self, store):
        """Re-writing an existing ID does not create duplicates."""
        await store.put_notified_ids(["vid_1", "vid_2"])
        await store.put_notified_ids(["vid_2", "vid_3"])
        result = await store.get_notified_ids()
        assert result == {"vid_1", "vid_2", "vid_3"}


class TestEntryLimit:
    async def test_enforces_500_entry_limit(self, store):
        """Deletes the oldest entries when count exceeds 500."""
        # Write 510 entries in batches
        all_ids = [f"vid_{i:04d}" for i in range(510)]

        # Write in smaller batches to avoid overwhelming batch_writer
        batch_size = 25
        for i in range(0, len(all_ids), batch_size):
            await store.put_notified_ids(all_ids[i : i + batch_size])

        result = await store.get_notified_ids()
        assert len(result) == 500

        # The oldest 10 should have been deleted
        for vid_id in all_ids[:10]:
            assert vid_id not in result

        # The newest 500 should remain
        for vid_id in all_ids[10:]:
            assert vid_id in result
